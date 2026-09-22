"""Operator work budgets are distinct from monotonically increasing run identities."""

from typing import Annotated, Literal, get_args

from pydantic import Field, StrictInt

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
