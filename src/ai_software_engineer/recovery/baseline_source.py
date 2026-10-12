"""Read-only terminal source epochs from fully verified engineering baselines."""

from dataclasses import dataclass
from pathlib import Path

from ai_software_engineer.context.execution_baseline import execution_baseline_from_context
from ai_software_engineer.context.models import ContextBundle
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.execution_baseline import (
    BaselineInputMode,
    ExecutionBaselineBinding,
)
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.recovery.models import RecoveryScope
from ai_software_engineer.team_workspace import _reject_symlinks
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart

LEGACY_CAPACITY_REASON = (
    "BUDGET_EXHAUSTED: Required context exceeds the configured input budget; no automatic retry."
)


@dataclass(frozen=True, slots=True)
class RecoveryBaselineEpoch:
    """A store-verified binding and its exact sealed execution reservation."""

    binding: ExecutionBaselineBinding
    minimum_attempt: int


def read_recovery_baseline_epochs(
    sidecar: Path, task: Task, scope: RecoveryScope, *, project_id: str
) -> tuple[RecoveryBaselineEpoch, ...]:
    root = sidecar / "state/execution-baselines" / task.id
    _reject_symlinks(root)
    if not root.exists():
        return ()
    store = FileExecutionBaselineStore(root, read_only=True)
    epochs = []
    for binding in store.bindings_for_task(task.id):
        binding.require_task(task)
        if (
            binding.scope.team_id,
            binding.scope.project_id,
            binding.scope.repository_id,
            binding.scope.repository_root,
        ) != (scope.team_id, project_id, scope.repository_id, scope.repository_root):
            raise ValueError("recovery baseline source scope mismatch")
        plan = store.plan(binding.plan_sha256)
        if binding.prior_task_revision != plan.facts.task_revision:
            raise ValueError("recovery baseline source revision mismatch")
        reservation = plan.facts.continuation
        minimum = (
            reservation.next_execution_attempt
            if reservation is not None
            else max(1, plan.facts.task.attempts)
        )
        epochs.append(RecoveryBaselineEpoch(binding, minimum))
    return tuple(epochs)


def validate_pre_candidate_sources(
    task: Task,
    events: tuple[StateEvent, ...],
    epochs: tuple[RecoveryBaselineEpoch, ...],
) -> None:
    """An arbitrary source appearing somewhere in the history never qualifies."""
    _validate_source_epochs(task, events, epochs, legacy_capacity_terminal=False)


def validate_legacy_capacity_pre_candidate_sources(
    task: Task,
    events: tuple[StateEvent, ...],
    epochs: tuple[RecoveryBaselineEpoch, ...],
) -> None:
    """Accept only the known terminal no-start bug; never rewrite the original event.

    The dedicated capacity reader must additionally verify the complete final Context,
    latest retained baseline, ended claim and absence of all invocation facts.
    """
    if (
        not events
        or not epochs
        or task.status is not TaskStatus.BLOCKED
        or epochs[-1].binding.input_mode is not BaselineInputMode.CODER_REAPPLY
        or events[-1].task_id != task.id
        or events[-1].from_status is not TaskStatus.IMPLEMENTING
        or events[-1].to_status is not TaskStatus.BLOCKED
        or events[-1].attempt != task.attempts
        or events[-1].reason != LEGACY_CAPACITY_REASON
    ):
        raise ValueError("not the exact legacy terminal capacity source exception")
    if events[-1].artifact_ids:
        plans = tuple(
            event
            for event in events[:-1]
            if event.from_status is TaskStatus.PLANNING
            and event.to_status is TaskStatus.IMPLEMENTING
            and event.reason == "plan_validated"
        )
        if (
            len(plans) != 1
            or len(plans[0].artifact_ids) != 1
            or events[-1].artifact_ids != plans[0].artifact_ids
        ):
            raise ValueError("legacy capacity terminal differs from its original Plan reference")
    _validate_source_epochs(task, events, epochs, legacy_capacity_terminal=True)


def _validate_source_epochs(
    task: Task,
    events: tuple[StateEvent, ...],
    epochs: tuple[RecoveryBaselineEpoch, ...],
    *,
    legacy_capacity_terminal: bool,
) -> None:
    previous = None
    for epoch in epochs:
        binding = epoch.binding
        binding.require_task(task)
        binding.require_predecessor(previous)
        if (
            binding.prior_task_revision >= len(events)
            or not 1 <= epoch.minimum_attempt <= task.attempts
            or (previous is not None and binding.prior_task_revision < previous.prior_task_revision)
        ):
            raise ValueError("recovery baseline epoch is outside the terminal history")
        previous = binding
    for revision, event in enumerate(events, 1):
        selected = next(
            (item for item in reversed(epochs) if item.binding.prior_task_revision < revision),
            None,
        )
        expected = task.base_ref
        if selected is not None:
            binding = selected.binding
            if event.occurred_at < binding.completed_at or event.attempt < selected.minimum_attempt:
                raise ValueError("pre-candidate event source precedes its exact execution epoch")
            expected = binding.execution_source_revision
        if event.source_revision != expected:
            if (
                legacy_capacity_terminal
                and selected is not None
                and revision == len(events)
                and event.source_revision == task.base_ref
            ):
                continue
            raise ValueError("pre-candidate event source revision mismatch")


def require_terminal_baseline_context(
    sidecar: Path,
    task: Task,
    context: ContextBundle,
    epochs: tuple[RecoveryBaselineEpoch, ...],
    *,
    run_id: str,
    request_sha256: str,
    attempt: int,
    source_revision: str,
) -> ExecutionBaselineBinding | None:
    """Read the original exact request, rather than reconstructing model authority."""
    if not epochs:
        if any(section.name == "execution.baseline" for section in context.sections):
            raise ValueError("terminal context has no verified execution baseline history")
        return None
    root = sidecar / "state/invocations"
    _reject_symlinks(root)
    starts = KnowledgeRecordStore(root, read_only=True).list(
        "invocation-starts", DeliveryInvocationStart
    )
    matching = tuple(start for start in starts if start.request.run_id == run_id)
    if len(matching) != 1:
        raise ValueError("terminal baseline has no unique original invocation request")
    start = matching[0]
    start.validate_integrity()
    request, latest = start.request, epochs[-1].binding
    if (
        request.task_id != task.id
        or request.role is not AgentRole.CODER
        or request.context_manifest_id != context.context_id
        or request.attempt != attempt
        or request.source_revision != source_revision
        or digest(request.to_wire()) != request_sha256
        or request.execution_baseline_sha256 != latest.binding_sha256
        or request.execution_base_ref != latest.execution_base_ref
        or request.attempt < epochs[-1].minimum_attempt
        or start.started_at < latest.completed_at
        or start.checkpoint_sequence < latest.prior_task_revision
    ):
        raise ValueError("terminal request differs from the exact latest execution baseline")
    baseline_root = sidecar / "state/execution-baselines" / task.id
    # Historical v1 callers may already supply fully verified epochs. They
    # retain their original inline-patch contract. V2 refuses an absent reader
    # in execution_baseline_from_context rather than trusting the projection.
    verifier = (
        StoredCoderExecutionInputResolver(FileExecutionBaselineStore(baseline_root, read_only=True))
        if baseline_root.exists()
        else None
    )
    observed = execution_baseline_from_context(
        context,
        request,
        task,
        verifier=verifier,
    )
    if observed != latest:
        raise ValueError("terminal context differs from the store-verified execution baseline")
    return latest
