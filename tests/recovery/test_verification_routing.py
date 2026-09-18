"""Successor verifier routing after a production configuration restart, without providers."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents import StoredContextResolver
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import (
    AgentModelRoutePolicy,
    ModelProviderKind,
    ProductionConfig,
    ProviderRouteConfig,
    ProviderRouteReference,
)
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import TeamRole
from ai_software_engineer.manager.dispatch import DispatchWorkforceSnapshot
from ai_software_engineer.manager.production_delivery import DispatchDeliveryAgentAdapter
from ai_software_engineer.manager.team_roster import production_team_roster
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.verification_entry import _policy_sha, _verification_allocation
from ai_software_engineer.recovery.verification_native import NativeCandidateSource
from tests.manager.test_dispatch import COMMITTED_AT, RecordingDispatchStore, _facts, _service
from tests.orchestration.test_runner import _definitions


def _config(tmp_path: Path, *, current: bool) -> ProductionConfig:
    routes = (
        ProviderRouteConfig(
            provider="codex",
            model="gpt-6-astra",
            reasoning_effort="medium",
            kind=ModelProviderKind.CODEX_CLI,
        ),
        ProviderRouteConfig(
            provider="codex",
            model="gpt-5.6-sol",
            reasoning_effort="high",
            kind=ModelProviderKind.CODEX_CLI,
        ),
    )
    reference = ProviderRouteReference(
        provider="codex",
        model=routes[int(current)].model,
        reasoning_effort=routes[int(current)].reasoning_effort,
    )
    return ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=routes,
        agent_model_routes=tuple(
            AgentModelRoutePolicy(role=role, routes=(reference,)) for role in TeamRole
        ),
    )


def _historical_source(
    tmp_path: Path,
) -> tuple[NativeCandidateSource, DispatchWorkforceSnapshot]:
    request, initial = _facts(tmp_path)
    dispatch = _service(RecordingDispatchStore(), initial, request).commit_dispatch(request)
    # Provenance is covered by native-reader tests. Here use real typed Task/Plan inputs to
    # exercise allocation against a historical workforce snapshot and today's adapter config.
    source = Mock(
        spec=NativeCandidateSource,
        runtime=Mock(task=dispatch.task),
        stages=Mock(plan=request.execution_plan),
        scope=Mock(repository_id=initial.repository_id),
        inputs=Mock(task_id=initial.task_id),
    )
    agents, old_policy = production_team_roster(_config(tmp_path, current=False))
    snapshot = DispatchWorkforceSnapshot.create(
        repository_id=initial.repository_id,
        task_id=initial.task_id,
        work_item=initial.work_item,
        agents=agents,
        model_policies=(old_policy,),
    )
    return source, snapshot


@pytest.mark.parametrize("current", [False, True])
def test_new_verifier_selection_resolves_in_current_role_routes(
    tmp_path: Path, current: bool
) -> None:
    source, snapshot = _historical_source(tmp_path)
    before = snapshot.to_wire()
    config = _config(tmp_path, current=current)
    reservation = _verification_allocation(
        source,
        snapshot,
        config=config,
        execution_task_id="task_verify_current_routes",
        plan_sha256="a" * 64,
        now=COMMITTED_AT,
    )
    definitions = _definitions()
    for phase in reservation.phases:
        selection = phase.model_selection
        definitions[phase.role] = definitions[phase.role].model_copy(
            update={
                "id": phase.agent_id,
                "provider": selection.provider,
                "model": selection.model,
                "reasoning_effort": selection.reasoning_effort,
            }
        )
    adapter = DispatchDeliveryAgentAdapter(
        dispatch=reservation,
        definitions=definitions,
        plan_adapter=None,
        config=config,
        repository_root=tmp_path,
        repository_workspace_root=tmp_path / "sidecar",
        context_resolver=StoredContextResolver(
            FileContextStore(tmp_path / "contexts"), FileArtifactStore(tmp_path / "artifacts")
        ),
        environment={},
    )
    for phase in reservation.phases:
        routes = adapter._ordered_routes(definitions[phase.role])
        assert routes == config.routes_for(TeamRole(phase.role.value))
        assert phase.model_selection.policy_version == production_team_roster(config)[1].version
    assert snapshot.to_wire() == before
    assert reservation.workforce_snapshot_sha256 == snapshot.snapshot_sha256
    assert len({phase.agent_id for phase in reservation.phases}) == 2


def test_role_only_route_change_invalidates_verification_approval(tmp_path: Path) -> None:
    old, current = _config(tmp_path, current=False), _config(tmp_path, current=True)
    assert old.enabled_routes() == current.enabled_routes()
    assert _policy_sha(_definitions(), old) != _policy_sha(_definitions(), current)


def test_role_route_order_invalidates_verification_approval(tmp_path: Path) -> None:
    config = _config(tmp_path, current=True)
    references = tuple(
        ProviderRouteReference(
            provider=route.provider, model=route.model, reasoning_effort=route.reasoning_effort
        )
        for route in config.enabled_routes()
    )
    original = config.model_copy(
        update={
            "agent_model_routes": tuple(
                AgentModelRoutePolicy(role=role, routes=references) for role in TeamRole
            )
        }
    )
    reversed_order = config.model_copy(
        update={
            "agent_model_routes": tuple(
                AgentModelRoutePolicy(role=role, routes=tuple(reversed(references)))
                for role in TeamRole
            )
        }
    )
    assert original.enabled_routes() == reversed_order.enabled_routes()
    assert _policy_sha(_definitions(), original) != _policy_sha(_definitions(), reversed_order)


@pytest.mark.parametrize("cause", ["policy", "capacity"])
def test_current_routes_do_not_bypass_agent_policy_or_occupancy(tmp_path: Path, cause: str) -> None:
    source, snapshot = _historical_source(tmp_path)
    config = _config(tmp_path, current=True)
    occupied = _verification_allocation(
        source,
        snapshot,
        config=config,
        execution_task_id="task_verify_existing",
        plan_sha256="c" * 64,
        now=COMMITTED_AT,
    )
    agents = tuple(
        agent.model_copy(
            update=(
                {"default_model_policy_id": "model_policy_other"}
                if cause == "policy"
                else {"max_parallel_assignments": 1}
            )
        )
        if agent.eligible_roles == (TeamRole.REVIEWER,)
        else agent
        for agent in snapshot.agents
    )
    unavailable = DispatchWorkforceSnapshot.create(
        repository_id=snapshot.repository_id,
        task_id=snapshot.task_id,
        work_item=snapshot.work_item,
        agents=agents,
        model_policies=snapshot.model_policies,
        active_leases=tuple(phase.lease for phase in occupied.phases),
        assignments=tuple(phase.assignment for phase in occupied.phases),
    )
    with pytest.raises(RecoveryRejected, match="reviewer"):
        _verification_allocation(
            source,
            unavailable,
            config=config,
            execution_task_id="task_verify_unavailable",
            plan_sha256="b" * 64,
            now=COMMITTED_AT,
        )
