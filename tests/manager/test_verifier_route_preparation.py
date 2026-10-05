"""All exact fallback routes prepare before a verifier model starts, without reexecution."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest

from ai_software_engineer.agents import (
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    StoredContextResolver,
)
from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.agents.models import AgentErrorCode, AgentFailure
from ai_software_engineer.agents.openai_compatible import (
    PromptBuilder,
    PromptMessage,
    PromptPayload,
)
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentDefinition, AgentRole
from ai_software_engineer.domain.agent import DELIVERY_ROLE_INPUTS, ROLE_OUTPUTS
from ai_software_engineer.domain.native_verification import (
    NativeVerificationWaiting,
    NativeVerificationWaitReason,
)
from ai_software_engineer.manager.dispatch import DeliveryAllocation
from ai_software_engineer.manager.native_verification import NativeRoleVerificationInputs
from ai_software_engineer.manager.production_delivery import (
    ConfiguredDeliveryRouteAdapterFactory,
    DispatchDeliveryAgentAdapter,
)
from ai_software_engineer.orchestration import ExecutionPlanAgentAdapter
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from tests.domain.factories import make_agent
from tests.manager.test_native_verification import _fake_ports, _Fixture, _fixture
from tests.manager.test_verifier_preparation import _gate, _marker, _Wait


class _StaticPrompt:
    def __init__(self, resolver: object) -> None:
        pass

    def build(self, request: AgentRequest) -> PromptPayload:
        return PromptPayload(
            messages=(PromptMessage(role="user", content="Original role context"),)
        )


class _RouteAdapter:
    def __init__(
        self, prompt: PromptBuilder, model: str, calls: list[tuple[str, PromptPayload]]
    ) -> None:
        self._prompt, self._model, self._calls = prompt, model, calls

    def run(self, request: AgentRequest) -> AgentResult:
        payload = self._prompt.build(request)
        self._calls.append((self._model, payload))
        return AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.FAILED,
            error=AgentFailure(
                code=AgentErrorCode.PROVIDER_UNAVAILABLE,
                message="Offline fixture forces fallback.",
                transient=True,
            ),
        )


def _routes(primary_kind: ModelProviderKind) -> tuple[ProviderRouteConfig, ...]:
    other = (
        ModelProviderKind.RESPONSES
        if primary_kind is ModelProviderKind.CODEX_CLI
        else ModelProviderKind.CODEX_CLI
    )
    return tuple(
        ProviderRouteConfig(
            provider="fixture",
            model=f"fixture-{kind.value}",
            kind=kind,
            endpoint="https://fixture.invalid/v1/responses"
            if kind is ModelProviderKind.RESPONSES
            else None,
            api_key_env="ASE_NATIVE_TOKEN" if kind is ModelProviderKind.RESPONSES else None,
        )
        for kind in (primary_kind, other)
    )


def _dispatch_adapter(
    tmp_path: Path,
    fixture: _Fixture,
    config: ProductionConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    DispatchDeliveryAgentAdapter, ConfiguredDeliveryRouteAdapterFactory, RoleWorktreeBinding
]:
    primary = config.model_routes[0]
    definition = AgentDefinition.model_validate(
        {
            **make_agent().to_wire(),
            "id": fixture.claim.assignment.agent_id,
            "role": fixture.request.role.value,
            "provider": primary.provider,
            "model": primary.model,
            "route_kind": primary.kind.value,
            "permissions": fixture.request.permissions.to_wire(),
            "input_artifacts": tuple(
                kind.value for kind in DELIVERY_ROLE_INPUTS[fixture.request.role]
            ),
            "output_artifacts": tuple(kind.value for kind in ROLE_OUTPUTS[fixture.request.role]),
        }
    )
    allocation = cast(
        DeliveryAllocation,
        SimpleNamespace(
            task_id=fixture.task.id,
            repository_id=fixture.registry.scope.repository_id,
            task=fixture.task,
        ),
    )
    factory = ConfiguredDeliveryRouteAdapterFactory(
        registered_verifier=fixture.registry, execution_guard=fixture.guard
    )
    adapter = DispatchDeliveryAgentAdapter(
        dispatch=allocation,
        definitions={fixture.request.role: definition},
        plan_adapter=cast(ExecutionPlanAgentAdapter, MagicMock()),
        config=config,
        repository_root=fixture.task.repository,
        repository_workspace_root=tmp_path / "sidecar",
        context_resolver=cast(StoredContextResolver, MagicMock()),
        environment={"ASE_NATIVE_TOKEN": "fixture-unused"},
        route_adapters=factory,
    )
    raw_binding = MagicMock()
    raw_binding.worktree.path = fixture.root
    raw_binding.worktree.attempt = fixture.request.attempt
    binding = cast(RoleWorktreeBinding, raw_binding)
    monkeypatch.setattr(adapter, "_binding", lambda request: binding)
    return adapter, factory, binding


@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
@pytest.mark.parametrize("primary_kind", [ModelProviderKind.CODEX_CLI, ModelProviderKind.RESPONSES])
def test_mixed_kind_fallback_prepares_all_routes_once_before_model_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: AgentRole,
    primary_kind: ModelProviderKind,
) -> None:
    fixture = _fixture(tmp_path, role)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)
    calls: list[tuple[str, PromptPayload]] = []

    def construct_adapter(
        *, prompt_builder: PromptBuilder, model: str, **kwargs: object
    ) -> _RouteAdapter:
        return _RouteAdapter(prompt_builder, model, calls)

    monkeypatch.setattr(
        "ai_software_engineer.manager.production_delivery.ContextPromptBuilder", _StaticPrompt
    )
    for name in ("CodexCliAgentAdapter", "ResponsesAgentAdapter"):
        monkeypatch.setattr(
            f"ai_software_engineer.manager.production_delivery.{name}", construct_adapter
        )
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"), model_routes=_routes(primary_kind)
    )
    adapter, _, _ = _dispatch_adapter(tmp_path, fixture, config, monkeypatch)
    gate, delegate, failure, records = _gate(fixture, tmp_path, prepare=adapter.prepare_verifier)

    assert gate.prepare(fixture.request) == fixture.request
    assert _marker(records).result == "READY" and delegate.calls == 1
    assert len(resources) == len(executions) == 1 and not calls
    result = adapter.run(fixture.request)

    assert result.status is AgentRunStatus.FAILED
    assert [model for model, _ in calls] == [route.model for route in config.model_routes]
    assert all(
        "native-role-verification://" in payload.messages[-1].content for _, payload in calls
    )
    assert len(resources) == len(executions) == 1 and not failure.events


def test_unsupported_fallback_waits_before_any_model_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)
    assert fixture.plan.content.verification_requirements is not None
    ordinary = fixture.plan.model_copy(
        update={
            "content": fixture.plan.content.model_copy(
                update={
                    "verification_requirements": tuple(
                        item.model_copy(update={"controlled_capability_kind": None})
                        for item in fixture.plan.content.verification_requirements
                    )
                }
            )
        }
    )
    original_reader = fixture.registry._inputs_reader
    assert original_reader is not None

    class Reader:
        def read(
            self,
            *,
            request: AgentRequest,
            workspace_root: Path,
            guard: ExecutionGuard,
        ) -> NativeRoleVerificationInputs:
            assert original_reader is not None
            return replace(
                original_reader.read(request=request, workspace_root=workspace_root, guard=guard),
                plan_artifact=ordinary,
            )

    monkeypatch.setattr(fixture.registry, "_inputs_reader", Reader())
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"), model_routes=_routes(ModelProviderKind.RESPONSES)
    )
    adapter, _, _ = _dispatch_adapter(tmp_path, fixture, config, monkeypatch)
    gate, delegate, failure, records = _gate(fixture, tmp_path, prepare=adapter.prepare_verifier)
    with pytest.raises(_Wait):
        gate.prepare(fixture.request)
    marker = _marker(records)
    assert marker.result == "WAIT"
    assert marker.failure_reason is NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT
    assert delegate.calls == 0 and len(failure.events) == 1
    assert not resources and not executions


@pytest.mark.parametrize("changed_scope", [False, True])
def test_exact_unprepared_route_cannot_reuse_another_routes_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_scope: bool
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)
    calls: list[tuple[str, PromptPayload]] = []

    def construct_adapter(
        *, prompt_builder: PromptBuilder, model: str, **kwargs: object
    ) -> _RouteAdapter:
        return _RouteAdapter(prompt_builder, model, calls)

    monkeypatch.setattr(
        "ai_software_engineer.manager.production_delivery.ContextPromptBuilder", _StaticPrompt
    )
    for name in ("CodexCliAgentAdapter", "ResponsesAgentAdapter"):
        monkeypatch.setattr(
            f"ai_software_engineer.manager.production_delivery.{name}", construct_adapter
        )
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"), model_routes=_routes(ModelProviderKind.CODEX_CLI)
    )
    adapter, factory, binding = _dispatch_adapter(tmp_path, fixture, config, monkeypatch)
    adapter.prepare_verifier(fixture.request)
    assert len(resources) == len(executions) == 1 and not calls
    extra = config.model_routes[0].model_copy(update={"model": "unprepared-new-model"})
    if changed_scope:
        monkeypatch.setattr(adapter, "_route_scope", (*config.model_routes, extra))
        with pytest.raises(NativeVerificationWaiting) as error:
            adapter.run(fixture.request)
    else:
        created = factory.create(
            route=extra,
            definition=adapter._definitions[fixture.request.role],
            binding=binding,
            context_resolver=cast(StoredContextResolver, MagicMock()),
            config=config,
            environment={"ASE_NATIVE_TOKEN": "fixture-unused"},
        )
        with pytest.raises(NativeVerificationWaiting) as error:
            created.run(fixture.request)
    assert error.value.reason is NativeVerificationWaitReason.FACTS_CHANGED
    assert len(resources) == len(executions) == 1 and not calls
