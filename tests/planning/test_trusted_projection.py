"""Committed joint planning reaches the native plan without a second routing decision."""

from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from ai_software_engineer.agents import StructuredModelClient, StructuredModelResult
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.manager import production_backend
from ai_software_engineer.manager.delivery_checkpoint import ProjectDeliveryCheckpoint
from ai_software_engineer.manager.production_agents import ExecutionPlanDraft
from ai_software_engineer.manager.production_backend import ProductionProjectDeliveryBackend
from tests.planning.conftest import execution_plan
from tests.planning.test_complex_planning import _package, _stage


class ProjectionClient:
    def __init__(self, draft: ExecutionPlanDraft) -> None:
        self.draft = draft
        self.calls = 0

    def for_project(
        self, repository_root: Path, role: TeamRole = TeamRole.PRODUCT
    ) -> StructuredModelClient:
        assert role is TeamRole.PLANNER
        return self

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        assert output_schema["title"] == "ExecutionPlanDraft"
        self.calls += 1
        return StructuredModelResult(payload=self.draft.to_wire(), duration_ms=0)


@pytest.mark.parametrize("trusted", (False, True))
def test_backend_preserves_committed_projection_instead_of_native_fast_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trusted: bool
) -> None:
    command, designs, requests, plans = _stage(tmp_path)
    requests.put_product_spec(command.product_spec)
    requests.put_approval(command.product_approval)
    base = execution_plan(command.product_spec, command.technical_design)
    draft = ExecutionPlanDraft.model_validate(
        {
            "phases": [
                {
                    key: value
                    for key, value in phase.to_wire().items()
                    if key not in {"id", "critical_path"}
                }
                for phase in base.phases
            ],
            "work_graph": {"packages": [_package().to_wire()]},
        }
    )
    client = ProjectionClient(draft)
    backend = object.__new__(ProductionProjectDeliveryBackend)
    monkeypatch.setattr(backend, "_trusted_plan_projection", trusted, raising=False)
    monkeypatch.setattr(backend, "_structured_clients", client, raising=False)
    facts = SimpleNamespace(
        workspace=SimpleNamespace(repository_root=tmp_path),
        product=requests,
        design=designs,
        planning=plans,
    )
    monkeypatch.setattr(backend, "_facts_for_checkpoint", lambda checkpoint: facts)
    monkeypatch.setattr(
        production_backend,
        "_designer_run_id",
        lambda delivery_id: command.design_checkpoint.run_id,
    )
    monkeypatch.setattr(production_backend, "_planner_run_id", lambda delivery_id: command.run_id)
    checkpoint = cast(
        ProjectDeliveryCheckpoint,
        SimpleNamespace(
            delivery_id="delivery_projection",
            product_spec_id=command.product_spec.id,
            approval_id=command.product_approval.id,
            checkpointed_at=command.transitioned_at,
        ),
    )
    result = backend.run_planner(checkpoint)
    if trusted:
        assert client.calls == 1
        assert result.run_record.planning_decision is None
        assert result.execution_plan.work_graph == draft.work_graph
        for actual, expected in zip(result.execution_plan.phases, draft.phases, strict=True):
            assert actual.objective == expected.objective
            assert actual.risk == expected.risk
            assert actual.checkpoints == expected.checkpoints
    else:
        assert client.calls == 0
        assert result.run_record.planning_decision is not None
        assert result.execution_plan.work_graph is None
