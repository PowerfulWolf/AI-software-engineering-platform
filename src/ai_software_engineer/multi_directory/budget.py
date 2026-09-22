"""One bounded Design retry policy shared by execution and read projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import Field, StrictInt

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.retry_policy import (
    ExecutionRetryPolicy,
    RetryLimit,
    StageRetryPolicy,
)

AttemptLimit = RetryLimit
AttemptCount = Annotated[StrictInt, Field(ge=0)]
DESIGN_TRANSIENT_COUNTER = "design_transient"


class DesignRetryPolicy(DomainModel):
    max_design_attempts: AttemptLimit = 3
    max_transient_failures: AttemptLimit = 5

    def budget(self, attempts: Mapping[str, int]) -> DesignBudget:
        design = attempts.get("design", 0)
        transient = attempts.get(DESIGN_TRANSIENT_COUNTER, 0)
        return DesignBudget(
            max_design_attempts=self.max_design_attempts,
            max_transient_failures=self.max_transient_failures,
            design_attempts=design,
            transient_failures=transient,
            exhausted=(
                "transient"
                if transient >= self.max_transient_failures
                else "design"
                if design >= self.max_design_attempts
                else None
            ),
        )


class DesignBudget(DesignRetryPolicy):
    """Read-only observation; unknown legacy transient counts default to zero."""

    design_attempts: AttemptCount
    transient_failures: AttemptCount
    exhausted: Literal["design", "transient"] | None = None


class StageBudget(StageRetryPolicy):
    role: Literal["product", "designer", "planner"]
    attempts: AttemptCount
    transient_failures: AttemptCount
    exhausted: Literal["work", "transient"] | None = None


def stage_budget(
    policy: ExecutionRetryPolicy, stage: str, attempts: Mapping[str, int]
) -> StageBudget | None:
    """Only the active model stage can block its continuation; old counters are history."""
    roles: dict[str, tuple[Literal["product", "designer", "planner"], str]] = {
        "PRODUCT_DISCOVERY": ("product", "product"),
        "WAITING_PRODUCT_REPLY": ("product", "product"),
        "DESIGNING": ("designer", "design"),
        "PLANNING": ("planner", "plan"),
    }
    selected = roles.get(stage)
    if selected is None:
        return None
    role, counter = selected
    limits = {"product": policy.product, "designer": policy.designer, "planner": policy.planner}[
        role
    ]
    work, transient = attempts.get(counter, 0), attempts.get(counter + "_transient", 0)
    return StageBudget(
        role=role,
        attempts=work,
        transient_failures=transient,
        max_attempts=limits.max_attempts,
        max_transient_failures=limits.max_transient_failures,
        exhausted="transient"
        if transient >= limits.max_transient_failures
        else "work"
        if work >= limits.max_attempts
        else None,
    )
