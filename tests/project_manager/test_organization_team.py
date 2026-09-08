"""Canonical organization-owned production roster contracts."""

from pathlib import Path

from ai_software_engineer.config import (
    ModelProviderKind,
    ProductionConfig,
    ProviderRouteConfig,
)
from ai_software_engineer.domain import OrganizationRole
from ai_software_engineer.project_manager.organization_team import (
    production_organization_team,
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


def test_production_roster_contains_seven_stable_organization_members(
    tmp_path: Path,
) -> None:
    profiles, policy = production_organization_team(_config(tmp_path))

    assert tuple(profile.eligible_roles[0] for profile in profiles) == (
        OrganizationRole.PROJECT_MANAGER,
        OrganizationRole.PRODUCT,
        OrganizationRole.DESIGNER,
        OrganizationRole.PLANNER,
        OrganizationRole.CODER,
        OrganizationRole.QA,
        OrganizationRole.REVIEWER,
    )
    assert len({profile.id for profile in profiles}) == 7
    assert all(profile.default_model_policy_id == policy.id for profile in profiles)
    assert all(profile.max_parallel_assignments == 8 for profile in profiles)
    assert set().union(*(set(profile.capabilities) for profile in profiles)) <= set(
        policy.routes[0].capabilities
    )


def test_original_delivery_member_identity_remains_exact_replay_compatible(
    tmp_path: Path,
) -> None:
    profiles, _ = production_organization_team(_config(tmp_path))
    by_role = {profile.eligible_roles[0]: profile for profile in profiles}

    assert by_role[OrganizationRole.CODER].display_name == "Team Coder"
    assert by_role[OrganizationRole.QA].display_name == "Team Qa"
    assert by_role[OrganizationRole.REVIEWER].display_name == "Team Reviewer"
    assert all(
        by_role[role].metadata == {}
        for role in (OrganizationRole.CODER, OrganizationRole.QA, OrganizationRole.REVIEWER)
    )
