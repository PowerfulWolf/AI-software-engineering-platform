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
CAPACITY_TIMEOUT_LIMIT = 3
BASE_STAGE_TIMEOUT_SECONDS = 600
MAX_STAGE_TIMEOUT_SECONDS = 2400


def stage_timeout_seconds(attempts: Mapping[str, int], stage: str) -> int:
    """Bounded geometric growth after a sealed local execution-limit failure."""
    count = attempts.get(stage + "_capacity_timeout", 0)
    if count < 0 or count >= CAPACITY_TIMEOUT_LIMIT:
        raise ValueError(f"joint {stage} execution time budget exhausted")
    return min(BASE_STAGE_TIMEOUT_SECONDS * (1 << count), MAX_STAGE_TIMEOUT_SECONDS)


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
    capacity_timeouts: AttemptCount = 0
    max_capacity_timeouts: Literal[3] = 3
    next_timeout_seconds: Annotated[StrictInt, Field(ge=600, le=2400)] | None = None
    exhausted: Literal["work", "transient", "capacity"] | None = None


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
    capacity = attempts.get(counter + "_capacity_timeout", 0)
    return StageBudget(
        role=role,
        attempts=work,
        transient_failures=transient,
        capacity_timeouts=capacity,
        next_timeout_seconds=(
            stage_timeout_seconds(attempts, counter) if capacity < CAPACITY_TIMEOUT_LIMIT else None
        ),
        max_attempts=limits.max_attempts,
        max_transient_failures=limits.max_transient_failures,
        exhausted="capacity"
        if capacity >= CAPACITY_TIMEOUT_LIMIT
        else "transient"
        if transient >= limits.max_transient_failures
        else "work"
        if work >= limits.max_attempts
        else None,
    )
