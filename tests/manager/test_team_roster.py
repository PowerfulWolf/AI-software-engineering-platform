"""Canonical Team-owned production roster contracts."""

from pathlib import Path

from ai_software_engineer.config import (
    AgentModelRoutePolicy,
    ModelProviderKind,
    ProductionConfig,
    ProviderRouteConfig,
    ProviderRouteReference,
)
from ai_software_engineer.domain import AgentRole, TeamRole
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


def test_delivery_model_policy_preserves_each_agent_route_order(tmp_path: Path) -> None:
    routes = (
        ProviderRouteConfig(
            provider="codex",
            model="coder-model",
            kind=ModelProviderKind.CODEX_CLI,
        ),
        ProviderRouteConfig(
            provider="codex",
            model="qa-model",
            kind=ModelProviderKind.CODEX_CLI,
        ),
    )
    policies = tuple(
        AgentModelRoutePolicy(
            role=role,
            routes=tuple(
                ProviderRouteReference(provider=route.provider, model=route.model)
                for route in (tuple(reversed(routes)) if role is TeamRole.QA else routes)
            ),
        )
        for role in TeamRole
    )
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=routes,
        agent_model_routes=policies,
    )

    _, policy = production_team_roster(config)

    role_routes = {item.role: item.routes for item in policy.role_routes}
    assert [item.model for item in role_routes[AgentRole.CODER]] == [
        "coder-model",
        "qa-model",
    ]
    assert [item.model for item in role_routes[AgentRole.QA]] == [
        "qa-model",
        "coder-model",
    ]


def test_roster_preserves_same_model_with_distinct_reasoning_efforts(tmp_path: Path) -> None:
    routes = (
        ProviderRouteConfig(
            provider="codex",
            model="gpt-5.6-sol",
            kind=ModelProviderKind.CODEX_CLI,
            reasoning_effort="medium",
        ),
        ProviderRouteConfig(
            provider="codex",
            model="gpt-5.6-sol",
            kind=ModelProviderKind.CODEX_CLI,
            reasoning_effort="high",
        ),
    )
    policies = tuple(
        AgentModelRoutePolicy(
            role=role,
            routes=(
                ProviderRouteReference(
                    provider="codex",
                    model="gpt-5.6-sol",
                    reasoning_effort="high" if role is TeamRole.CODER else "medium",
                ),
            ),
        )
        for role in TeamRole
    )
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=routes,
        agent_model_routes=policies,
    )

    _, policy = production_team_roster(config)

    coder = next(item for item in policy.role_routes if item.role is AgentRole.CODER)
    qa = next(item for item in policy.role_routes if item.role is AgentRole.QA)
    assert coder.routes[0].reasoning_effort == "high"
    assert qa.routes[0].reasoning_effort == "medium"
