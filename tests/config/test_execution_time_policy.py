"""Time capacity is configurable independently of provider and work budgets."""

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, ExecutionTimePolicy
from ai_software_engineer.multi_directory.budget import stage_budget, stage_timeout_seconds


def test_geometric_time_windows_and_independent_limits() -> None:
    time = ExecutionTimePolicy(initial_seconds=30, max_seconds=90, max_capacity_timeouts=4)
    assert [time.window(i) for i in range(4)] == [30, 60, 90, 90]
    with pytest.raises(ValueError, match="exhausted"):
        time.window(4)
    with pytest.raises(ValueError):
        time.window(-1)
    policy = ExecutionRetryPolicy.model_validate({"execution_time": {"planner": time.to_wire()}})
    budget = stage_budget(policy, "PLANNING", {"plan_capacity_timeout": 3, "plan_transient": 2})
    assert budget is not None
    assert budget.next_timeout_seconds == 90
    assert budget.max_capacity_timeouts == 4
    assert budget.exhausted is None
    assert stage_timeout_seconds({"plan_capacity_timeout": 1}, "plan", time) == 60


@pytest.mark.parametrize("field", ["initial_seconds", "max_seconds", "max_capacity_timeouts"])
@pytest.mark.parametrize("value", [True, "30", 0, -1, 86401])
def test_time_policy_rejects_invalid_bounds(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ExecutionTimePolicy.model_validate({field: value})


def test_ceiling_and_manager_defaults() -> None:
    with pytest.raises(ValidationError):
        ExecutionTimePolicy(initial_seconds=300, max_seconds=60)
    policy = ExecutionRetryPolicy()
    assert policy.manager.max_attempts == 2
    assert policy.manager.max_transient_failures == 5
    assert policy.manager.max_coordination_rounds == 3
    assert policy.execution_time.manager.window(0) == 600
    assert policy.delivery_policy().execution_limit == 18
