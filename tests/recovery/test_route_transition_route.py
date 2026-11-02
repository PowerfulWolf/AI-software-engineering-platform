"""The old claim may end only after its frozen provider route truly changes."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import BrainTier, ModelRouteReason, ModelSelection
from ai_software_engineer.domain.enums import TaskStatus
from ai_software_engineer.manager.delivery_checkpoint import DeliveryFailureCode, DeliveryStage
from ai_software_engineer.manager.team_roster import production_team_roster
from ai_software_engineer.recovery.entry import NativeRecoveryEntry
from ai_software_engineer.recovery.route_transition_claim import UninvokedRouteClaimReader
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


def test_settled_source_rechecks_route_before_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    claim = SimpleNamespace(model_selection=selection)
    service = object.__new__(RouteTransitionSettlementService)
    service.queue = SimpleNamespace(original_claim=lambda _lease_id: claim)
    service.policy_lookup = lambda _id, _version: policy
    monkeypatch.setattr(
        "ai_software_engineer.recovery.route_transition_settlement.record_digest",
        lambda _claim: "a" * 64,
    )
    sealed = SimpleNamespace(
        work_item=SimpleNamespace(wait_reason="lease_expired:lease_fixture"),
        original_claim_sha256="a" * 64,
    )
    service.config = configured
    with pytest.raises(QueueConflict, match="again configured"):
        service.require_changed_route(sealed)
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
    service.require_changed_route(sealed)


@pytest.mark.parametrize("invalid_policy", [False, True])
def test_route_transition_rejects_ambiguous_routes_or_changed_policy(
    monkeypatch: pytest.MonkeyPatch, invalid_policy: bool
) -> None:
    original = ProviderRouteConfig(
        provider="codex", model="gpt-6-sol", kind=ModelProviderKind.CODEX_CLI
    )
    _, policy = production_team_roster(ProductionConfig(model_routes=(original,)))
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
    configured = ProductionConfig(
        model_routes=(
            ProviderRouteConfig(
                provider="codex",
                model="gpt-6-sol",
                kind=ModelProviderKind.RESPONSES,
                reasoning_effort="high",
                endpoint="https://example.invalid/responses",
                api_key_env="CODEX_RESPONSES_API_KEY",
            ),
            ProviderRouteConfig(
                provider="codex",
                model="gpt-6-sol",
                kind=ModelProviderKind.RESPONSES,
                reasoning_effort="low",
                endpoint="https://example.invalid/responses",
                api_key_env="CODEX_RESPONSES_API_KEY",
            ),
        )
    )
    service = object.__new__(RouteTransitionSettlementService)
    service.config = configured
    if invalid_policy:
        stored_policy = policy.model_copy(update={"version": "v2"})
        message = "frozen policy differs"
    else:
        stored_policy = policy.model_copy(
            update={
                "role_routes": (),
                "routes": (
                    policy.routes[0].model_copy(
                        update={
                            "route_kind": None,
                            "reasoning_effort": None,
                            "connection_mode": None,
                        }
                    ),
                ),
            }
        )
        message = "ambiguous"
    service.policy_lookup = lambda _id, _version: stored_policy
    claim = SimpleNamespace(model_selection=selection)
    with pytest.raises(QueueConflict, match=message):
        service._require_route_changed(SimpleNamespace(original_claim=claim))
    service.queue = SimpleNamespace(original_claim=lambda _lease_id: claim)
    monkeypatch.setattr(
        "ai_software_engineer.recovery.route_transition_settlement.record_digest",
        lambda _claim: "a" * 64,
    )
    sealed = SimpleNamespace(
        work_item=SimpleNamespace(wait_reason="lease_expired:lease_fixture"),
        original_claim_sha256="a" * 64,
    )
    with pytest.raises(QueueConflict, match=message):
        service.require_changed_route(sealed)


def test_ordinary_permission_failure_does_not_require_route_transition_operator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = object.__new__(NativeRecoveryEntry)
    entry.config = SimpleNamespace(require_mysql_dsn=lambda _env: "isolated-fixture-dsn")
    entry.environment = {}
    entry.operator_principal = None
    checkpoint = SimpleNamespace(
        stage=DeliveryStage.BLOCKED,
        task_status=TaskStatus.IMPLEMENTING,
        task_id="task_ordinary_failure",
        candidate_revision=None,
        failure_code=DeliveryFailureCode.PERMISSION_DENIED,
        repository_id="repo_fixture",
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.entry._repository_sidecar", lambda *_: tmp_path
    )
    monkeypatch.setattr(UninvokedRouteClaimReader, "has_expired_retry_shape", lambda *_: False)
    entry.settle_route_transition_if_needed(checkpoint)
