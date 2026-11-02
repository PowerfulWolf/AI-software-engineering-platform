"""A retained queue claim cannot silently acquire newly configured fallback models."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import (
    AgentRole,
    BrainTier,
    ModelPolicy,
    ModelRouteReason,
    ModelSelection,
)
from ai_software_engineer.domain.model import ReasoningEffort
from ai_software_engineer.manager.dispatch import DeliveryAllocation
from ai_software_engineer.manager.queued_delivery import (
    require_compatible_baseline_routes,
    validate_frozen_routes,
)
from ai_software_engineer.manager.team_roster import production_team_roster
from ai_software_engineer.work_queue.ports import QueueConflict


def test_frozen_routes_preserve_explicit_fallback_and_recovery_narrowing() -> None:
    efforts: tuple[ReasoningEffort, ...] = ("high", "medium", "low")
    routes = tuple(
        ProviderRouteConfig(
            provider="codex",
            model="gpt-5.5",
            kind=ModelProviderKind.CODEX_CLI,
            reasoning_effort=effort,
        )
        for effort in efforts
    )
    _, policy = production_team_roster(ProductionConfig(model_routes=routes))
    selection = ModelSelection(
        policy_id=policy.id,
        policy_version=policy.version,
        provider="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        tier=BrainTier.CRITICAL,
        reasons=(ModelRouteReason.DEFAULT,),
        selected_at=datetime.now(UTC),
    )
    validate_frozen_routes(AgentRole.CODER, selection, policy, routes)
    validate_frozen_routes(AgentRole.CODER, selection, policy, routes[:1])
    legacy = policy.model_copy(
        update={
            "role_routes": (),
            "routes": (policy.routes[0].model_copy(update={"reasoning_effort": None}),),
        }
    )
    legacy_selection = selection.model_copy(update={"reasoning_effort": None})
    validate_frozen_routes(AgentRole.CODER, legacy_selection, legacy, routes[:1])
    with pytest.raises(QueueConflict, match="ambiguous"):
        validate_frozen_routes(AgentRole.CODER, legacy_selection, legacy, routes)
    invalid = (
        routes[1:],
        (routes[0], routes[2], routes[1]),
        (routes[0], routes[1].model_copy(update={"model": "unapproved-new-model"})),
        (routes[0], routes[1].model_copy(update={"reasoning_effort": "xhigh"})),
        (routes[0], routes[0]),
    )
    for changed in invalid:
        with pytest.raises(QueueConflict):
            validate_frozen_routes(AgentRole.CODER, selection, policy, changed)
    with pytest.raises(QueueConflict, match="policy changed"):
        validate_frozen_routes(
            AgentRole.CODER,
            selection,
            policy.model_copy(update={"version": "v2"}),
            routes,
        )


def test_frozen_routes_bind_type_and_reject_legacy_ambiguity() -> None:
    routes = (
        ProviderRouteConfig(provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI),
        ProviderRouteConfig(
            provider="codex",
            model="gpt-5.5",
            kind=ModelProviderKind.RESPONSES,
            endpoint="https://example.invalid/responses",
            api_key_env="CODEX_RESPONSES_API_KEY",
        ),
    )
    _, policy = production_team_roster(ProductionConfig(model_routes=routes))
    selection = ModelSelection(
        policy_id=policy.id,
        policy_version=policy.version,
        provider="codex",
        model="gpt-5.5",
        reasoning_effort="medium",
        route_kind="codex_cli",
        tier=BrainTier.CRITICAL,
        reasons=(ModelRouteReason.DEFAULT,),
        selected_at=datetime.now(UTC),
    )
    validate_frozen_routes(AgentRole.CODER, selection, policy, routes)
    with pytest.raises(QueueConflict):
        validate_frozen_routes(AgentRole.CODER, selection, policy, routes[::-1])
    legacy_policy = policy.model_copy(
        update={
            "role_routes": (),
            "routes": (
                policy.routes[0].model_copy(update={"route_kind": None, "connection_mode": None}),
            ),
        }
    )
    with pytest.raises(QueueConflict, match="ambiguous"):
        validate_frozen_routes(
            AgentRole.CODER,
            selection.model_copy(update={"route_kind": None}),
            legacy_policy,
            routes,
        )


def test_frozen_routes_bind_codex_connection_and_reject_legacy_ambiguity() -> None:
    routes = (
        ProviderRouteConfig(
            provider="codex",
            model="gpt-5.5",
            kind=ModelProviderKind.CODEX_CLI,
            connection_mode="direct",
        ),
        ProviderRouteConfig(
            provider="codex",
            model="gpt-5.5",
            kind=ModelProviderKind.CODEX_CLI,
            connection_mode="proxy",
        ),
    )
    config = ProductionConfig(
        model_routes=routes, codex_cli_proxy_base_url="http://127.0.0.1:8317/v1"
    )
    _, policy = production_team_roster(config)
    selection = ModelSelection(
        policy_id=policy.id,
        policy_version=policy.version,
        provider="codex",
        model="gpt-5.5",
        reasoning_effort="medium",
        route_kind="codex_cli",
        connection_mode="direct",
        tier=BrainTier.CRITICAL,
        reasons=(ModelRouteReason.DEFAULT,),
        selected_at=datetime.now(UTC),
    )
    validate_frozen_routes(
        AgentRole.CODER, selection, policy, routes, proxy_base_url=config.codex_cli_proxy_base_url
    )
    with pytest.raises(QueueConflict):
        validate_frozen_routes(
            AgentRole.CODER,
            selection,
            policy,
            routes[::-1],
            proxy_base_url=config.codex_cli_proxy_base_url,
        )
    legacy_policy = policy.model_copy(
        update={
            "role_routes": (),
            "routes": (policy.routes[0].model_copy(update={"connection_mode": None}),),
        }
    )
    with pytest.raises(QueueConflict, match="ambiguous"):
        validate_frozen_routes(
            AgentRole.CODER,
            selection.model_copy(update={"connection_mode": None}),
            legacy_policy,
            routes,
            proxy_base_url=config.codex_cli_proxy_base_url,
        )


def test_baseline_resume_refuses_cli_to_responses_route_transition() -> None:
    cli = ProviderRouteConfig(provider="codex", model="gpt-6-sol", kind=ModelProviderKind.CODEX_CLI)
    responses = ProviderRouteConfig(
        provider="codex",
        model="codex/gpt-6-sol",
        kind=ModelProviderKind.RESPONSES,
        endpoint="https://example.invalid/responses",
        api_key_env="CODEX_RESPONSES_API_KEY",
    )
    original = ProductionConfig(model_routes=(cli,))
    _, frozen_policy = production_team_roster(original)
    selection = ModelSelection(
        policy_id=frozen_policy.id,
        policy_version=frozen_policy.version,
        provider=cli.provider,
        model=cli.model,
        reasoning_effort=cli.reasoning_effort,
        route_kind=cli.kind.value,
        tier=BrainTier.CRITICAL,
        reasons=(ModelRouteReason.DEFAULT,),
        selected_at=datetime.now(UTC),
    )
    allocation = cast(
        DeliveryAllocation,
        SimpleNamespace(phases=(SimpleNamespace(role=AgentRole.CODER, model_selection=selection),)),
    )

    def get_policy(_id: str, _version: str) -> ModelPolicy:
        return frozen_policy

    require_compatible_baseline_routes(original, allocation, get_policy)
    changed = ProductionConfig(model_routes=(responses,))
    with pytest.raises(QueueConflict, match="new recovery Task"):
        require_compatible_baseline_routes(changed, allocation, get_policy)
