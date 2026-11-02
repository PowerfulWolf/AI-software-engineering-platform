"""The old claim may end only after its frozen provider route truly changes."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import BrainTier, ModelRouteReason, ModelSelection
from ai_software_engineer.manager.team_roster import production_team_roster
from ai_software_engineer.recovery.route_transition_settlement import (
    RouteTransitionSettlementService,
)
from ai_software_engineer.work_queue.ports import QueueConflict


def test_settlement_requires_changed_frozen_coder_route() -> None:
    original = ProviderRouteConfig(
        provider="codex", model="gpt-6-sol", kind=ModelProviderKind.CODEX_CLI
    )
    configured = ProductionConfig(model_routes=(original,))
    _, policy = production_team_roster(configured)
    selection = ModelSelection(
        policy_id=policy.id,
        policy_version=policy.version,
        provider="codex",
        model="gpt-6-sol",
        reasoning_effort="medium",
        route_kind="codex_cli",
        tier=BrainTier.CRITICAL,
        reasons=(ModelRouteReason.DEFAULT,),
        selected_at=datetime.now(UTC),
    )
    observed = SimpleNamespace(original_claim=SimpleNamespace(model_selection=selection))
    service = object.__new__(RouteTransitionSettlementService)
    service.config = configured
    service.policy_lookup = lambda _id, _version: policy
    with pytest.raises(QueueConflict, match="still configured"):
        service._require_route_changed(observed)
    service.config = ProductionConfig(
        model_routes=(
            ProviderRouteConfig(
                provider="codex",
                model="gpt-6-sol",
                kind=ModelProviderKind.RESPONSES,
                endpoint="https://example.invalid/responses",
                api_key_env="CODEX_RESPONSES_API_KEY",
            ),
        )
    )
    service._require_route_changed(observed)
