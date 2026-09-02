"""Append-only FileExecutionPlanStore contract tests."""

import json
import os
from pathlib import Path

import pytest

import ai_software_engineer.planning.store as planning_store_module
from ai_software_engineer.domain import (
    ExecutionPlan,
    ProductSpec,
    ProjectRequestStatus,
    TechnicalDesign,
)
from ai_software_engineer.planning import (
    ExecutionPlanConflict,
    ExecutionPlanCorruption,
    ExecutionPlanNotFound,
    ExecutionPlanPathError,
    FileExecutionPlanStore,
    PlannerCommitCheckpoint,
    PlannerRunOutcome,
    PlannerRunRecord,
)
from ai_software_engineer.product.models import ProjectRequestRevision
from tests.planning.conftest import (
    NOW,
    approval,
    execution_plan,
    planning_request,
    preparation,
    product_spec,
    ready_request,
    request_revision,
    technical_design,
)


def _stage(tmp_path: Path) -> tuple[ProductSpec, TechnicalDesign, ExecutionPlan]:
    request = planning_request(preparation(tmp_path))
    spec = product_spec(request)
    approved = approval(spec)
    design = technical_design(spec, approved)
    return spec, design, execution_plan(spec, design)


def _planner_record(tmp_path: Path) -> PlannerRunRecord:
    request = planning_request(preparation(tmp_path))
    current = request_revision(request)
    spec = product_spec(request)
    design = technical_design(spec, approval(spec))
    plan = execution_plan(spec, design)
    ready = ready_request(request)
    assert ready.status is ProjectRequestStatus.READY_FOR_DELIVERY
    ready_revision = ProjectRequestRevision.create(
        ready,
        revision=current.revision + 1,
        supersedes_sha256=current.request_revision_sha256,
        recorded_at=ready.updated_at,
    )
    return PlannerRunRecord.create(
        run_id="run_planner_store_001",
        project_id=request.project_id,
        request_id=request.id,
        context_id="ctx_" + "a" * 64,
        input_sha256="b" * 64,
        input_request_revision_sha256=current.request_revision_sha256,
        design_checkpoint_sha256="c" * 64,
        planning_authorization_sha256="d" * 64,
        outcome=PlannerRunOutcome.READY_FOR_DELIVERY,
        execution_plan=plan,
        ready_request_revision=ready_revision,
        recorded_at=NOW,
    )


def test_file_execution_plan_store_round_trip_exact_replay_and_conflict(tmp_path: Path) -> None:
    spec, design, plan = _stage(tmp_path)
    store = FileExecutionPlanStore(tmp_path / "sidecar-records")

    first = store.put_execution_plan(plan)
    assert store.put_execution_plan(plan) == first
    assert store.get_execution_plan(plan.id) == plan
    assert store.find_for_request(plan.request_id) == plan
    assert store.find_for_request("request_missing_001") is None

    changed_phase = plan.phases[0].model_copy(update={"objective": "Changed objective"})
    changed = ExecutionPlan.create(
        spec,
        design,
        plan_id=plan.id,
        version=plan.version,
        phases=(changed_phase, plan.phases[1], plan.phases[2]),
        created_at=plan.created_at,
    )
    with pytest.raises(ExecutionPlanConflict):
        store.put_execution_plan(changed)

    ambiguous = ExecutionPlan.create(
        spec,
        design,
        plan_id="execution_plan_planning_duplicate",
        version=1,
        phases=plan.phases,
        created_at=plan.created_at,
    )
    store.put_execution_plan(ambiguous)
    with pytest.raises(ExecutionPlanCorruption, match="ambiguous"):
        store.find_for_request(plan.request_id)


def test_file_execution_plan_store_detects_envelope_tamper(tmp_path: Path) -> None:
    _, _, plan = _stage(tmp_path)
    root = tmp_path / "sidecar-records"
    store = FileExecutionPlanStore(root)
    store.put_execution_plan(plan)
    target = root / "execution-plans" / f"{plan.id}.json"
    envelope = json.loads(target.read_text(encoding="utf-8"))
    envelope["record"]["version"] = 2
    target.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ExecutionPlanCorruption):
        store.get_execution_plan(plan.id)


def test_file_execution_plan_store_writes_all_bytes_on_short_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, plan = _stage(tmp_path)
    run = _planner_record(tmp_path)
    checkpoint = PlannerCommitCheckpoint.create(run, committed_at=NOW)
    store = FileExecutionPlanStore(tmp_path / "sidecar-records")
    real_write = os.write
    short_writes = 0

    def write_part(descriptor: int, payload: bytes) -> int:
        nonlocal short_writes
        short_writes += 1
        return real_write(descriptor, payload[: max(1, len(payload) // 2)])

    monkeypatch.setattr(os, "write", write_part)

    assert store.put_execution_plan(plan) == plan
    assert store.get_execution_plan(plan.id) == plan
    assert store.put_run(run) == run
    assert store.put_checkpoint(checkpoint) == checkpoint
    assert store.get_checkpoint(run.run_id) == checkpoint
    assert short_writes > 1


def test_planner_checkpoint_requires_exact_durable_run(tmp_path: Path) -> None:
    run = _planner_record(tmp_path)
    checkpoint = PlannerCommitCheckpoint.create(run, committed_at=NOW)
    store = FileExecutionPlanStore(tmp_path / "sidecar-records")

    with pytest.raises(ExecutionPlanNotFound):
        store.put_checkpoint(checkpoint)

    assert store.put_run(run) == run
    assert store.put_checkpoint(checkpoint) == checkpoint
    assert store.get_checkpoint(run.run_id) == checkpoint

    forged_run = PlannerRunRecord.create(
        run_id=run.run_id,
        project_id=run.project_id,
        request_id=run.request_id,
        context_id=run.context_id,
        input_sha256=run.input_sha256,
        input_request_revision_sha256=run.input_request_revision_sha256,
        design_checkpoint_sha256=run.design_checkpoint_sha256,
        planning_authorization_sha256="e" * 64,
        outcome=run.outcome,
        execution_plan=run.execution_plan,
        ready_request_revision=run.ready_request_revision,
        recorded_at=run.recorded_at,
    )
    forged = PlannerCommitCheckpoint.create(forged_run, committed_at=NOW)
    with pytest.raises(ExecutionPlanCorruption, match="exact durable"):
        store.put_checkpoint(forged)


def test_file_execution_plan_store_rejects_parent_swap_without_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, plan = _stage(tmp_path)
    root = tmp_path / "sidecar-records"
    store = FileExecutionPlanStore(root)
    category = root / "execution-plans"
    category.mkdir()
    displaced = root / "execution-plans-displaced"
    outside = tmp_path / "outside"
    outside.mkdir()
    real_matches = planning_store_module._directory_fd_matches_path
    swapped = False

    def swap_then_check(descriptor: int, path: Path) -> bool:
        nonlocal swapped
        if path == category and not swapped:
            swapped = True
            category.rename(displaced)
            category.symlink_to(outside, target_is_directory=True)
        return real_matches(descriptor, path)

    monkeypatch.setattr(planning_store_module, "_directory_fd_matches_path", swap_then_check)

    with pytest.raises(ExecutionPlanPathError, match="changed during publication"):
        store.put_execution_plan(plan)

    assert tuple(outside.iterdir()) == ()
    assert not (displaced / f"{plan.id}.json").exists()
