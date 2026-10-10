"""Reconcile original durable execution facts without impersonating an old Worker."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git.mutation import (
    capture_mutation_inventory,
    changed_mutation_paths,
    is_execution_cache_path,
)
from ai_software_engineer.git.ports import WorktreeSpec
from ai_software_engineer.orchestration.continuation import (
    ContinuationGitWorkspace,
    NativeCoderContinuation,
)
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.recovery.models import CapturedChanges
from ai_software_engineer.work_queue.models import QueueClaim


class CaptureStopProcessUncertain(ContinuationRejected):
    """The exact original process group is live or cannot be checked safely."""


def validate_capture_stop(
    *,
    start: ExecutionCaptureStart,
    stop: ExecutionCaptureStop,
    task: Task,
    task_revision: int,
    historical_claim: QueueClaim,
    task_lock: ExecutionGuard,
    validate_inputs: Callable[[AgentRequest], None],
) -> None:
    """Verify the original owned stop; it proves no outcome or checkpoint readiness."""
    start.validate_integrity()
    stop.validate_integrity()
    request, policy = start.request, task.interruption_continuation_policy
    claim, recorded = historical_claim, start.claim
    if (
        not task_lock.inherited_fds
        or task.status is not TaskStatus.IMPLEMENTING
        or request.task_id != task.id
        or task.attempts != request.attempt
        or task_intent_sha256(task) != start.task_intent_sha256
        or task_revision != start.task_revision
        or policy is None
        or policy.policy_sha256 != start.policy_sha256
        or stop.task_id != task.id
        or stop.run_id != request.run_id
        or stop.capture_start_sha256 != start.start_sha256
        or stop.process_stop.stopped_at < start.started_at
        or claim.assignment != recorded.assignment
        or claim.model_selection != recorded.model_selection
        # Heartbeats legitimately extend expires_at; all immutable lease and
        # producer fields must still match the original sealed claim.
        or claim.lease.model_dump(exclude={"expires_at"})
        != recorded.lease.model_dump(exclude={"expires_at"})
        or claim.work_item != recorded.work_item
        or claim.worker_id != recorded.worker_id
        or claim.claimed_at != recorded.claimed_at
    ):
        raise ContinuationRejected("原执行事实不足以安全保存接续现场, 原记录与草稿保留")
    validate_inputs(request)
    try:
        NativeCoderContinuation._require_stopped(stop.process_stop, request)
    except ContinuationRejected as error:
        raise CaptureStopProcessUncertain("原执行进程组仍在运行或状态未知, 暂不能处理") from error


def reconcile_capture(
    *,
    start: ExecutionCaptureStart,
    stop: ExecutionCaptureStop,
    task: Task,
    task_revision: int,
    historical_claim: QueueClaim,
    store: FileContinuationStore,
    git: ContinuationGitWorkspace,
    task_lock: ExecutionGuard,
    validate_inputs: Callable[[AgentRequest], None],
    has_output: Callable[[AgentRequest], bool],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExecutionInterruptionReceipt:
    """Only a known stopped, output-absent failure can produce a complete receipt.

    Composition also holds the queue's idle Task fence. No original live claim,
    retry budget transaction, provider call, candidate or verdict is fabricated.
    """
    validate_capture_stop(
        start=start,
        stop=stop,
        task=task,
        task_revision=task_revision,
        historical_claim=historical_claim,
        task_lock=task_lock,
        validate_inputs=validate_inputs,
    )
    request, policy = start.request, task.interruption_continuation_policy
    assert policy is not None
    if (
        stop.cause is None
        or stop.original_error_code is None
        or stop.output_present
        or has_output(request)
    ):
        raise ContinuationRejected("原执行事实不足以安全保存接续现场, 原记录与草稿保留")
    worktree = git.recover(
        WorktreeSpec(
            task_id=task.id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=request.source_revision,
        )
    )
    if worktree.detached or str(worktree.path) != start.worktree_path:
        raise ContinuationRejected("中断收集不再绑定原 Coder 工作区")
    before, after = start.inventory_before, capture_mutation_inventory(worktree.path)
    mutations = changed_mutation_paths(before, after)
    denied = task.constraints.denied_paths if task.constraints else ()
    NativeCoderContinuation._authorize_mutations(request, worktree.path, mutations, denied)
    noncache = tuple(path for path in mutations if not is_execution_cache_path(path))
    admission = store.admission_for_run(request.run_id) if policy.schema_version == "v2" else None
    if policy.schema_version == "v2":
        capture = git.capture_mutations(worktree, request.permissions, denied_paths=denied)
        persisted: CapturedMutations | CapturedChanges = CapturedMutations.from_capture(capture)
        inherited = set(request.continuation_changed_paths)
        if admission is not None:
            inherited.update(
                store.get_receipt(admission.interrupted_run_id).capture.to_capture().changed_paths
            )
        if not set(noncache).issubset(set(capture.changed_paths) | inherited):
            raise ContinuationRejected("完整现场未覆盖全部非缓存变更")
    else:
        legacy_capture = git.capture_changes(worktree, request.permissions, denied_paths=denied)
        persisted = CapturedChanges.from_capture(legacy_capture)
        if noncache != legacy_capture.changed_paths:
            raise ContinuationRejected("旧版本接续现场未覆盖完整草稿")
    if policy.schema_version == "v1" and not persisted.to_capture().changed_paths:
        raise ContinuationRejected("本次没有可保存的源码草稿, 不能补造 checkpoint")
    receipt = ExecutionInterruptionReceipt.create(
        schema_version=policy.schema_version,
        scope=start.scope,
        request=request,
        task_intent_sha256=start.task_intent_sha256,
        task_revision=start.task_revision,
        original_work_item_id=start.claim.work_item.id,
        claim_lease_id=start.claim.lease.id,
        policy_sha256=start.policy_sha256,
        cause=stop.cause,
        original_error_code=stop.original_error_code,
        process_stop=stop.process_stop,
        process_stop_sha256=stop.process_stop.stop_sha256,
        capture=persisted,
        inventory_before=before,
        inventory_after=after,
        inventory_before_sha256=before.sha256,
        inventory_after_sha256=after.sha256,
        mutation_paths=mutations,
        created_at=max(clock(), stop.process_stop.stopped_at),
        previous_admission_sha256=admission.admission_sha256 if admission else None,
    )
    # Full capture validation includes HEAD, index, complete bodies and write policy.
    if isinstance(persisted, CapturedMutations):
        git.verify_mutations(persisted.to_capture(), request.permissions, denied_paths=denied)
    else:
        git.verify_capture(persisted.to_capture(), request.permissions, denied_paths=denied)
    validate_inputs(request)
    if has_output(request) or capture_mutation_inventory(Path(start.worktree_path)) != after:
        raise ContinuationRejected("封存前原执行结果或工作现场已变化")
    return store.put_receipt(receipt)
