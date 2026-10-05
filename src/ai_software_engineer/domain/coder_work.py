"""Select bounded serial work without turning every plan package into a Run."""

from __future__ import annotations

from math import ceil

from ai_software_engineer.domain.artifact import (
    Artifact,
    CoderProgressArtifact,
    ImplementationReportArtifact,
    PlanArtifact,
)
from ai_software_engineer.domain.execution_window import CoderWorkSlice
from ai_software_engineer.domain.task import Task


class CoderSliceRejected(ValueError):
    """The input/output cannot prove the frozen step partition."""


def select_coder_work_slice(
    task: Task,
    plan: PlanArtifact,
    *,
    attempt: int,
    source_revision: str,
    progress: CoderProgressArtifact | None,
) -> CoderWorkSlice | None:
    window = plan.content.execution_window
    if window is None:
        # Legacy plans retain their old bytes and execution semantics.
        return None
    if plan.task_id != task.id or attempt != max(task.attempts, 1):
        raise CoderSliceRejected("work slice does not bind the current Task reservation")
    all_ids = tuple(step.step_id for step in plan.content.steps)
    completed: tuple[str, ...] = ()
    if progress is not None:
        if progress.task_id != task.id or progress.source_revision != source_revision:
            raise CoderSliceRejected("work slice progress belongs to another Task or revision")
        completed_set = set(progress.content.completed_step_ids)
        remaining_set = set(progress.content.remaining_step_ids)
        if completed_set | remaining_set != set(all_ids):
            raise CoderSliceRejected("progress must cover the exact complete approved step set")
        completed = tuple(step_id for step_id in all_ids if step_id in completed_set)
    completed_set = set(completed)
    pending = tuple(step_id for step_id in all_ids if step_id not in completed_set)
    if not pending:
        raise CoderSliceRejected("noncandidate progress cannot have no remaining work")
    work_limit = task.retry_policy.max_work_attempts if task.retry_policy else task.max_attempts
    work_remaining = work_limit - max(task.work_attempt, 1) + 1
    if work_remaining < 1:
        raise CoderSliceRejected("frozen Coder work allowance is exhausted")
    # Keep at most one future work attempt for independent QA/Review rework.
    # Sixteen packages with three work attempts become two aggregated slices,
    # not sixteen executions. If only one work slot remains, it covers all pending work.
    slots = max(1, work_remaining - window.reserve_rework_attempts)
    count = ceil(len(pending) / slots)
    return CoderWorkSlice(
        task_id=task.id,
        attempt=attempt,
        source_revision=source_revision,
        plan_artifact_id=plan.artifact_id,
        plan_sha256=plan.integrity.sha256,
        window=window,
        authorized_work_remaining=work_remaining,
        completed_step_ids=completed,
        selected_step_ids=pending[:count],
        later_step_ids=pending[count:],
    )


def validate_coder_slice_output(work: CoderWorkSlice, artifact: Artifact) -> None:
    if artifact.task_id != work.task_id:
        raise CoderSliceRejected("Coder output belongs to another work slice")
    if isinstance(artifact, ImplementationReportArtifact):
        if work.later_step_ids:
            raise CoderSliceRejected("a bounded partial slice cannot publish a complete candidate")
        return
    if not isinstance(artifact, CoderProgressArtifact):
        raise CoderSliceRejected("work slice requires implementation-report or coder-progress")
    if artifact.source_revision != work.source_revision:
        raise CoderSliceRejected("progress changed the slice source revision")
    completed = set(artifact.content.completed_step_ids)
    remaining = set(artifact.content.remaining_step_ids)
    expected = set((*work.completed_step_ids, *work.selected_step_ids, *work.later_step_ids))
    if completed | remaining != expected or completed & remaining:
        raise CoderSliceRejected("progress must partition the exact complete approved step set")
    if not set(work.completed_step_ids) <= completed:
        raise CoderSliceRejected("progress cannot erase previously completed steps")
    if not completed <= set((*work.completed_step_ids, *work.selected_step_ids)):
        raise CoderSliceRejected("progress completed steps outside the current bounded slice")
    if not set(work.later_step_ids) <= remaining:
        raise CoderSliceRejected("progress cannot omit deferred plan steps")


def successor_coder_work_slice(work: CoderWorkSlice, *, consume_work: bool) -> CoderWorkSlice:
    """Recompute the exact next bounded partition from a sealed interrupted slice.

    A local execution window consumes one work reservation; provider failures
    consume transient allowance instead. The current Task/plan/progress must
    separately validate this result before a model invocation.
    """
    remaining = work.authorized_work_remaining - int(consume_work)
    if remaining < 1:
        raise CoderSliceRejected("interrupted work slice has no authorized successor")
    pending = (*work.selected_step_ids, *work.later_step_ids)
    slots = max(1, remaining - work.window.reserve_rework_attempts)
    count = ceil(len(pending) / slots)
    return CoderWorkSlice.model_validate(
        {
            **work.to_wire(),
            "attempt": work.attempt + 1,
            "authorized_work_remaining": remaining,
            "selected_step_ids": pending[:count],
            "later_step_ids": pending[count:],
        }
    )
