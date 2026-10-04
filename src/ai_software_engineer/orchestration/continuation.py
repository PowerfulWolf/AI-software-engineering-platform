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
    InterruptionBudgetExhausted,
    InterruptionObservation,
)
from ai_software_engineer.agents.execution import ExecutionGuard, NativeProcessStop
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
from ai_software_engineer.git.policy import WorkspacePolicy
from ai_software_engineer.git.ports import WorktreeRef, WorktreeSnapshot, WorktreeSpec
from ai_software_engineer.git.worktree import GitWorkspaceError
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationAdmission,
    ContinuationRecordMissing,
    ContinuationRejected,
    ContinuationScope,
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


@dataclass(frozen=True, slots=True)
class _Started:
    request: AgentRequest
    task_intent: str
    task_revision: int
    work_item_id: str
    lease_id: str
    inventory_sha256: str


class NativeCoderContinuation:
    """Observe, seal and admit once; queue owners still decide actual dispatch."""

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
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._scope, self._store, self._git, self._guard = scope, store, git_workspace, guard
        self._current_task, self._revision, self._claim = current_task, current_revision, claim
        self._has_output, self._clock = has_accepted_output, clock
        self._starts: dict[str, _Started] = {}

    def prepare(self, request: AgentRequest, root: Path) -> str | None:
        if request.role is not AgentRole.CODER or request.attempt != 2:
            return None
        receipt = self._store.receipt_for_task(request.task_id)
        if receipt is None:
            return None
        task, claim = self._current(request)
        self._require_receipt_current(receipt, task)
        if (
            self._has_output()
            or request.run_id == receipt.request.run_id
            or request.context_manifest_id == receipt.request.context_manifest_id
            or claim.lease.id == receipt.claim_lease_id
            or claim.work_item.id == receipt.original_work_item_id
            or claim.work_item.parent_work_item_id != receipt.original_work_item_id
            or request.source_revision != receipt.request.source_revision
            or request.permissions != receipt.request.permissions
            or request.timeout_seconds != receipt.request.timeout_seconds
            or request.output_schema != receipt.request.output_schema
            or request.input_artifact_ids != receipt.request.input_artifact_ids
            or request.expected_parent_artifact_ids != receipt.request.expected_parent_artifact_ids
            or request.expected_supersedes_by_kind != receipt.request.expected_supersedes_by_kind
            or request.continuation_checkpoint_id is not None
            or task.attempts != 2
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
        record = ContinuationAdmission.create(
            scope=self._scope,
            task_id=task.id,
            interrupted_run_id=receipt.request.run_id,
            receipt_sha256=receipt.receipt_sha256,
            policy_sha256=receipt.policy_sha256,
            new_request=request,
            next_work_item_id=claim.work_item.id,
            next_lease_id=claim.lease.id,
            created_at=self._clock(),
        )
        try:
            existing = self._store.get_admission(task.id)
        except ContinuationRecordMissing:
            existing = None
        if existing is not None:
            # Timestamp is the original decision, never a new permission on replay.
            record = record.model_copy(update={"created_at": existing.created_at})
            record = record.model_copy(update={"admission_sha256": record.recompute_sha256()})
        with self._guard.write_scope():
            self._require_receipt_current(receipt, self._current_task())
            self._verify_workspace(receipt, request.permissions, self._denied(task))
            self._store.put_admission(record)
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
        try:
            self._workspace(request, root)
        except (GitWorkspaceError, ValueError) as error:
            raise ContinuationRejected("invocation workspace does not bind its source") from error
        before = capture_mutation_inventory(root)
        self._guard.check()
        self._starts[request.run_id] = _Started(
            request,
            task_intent_sha256(task),
            self._revision(),
            claim.work_item.id,
            claim.lease.id,
            before.sha256,
        )
        return before

    def interrupted(
        self,
        request: AgentRequest,
        root: Path,
        *,
        before: WorkspaceMutationInventory,
        cause: ContinuationCause,
        original_error_code: AgentErrorCode,
        process_stop: NativeProcessStop | None,
        output_present: bool,
    ) -> InterruptionObservation:
        task, claim = self._current(request)
        after = capture_mutation_inventory(root)
        mutations = changed_mutation_paths(before, after)
        # True write violations retain their policy classification, including
        # ignored files and explicit denies inside otherwise allowed caches.
        self._authorize_mutations(request, root, mutations, self._denied(task))
        if not mutations:
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
            or self._has_output()
            or self._store.receipt_for_task(task.id) is not None
        ):
            return InterruptionObservation.PRESERVED
        # Cache-only writes have been observed and authorized, but are not a
        # resumable source-code draft. They remain an unchanged delivery fact.
        if not noncache_paths:
            return InterruptionObservation.UNCHANGED
        try:
            policy = task.interruption_continuation_policy
            if policy is None:
                return InterruptionObservation.PRESERVED
            process_stop.validate_integrity()
            self._require_stopped(process_stop)
            worktree = self._workspace(request, root)
            capture = self._git.capture_changes(
                worktree, request.permissions, denied_paths=self._denied(task)
            )
            paths = tuple(path for path in mutations if not is_execution_cache_path(path))
            if (
                not capture.changed_paths
                or paths != capture.changed_paths
                or capture.index_diff_sha256 != _EMPTY_DIFF_SHA256
            ):
                return InterruptionObservation.PRESERVED
            receipt = ExecutionInterruptionReceipt.create(
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
                capture=CapturedChanges.from_capture(capture),
                inventory_before=before,
                inventory_after=after,
                inventory_before_sha256=before.sha256,
                inventory_after_sha256=after.sha256,
                mutation_paths=mutations,
                created_at=self._clock(),
            )
            self._verify_workspace(receipt, request.permissions, self._denied(task))
            with self._guard.write_scope():
                current, current_claim = self._current(request)
                if (
                    task_intent_sha256(current) != receipt.task_intent_sha256
                    or self._revision() != receipt.task_revision
                    or current_claim.work_item.id != receipt.original_work_item_id
                    or current_claim.lease.id != receipt.claim_lease_id
                    or self._has_output()
                ):
                    return InterruptionObservation.PRESERVED
                self._store.put_receipt(receipt)
            return InterruptionObservation.CAPTURED
        except (ContinuationRejected, GitWorkspaceError, MutationInventoryRejected, ValueError):
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
        # recover requires the original source HEAD, before platform candidate
        # publication. A native commit cannot bypass inventory validation.
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
        """Replay sealed interruption facts without invoking the original Run again."""
        receipt = self._store.receipt_for_task(task.id)
        if receipt is None:
            return None
        self._guard.check()
        claimed = self._claim()
        if claimed.work_item.attempt != 1:
            # A replacement claim uses prepare's one-use admission, not the
            # old WorkItem crash-replay path.
            return None
        current = repository.get(task.id)
        self._require_receipt_current(receipt, current)
        _, claimed = self._current(receipt.request, allow_reserved=True)
        if claimed.work_item.id != receipt.original_work_item_id or self._has_output():
            raise ContinuationRejected("interruption replay is not the original claimed WorkItem")
        try:
            self._store.get_admission(task.id)
        except ContinuationRecordMissing:
            pass
        else:
            raise ContinuationRejected("an admitted replacement cannot be rebound after restart")
        try:
            self._verify_workspace(receipt, receipt.request.permissions, self._denied(current))
        except (GitWorkspaceError, MutationInventoryRejected, ValueError) as error:
            raise ContinuationRejected("interruption replay workspace cannot be trusted") from error
        # _require_receipt_current has proven the old process group stopped;
        # the new lease owns the same original WorkItem and exclusive Task lock.
        # A different lease is expected after reclaim, never proof of a new Run.
        successor = self._reserve_attempt(receipt, current, repository)
        if successor is None:
            updated = repository.get(current.id)
            exhausted = (
                updated.retry_policy is not None
                and updated.transient_failures(AgentRole.CODER)
                >= updated.retry_policy.transient_limit(AgentRole.CODER)
                if receipt.cause == "provider_transient"
                else updated.work_budget_exhausted or updated.attempts >= updated.max_attempts
            )
            if exhausted:
                raise InterruptionBudgetExhausted(
                    "interruption replay has no remaining continuation budget"
                )
            raise ContinuationRejected("interruption replay cannot reserve a replacement")
        return successor

    def next_attempt(
        self, task: Task, result: AgentResult, repository: TaskRepository
    ) -> int | None:
        receipt = self._store.receipt_for_task(task.id)
        if (
            receipt is None
            or result.error is None
            or result.error.code is not AgentErrorCode.WORK_INTERRUPTED
        ):
            return None
        try:
            current = repository.get(task.id)
            self._require_receipt_current(receipt, current)
            if (
                result.status is not AgentRunStatus.FAILED
                or result.artifact is not None
                or result.run_id != receipt.request.run_id
                or result.task_id != receipt.request.task_id
                or result.role is not AgentRole.CODER
                or result.attempt != 1
                or result.source_revision != receipt.request.source_revision
                or result.context_manifest_id != receipt.request.context_manifest_id
                or self._has_output()
                or current.attempts not in (1, 2)
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
        except (ContinuationRejected, GitWorkspaceError, MutationInventoryRejected, ValueError):
            return None

    def _reserve_attempt(
        self,
        receipt: ExecutionInterruptionReceipt,
        current: Task,
        repository: TaskRepository,
    ) -> int | None:
        self._guard.check()
        if receipt.cause == "provider_transient":
            if current.retry_policy is None:
                return None
            failure = DeliveryRetryFailure.model_validate(
                {
                    "role": "coder",
                    "attempt": 1,
                    "code": receipt.original_error_code.value,
                    "run_id": receipt.request.run_id,
                }
            )
            # Exhaustion is a durable failure too. Exact replay after a crash
            # cannot obtain another debit or a free replacement identity.
            repository.record_retry_failure(current.id, failure)
        else:
            if current.attempts == 2:
                return 2
            if current.work_budget_exhausted or current.attempts >= current.max_attempts:
                return None
            repository.record_attempt(current.id, 2)
        self._guard.check()
        updated = repository.get(current.id)
        return 2 if updated.attempts == 2 and updated.status is TaskStatus.IMPLEMENTING else None

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
                and not (allow_reserved and task.attempts == 2 and request.attempt == 1)
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

    def _require_receipt_current(self, receipt: ExecutionInterruptionReceipt, task: Task) -> None:
        receipt.validate_integrity()
        policy = task.interruption_continuation_policy
        if (
            receipt.scope != self._scope
            or receipt.request.task_id != task.id
            or task.status is not TaskStatus.IMPLEMENTING
            or task.attempts not in (1, 2)
            or task_intent_sha256(task) != receipt.task_intent_sha256
            or self._revision() != receipt.task_revision
            or policy is None
            or policy.policy_sha256 != receipt.policy_sha256
            or task.base_ref != receipt.request.source_revision
        ):
            raise ContinuationRejected("continuation receipt no longer binds current Task intent")
        self._require_stopped(receipt.process_stop)

    @staticmethod
    def _require_stopped(stop: NativeProcessStop) -> None:
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
                # This capability permits exact disposable cache paths; explicit
                # Task denies and protected-directory checks still take precedence.
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
