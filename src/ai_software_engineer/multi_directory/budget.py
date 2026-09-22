"""One bounded Design retry policy shared by execution and read projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import Field, StrictInt

from ai_software_engineer.domain.model import DomainModel

AttemptLimit = Annotated[StrictInt, Field(ge=1, le=100)]
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
