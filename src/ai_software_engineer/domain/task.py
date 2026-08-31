"""Task aggregate and acceptance-contract value objects."""

from typing import Annotated, Self

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.enums import TaskStatus
from ai_software_engineer.domain.model import DomainModel, JsonValue, NonEmptyStr, ensure_unique

TaskId = Annotated[str, StringConstraints(pattern=r"^task_[a-z0-9][a-z0-9_-]{2,63}$")]
AcceptanceCriterionId = Annotated[str, StringConstraints(pattern=r"^ac_[a-z0-9][a-z0-9_-]{1,63}$")]
AttemptLimit = Annotated[StrictInt, Field(ge=1, le=10)]
AttemptCount = Annotated[StrictInt, Field(ge=0, le=10)]
TaskTitle = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class AcceptanceCriterion(DomainModel):
    """One independently verifiable condition for Task delivery."""

    id: AcceptanceCriterionId
    description: NonEmptyStr
    required: StrictBool
    verification: NonEmptyStr
    test_ids: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_unique_test_ids(self) -> Self:
        ensure_unique(self.test_ids, "acceptance criterion test_ids")
        return self


class TaskConstraints(DomainModel):
    """Machine-consumable restrictions attached to a Task."""

    allowed_paths: tuple[NonEmptyStr, ...] = ()
    denied_paths: tuple[NonEmptyStr, ...] = ()
    allowed_commands: tuple[NonEmptyStr, ...] = ()
    max_attempts: AttemptLimit | None = None
    notes: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_unique_entries(self) -> Self:
        ensure_unique(self.allowed_paths, "constraints.allowed_paths")
        ensure_unique(self.denied_paths, "constraints.denied_paths")
        ensure_unique(self.allowed_commands, "constraints.allowed_commands")
        return self


class Task(DomainModel):
    """A bounded request tied to one repository and delivery state."""

    id: TaskId
    title: TaskTitle
    description: NonEmptyStr
    repository: NonEmptyStr
    base_ref: NonEmptyStr
    acceptance_criteria: Annotated[tuple[AcceptanceCriterion, ...], Field(min_length=1)]
    constraints: TaskConstraints | None = None
    status: TaskStatus
    max_attempts: AttemptLimit
    attempts: AttemptCount = 0
    owner: NonEmptyStr | None = None
    labels: tuple[NonEmptyStr, ...] = ()
    created_at: AwareDatetime
    updated_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_task_invariants(self) -> Self:
        ensure_unique((criterion.id for criterion in self.acceptance_criteria), "criterion IDs")
        ensure_unique(self.labels, "labels")
        if self.attempts > self.max_attempts:
            raise ValueError("attempts cannot exceed max_attempts")
        if self.constraints is not None:
            constraint_limit = self.constraints.max_attempts
            if constraint_limit is not None and constraint_limit != self.max_attempts:
                raise ValueError("constraints.max_attempts must equal Task max_attempts")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        return self
