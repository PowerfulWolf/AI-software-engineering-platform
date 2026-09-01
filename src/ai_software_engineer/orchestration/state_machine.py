"""Deterministic Task transition guard and StateEvent reducer."""

from datetime import datetime

from ai_software_engineer.domain.artifact import ArtifactId
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.event import EventId, StateEvent
from ai_software_engineer.domain.task import Task

LEGAL_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.NEW: frozenset({TaskStatus.PLANNING, TaskStatus.FAILED}),
    TaskStatus.PLANNING: frozenset(
        {TaskStatus.IMPLEMENTING, TaskStatus.BLOCKED, TaskStatus.FAILED}
    ),
    TaskStatus.IMPLEMENTING: frozenset({TaskStatus.QA, TaskStatus.BLOCKED, TaskStatus.FAILED}),
    TaskStatus.QA: frozenset(
        {TaskStatus.REVIEW, TaskStatus.IMPLEMENTING, TaskStatus.BLOCKED, TaskStatus.FAILED}
    ),
    TaskStatus.REVIEW: frozenset(
        {TaskStatus.DONE, TaskStatus.IMPLEMENTING, TaskStatus.BLOCKED, TaskStatus.FAILED}
    ),
    TaskStatus.DONE: frozenset(),
    TaskStatus.BLOCKED: frozenset(),
    TaskStatus.FAILED: frozenset(),
}
TERMINAL_STATUSES = frozenset({TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED})


class StateMachineError(ValueError):
    """Base class for deterministic state-machine guard failures."""


class IllegalTransition(StateMachineError):
    """Raised when an edge is not part of the v0.1 transition graph."""


class TerminalTask(StateMachineError):
    """Raised when a terminal Task is asked to transition."""


class TaskMismatch(StateMachineError):
    """Raised when a StateEvent belongs to another Task."""


class StaleEvent(StateMachineError):
    """Raised when an event does not start from or postdate the snapshot."""


def validate_transition(task: Task, to_status: TaskStatus) -> None:
    """Validate one status edge without changing the Task."""
    if task.status in TERMINAL_STATUSES:
        raise TerminalTask(f"Task {task.id} is terminal at {task.status}")
    if to_status not in LEGAL_TRANSITIONS[task.status]:
        raise IllegalTransition(f"{task.status} -> {to_status} is not legal")


def build_event(
    task: Task,
    to_status: TaskStatus,
    *,
    event_id: EventId,
    reason: str,
    source_revision: str,
    artifact_ids: tuple[ArtifactId, ...] = (),
    attempt: int = 1,
    occurred_at: datetime,
) -> StateEvent:
    """Create an orchestrator-owned event after validating its status edge."""
    validate_transition(task, to_status)
    event = StateEvent(
        event_id=event_id,
        task_id=task.id,
        from_status=task.status,
        to_status=to_status,
        actor=AgentRole.ORCHESTRATOR,
        attempt=attempt,
        reason=reason,
        artifact_ids=artifact_ids,
        source_revision=source_revision,
        occurred_at=occurred_at,
    )
    apply_event(task, event)
    return event


def apply_event(task: Task, event: StateEvent) -> Task:
    """Reduce one valid event into a new immutable Task snapshot."""
    if event.task_id != task.id:
        raise TaskMismatch(f"event {event.event_id} belongs to {event.task_id}, not {task.id}")
    if event.from_status != task.status:
        raise StaleEvent(f"Task {task.id} is {task.status}, event starts at {event.from_status}")
    validate_transition(task, event.to_status)
    if event.occurred_at < task.updated_at:
        raise StaleEvent(f"event {event.event_id} predates Task snapshot")
    if event.attempt > task.max_attempts:
        raise StaleEvent(
            f"event {event.event_id} attempt {event.attempt} exceeds Task max_attempts"
        )
    return task.model_copy(
        update={
            "status": event.to_status,
            "updated_at": event.occurred_at,
        }
    )
