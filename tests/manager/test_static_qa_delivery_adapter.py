"""Only a consumed QA proof can select commandless static verification."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.agents.verification_output import (
    TrustedStaticQaMissingEntryOutputContract,
)
from ai_software_engineer.config import (
    ModelProviderKind,
    ProductionConfigError,
    ProviderRouteConfig,
)
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.manager.production_delivery import (
    ConfiguredDeliveryRouteAdapterFactory,
)
from tests.agents.test_static_qa_missing_entry_output import _subject
from tests.manager.test_production_delivery import _config


def _route(kind: ModelProviderKind) -> ProviderRouteConfig:
    return ProviderRouteConfig(
        provider="fixture",
        model="fixture",
        kind=kind,
        endpoint="https://example.invalid/responses"
        if kind is ModelProviderKind.RESPONSES
        else None,
        api_key_env="FIXTURE_KEY" if kind is ModelProviderKind.RESPONSES else None,
    )


def test_factory_skips_ordinary_verifier_only_for_exact_static_qa_claim(
    tmp_path: Path,
) -> None:
    request, contract, _ = _subject()
    registry = MagicMock()
    calls: list[AgentRequest] = []

    def resolve(
        candidate: AgentRequest, root: Path, guard: object
    ) -> TrustedStaticQaMissingEntryOutputContract | None:
        calls.append(candidate)
        assert root == tmp_path and guard is None
        return contract if candidate == request else None

    factory = (
        ConfiguredDeliveryRouteAdapterFactory()
        .with_registered_verifier(registry)
        .with_static_qa_contract_resolver(resolve)
    )
    binding = MagicMock()
    binding.worktree.path = tmp_path
    factory.prepare_verifier(
        request=request,
        route=_route(ModelProviderKind.CODEX_CLI),
        binding=binding,
        config=_config(tmp_path),
    )
    assert calls == [request]
    registry.prepare_verifier.assert_not_called()

    other = request.model_copy(update={"run_id": "run_other_qa"})
    factory.prepare_verifier(
        request=other,
        route=_route(ModelProviderKind.CODEX_CLI),
        binding=binding,
        config=_config(tmp_path),
    )
    registry.prepare_verifier.assert_called_once()


def test_static_qa_responses_fallback_refuses_before_ordinary_verifier(
    tmp_path: Path,
) -> None:
    request, contract, _ = _subject()
    registry = MagicMock()
    factory = (
        ConfiguredDeliveryRouteAdapterFactory()
        .with_registered_verifier(registry)
        .with_static_qa_contract_resolver(lambda *_: contract)
    )
    binding = MagicMock()
    binding.worktree.path = tmp_path
    with pytest.raises(ProductionConfigError, match="guarded Codex CLI"):
        factory.prepare_verifier(
            request=request,
            route=_route(ModelProviderKind.RESPONSES),
            binding=binding,
            config=_config(tmp_path),
        )
    registry.prepare_verifier.assert_not_called()


def test_static_qa_callback_is_never_consulted_for_reviewer(tmp_path: Path) -> None:
    request, contract, _ = _subject()
    registry = MagicMock()
    factory = (
        ConfiguredDeliveryRouteAdapterFactory()
        .with_registered_verifier(registry)
        .with_static_qa_contract_resolver(lambda *_: contract)
    )
    binding = MagicMock()
    binding.worktree.path = tmp_path
    factory.prepare_verifier(
        request=request.model_copy(update={"role": AgentRole.REVIEWER}),
        route=_route(ModelProviderKind.CODEX_CLI),
        binding=binding,
        config=_config(tmp_path),
    )
    registry.prepare_verifier.assert_called_once()
