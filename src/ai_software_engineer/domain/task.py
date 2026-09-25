"""Task aggregate and acceptance-contract value objects."""

from typing import Annotated, Self

from pydantic import AwareDatetime, Field, StrictBool, StringConstraints, model_validator

from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.model import DomainModel, JsonValue, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.retry_policy import (
    DeliveryRetryFailure,
    DeliveryRetryPolicy,
    ExecutionAttempt,
    ExecutionCount,
)

TaskId = Annotated[str, StringConstraints(pattern=r"^task_[a-z0-9][a-z0-9_-]{2,63}$")]
AcceptanceCriterionId = Annotated[str, StringConstraints(pattern=r"^ac_[a-z0-9][a-z0-9_-]{1,63}$")]
AttemptLimit = ExecutionAttempt
AttemptCount = ExecutionCount
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
    retry_policy: DeliveryRetryPolicy | None = None
    retry_failures: tuple[DeliveryRetryFailure, ...] | None = None

    @model_validator(mode="after")
    def validate_task_invariants(self) -> Self:
        ensure_unique((criterion.id for criterion in self.acceptance_criteria), "criterion IDs")
        ensure_unique(self.labels, "labels")
        if self.attempts > self.max_attempts:
            raise ValueError("attempts cannot exceed max_attempts")
        if self.retry_policy is not None and self.max_attempts != self.retry_policy.execution_limit:
            raise ValueError("Task execution limit must match the frozen retry policy")
        if self.retry_failures is not None:
            if self.retry_policy is None:
                raise ValueError("retry failure facts require a frozen retry policy")
            ensure_unique((failure.attempt for failure in self.retry_failures), "retry attempts")
            if any(failure.attempt > self.attempts for failure in self.retry_failures):
                raise ValueError("retry failure cannot precede its execution reservation")
            for role in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER):
                if self.transient_failures(role) > self.retry_policy.transient_limit(role):
                    raise ValueError("retry facts exceed the frozen allowance")
        if self.constraints is not None:
            constraint_limit = self.constraints.max_attempts
            if constraint_limit is not None and constraint_limit != self.max_attempts:
                raise ValueError("constraints.max_attempts must equal Task max_attempts")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        return self

    def transient_failures(self, role: AgentRole) -> int:
        return sum(failure.role is role for failure in self.retry_failures or ())

    @property
    def work_attempt(self) -> int:
        return self.attempts - sum(
            failure.attempt < self.attempts for failure in self.retry_failures or ()
        )

    @property
    def work_budget_exhausted(self) -> bool:
        limit = self.retry_policy.max_work_attempts if self.retry_policy else self.max_attempts
        return self.work_attempt >= limit

    def with_retry_failure(self, failure: DeliveryRetryFailure) -> Self:
        """Append one fact and reserve the next identity in the same repository transaction."""
        for prior in self.retry_failures or ():
            if prior.attempt == failure.attempt:
                if prior == failure:
                    return self
                raise ValueError("retry failure conflicts with an existing execution fact")
        expected = {
            AgentRole.CODER: TaskStatus.IMPLEMENTING,
            AgentRole.QA: TaskStatus.QA,
            AgentRole.REVIEWER: TaskStatus.REVIEW,
        }
        if (
            self.retry_policy is None
            or self.status is not expected[failure.role]
            or failure.attempt != self.attempts
        ):
            raise ValueError("retry failure does not match the active Task reservation")
        count = self.transient_failures(failure.role) + 1
        limit = self.retry_policy.transient_limit(failure.role)
        if count > limit:
            raise ValueError("transient allowance is already exhausted")
        payload = self.to_wire()
        payload["retry_failures"] = [
            item.to_wire() for item in (*(self.retry_failures or ()), failure)
        ]
        payload["attempts"] = self.attempts + int(
            count < limit and self.attempts < self.max_attempts
        )
        return type(self).model_validate(payload)


def task_matches_dispatch(
    current: Task, dispatched: Task, *, allow_legacy_retry_policy: bool = False
) -> bool:
    """Compare frozen intent, excluding only fields changed by normal execution.

    Retry failures are runtime facts, just like attempts. Their validation and
    persistence remain the Task/repository's responsibility; this does not reset
    them or authorize another run. Recovery keeps retry policy exact. Only the
    read-only projection may opt into its existing legacy-policy compatibility.
    """
    runtime_fields = {"status", "attempts", "updated_at", "retry_failures"}
    if allow_legacy_retry_policy and dispatched.retry_policy is None:
        runtime_fields.add("retry_policy")
    return all(
        getattr(current, name) == getattr(dispatched, name)
        for name in Task.model_fields
        if name not in runtime_fields
    )
