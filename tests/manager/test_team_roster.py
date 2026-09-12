"""Canonical Team-owned production roster contracts."""

from pathlib import Path

from ai_software_engineer.config import (
    ModelProviderKind,
    ProductionConfig,
    ProviderRouteConfig,
)
from ai_software_engineer.domain import TeamRole
from ai_software_engineer.manager.team_roster import (
    production_team_roster,
)


def _config(tmp_path: Path) -> ProductionConfig:
    return ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex",
                model="gpt-5.5",
                kind=ModelProviderKind.CODEX_CLI,
            ),
        ),
    )


def test_production_roster_contains_seven_stable_team_members(
    tmp_path: Path,
) -> None:
    profiles, policy = production_team_roster(_config(tmp_path))

    assert tuple(profile.eligible_roles[0] for profile in profiles) == (
        TeamRole.MANAGER,
        TeamRole.PRODUCT,
        TeamRole.DESIGNER,
        TeamRole.PLANNER,
        TeamRole.CODER,
        TeamRole.QA,
        TeamRole.REVIEWER,
    )
    assert len({profile.id for profile in profiles}) == 7
    assert all(profile.default_model_policy_id == policy.id for profile in profiles)
    assert all(profile.max_parallel_assignments == 8 for profile in profiles)
    assert set().union(*(set(profile.capabilities) for profile in profiles)) <= set(
        policy.routes[0].capabilities
    )


def test_roster_uses_the_user_facing_team_order_and_names(
    tmp_path: Path,
) -> None:
    profiles, _ = production_team_roster(_config(tmp_path))

    assert tuple(profile.display_name for profile in profiles) == (
        "Manager Agent",
        "Product Agent",
        "Designer Agent",
        "Planner Agent",
        "Coder Agent",
        "QA Agent",
        "Reviewer Agent",
    )
    assert all(
        profile.metadata == {"ownership": "team", "member_type": "model_agent"}
        for profile in profiles
    )
