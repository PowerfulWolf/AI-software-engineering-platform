"""Draft 2020-12 contracts for Designer, Planner preview, and dispatch."""

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.design import (
    DesignContextBuilder,
    DesignerAgentRequest,
    FakeDesignerAgentAdapter,
    FakeDesignerBehavior,
    FakeDesignerScenario,
)
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.planning import (
    FakePlannerAgentAdapter,
    FakePlannerBehavior,
    FakePlannerScenario,
    PlannerAgentRequest,
    PlannerContextBuilder,
)
from ai_software_engineer.project_manager.dispatch import DispatchCommitRecord
from tests.design.factories import NOW as DESIGN_NOW
from tests.design.factories import approved_facts, design_for
from tests.planning.conftest import NOW as PLANNING_NOW
from tests.planning.conftest import (
    approval,
    committed_design_handoff,
    execution_plan,
    planning_request,
    preparation,
    product_spec,
    request_revision,
    technical_design,
)
from tests.project_manager.test_contracts import schema_registry
from tests.project_manager.test_dispatch import RecordingDispatchStore, _facts, _service


def _errors(schema_name: str, payload: WirePayload) -> list[str]:
    schemas, registry = schema_registry()
    return [
        error.message
        for error in Draft202012Validator(
            schemas[schema_name],
            registry=registry,
            format_checker=FormatChecker(),
        ).iter_errors(payload)
    ]


def _payloads(tmp_path: Path) -> dict[str, WirePayload]:
    designer_root = tmp_path / "designer"
    designer_root.mkdir()
    designer_command, _, _ = approved_facts(designer_root)
    designer_context = DesignContextBuilder().build(
        designer_command.preparation,
        designer_command.project_profile,
        designer_command.project_baseline,
        designer_command.request_revision.request,
        designer_command.product_spec,
        designer_command.product_approval,
        designer_command.solution_design_authorization,
        built_at=DESIGN_NOW,
    )
    designer_request = DesignerAgentRequest(
        run_id=designer_command.run_id,
        project_id=designer_context.project_id,
        request_id=designer_context.request_id,
        context=designer_context,
    )
    designer_result = FakeDesignerAgentAdapter(
        default=FakeDesignerScenario(
            behavior=FakeDesignerBehavior.READY,
            technical_design=design_for(designer_command),
        )
    ).run(designer_request)

    planner_root = tmp_path / "planner"
    planner_root.mkdir()
    project_request = planning_request(preparation(planner_root))
    current_revision = request_revision(project_request)
    spec = product_spec(project_request)
    approved = approval(spec)
    design = technical_design(spec, approved)
    design_store, design_checkpoint = committed_design_handoff(
        planner_root,
        current_revision,
        spec,
        approved,
        design,
    )
    design_run = design_store.get_run(design_checkpoint.run_id)
    assert design_run.planning_authorization is not None
    planner_context = PlannerContextBuilder().build(
        project_request_revision=current_revision,
        product_spec=spec,
        product_approval=approved,
        technical_design=design,
        design_checkpoint=design_checkpoint,
        planning_authorization=design_run.planning_authorization,
        expected_execution_plan_version=1,
        built_at=PLANNING_NOW + timedelta(minutes=4),
    )
    planner_request = PlannerAgentRequest(
        run_id="run_planner_schema_001",
        project_id=planner_context.project_id,
        request_id=planner_context.request_id,
        context=planner_context,
    )
    planner_result = FakePlannerAgentAdapter(
        default=FakePlannerScenario(
            behavior=FakePlannerBehavior.READY,
            execution_plan=execution_plan(spec, design),
        )
    ).run(planner_request)

    dispatch_root = tmp_path / "dispatch"
    dispatch_root.mkdir()
    dispatch_request, dispatch_snapshot = _facts(dispatch_root)
    dispatch_record = _service(
        RecordingDispatchStore(), dispatch_snapshot, dispatch_request
    ).commit_dispatch(dispatch_request)
    return {
        "designer-context.schema.json": designer_context.to_wire(),
        "designer-agent-run.schema.json": designer_request.to_wire(),
        "designer-result": designer_result.to_wire(),
        "planner-context.schema.json": planner_context.to_wire(),
        "planner-agent-run.schema.json": planner_request.to_wire(),
        "planner-result": planner_result.to_wire(),
        "planner-preview.schema.json": dispatch_request.planning_preview.to_wire(),
        "dispatch-commit.schema.json": dispatch_record.to_wire(),
    }


