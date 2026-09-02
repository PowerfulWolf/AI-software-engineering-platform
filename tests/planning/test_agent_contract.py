"""Planner context, least-authority, adapter, and abstract-plan contracts."""

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.design import FileDesignRecordStore
from ai_software_engineer.domain import ProjectRequest, ProjectRequestStatus
from ai_software_engineer.planning import (
    PLANNER_AGENT_PERMISSIONS,
    FakePlannerAgentAdapter,
    FakePlannerBehavior,
    FakePlannerScenario,
    PlannerAgentRequest,
    PlannerAgentRequestConflict,
    PlannerAgentRunStatus,
    PlannerContextBuilder,
    PlannerContextIntegrityError,
    PlannerContextLineageError,
    PlannerContextManifest,
)
from ai_software_engineer.product.models import ProjectRequestRevision
from tests.planning.conftest import (
    NOW,
    approval,
    committed_design_handoff,
    execution_plan,
    planning_request,
    preparation,
    product_spec,
    request_revision,
    technical_design,
)


def _context(tmp_path: Path) -> PlannerContextManifest:
    request = planning_request(preparation(tmp_path))
    spec = product_spec(request)
    approved = approval(spec)
    design = technical_design(spec, approved)
    current = request_revision(request)
    _, checkpoint = committed_design_handoff(tmp_path, current, spec, approved, design)
    run = FileDesignRecordStore(tmp_path / "design-records").get_run(checkpoint.run_id)
    assert run.planning_authorization is not None
    return PlannerContextBuilder().build(
        project_request_revision=current,
        product_spec=spec,
        product_approval=approved,
        technical_design=design,
        design_checkpoint=checkpoint,
        planning_authorization=run.planning_authorization,
        expected_execution_plan_version=1,
        built_at=NOW + timedelta(minutes=4),
    )


def test_context_is_deterministic_task_free_and_fail_closed(tmp_path: Path) -> None:
    first = _context(tmp_path)
    second = PlannerContextBuilder().build(
        project_request_revision=first.project_request_revision,
        product_spec=first.product_spec,
        product_approval=first.product_approval,
        technical_design=first.technical_design,
        design_checkpoint=first.design_checkpoint,
        planning_authorization=first.planning_authorization,
        expected_execution_plan_version=1,
        built_at=NOW + timedelta(hours=1),
    )

    assert first.context_id == second.context_id
    assert first.context_sha256 == second.context_sha256
    assert "task" not in first.to_wire()
    assert first.permissions == PLANNER_AGENT_PERMISSIONS
    assert first.permissions.preview_scheduler is True
    assert first.permissions.persist_assignments_or_leases is False
    assert first.permissions.persist_model_selection is False
    assert first.permissions.run_commands is False

    tampered = first.model_copy(update={"expected_execution_plan_version": 2})
    with pytest.raises(PlannerContextIntegrityError):
        tampered.validate_integrity()


def test_context_rejects_non_planning_request(tmp_path: Path) -> None:
    original = planning_request(preparation(tmp_path))
    request = ProjectRequest.create(
        request_id=original.id,
        project_id=original.project_id,
        preparation_sha256=original.preparation_sha256,
        title=original.title,
        original_request=original.original_request,
        status=ProjectRequestStatus.DESIGNING,
        created_at=original.created_at,
        updated_at=original.updated_at,
    )
    spec = product_spec(request)
    approved = approval(spec)
    design = technical_design(spec, approved)
    valid_current = request_revision(original)
    _, checkpoint = committed_design_handoff(
        tmp_path,
        valid_current,
        product_spec(original),
        approval(product_spec(original)),
        technical_design(product_spec(original), approval(product_spec(original))),
    )
    invalid_revision = ProjectRequestRevision.create(
        request,
        revision=valid_current.revision,
        supersedes_sha256=valid_current.supersedes_sha256,
        recorded_at=request.updated_at,
    )
    run = FileDesignRecordStore(tmp_path / "design-records").get_run(checkpoint.run_id)
    assert run.planning_authorization is not None

    with pytest.raises(PlannerContextLineageError, match="PLANNING"):
        PlannerContextBuilder().build(
            project_request_revision=invalid_revision,
            product_spec=spec,
            product_approval=approved,
            technical_design=design,
            design_checkpoint=checkpoint,
            planning_authorization=run.planning_authorization,
            expected_execution_plan_version=1,
            built_at=NOW,
        )


def test_fake_adapter_exact_replay_and_changed_run_conflict(tmp_path: Path) -> None:
    context = _context(tmp_path)
    plan = execution_plan(context.product_spec, context.technical_design)
    adapter = FakePlannerAgentAdapter(
        default=FakePlannerScenario(
            behavior=FakePlannerBehavior.READY,
            execution_plan=plan,
        )
    )
    request = PlannerAgentRequest(
        run_id="run_planner_001",
        project_id=context.project_id,
        request_id=context.request_id,
        context=context,
    )

    first = adapter.run(request)
    assert first is adapter.run(request)
    assert first.status is PlannerAgentRunStatus.SUCCEEDED
    assert first.execution_plan == plan

    changed = request.model_copy(update={"timeout_seconds": 601})
    with pytest.raises(PlannerAgentRequestConflict):
        adapter.run(changed)


def test_fake_adapter_maps_timeout_and_rejects_stale_plan_version(tmp_path: Path) -> None:
    context = _context(tmp_path)
    plan = execution_plan(context.product_spec, context.technical_design).model_copy(
        update={"version": 2}
    )
    invalid = FakePlannerAgentAdapter(
        default=FakePlannerScenario(
            behavior=FakePlannerBehavior.READY,
            execution_plan=plan,
        )
    ).run(
        PlannerAgentRequest(
            run_id="run_planner_invalid_001",
            project_id=context.project_id,
            request_id=context.request_id,
            context=context,
        )
    )
    assert invalid.status is PlannerAgentRunStatus.FAILED
    assert invalid.error is not None and invalid.error.code.value == "INVALID_OUTPUT"

    timed_out = FakePlannerAgentAdapter(
        default=FakePlannerScenario(behavior=FakePlannerBehavior.TIMEOUT)
    ).run(
        PlannerAgentRequest(
            run_id="run_planner_timeout_001",
            project_id=context.project_id,
            request_id=context.request_id,
            context=context,
        )
    )
    assert timed_out.status is PlannerAgentRunStatus.TIMED_OUT
    assert timed_out.execution_plan is None


def test_execution_plan_rejects_concrete_allocation_fields(tmp_path: Path) -> None:
    context = _context(tmp_path)
    payload = execution_plan(context.product_spec, context.technical_design).to_wire()
    phases = payload["phases"]
    assert isinstance(phases, list)
    phase = phases[0]
    assert isinstance(phase, dict)
    phase["agent_id"] = "agent_coder_001"
    phase["provider"] = "provider_a"
    phase["lease_id"] = "lease_coder_001"

    with pytest.raises(ValidationError):
        type(execution_plan(context.product_spec, context.technical_design)).model_validate(payload)
