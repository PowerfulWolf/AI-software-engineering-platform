"""Composition guards for production delivery role adapters."""

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest

from ai_software_engineer.agents import AgentRequest, StoredContextResolver
from ai_software_engineer.config import (
    ModelProviderKind,
    ProductionConfig,
    ProductionConfigError,
    ProviderRouteConfig,
)
from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
from ai_software_engineer.manager.dispatch import (
    DispatchCommitRecord,
    VerificationReservation,
)
from ai_software_engineer.manager.production_delivery import DispatchDeliveryAgentAdapter
from ai_software_engineer.orchestration import ExecutionPlanAgentAdapter
from tests.manager.test_dispatch import RecordingDispatchStore, _facts, _service


def _reservation(tmp_path: Path) -> VerificationReservation:
    request, snapshot = _facts(tmp_path)
    dispatch = _service(RecordingDispatchStore(), snapshot, request).commit_dispatch(request)
    task_id = "task_verification_fixture"
    phases = []
    for index, phase in enumerate(dispatch.phases[1:]):
        assignment_id = f"assignment_verification_{index}"
        lease_id = f"lease_verification_{index}"
        phases.append(
            phase.model_copy(
                update={
                    "assignment": phase.assignment.model_copy(
                        update={
                            "id": assignment_id,
                            "lease_id": lease_id,
                            "task_id": task_id,
                        }
                    ),
                    "lease": phase.lease.model_copy(
                        update={
                            "id": lease_id,
                            "assignment_id": assignment_id,
                            "task_id": task_id,
                        }
                    ),
                }
            )
        )
    return VerificationReservation(
        plan_sha256="a" * 64,
        repository_id=dispatch.repository_id,
        source_task_id=dispatch.task_id,
        task_id=task_id,
        workforce_snapshot_sha256=snapshot.snapshot_sha256,
        phases=tuple(phases),
        committed_at=dispatch.committed_at,
    )


def _config(tmp_path: Path) -> ProductionConfig:
    return ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex",
                model="fixture-model",
                kind=ModelProviderKind.CODEX_CLI,
            ),
        ),
    )


def _orchestrator_request(task_id: str) -> AgentRequest:
    return AgentRequest(
        run_id="run_verification_orchestrator_guard",
        task_id=task_id,
        role=AgentRole.ORCHESTRATOR,
        attempt=1,
        source_revision="a" * 40,
        context_manifest_id="ctx_" + "b" * 64,
        input_artifact_ids=(),
        permissions=AgentPermissions(
            read_paths=("**",),
            write_paths=(),
            commands=(),
            network=NetworkAccess.NONE,
        ),
        output_schema="schemas/plan.schema.json",
        timeout_seconds=60,
    )


def _adapter(
    tmp_path: Path,
    dispatch: DispatchCommitRecord | VerificationReservation,
    plan_adapter: ExecutionPlanAgentAdapter | None,
) -> DispatchDeliveryAgentAdapter:
    return DispatchDeliveryAgentAdapter(
        dispatch=dispatch,
        definitions={},
        plan_adapter=plan_adapter,
        config=_config(tmp_path),
        repository_root=tmp_path,
        repository_workspace_root=tmp_path / "sidecar",
        context_resolver=cast(StoredContextResolver, MagicMock()),
    )


def test_verification_adapter_needs_no_planner_and_rejects_orchestrator(
    tmp_path: Path,
) -> None:
    reservation = _reservation(tmp_path)
    adapter = _adapter(tmp_path, reservation, None)

    with pytest.raises(
        ProductionConfigError,
        match="candidate verification cannot invoke Orchestrator",
    ):
        adapter.run(_orchestrator_request(reservation.task_id))


def test_delivery_and_verification_require_distinct_planning_composition(
    tmp_path: Path,
) -> None:
    request, snapshot = _facts(tmp_path)
    delivery = _service(RecordingDispatchStore(), snapshot, request).commit_dispatch(request)

    with pytest.raises(ProductionConfigError, match="delivery requires a planning adapter"):
        _adapter(tmp_path, delivery, None)
    with pytest.raises(
        ProductionConfigError,
        match="candidate verification must not configure a planning adapter",
    ):
        verification_root = tmp_path / "verification"
        verification_root.mkdir()
        _adapter(
            verification_root,
            _reservation(verification_root),
            cast(ExecutionPlanAgentAdapter, MagicMock()),
        )
