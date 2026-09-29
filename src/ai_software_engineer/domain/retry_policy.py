"""Operator work budgets are distinct from monotonically increasing run identities."""

from typing import Annotated, Literal, Self, get_args

from pydantic import Field, StrictInt, model_validator

from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel

MAX_EXECUTION_ATTEMPTS = 400
ExecutionAttempt = Annotated[StrictInt, Field(ge=1, le=MAX_EXECUTION_ATTEMPTS)]
ExecutionCount = Annotated[StrictInt, Field(ge=0, le=MAX_EXECUTION_ATTEMPTS)]
RetryLimit = Annotated[StrictInt, Field(ge=1, le=100)]
TransientCode = Literal["TIMEOUT", "QUOTA_EXHAUSTED", "RATE_LIMITED", "PROVIDER_UNAVAILABLE"]
TRANSIENT_CODES: frozenset[str] = frozenset(get_args(TransientCode))


class TransientRetryPolicy(DomainModel):
    max_transient_failures: RetryLimit = 5


class StageRetryPolicy(TransientRetryPolicy):
    max_attempts: RetryLimit = 3


class ExecutionTimePolicy(DomainModel):
    initial_seconds: Annotated[StrictInt, Field(ge=1, le=86400)] = 600
    max_seconds: Annotated[StrictInt, Field(ge=1, le=86400)] = 2400
    max_capacity_timeouts: RetryLimit = 3

    @model_validator(mode="after")
    def ordered_window(self) -> Self:
        if self.max_seconds < self.initial_seconds:
            raise ValueError("execution time ceiling must not be below the initial window")
        return self

    def window(self, capacity_timeouts: int) -> int:
        if not 0 <= capacity_timeouts < self.max_capacity_timeouts:
            raise ValueError("execution time budget exhausted")
        return min(self.initial_seconds * (1 << capacity_timeouts), self.max_seconds)


class ExecutionTimePolicies(DomainModel):
    manager: ExecutionTimePolicy = ExecutionTimePolicy()
    product: ExecutionTimePolicy = ExecutionTimePolicy()
    designer: ExecutionTimePolicy = ExecutionTimePolicy()
    planner: ExecutionTimePolicy = ExecutionTimePolicy()

    def for_stage(self, stage: str) -> ExecutionTimePolicy:
        return {
            "manager": self.manager,
            "product": self.product,
            "design": self.designer,
            "plan": self.planner,
        }[stage]


class ManagerRetryPolicy(StageRetryPolicy):
    max_attempts: RetryLimit = 2
    max_coordination_rounds: RetryLimit = 3


class DeliveryRetryPolicy(DomainModel):
    max_work_attempts: RetryLimit = 3
    coder: TransientRetryPolicy = TransientRetryPolicy()
    qa: TransientRetryPolicy = TransientRetryPolicy()
    reviewer: TransientRetryPolicy = TransientRetryPolicy()

    def transient_limit(self, role: AgentRole) -> int:
        if role is AgentRole.ORCHESTRATOR:
            raise ValueError("deterministic delivery planning has no transient budget")
        return {
            AgentRole.CODER: self.coder,
            AgentRole.QA: self.qa,
            AgentRole.REVIEWER: self.reviewer,
        }[role].max_transient_failures

    @property
    def execution_limit(self) -> int:
        return self.max_work_attempts + sum(
            self.transient_limit(role)
            for role in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)
        )


class ExecutionRetryPolicy(DomainModel):
    manager: ManagerRetryPolicy = ManagerRetryPolicy()
    execution_time: ExecutionTimePolicies = ExecutionTimePolicies()
    product: StageRetryPolicy = StageRetryPolicy(max_attempts=20)
    designer: StageRetryPolicy = StageRetryPolicy()
    planner: StageRetryPolicy = StageRetryPolicy()
    coder: StageRetryPolicy = StageRetryPolicy()
    qa: TransientRetryPolicy = TransientRetryPolicy()
    reviewer: TransientRetryPolicy = TransientRetryPolicy()

    def delivery_policy(self) -> DeliveryRetryPolicy:
        return DeliveryRetryPolicy(
            max_work_attempts=self.coder.max_attempts,
            coder=TransientRetryPolicy(max_transient_failures=self.coder.max_transient_failures),
            qa=self.qa,
            reviewer=self.reviewer,
        )


class DeliveryRetryFailure(DomainModel):
    role: Literal[AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER]
    attempt: ExecutionAttempt
    code: TransientCode
    run_id: RunId | None = None
