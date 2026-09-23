"""A retained queue claim cannot silently acquire newly configured fallback models."""

from datetime import UTC, datetime

import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole, BrainTier, ModelRouteReason, ModelSelection
from ai_software_engineer.domain.model import ReasoningEffort
from ai_software_engineer.manager.queued_delivery import validate_frozen_routes
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
            "routes": (policy.routes[0].model_copy(update={"route_kind": None}),),
        }
    )
    with pytest.raises(QueueConflict, match="ambiguous"):
        validate_frozen_routes(
            AgentRole.CODER,
            selection.model_copy(update={"route_kind": None}),
            legacy_policy,
            routes,
        )
