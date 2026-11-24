"""Execution policy is bounded, role-aware and compatible with Design-only settings."""

import pytest
from pydantic import ValidationError

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy


def test_default_policy_separates_work_and_infrastructure() -> None:
    policy = ExecutionRetryPolicy()
    assert policy.product.max_attempts == 20
    assert policy.designer.max_attempts == policy.planner.max_attempts == 3
    assert policy.coder.max_attempts == 3
    assert policy.qa.max_transient_failures == policy.reviewer.max_transient_failures == 5
    delivery = policy.delivery_policy()
    assert delivery.max_work_attempts == 3
    assert delivery.execution_limit == 18


def test_legacy_design_settings_migrate_without_losing_limits() -> None:
    payload = ProductionConfig.default().to_wire()
    payload.pop("execution_retry_policy", None)
    payload["design_retry_policy"] = {"max_design_attempts": 8, "max_transient_failures": 17}
    config = ProductionConfig.model_validate(payload)
    assert config.execution_retry_policy.designer.max_attempts == 8
    assert config.execution_retry_policy.designer.max_transient_failures == 17
    assert config.execution_retry_policy.product.max_attempts == 20
    assert "design_retry_policy" not in config.to_wire()


@pytest.mark.parametrize("value", [True, "3", 0, 101])
def test_every_role_rejects_invalid_transient_limit(value: object) -> None:
    for role in ("manager", "product", "designer", "planner", "coder", "qa", "reviewer"):
        with pytest.raises(ValidationError):
            ExecutionRetryPolicy.model_validate({role: {"max_transient_failures": value}})


def test_conflicting_legacy_and_canonical_policy_is_rejected() -> None:
    payload = ProductionConfig.default().to_wire()
    payload["design_retry_policy"] = {"max_design_attempts": 9}
    with pytest.raises(ValidationError, match="conflicting"):
        ProductionConfig.model_validate(payload)
    payload["design_retry_policy"] = {"max_design_attempts": 3}
    assert ProductionConfig.model_validate(payload).execution_retry_policy == ExecutionRetryPolicy()


@pytest.mark.parametrize("role", ["qa", "reviewer"])
def test_no_operator_policy_can_retry_valid_verdicts(role: str) -> None:
    with pytest.raises(ValidationError):
        ExecutionRetryPolicy.model_validate({role: {"max_attempts": 8}})


def test_coder_max_steps_per_run_defaults_to_3() -> None:
    assert ExecutionRetryPolicy().coder_max_steps_per_run == 3
    config = ProductionConfig.default()
    assert config.execution_retry_policy.coder_max_steps_per_run == 3


def test_legacy_config_without_field_uses_default() -> None:
    payload = ProductionConfig.default().to_wire()
    policy = payload["execution_retry_policy"]
    assert isinstance(policy, dict)
    policy.pop("coder_max_steps_per_run", None)
    config = ProductionConfig.model_validate(payload)
    assert config.execution_retry_policy.coder_max_steps_per_run == 3


@pytest.mark.parametrize("value", [1, 16])
def test_coder_max_steps_per_run_accepts_bounds(value: int) -> None:
    policy = ExecutionRetryPolicy.model_validate({"coder_max_steps_per_run": value})
    assert policy.coder_max_steps_per_run == value
    payload = ProductionConfig.default().to_wire()
    payload["execution_retry_policy"] = {"coder_max_steps_per_run": value}
    config = ProductionConfig.model_validate(payload)
    assert config.execution_retry_policy.coder_max_steps_per_run == value
    assert config.to_wire()["execution_retry_policy"]["coder_max_steps_per_run"] == value


@pytest.mark.parametrize("value", [0, 17, -1, 3.0, "3", True])
def test_coder_max_steps_per_run_rejects_invalid(value: object) -> None:
    with pytest.raises(ValidationError) as direct:
        ExecutionRetryPolicy.model_validate({"coder_max_steps_per_run": value})
    assert any("coder_max_steps_per_run" in error["loc"] for error in direct.value.errors())
    payload = ProductionConfig.default().to_wire()
    payload["execution_retry_policy"] = {"coder_max_steps_per_run": value}
    with pytest.raises(ValidationError) as nested:
        ProductionConfig.model_validate(payload)
    assert any(
        "execution_retry_policy" in error["loc"] and "coder_max_steps_per_run" in error["loc"]
        for error in nested.value.errors()
    )
