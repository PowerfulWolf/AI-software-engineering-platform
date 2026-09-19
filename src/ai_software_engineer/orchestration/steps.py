"""Bound one existing orchestration pass to an explicitly permitted role Run."""

from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictInt
from pydantic.dataclasses import dataclass

from ai_software_engineer.domain import AgentRole, Task
from ai_software_engineer.domain.model import NonEmptyStr
from ai_software_engineer.domain.task import AttemptLimit, TaskId
from ai_software_engineer.store import TaskRepository


@dataclass(frozen=True, slots=True, config=ConfigDict(extra="forbid"))
class RoleRunBoundary:
    task_id: TaskId
    role: Literal[AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER]
    attempt: AttemptLimit
    checkpoint_sequence: Annotated[StrictInt, Field(ge=0, le=10_000)]
    source_revision: NonEmptyStr


class RoleRunPending(Exception):
    """A scheduling boundary, never an Agent failure or a role verdict."""

    def __init__(self, boundary: RoleRunBoundary) -> None:
        self.boundary = boundary
        super().__init__(
            f"{boundary.task_id} awaits {boundary.role.value} attempt {boundary.attempt}"
        )


class BoundedRunControl:
    """Guard all accepted writes and stop before a second delivery invocation.

    A probe has no permit. Production's planning adapter is deterministic and may
    publish its approved plan; delivery Context creation requires a real permit.
    Recovery may consume zero model calls when a sealed Artifact already exists.
    """

    def __init__(
        self,
        repository: TaskRepository,
        *,
        permit: RoleRunBoundary | None = None,
        guard: Callable[[], None] | None = None,
    ) -> None:
        self._repository = repository
        self._permit = permit
        self._guard = guard
        self._consumed = False

    def before_write(self) -> None:
        if self._guard is not None:
            self._guard()

    def before_run(self, task: Task, role: AgentRole, attempt: int, source_revision: str) -> None:
        self.before_write()
        if role is AgentRole.ORCHESTRATOR:
            if self._permit is not None:
                raise ValueError("a delivery permit cannot invoke planning")
            return
        boundary = RoleRunBoundary(
            task.id, role, attempt, self._repository.current_revision(task.id), source_revision
        )
        if self._consumed or boundary != self._permit:
            raise RoleRunPending(boundary)
        self._consumed = True


__all__ = ["BoundedRunControl", "RoleRunBoundary", "RoleRunPending"]
