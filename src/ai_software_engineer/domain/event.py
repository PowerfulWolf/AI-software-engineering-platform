"""Task state events used to durably replay Orchestrator decisions."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, StringConstraints, model_validator

from ai_software_engineer.domain.artifact import ArtifactId
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import TaskId

EventId = Annotated[str, StringConstraints(pattern=r"^evt_[a-z0-9][a-z0-9_-]{2,63}$")]


class StateEvent(DomainModel):
    """An immutable, replayable Task status transition record."""

    event_id: EventId
    task_id: TaskId
    from_status: TaskStatus
    to_status: TaskStatus
    actor: Literal[AgentRole.ORCHESTRATOR]
    reason: NonEmptyStr
    artifact_ids: tuple[ArtifactId, ...]
    source_revision: NonEmptyStr
    occurred_at: AwareDatetime

    @model_validator(mode="after")
    def validate_unique_artifacts(self) -> Self:
        ensure_unique(self.artifact_ids, "state event artifact_ids")
        return self
