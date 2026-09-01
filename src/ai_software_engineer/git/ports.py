"""Typed seam for isolated Git role worktrees."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Protocol, Self

from pydantic import Field, StrictInt, model_validator

from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.task import TaskId

AttemptNumber = Annotated[StrictInt, Field(ge=1, le=10)]


class WorktreeSpec(DomainModel):
    """Validated request for one role worktree at an explicit revision."""

    task_id: TaskId
    role: AgentRole
    attempt: AttemptNumber
    source_revision: NonEmptyStr

    @model_validator(mode="after")
    def reject_orchestrator_worktree(self) -> Self:
        if self.role is AgentRole.ORCHESTRATOR:
            raise ValueError("orchestrator does not receive an Agent worktree")
        return self


@dataclass(frozen=True, slots=True)
class WorktreeRef:
    """Stable metadata for one manager-owned role worktree."""

    task_id: TaskId
    role: AgentRole
    attempt: int
    path: Path
    head_revision: str
    branch: str | None
    detached: bool


@dataclass(frozen=True, slots=True)
class WorktreeSnapshot:
    """Observable Git state of one role worktree."""

    head_revision: str
    changed_paths: tuple[str, ...]

    @property
    def dirty(self) -> bool:
        return bool(self.changed_paths)


class GitWorkspace(Protocol):
    """Repository Plane seam consumed by the Orchestrator."""

    def create(self, spec: WorktreeSpec) -> WorktreeRef: ...

    def inspect(self, worktree: WorktreeRef) -> WorktreeSnapshot: ...

    def remove(self, worktree: WorktreeRef) -> None: ...
