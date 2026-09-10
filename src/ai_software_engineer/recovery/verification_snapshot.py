"""Read-only SQL evidence for terminal post-candidate verification.

Native checkpoint projections from old platform versions may lag actual runtime facts.
This reader checks immutable dispatch identity but derives status/revision from SQL. It
does not authorize execution or replace the required upstream/joint provenance checks.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from pymysql.cursors import DictCursor

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import Task, TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.project_manager.delivery_checkpoint import ProjectDeliveryCheckpoint
from ai_software_engineer.project_manager.dispatch import (
    DeliveryAllocation,
    DispatchCommitRecord,
)
from ai_software_engineer.project_manager.mysql_dispatch_authority import _decode_allocation
from ai_software_engineer.recovery.allocation_lineage import resolve_planner_dispatch
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.store.mysql_repository import (
    _decode_event,
    _decode_task,
    _non_negative_int,
    _text,
    open_mysql_connection,
)


@dataclass(frozen=True, slots=True)
class CandidateRuntimeSnapshot:
    task: Task
    revision: int
    dispatch: DeliveryAllocation
    planner_dispatch: DispatchCommitRecord
    events: tuple[StateEvent, ...]


def validate_candidate_snapshot(
    checkpoint: ProjectDeliveryCheckpoint, snapshot: CandidateRuntimeSnapshot
) -> None:
    """Validate actual runtime progress without trusting stale cached status/candidate."""
    task, dispatch, events = snapshot.task, snapshot.dispatch, snapshot.events
    normalized = task.model_copy(
        update={
            "status": TaskStatus.NEW,
            "attempts": 0,
            "updated_at": dispatch.task.updated_at,
        }
    )
    if (
        checkpoint.task_id != task.id
        or checkpoint.dispatch_commit_id != dispatch.id
        or checkpoint.dispatch_commit_sha256 != dispatch.dispatch_sha256
        or checkpoint.project_id != dispatch.project_id
        or checkpoint.project_root != task.repository
        or normalized != dispatch.task
        or task.status not in (TaskStatus.FAILED, TaskStatus.BLOCKED)
        or snapshot.revision != len(events)
        or len(events) < 2
        or (checkpoint.task_revision is not None and checkpoint.task_revision > snapshot.revision)
    ):
        raise RecoveryRejected("candidate runtime does not match its original dispatch")
    previous = TaskStatus.NEW
    previous_time = task.created_at
    for event in events:
        if (
            event.task_id != task.id
            or event.from_status is not previous
            or event.attempt > task.attempts
            or event.occurred_at < previous_time
        ):
            raise RecoveryRejected("candidate runtime event chain is inconsistent")
        previous, previous_time = event.to_status, event.occurred_at
    terminal_candidate_event(task, events)
    if previous is not task.status or previous_time != task.updated_at:
        raise RecoveryRejected("runtime is not a terminal post-candidate QA failure")


def candidate_event(events: tuple[StateEvent, ...]) -> tuple[int, StateEvent]:
    """Return the latest candidate checkpoint retained before a terminal retry failure."""
    matches = tuple(
        (index, event)
        for index, event in enumerate(events)
        if event.to_status is TaskStatus.QA
        and event.reason in {"candidate_ready", "candidate_recovered"}
    )
    if not matches:
        raise RecoveryRejected("terminal runtime has no candidate checkpoint")
    index, event = matches[-1]
    if (
        len(event.artifact_ids) != 1
        or len(event.source_revision) not in (40, 64)
        or any(character not in "0123456789abcdef" for character in event.source_revision)
    ):
        raise RecoveryRejected("candidate checkpoint identity is invalid")
    return index, event


def terminal_candidate_event(task: Task, events: tuple[StateEvent, ...]) -> StateEvent:
    """Return a candidate only when the remaining events form a valid terminal tail."""
    index, candidate = candidate_event(events)
    if not _valid_terminal_tail(task, events[index + 1 :], candidate):
        raise RecoveryRejected("runtime is not a terminal post-candidate QA failure")
    return candidate


def _valid_terminal_tail(
    task: Task,
    tail: tuple[StateEvent, ...],
    candidate: StateEvent,
) -> bool:
    if not tail:
        return False
    current = TaskStatus.QA
    offset = 0
    if (
        tail[0].from_status is TaskStatus.QA
        and tail[0].to_status is TaskStatus.REVIEW
        and tail[0].reason == "qa_passed"
    ):
        if tail[0].source_revision != candidate.source_revision:
            return False
        current, offset = TaskStatus.REVIEW, 1
    remaining = tail[offset:]
    if len(remaining) == 1:
        terminal = remaining[0]
        return (
            terminal.from_status is current
            and terminal.to_status is task.status
            and terminal.source_revision in (task.base_ref, candidate.source_revision)
        )
    feedback_reason = {
        TaskStatus.QA: "qa_failed_route_to_coder",
        TaskStatus.REVIEW: "review_rejected_route_to_coder",
    }[current]
    if len(remaining) != 2:
        return False
    feedback, terminal = remaining
    return (
        feedback.from_status is current
        and feedback.to_status is TaskStatus.IMPLEMENTING
        and feedback.reason == feedback_reason
        and feedback.source_revision == candidate.source_revision
        and terminal.from_status is TaskStatus.IMPLEMENTING
        and terminal.to_status is task.status
        and terminal.source_revision in (task.base_ref, candidate.source_revision)
    )


def read_candidate_snapshot(
    config: ProductionConfig,
    environment: Mapping[str, str],
    checkpoint: ProjectDeliveryCheckpoint,
    history: tuple[ProjectDeliveryCheckpoint, ...],
) -> CandidateRuntimeSnapshot:
    """One consistent read-only transaction; no repository construction or DDL."""
    if checkpoint.task_id is None or checkpoint.dispatch_commit_id is None:
        raise RecoveryRejected("missing original Task or dispatch reference")
    if not history or history[-1] != checkpoint:
        raise RecoveryRejected("candidate checkpoint history is incomplete")
    connection = open_mysql_connection(config.require_mysql_dsn(environment))
    try:
        with connection.cursor(DictCursor) as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            allocations: dict[str, DeliveryAllocation] = {}
            for historic in history:
                commit_id = historic.dispatch_commit_id
                if commit_id is None or commit_id in allocations:
                    continue
                cursor.execute("SELECT * FROM dispatch_commits WHERE id = %s", (commit_id,))
                row = cursor.fetchone()
                if row is None:
                    raise RecoveryRejected("candidate dispatch history is missing")
                allocation = _decode_allocation(row)
                if (
                    allocation.id != commit_id
                    or allocation.dispatch_sha256 != historic.dispatch_commit_sha256
                    or allocation.project_id != historic.project_id
                    or allocation.task_id != historic.task_id
                ):
                    raise RecoveryRejected("candidate dispatch history is inconsistent")
                allocations[commit_id] = allocation
            dispatch = allocations[checkpoint.dispatch_commit_id]
            planner_dispatch = resolve_planner_dispatch(dispatch, allocations, history)
            cursor.execute("SELECT * FROM tasks WHERE id = %s", (checkpoint.task_id,))
            row = cursor.fetchone()
            if row is None:
                raise RecoveryRejected("original Task is missing")
            task = _decode_task(checkpoint.task_id, _text(row, "payload_json"))
            revision = _non_negative_int(row, "revision")
            if _text(row, "status") != task.status.value:
                raise RecoveryRejected("Task status columns disagree")
            cursor.execute(
                "SELECT * FROM state_events WHERE task_id = %s ORDER BY revision", (task.id,)
            )
            rows = cursor.fetchall()
            if [r["revision"] for r in rows] != list(range(1, revision + 1)):
                raise RecoveryRejected("candidate runtime event revisions have gaps")
            events = tuple(_decode_event(_text(r, "payload_json")) for r in rows)
            if any(
                event.event_id != row["event_id"] for event, row in zip(events, rows, strict=True)
            ):
                raise RecoveryRejected("candidate event identities disagree")
            snapshot = CandidateRuntimeSnapshot(task, revision, dispatch, planner_dispatch, events)
            validate_candidate_snapshot(checkpoint, snapshot)
            return snapshot
    finally:
        connection.rollback()
        connection.close()