def test_t031_models_match_draft_2020_12_schemas(tmp_path: Path) -> None:
    payloads = _payloads(tmp_path)
    schema_names = {
        "designer-result": "designer-agent-run.schema.json",
        "planner-result": "planner-agent-run.schema.json",
    }

    for name, payload in payloads.items():
        assert _errors(schema_names.get(name, name), payload) == []


@pytest.mark.parametrize(
    "name",
    (
        "designer-context.schema.json",
        "designer-agent-run.schema.json",
        "planner-context.schema.json",
        "planner-agent-run.schema.json",
        "planner-preview.schema.json",
        "dispatch-commit.schema.json",
    ),
)
def test_t031_schemas_reject_ambient_additional_properties(
    tmp_path: Path,
    name: str,
) -> None:
    payload = deepcopy(_payloads(tmp_path)[name])
    payload["ambient_authority"] = "forbidden"

    assert _errors(name, payload)


@pytest.mark.parametrize(
    ("name", "permission"),
    (
        ("designer-context.schema.json", "execute_shell"),
        ("planner-context.schema.json", "persist_assignments_or_leases"),
    ),
)
def test_context_schemas_reject_permission_widening(
    tmp_path: Path,
    name: str,
    permission: str,
) -> None:
    payload = deepcopy(_payloads(tmp_path)[name])
    permissions = cast(dict[str, object], payload["permissions"])
    permissions[permission] = True

    assert _errors(name, payload)


def test_agent_results_require_typed_terminal_shape(tmp_path: Path) -> None:
    payloads = _payloads(tmp_path)
    designer = deepcopy(payloads["designer-result"])
    planner = deepcopy(payloads["planner-result"])
    designer.pop("technical_design")
    planner["error"] = {
        "code": "PROVIDER_ERROR",
        "message": "cannot coexist with success",
        "transient": True,
    }

    assert _errors("designer-agent-run.schema.json", designer)
    assert _errors("planner-agent-run.schema.json", planner)


def test_preview_and_dispatch_reject_concrete_or_partial_shapes(tmp_path: Path) -> None:
    payloads = _payloads(tmp_path)
    preview = deepcopy(payloads["planner-preview.schema.json"])
    preview_phases = cast(list[dict[str, object]], preview["phases"])
    preview_phases[0]["persisted_assignment"] = preview_phases[0]["assignment_decision"]
    wrong_roles = deepcopy(payloads["planner-preview.schema.json"])
    wrong_phase = cast(list[dict[str, object]], wrong_roles["phases"])[0]
    wrong_demand = cast(dict[str, object], wrong_phase["demand"])
    wrong_demand["role"] = "reviewer"

    dispatch = deepcopy(payloads["dispatch-commit.schema.json"])
    dispatch_phases = cast(list[dict[str, object]], dispatch["phases"])
    dispatch_phases[2].pop("lease")

    assert _errors("planner-preview.schema.json", preview)
    assert _errors("planner-preview.schema.json", wrong_roles)
    assert _errors("dispatch-commit.schema.json", dispatch)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("execution_plan_id", "invalid-plan-id"),
        ("planning_preview_id", "invalid-preview-id"),
        ("phase_id", "invalid-phase-id"),
    ),
)
def test_dispatch_identifier_constraints_match_schema_and_pydantic(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    payload = deepcopy(_payloads(tmp_path)["dispatch-commit.schema.json"])
    if field == "phase_id":
        phases = cast(list[dict[str, object]], payload["phases"])
        phases[0][field] = value
    else:
        payload[field] = value

    assert _errors("dispatch-commit.schema.json", payload)
    with pytest.raises(ValidationError):
        DispatchCommitRecord.model_validate(payload)


def test_dispatch_pydantic_rejects_nested_cross_project_assignment(tmp_path: Path) -> None:
    payload = deepcopy(_payloads(tmp_path)["dispatch-commit.schema.json"])
    phases = cast(list[dict[str, object]], payload["phases"])
    assignment = cast(dict[str, object], phases[0]["assignment"])
    assignment["project_id"] = "project_other_001"

    with pytest.raises(ValidationError, match="project"):
        DispatchCommitRecord.model_validate(payload)
