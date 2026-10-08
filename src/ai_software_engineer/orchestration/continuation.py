"""One bounded first-Coder interruption path through the existing claimed runtime."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from ai_software_engineer.agents.continuation import (
    ContinuationExecutionUncertain,
    InterruptionBudgetExhausted,
    InterruptionObservation,
    same_continuation_inputs,
)
from ai_software_engineer.agents.execution import (
    ExecutionGuard,
    ExecutionStop,
    NativeProcessStop,
    SynchronousToolLoopStop,
)
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.domain import AgentPermissions, AgentRole, TaskStatus
from ai_software_engineer.domain.continuation import ContinuationCause, task_intent_sha256
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git.capture import WorktreeChangeCapture
from ai_software_engineer.git.mutation import (
    MutationInventoryRejected,
    WorkspaceMutationInventory,
    capture_mutation_inventory,
    changed_mutation_paths,
    is_execution_cache_path,
)
from ai_software_engineer.git.mutation_capture import WorktreeMutationCapture
from ai_software_engineer.git.policy import WorkspacePolicy
from ai_software_engineer.git.ports import WorktreeRef, WorktreeSnapshot, WorktreeSpec
from ai_software_engineer.git.worktree import GitWorkspaceError
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationAdmission,
    ContinuationRejected,
    ContinuationScope,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.recovery.models import CapturedChanges
from ai_software_engineer.store.ports import TaskRepository
from ai_software_engineer.work_queue.models import QueueClaim

_EMPTY_DIFF_SHA256 = hashlib.sha256(b"").hexdigest()


class ContinuationGitWorkspace(Protocol):
    """Existing read-only Git verification seams; no seed/rebase or mutation port."""

    def recover(self, spec: WorktreeSpec) -> WorktreeRef: ...

    def inspect(self, worktree: WorktreeRef) -> WorktreeSnapshot: ...

    def capture_changes(
        self,
        worktree: WorktreeRef,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
        base_revision: str | None = None,
    ) -> WorktreeChangeCapture: ...

    def verify_capture(
        self,
        capture: WorktreeChangeCapture,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
    ) -> None: ...

    def capture_mutations(
        self,
        worktree: WorktreeRef,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
        base_revision: str | None = None,
    ) -> WorktreeMutationCapture: ...

    def verify_mutations(
        self,
        capture: WorktreeMutationCapture,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class _Started:
    request: AgentRequest
    task_intent: str
    task_revision: int
    work_item_id: str
    lease_id: str
    inventory_sha256: str


class NativeCoderContinuation:
    """Seal each stopped invocation and consume distinct policy-bound successor admissions."""

    def __init__(
        self,
        *,
        scope: ContinuationScope,
        store: FileContinuationStore,
        git_workspace: ContinuationGitWorkspace,
        guard: ExecutionGuard,
        current_task: Callable[[], Task],
        current_revision: Callable[[], int],
        claim: Callable[[], QueueClaim],
        has_accepted_output: Callable[[], bool],
        has_accepted_output_for_request: Callable[[AgentRequest], bool] | None = None,
        current_source_revision: Callable[[], str] | None = None,
        validate_active_request: Callable[[AgentRequest], None] | None = None,
        resolved_interruption_receipts: Callable[[], tuple[str, ...]] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._scope, self._store, self._git, self._guard = scope, store, git_workspace, guard
        self._current_task, self._revision, self._claim = current_task, current_revision, claim
        self._has_output, self._clock = has_accepted_output, clock
        self._has_request_output = has_accepted_output_for_request
        self._source_revision, self._validate_active_request = (
            current_source_revision,
            validate_active_request,
        )
        self._resolved_receipts = resolved_interruption_receipts
        self._starts: dict[str, _Started] = {}
        self._prepared: set[str] = set()

    def prepare(self, request: AgentRequest, root: Path) -> str | None:
        if request.role is not AgentRole.CODER:
            return None
        task = self._current_task()
        policy = task.interruption_continuation_policy
        if policy is None or (policy.schema_version == "v1" and request.attempt != 2):
            return None
        receipts = self._store.receipts_for_task(request.task_id)
        predecessors = tuple(
            receipt
            for receipt in receipts
            if receipt.request.attempt + 1 == request.attempt
            and not self._receipt_resolved_by_baseline(receipt)
        )
        if not predecessors:
            return None
        if len(predecessors) != 1:
            raise ContinuationRejected("replacement has ambiguous interruption predecessors")
        receipt = predecessors[0]
        task, claim = self._current(request)
        policy = task.interruption_continuation_policy
        assert policy is not None
        self._require_receipt_current(receipt, task)
        self._require_active_request(request, task)
        if (
            self._output(receipt.request)
            or self._output(request)
            or request.run_id == receipt.request.run_id
            or request.context_manifest_id == receipt.request.context_manifest_id
            or claim.lease.id == receipt.claim_lease_id
            or claim.work_item.id == receipt.original_work_item_id
            or claim.work_item.parent_work_item_id != receipt.original_work_item_id
            or not same_continuation_inputs(request, receipt.request, cause=receipt.cause)
            or task.attempts != request.attempt
        ):
            raise ContinuationRejected(
                "replacement request changed the original engineering authority"
            )
        try:
            worktree = self._workspace(request, root)
            if worktree != receipt.capture.to_capture().worktree:
                raise ContinuationRejected("replacement changed the original Coder worktree")
            self._verify_workspace(receipt, request.permissions, self._denied(task))
        except (GitWorkspaceError, MutationInventoryRejected, ValueError) as error:
            raise ContinuationRejected(
                "replacement workspace no longer matches its receipt"
            ) from error
        prior_admissions = self._store.admissions_for_task(task.id)
        existing = next(
            (
                record
                for record in prior_admissions
                if record.interrupted_run_id == receipt.request.run_id
            ),
            None,
        )
        if existing is not None:
            if policy.schema_version == "v2" and (
                request.run_id not in self._prepared or request.run_id in self._starts
            ):
                self._uncertain(task, "已发布接续准入。但原执行是否开始无法确认。现场已保留。")
            if (
                existing.new_request != request
                or existing.next_work_item_id != claim.work_item.id
                or existing.next_lease_id != claim.lease.id
            ):
                self._uncertain(task, "已发布的接续准入不能绑定新的执行或租约。现场已保留。")
        elif len(prior_admissions) >= policy.max_continuations:
            raise InterruptionBudgetExhausted("frozen continuation capability is exhausted")
        record = ContinuationAdmission.create(
            schema_version=policy.schema_version,
            scope=self._scope,
            task_id=task.id,
            interrupted_run_id=receipt.request.run_id,
            receipt_sha256=receipt.receipt_sha256,
            policy_sha256=receipt.policy_sha256,
            new_request=request,
            next_work_item_id=claim.work_item.id,
            next_lease_id=claim.lease.id,
            created_at=existing.created_at if existing is not None else self._clock(),
            interrupted_attempt=receipt.request.attempt if policy.schema_version == "v2" else None,
        )
        with self._guard.write_scope():
            self._require_receipt_current(receipt, self._current_task())
            self._verify_workspace(receipt, request.permissions, self._denied(task))
            self._store.put_admission(record)
        self._prepared.add(request.run_id)
        return (
            "平台按组织工程授权核验了上次中断的草稿。此次是新的独立执行记录。\n"
            "以下完整补丁是已核验的既有工作; 不是 CoderProgress、候选提交或验收结论。\n"
            "请在原范围和权限内继续。不得修改规范、直接提交或宣称未经独立验收的通过。\n"
            f"中断回执: {receipt.receipt_sha256}\n完整补丁:\n{receipt.capture.patch}"
        )

    def started(self, request: AgentRequest, root: Path) -> WorkspaceMutationInventory | None:
        if request.role is not AgentRole.CODER:
            return None
        task = self._current_task()
        if task.interruption_continuation_policy is None:
            return None
        task, claim = self._current(request)
        policy = task.interruption_continuation_policy
        assert policy is not None
        self._require_active_request(request, task)
        if request.run_id in self._starts:
            self._uncertain(task, "同一执行记录已开始。不能再次调用模型。")
        try:
            self._workspace(request, root)
        except (GitWorkspaceError, ValueError) as error:
            raise ContinuationRejected("invocation workspace does not bind its source") from error
        before = capture_mutation_inventory(root)
        self._guard.check()
        capture_start = ExecutionCaptureStart.create(
            scope=self._scope,
            request=request,
            claim=claim,
            task_intent_sha256=task_intent_sha256(task),
            task_revision=self._revision(),
            policy_sha256=policy.policy_sha256,
            worktree_path=str(root),
            inventory_before=before,
            started_at=self._clock(),
        )
        with self._guard.write_scope():
            self._store.put_capture_start(capture_start)
        self._starts[request.run_id] = _Started(
            request,
            task_intent_sha256(task),
            self._revision(),
            claim.work_item.id,
            claim.lease.id,
            before.sha256,
        )
        return before

    def record_native_stop(
        self,
        request: AgentRequest,
        root: Path,
        *,
        process_stop: NativeProcessStop,
        output_present: bool,
        cause: ContinuationCause | None,
        original_error_code: AgentErrorCode | None,
    ) -> None:
        """Seal only the runner's observation, even if ownership ended meanwhile.

        The original claimed start and still-held Task lock own this fact-only
        publication. It cannot write Task, budget, artifacts or a verdict.
        """
        if request.role is not AgentRole.CODER or request.run_id not in self._starts:
            return
        if not self._guard.inherited_fds:
            raise ContinuationRejected("native stop recording requires the original Task lock")
        start = self._store.capture_start(request.run_id)
        if start.request != request or start.worktree_path != str(root):
            raise ContinuationRejected("native stop recording changed its claimed start")
        self._store.put_capture_stop(
            ExecutionCaptureStop.create(
                task_id=request.task_id,
                run_id=request.run_id,
                capture_start_sha256=start.start_sha256,
                process_stop=process_stop,
                output_present=output_present,
                cause=cause,
                original_error_code=original_error_code,
            )
        )

    def interrupted(
        self,
        request: AgentRequest,
        root: Path,
        *,
        before: WorkspaceMutationInventory,
        cause: ContinuationCause,
        original_error_code: AgentErrorCode,
        process_stop: ExecutionStop | None,
        output_present: bool,
    ) -> InterruptionObservation:
        task, claim = self._current(request)
        policy = task.interruption_continuation_policy
        assert policy is not None
        after = capture_mutation_inventory(root)
        mutations = changed_mutation_paths(before, after)
        self._authorize_mutations(request, root, mutations, self._denied(task))
        v2 = policy.schema_version == "v2"
        if not mutations and not v2:
            return InterruptionObservation.UNCHANGED
        noncache_paths = tuple(path for path in mutations if not is_execution_cache_path(path))
        started = self._starts.get(request.run_id)
        if (
            not self._initial(task, request)
            or started is None
            or started.request != request
            or started.inventory_sha256 != before.sha256
            or started.task_intent != task_intent_sha256(task)
            or started.task_revision != self._revision()
            or started.work_item_id != claim.work_item.id
            or started.lease_id != claim.lease.id
            or process_stop is None
            or output_present
            or self._output(request)
            or (not v2 and self._store.receipt_for_task(task.id) is not None)
        ):
            return self._preserved(task, "中断的执行、输出或输入事实无法确认。草稿和历史已保留。")
        if not noncache_paths and not v2:
            return InterruptionObservation.UNCHANGED
        try:
            self._require_active_request(request, task)
            process_stop.validate_integrity()
            self._require_stopped(process_stop, request)
            worktree = self._workspace(request, root)
            capture: WorktreeChangeCapture | WorktreeMutationCapture
            persisted_capture: CapturedChanges | CapturedMutations
            prior_admission = self._store.admission_for_run(request.run_id) if v2 else None
            if v2:
                capture = self._git.capture_mutations(
                    worktree, request.permissions, denied_paths=self._denied(task)
                )
                persisted_capture = CapturedMutations.from_capture(capture)
                inherited_paths = set(request.continuation_changed_paths)
                if prior_admission is not None:
                    inherited_paths.update(
                        self._store.get_receipt(prior_admission.interrupted_run_id)
                        .capture.to_capture()
                        .changed_paths
                    )
                if not set(noncache_paths).issubset(set(capture.changed_paths) | inherited_paths):
                    return self._preserved(
                        task, "存在未进入完整草稿的非缓存变更。现场已保留。等待工程核验。"
                    )
            else:
                capture = self._git.capture_changes(
                    worktree, request.permissions, denied_paths=self._denied(task)
                )
                persisted_capture = CapturedChanges.from_capture(capture)
            if not capture.changed_paths:
                # No source-code draft exists. Authorized disposable cache writes
                # remain an unchanged delivery fact and use ordinary clean retry.
                return InterruptionObservation.UNCHANGED
            if (
                not v2 and noncache_paths != capture.changed_paths
            ) or capture.index_diff_sha256 != _EMPTY_DIFF_SHA256:
                return self._preserved(task, "草稿或暂存区不满足已授权的接续能力。现场已保留。")
            receipt = ExecutionInterruptionReceipt.create(
                schema_version=policy.schema_version,
                scope=self._scope,
                request=request,
                task_intent_sha256=task_intent_sha256(task),
                task_revision=self._revision(),
                original_work_item_id=claim.work_item.id,
                claim_lease_id=claim.lease.id,
                policy_sha256=policy.policy_sha256,
                cause=cause,
                original_error_code=original_error_code,
                process_stop=process_stop,
                process_stop_sha256=process_stop.stop_sha256,
                capture=persisted_capture,
                inventory_before=before,
                inventory_after=after,
                inventory_before_sha256=before.sha256,
                inventory_after_sha256=after.sha256,
                mutation_paths=mutations,
                created_at=self._clock(),
                previous_admission_sha256=(
                    prior_admission.admission_sha256 if prior_admission is not None else None
                ),
            )
            self._verify_workspace(receipt, request.permissions, self._denied(task))
            with self._guard.write_scope():
                current, current_claim = self._current(request)
                if (
                    task_intent_sha256(current) != receipt.task_intent_sha256
                    or self._revision() != receipt.task_revision
                    or current_claim.work_item.id != receipt.original_work_item_id
                    or current_claim.lease.id != receipt.claim_lease_id
                    or self._output(request)
                ):
                    return self._preserved(task, "封存前执行事实已变化。草稿和历史已保留。")
                self._store.put_receipt(receipt)
            return InterruptionObservation.CAPTURED
        except (
            ContinuationRejected,
            GitWorkspaceError,
            MutationInventoryRejected,
            ValueError,
        ) as error:
            if v2:
                raise ContinuationExecutionUncertain(
                    "中断现场不满足安全接续条件。草稿和历史已保留。等待工程核验。"
                ) from error
            return InterruptionObservation.PRESERVED

    def finished(
        self,
        request: AgentRequest,
        root: Path,
        *,
        before: WorkspaceMutationInventory | None,
    ) -> None:
        """Validate native writes before any candidate or progress can be accepted."""
        if request.role is not AgentRole.CODER:
            return
        task = self._current_task()
        if task.interruption_continuation_policy is None:
            return
        current, claimed = self._current(request)
        self._require_active_request(request, current)
        started = self._starts.get(request.run_id)
        if (
            before is None
            or started is None
            or started.request != request
            or started.inventory_sha256 != before.sha256
            or started.task_intent != task_intent_sha256(current)
            or started.task_revision != self._revision()
            or started.work_item_id != claimed.work_item.id
            or started.lease_id != claimed.lease.id
        ):
            raise ContinuationRejected("completed Coder no longer binds its checked invocation")
        try:
            self._workspace(request, root)
            after = capture_mutation_inventory(root)
        except (GitWorkspaceError, MutationInventoryRejected, ValueError) as error:
            raise ContinuationRejected("completed Coder workspace cannot be trusted") from error
        self._authorize_mutations(
            request, root, changed_mutation_paths(before, after), self._denied(current)
        )
        self._guard.check()

    def resume(self, task: Task, repository: TaskRepository) -> int | None:
        """Replay sealed original-WorkItem facts without invoking its Run again."""
        self._guard.check()
        claimed = self._claim()
        attempt_receipts = tuple(
            receipt
            for receipt in self._store.receipts_for_task(task.id)
            if receipt.request.attempt == claimed.work_item.attempt
            and not self._receipt_resolved_by_baseline(receipt)
        )
        if any(
            receipt.original_work_item_id != claimed.work_item.id for receipt in attempt_receipts
        ):
            raise ContinuationRejected("original interruption belongs to another WorkItem")
        receipts = attempt_receipts
        if not receipts:
            return None
        if len(receipts) != 1:
            raise ContinuationRejected("original WorkItem has ambiguous interruption facts")
        receipt = receipts[0]
        current = repository.get(task.id)
        self._require_receipt_current(receipt, current)
        _, claimed = self._current(receipt.request, allow_reserved=True)
        if self._output(receipt.request):
            raise ContinuationRejected("interruption replay already has accepted output")
        if any(
            admission.interrupted_run_id == receipt.request.run_id
            for admission in self._store.admissions_for_task(task.id)
        ):
            self._uncertain(current, "接续已准入。不能重绑原执行。现场已保留。等待工程核验。")
        try:
            self._verify_workspace(receipt, receipt.request.permissions, self._denied(current))
        except (GitWorkspaceError, MutationInventoryRejected, ValueError) as error:
            raise ContinuationRejected("interruption replay workspace cannot be trusted") from error
        successor = self._reserve_attempt(receipt, current, repository)
        if successor is None:
            updated = repository.get(current.id)
            policy = updated.interruption_continuation_policy
            exhausted = (
                updated.retry_policy is not None
                and updated.transient_failures(AgentRole.CODER)
                >= updated.retry_policy.transient_limit(AgentRole.CODER)
                if receipt.cause == "provider_transient"
                else updated.work_budget_exhausted or updated.attempts >= updated.max_attempts
            )
            exhausted = exhausted or (
                policy is not None
                and len(self._store.receipts_for_task(task.id)) > policy.max_continuations
            )
            if exhausted:
                raise InterruptionBudgetExhausted(
                    "interruption replay has no remaining continuation budget"
                )
            self._uncertain(current, "无法按原中断事实预留接续执行。等待工程核验。")
        return successor

    def next_attempt(
        self, task: Task, result: AgentResult, repository: TaskRepository
    ) -> int | None:
        if result.error is None or result.error.code is not AgentErrorCode.WORK_INTERRUPTED:
            return None
        try:
            receipt = next(
                (
                    item
                    for item in self._store.receipts_for_task(task.id)
                    if item.request.run_id == result.run_id
                ),
                None,
            )
        except ContinuationRejected as error:
            policy = task.interruption_continuation_policy
            if policy is not None and policy.schema_version == "v2":
                raise ContinuationExecutionUncertain(
                    "中断记录无法完整核验。现场已保留。等待工程核验。"
                ) from error
            return None
        if receipt is None or self._receipt_resolved_by_baseline(receipt):
            return None
        try:
            current = repository.get(task.id)
            self._require_receipt_current(receipt, current)
            if (
                result.status is not AgentRunStatus.FAILED
                or result.artifact is not None
                or result.task_id != receipt.request.task_id
                or result.role is not AgentRole.CODER
                or result.attempt != receipt.request.attempt
                or result.source_revision != receipt.request.source_revision
                or result.context_manifest_id != receipt.request.context_manifest_id
                or self._output(receipt.request)
                or current.attempts not in (receipt.request.attempt, receipt.request.attempt + 1)
            ):
                return None
            _, claimed = self._current(receipt.request, allow_reserved=True)
            if (
                claimed.lease.id != receipt.claim_lease_id
                or claimed.work_item.id != receipt.original_work_item_id
            ):
                return None
            self._verify_workspace(receipt, receipt.request.permissions, self._denied(current))
            return self._reserve_attempt(receipt, current, repository)
        except (
            ContinuationRejected,
            GitWorkspaceError,
            MutationInventoryRejected,
            ValueError,
        ) as error:
            if (
                current.interruption_continuation_policy is not None
                and current.interruption_continuation_policy.schema_version == "v2"
            ):
                raise ContinuationExecutionUncertain(
                    "中断事实变化。无法安全预留接续执行。现场已保留。等待工程核验。"
                ) from error
            return None

    def _reserve_attempt(
        self,
        receipt: ExecutionInterruptionReceipt,
        current: Task,
        repository: TaskRepository,
    ) -> int | None:
        self._guard.check()
        successor = receipt.request.attempt + 1
        policy = current.interruption_continuation_policy
        if (
            policy is None
            or len(self._store.receipts_for_task(current.id)) > policy.max_continuations
        ):
            return None
        if receipt.cause == "provider_transient":
            if current.retry_policy is None:
                return None
            failure = DeliveryRetryFailure.model_validate(
                {
                    "role": "coder",
                    "attempt": receipt.request.attempt,
                    "code": receipt.original_error_code.value,
                    "run_id": receipt.request.run_id,
                }
            )
            repository.record_retry_failure(current.id, failure)
        else:
            if current.attempts == successor:
                return successor
            if current.work_budget_exhausted or successor > current.max_attempts:
                return None
            repository.record_attempt(current.id, successor)
        self._guard.check()
        updated = repository.get(current.id)
        return (
            successor
            if updated.attempts == successor and updated.status is TaskStatus.IMPLEMENTING
            else None
        )

    def _current(
        self, request: AgentRequest, *, allow_reserved: bool = False
    ) -> tuple[Task, QueueClaim]:
        self._guard.check()
        if not self._guard.inherited_fds:
            raise ContinuationRejected("continuation requires the inherited exclusive Task lock")
        task, claim = self._current_task(), self._claim()
        if (
            task.id != request.task_id
            or task.status is not TaskStatus.IMPLEMENTING
            or (
                task.attempts != request.attempt
                and not (allow_reserved and task.attempts == request.attempt + 1)
            )
            or task.interruption_continuation_policy is None
            or claim.work_item.task_id != task.id
            or claim.work_item.repository_id != self._scope.repository_id
            or claim.work_item.role is not AgentRole.CODER
            or claim.work_item.attempt != request.attempt
            or task.metadata.get("repository_id", self._scope.repository_id)
            != self._scope.repository_id
        ):
            raise ContinuationRejected(
                "continuation requires the exact active claimed Coder checkpoint"
            )
        return task, claim

    def _initial(self, task: Task, request: AgentRequest) -> bool:
        policy = task.interruption_continuation_policy
        if policy is not None and policy.schema_version == "v2":
            self._require_active_request(request, task)
            return task.attempts == request.attempt
        return (
            request.attempt == 1
            and task.attempts == 1
            and self._revision() == 2
            and not task.retry_failures
            and request.source_revision == task.base_ref
            and len(request.input_artifact_ids) == 1
            and request.continuation_checkpoint_id is None
        )

    def _workspace(self, request: AgentRequest, root: Path) -> WorktreeRef:
        worktree = self._git.recover(
            WorktreeSpec(
                task_id=request.task_id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=request.source_revision,
            )
        )
        if worktree.path != root or worktree.detached:
            raise ContinuationRejected("continuation workspace is not the original Coder checkout")
        return worktree

    def _receipt_resolved_by_baseline(self, receipt: ExecutionInterruptionReceipt) -> bool:
        # The trusted callback must validate the current append-only Binding,
        # Task intent, authority and retained full body before returning hashes.
        # Never infer supersession merely from a different source revision.
        if self._resolved_receipts is None:
            return False
        resolved = self._resolved_receipts()
        if len(set(resolved)) != len(resolved):
            raise ContinuationRejected("baseline resolution contains duplicate interruption facts")
        return receipt.receipt_sha256 in resolved

    def _require_receipt_current(self, receipt: ExecutionInterruptionReceipt, task: Task) -> None:
        receipt.validate_integrity()
        policy = task.interruption_continuation_policy
        if (
            receipt.scope != self._scope
            or receipt.request.task_id != task.id
            or task.status is not TaskStatus.IMPLEMENTING
            or task.attempts not in (receipt.request.attempt, receipt.request.attempt + 1)
            or task_intent_sha256(task) != receipt.task_intent_sha256
            or self._revision() != receipt.task_revision
            or policy is None
            or policy.schema_version != receipt.schema_version
            or policy.policy_sha256 != receipt.policy_sha256
            or (policy.schema_version == "v1" and task.base_ref != receipt.request.source_revision)
        ):
            raise ContinuationRejected("continuation receipt no longer binds current Task intent")
        self._require_active_request(receipt.request, task)
        self._require_stopped(receipt.process_stop, receipt.request)

    def _require_active_request(self, request: AgentRequest, task: Task) -> None:
        policy = task.interruption_continuation_policy
        if policy is None or policy.schema_version != "v2":
            return
        if (
            self._source_revision is None
            or self._validate_active_request is None
            or self._has_request_output is None
        ):
            raise ContinuationRejected(
                "v2 continuation requires current source, inputs and exact-output resolvers"
            )
        if request.source_revision != self._source_revision():
            raise ContinuationRejected(
                "Coder request differs from the current delivery checkpoint source"
            )
        self._validate_active_request(request)

    def _output(self, request: AgentRequest) -> bool:
        task = self._current_task()
        policy = task.interruption_continuation_policy
        if policy is not None and policy.schema_version == "v2":
            if self._has_request_output is None:
                raise ContinuationRejected("v2 continuation requires exact accepted-output facts")
            return self._has_request_output(request)
        return self._has_output()

    @staticmethod
    def _uncertain(task: Task, message: str) -> None:
        policy = task.interruption_continuation_policy
        if policy is not None and policy.schema_version == "v2":
            raise ContinuationExecutionUncertain(message)
        raise ContinuationRejected(message)

    def _preserved(self, task: Task, message: str) -> InterruptionObservation:
        policy = task.interruption_continuation_policy
        if policy is not None and policy.schema_version == "v2":
            raise ContinuationExecutionUncertain(message)
        return InterruptionObservation.PRESERVED

    @staticmethod
    def _require_stopped(stop: ExecutionStop, request: AgentRequest | None = None) -> None:
        if isinstance(stop, SynchronousToolLoopStop):
            if request is None:
                raise ContinuationRejected("synchronous stop requires the original exact request")
            stop.require_request(request)
            return
        try:
            os.killpg(stop.group_id, 0)
        except ProcessLookupError:
            return
        except OSError as error:
            raise ContinuationRejected("prior process group state is unknown") from error
        raise ContinuationRejected("prior Coder process group remains alive")

    def _verify_workspace(
        self,
        receipt: ExecutionInterruptionReceipt,
        permissions: AgentPermissions,
        denied_paths: tuple[str, ...],
    ) -> None:
        self._guard.check()
        if isinstance(receipt.capture, CapturedMutations):
            self._git.verify_mutations(
                receipt.capture.to_capture(), permissions, denied_paths=denied_paths
            )
        else:
            self._git.verify_capture(
                receipt.capture.to_capture(), permissions, denied_paths=denied_paths
            )
        current = capture_mutation_inventory(Path(receipt.capture.worktree_path))
        if current != receipt.inventory_after:
            raise ContinuationRejected("workspace mutation inventory drifted after interruption")
        self._guard.check()

    @staticmethod
    def _denied(task: Task) -> tuple[str, ...]:
        return task.constraints.denied_paths if task.constraints else ()

    @staticmethod
    def _authorize_mutations(
        request: AgentRequest, root: Path, paths: tuple[str, ...], denied_paths: tuple[str, ...]
    ) -> None:
        policy = WorkspacePolicy(root, request.permissions, denied_paths=denied_paths)
        for path in paths:
            if is_execution_cache_path(path):
                cache_permissions = request.permissions.model_copy(
                    update={
                        "read_paths": (*request.permissions.read_paths, path),
                        "write_paths": (*request.permissions.write_paths, path),
                    }
                )
                WorkspacePolicy(root, cache_permissions, denied_paths=denied_paths).authorize_write(
                    path
                )
            else:
                policy.authorize_read(path)
                policy.authorize_write(path)
