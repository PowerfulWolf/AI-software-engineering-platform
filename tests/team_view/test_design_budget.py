"""The read projection uses the same configured allowances without rewriting history."""

from pathlib import Path

import pytest

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.multi_directory.budget import DesignRetryPolicy
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
            "design_retry_policy": policy.to_wire(),
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
