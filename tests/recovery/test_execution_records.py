"""Recovery wire/allocation/receipt rejection and replay, with fake facts only."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.project_manager.dispatch import (
    ContinuationDispatchRecord,
    RecoveryDispatchRecord,
    _record_digest,
)
from ai_software_engineer.recovery import (
    CapturedChanges,
    FileRecoveryStore,
    RecoveryAuthorization,
    RecoveryRejected,
)
from ai_software_engineer.recovery.records import RecoveryInvocationRecord, RecoverySeedRecord
from tests.project_manager.test_dispatch_authority import _durable_facts
from tests.recovery.test_authorization import Human, approval, make_plan
from tests.recovery.test_task_record import record_for


def allocation(tmp_path: Path) -> RecoveryDispatchRecord:
    _, _, native, _, _ = _durable_facts(tmp_path)
    sha = "9" * 64
    task_id = f"task_recovery_{sha[:32]}"
    task = native.task.model_copy(
        update={
            "id": task_id,
            "metadata": {
                **native.task.metadata,
                "recovery_plan_sha256": sha,
            },
        }
    )
    phases = tuple(
        p.model_copy(
            update={
                "assignment": p.assignment.model_copy(update={"task_id": task_id}),
                "lease": p.lease.model_copy(update={"task_id": task_id}),
            }
        )
        for p in native.phases
    )
    result = RecoveryDispatchRecord(
        id=f"dispatch_commit_{sha}",
        project_id=native.project_id,
        task_id=task_id,
        project_request_id=native.project_request_id,
        execution_plan_id=native.execution_plan_id,
        execution_plan_sha256=native.execution_plan_sha256,
        execution_plan_phase_ids=native.execution_plan_phase_ids,
        recovery_plan_sha256=sha,
        recovery_task_record_sha256="8" * 64,
        workforce_snapshot_sha256="7" * 64,
        task=task,
        phases=phases,
        committed_at=native.committed_at,
        dispatch_sha256="0" * 64,
    )
    return result.model_copy(update={"dispatch_sha256": _record_digest(result)})


def continuation_allocation(tmp_path: Path) -> ContinuationDispatchRecord:
    _, _, native, _, _ = _durable_facts(tmp_path)
    sha = "6" * 64
    task_id = f"task_continue_{sha[:32]}"
    source = {
        "continuation_kind": "verification_remediation",
        "continuation_sha256": sha,
        "continuation_plan_sha256": "5" * 64,
        "continuation_context_sha256": "4" * 64,
        "continuation_target_preparation_sha256": "3" * 64,
        "continuation_of_delivery_id": "delivery_alpha",
        "continuation_of_task_id": native.task_id,
        "continuation_source_base_revision": native.task.base_ref,
        "continuation_source_revision": "7" * 40,
        "continuation_source_dispatch_id": native.id,
    }
    task = native.task.model_copy(
        update={"id": task_id, "metadata": {**native.task.metadata, **source}}
    )
    phases = tuple(
        p.model_copy(
            update={
                "assignment": p.assignment.model_copy(update={"task_id": task_id}),
                "lease": p.lease.model_copy(update={"task_id": task_id}),
            }
        )
        for p in native.phases
    )
    assert len(phases) == 3
    result = ContinuationDispatchRecord(
        id=f"dispatch_commit_{sha}",
        project_id=native.project_id,
        task_id=task_id,
        project_request_id=native.project_request_id,
        execution_plan_id=native.execution_plan_id,
        execution_plan_sha256=native.execution_plan_sha256,
        execution_plan_phase_ids=native.execution_plan_phase_ids,
        continuation_kind="verification_remediation",
        continuation_sha256=sha,
        continuation_plan_sha256="5" * 64,
        continuation_context_sha256="4" * 64,
        target_preparation_sha256="3" * 64,
        source_delivery_id="delivery_alpha",
        source_task_id=native.task_id,
        source_base_revision=native.task.base_ref,
        source_revision="7" * 40,
        source_dispatch_id=native.id,
        workforce_snapshot_sha256="8" * 64,
        task=task,
        phases=phases,
        committed_at=native.committed_at,
        dispatch_sha256="0" * 64,
    )
    return result.model_copy(update={"dispatch_sha256": _record_digest(result)})


def schema() -> Draft202012Validator:
    value = json.loads(
        (Path(__file__).parents[2] / "schemas/recovery-execution.schema.json").read_text()
    )
    assert value["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert value["$id"].endswith("/recovery-execution.schema.json")
    Draft202012Validator.check_schema(value)
    return Draft202012Validator(value)


def test_recovery_allocation_schema_and_no_fake_planner_provenance(tmp_path: Path) -> None:
    record = allocation(tmp_path)
    record.validate_integrity()
    schema().validate(record.to_wire())
    assert "planner_run_id" not in record.to_wire()
    for field, value in (
        ("task_id", "task_wrong"),
        ("project_id", "project_wrong"),
        ("id", "dispatch_commit_" + "1" * 64),
        ("recovery_plan_sha256", "1" * 64),
        ("project_request_id", "request_wrong"),
    ):
        with pytest.raises(ValidationError):
            RecoveryDispatchRecord.model_validate({**record.to_wire(), field: value})
    payload = record.to_wire()
    for phases in (tuple(reversed(record.phases)), (record.phases[0],) * 3):
        with pytest.raises(ValidationError):
            RecoveryDispatchRecord.model_validate({**payload, "phases": phases})
    with pytest.raises(RuntimeError):
        record.model_copy(update={"dispatch_sha256": "0" * 64}).validate_integrity()


def test_continuation_allocation_binds_rejected_candidate_and_successor_task(
    tmp_path: Path,
) -> None:
    record = continuation_allocation(tmp_path)

    record.validate_integrity()
    schema().validate(record.to_wire())
    assert record.task.metadata["continuation_sha256"] == record.continuation_sha256
    assert record.task.metadata["continuation_of_task_id"] == record.source_task_id
    for field, value in (
        ("source_delivery_id", "delivery_other"),
        ("source_task_id", "task_other"),
        ("source_revision", "9" * 40),
        ("source_dispatch_id", "dispatch_commit_" + "1" * 64),
    ):
        with pytest.raises(ValidationError):
            ContinuationDispatchRecord.model_validate({**record.to_wire(), field: value})
    with pytest.raises(RuntimeError):
        record.model_copy(update={"dispatch_sha256": "0" * 64}).validate_integrity()


def test_seed_invocation_store_schema_lock_and_replay(tmp_path: Path) -> None:
    plan = make_plan(tmp_path / "project")
    auth = RecoveryAuthorization.create(approval(plan), Human().verify(approval(plan)))
    task_record = record_for(plan, auth)
    capture = plan.capture.to_capture()
    target = replace(
        capture.worktree,
        task_id=plan.new_task_id,
        head_revision=plan.target_base_revision,
        path=tmp_path / "target",
        branch=f"ai/{plan.new_task_id}/attempt-1",
    )
    seed = RecoverySeedRecord.create(
        plan_sha256=plan.plan_sha256,
        dispatch_sha256="8" * 64,
        capture=CapturedChanges.from_capture(replace(capture, worktree=target)),
    )
    store = FileRecoveryStore.initialize(tmp_path / "records", scope=plan.source.scope)
    store.put_plan(plan)
    store.put_authorization(auth)
    store.put_task_record(task_record)
    assert store.put_seed(seed) == seed
    schema().validate(seed.to_wire())
    reopened = FileRecoveryStore(tmp_path / "records", scope=plan.source.scope)
    before = {p.name: p.read_bytes() for p in (tmp_path / "records").iterdir()}
    assert reopened.put_seed(seed) == seed
    assert {p.name: p.read_bytes() for p in (tmp_path / "records").iterdir()} == before
    with (
        store.execution_lock(),
        pytest.raises(RecoveryRejected, match="executor"),
        reopened.execution_lock(),
    ):
        pytest.fail("second executor admitted")
    invocation = RecoveryInvocationRecord(
        recovery_plan_sha256=plan.plan_sha256,
        seed_record_sha256=seed.record_sha256,
        run_id="run_recovery",
        context_manifest_id="ctx_" + "3" * 64,
        record_sha256="0" * 64,
    )
    invocation = invocation.model_copy(update={"record_sha256": invocation.recompute_sha256()})
    schema().validate(invocation.to_wire())
    assert store.put_invocation(invocation) == invocation
    assert reopened.get_invocation(plan.plan_sha256) == invocation
    with pytest.raises(RecoveryRejected):
        store.put_invocation(invocation.model_copy(update={"seed_record_sha256": "0" * 64}))
    with pytest.raises(RecoveryRejected):
        store.put_seed(seed.model_copy(update={"record_sha256": "0" * 64}))
    (tmp_path / "records" / f"seed-{plan.plan_sha256}.json").write_text("{}")
    with pytest.raises(RecoveryRejected):
        reopened.get_invocation(plan.plan_sha256)
