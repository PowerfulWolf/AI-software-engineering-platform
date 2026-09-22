"""The read projection uses the same configured allowances without rewriting history."""

from pathlib import Path

import pytest

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.multi_directory.budget import DesignRetryPolicy
from ai_software_engineer.multi_directory.models import JointStage
from ai_software_engineer.team_view.reader import ProductionTeamReader
from tests.manager.test_joint_designer_feedback import setup_design


@pytest.mark.parametrize(
    ("policy", "attempts", "exhausted"),
    [
        (DesignRetryPolicy(), {"design": 3}, "design"),
        (DesignRetryPolicy(max_design_attempts=4), {"design": 3}, None),
        (
            DesignRetryPolicy(max_transient_failures=2),
            {"design": 1, "design_transient": 2},
            "transient",
        ),
    ],
)
def test_projection_observes_configured_budgets_without_writes(
    tmp_path: Path, policy: DesignRetryPolicy, attempts: dict[str, int], exhausted: str | None
) -> None:
    service, _, seed, _ = setup_design(tmp_path)
    checkpoint = service._save(seed, attempts=attempts)
    config = ProductionConfig.model_validate(
        {
            **ProductionConfig.default().to_wire(),
            "platform_root": service.team.manifest.platform_root,
            "team_id": service.team.manifest.team_id,
            "execution_retry_policy": {
                "designer": {
                    "max_attempts": policy.max_design_attempts,
                    "max_transient_failures": policy.max_transient_failures,
                }
            },
        }
    )
    before = service.journal.history(seed.delivery_id)
    view = (
        ProductionTeamReader(config, {}).snapshot(service.project.manifest.project_id).requests[0]
    )
    assert view.checkpoint_sha256 == checkpoint.checkpoint_sha256
    assert view.design_budget is not None
    assert view.design_budget.exhausted == exhausted
    assert view.design_budget.max_design_attempts == policy.max_design_attempts
    assert view.design_budget.max_transient_failures == policy.max_transient_failures
    assert not view.design_recovery_available, "no approved historical knowledge wait"
    assert bool(view.blocker) == (exhausted is not None)
    assert service.journal.history(seed.delivery_id) == before


@pytest.mark.parametrize(
    ("stage", "counter", "role"),
    [
        (JointStage.PRODUCT_DISCOVERY, "product", "product"),
        (JointStage.PLANNING, "plan", "planner"),
    ],
)
def test_product_and_planner_budget_projection(
    tmp_path: Path, stage: JointStage, counter: str, role: str
) -> None:
    service, backend, seed, _ = setup_design(tmp_path)
    service._save(
        seed,
        stage=stage,
        design=backend.designs[1] if counter == "plan" else None,
        attempts={counter + "_transient": 2},
    )
    config = ProductionConfig.model_validate(
        {
            **ProductionConfig.default().to_wire(),
            "platform_root": service.team.manifest.platform_root,
            "team_id": service.team.manifest.team_id,
            "execution_retry_policy": {role: {"max_transient_failures": 2}},
        }
    )
    before = service.journal.history(seed.delivery_id)
    view = (
        ProductionTeamReader(config, {}).snapshot(service.project.manifest.project_id).requests[0]
    )
    assert view.stage_budget is not None
    assert view.stage_budget.role == role
    assert view.stage_budget.exhausted == "transient"
    assert view.blocker is not None
    assert service.journal.history(seed.delivery_id) == before
