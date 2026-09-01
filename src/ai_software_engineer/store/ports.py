"""Typed persistence ports consumed by the future Orchestrator."""

from typing import Protocol

from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.task import Task, TaskId


class TaskRepository(Protocol):
    """The minimal durable Task/event boundary for v0.1."""

    def create(self, task: Task) -> None: ...

    def get(self, task_id: TaskId) -> Task: ...

    def append_event(self, event: StateEvent) -> None: ...

    def record_attempt(self, task_id: TaskId, attempt: int) -> None: ...

    def list_events(self, task_id: TaskId) -> tuple[StateEvent, ...]: ...

    def current_revision(self, task_id: TaskId) -> int: ...
