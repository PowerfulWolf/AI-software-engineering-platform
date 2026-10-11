"""Wire/store contracts for sealed Task input; fake lineage is never executable authority."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.domain import (
    AcceptanceCriterion,
    ProjectRequest,
    ProjectRequestStatus,
    Task,
    TaskStatus,
)
from ai_software_engineer.recovery import (
    FileRecoveryStore,
    RecoveryAuthorization,
    RecoveryConflict,
    RecoveryPlan,
    RecoveryRejected,
)
from ai_software_engineer.recovery.records import RecoveryTaskRecord
from tests.recovery.test_authorization import Human, approval, make_plan
from tests.recovery.test_task_policy_builder import authorized_plan, policy_fixture


def record_for(plan: RecoveryPlan, authorization: RecoveryAuthorization) -> RecoveryTaskRecord:
    request = ProjectRequest.create(
        request_id="request_record",
        repository_id=plan.source.scope.repository_id,
        preparation_sha256=plan.target_preparation_sha256,
        title="Recovery",
        original_request="Change greeting",
        status=ProjectRequestStatus.READY_FOR_DELIVERY,
        created_at=plan.created_at,
    )
    task = Task(
        id=plan.new_task_id,
        title=request.title,
        description="fixture",
        repository=plan.source.scope.repository_root,
        base_ref=plan.target_base_revision,
        acceptance_criteria=(
            AcceptanceCriterion(
                id="ac_001", description="Greeting", required=True, verification="test"
            ),
        ),
        status=TaskStatus.NEW,
        max_attempts=(
            plan.target_authorization.source_max_attempts if plan.target_authorization else 1
        ),
        retry_policy=(
            plan.target_authorization.source_retry_policy if plan.target_authorization else None
        ),
        engineering_policy=(
            plan.target_authorization.engineering_policy if plan.target_authorization else None
        ),
        interruption_continuation_policy=(
            plan.target_authorization.interruption_continuation_policy
            if plan.target_authorization
            else None
        ),
        created_at=plan.created_at,
        updated_at=plan.created_at,
        metadata={
            "repository_id": request.repository_id,
            "project_request_id": request.id,
            "recovery_plan_sha256": plan.plan_sha256,
            "recovery_rebound_request_sha256": request.request_sha256,
            "recovery_target_preparation_sha256": request.preparation_sha256,
            "recovery_of_task_id": plan.source.task_id,
            "recovery_of_delivery_id": plan.source.scope.delivery_id,
            "recovery_source_checkpoint_sha256": plan.source.checkpoint_sha256,
            "product_spec_sha256": plan.source.product_spec_sha256,
            "technical_design_sha256": plan.source.technical_design_sha256,
            "execution_plan_sha256": plan.source.execution_plan_sha256,
        },
    )
    provisional = RecoveryTaskRecord(
        recovery_plan_sha256=plan.plan_sha256,
        authorization_sha256=authorization.authorization_sha256,
        rebound_request=request,
        task=task,
        record_sha256="0" * 64,
    )
    return provisional.model_copy(update={"record_sha256": provisional.recompute_sha256()})


def test_task_record_wire_store_and_corruption(tmp_path: Path) -> None:
    plan = make_plan(tmp_path / "project")
    decision = RecoveryAuthorization.create(approval(plan), Human().verify(approval(plan)))
    record = record_for(plan, decision)
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/recovery-task-record.schema.json").read_text()
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("/recovery-task-record.schema.json")
    Draft202012Validator.check_schema(schema)
    validator.validate(record.to_wire())
    assert RecoveryTaskRecord.model_validate(record.to_wire()) == record
    record.validate_binding(plan, decision)
    store = FileRecoveryStore.initialize(tmp_path / "records", scope=plan.source.scope)
    store.put_plan(plan)
    with pytest.raises(RecoveryRejected):
        store.put_task_record(record)
    store.put_authorization(decision)
    store.put_task_record(record)
    before = {p.name: p.read_bytes() for p in (tmp_path / "records").iterdir()}
    reopened = FileRecoveryStore(tmp_path / "records", scope=plan.source.scope)
    assert reopened.get_task_record(plan.plan_sha256) == record
    assert reopened.put_task_record(record) == record
    assert {p.name: p.read_bytes() for p in (tmp_path / "records").iterdir()} == before
    changed = record.model_copy(
        update={"task": record.task.model_copy(update={"title": "Changed"})}
    )
    changed = changed.model_copy(update={"record_sha256": changed.recompute_sha256()})
    with pytest.raises(RecoveryConflict):
        reopened.put_task_record(changed)
    path = tmp_path / "records" / f"task-{plan.plan_sha256}.json"
    path.write_text("{}")
    with pytest.raises(RecoveryRejected):
        reopened.get_task_record(plan.plan_sha256)


@pytest.mark.parametrize(
    "change",
    ["status", "attempts", "identity", "metadata", "secret", "digest", "base", "authorization"],
)
def test_bad_task_record_rejected(tmp_path: Path, change: str) -> None:
    plan = make_plan(tmp_path / "project")
    decision = RecoveryAuthorization.create(approval(plan), Human().verify(approval(plan)))
    record = record_for(plan, decision)
    wire = json.loads(record.model_dump_json())
    if change == "status":
        wire["task"]["status"] = "DONE"
    elif change == "attempts":
        wire["task"]["attempts"] = 1
    elif change == "identity":
        wire["task"]["id"] = plan.source.task_id
    elif change == "metadata":
        wire["task"]["metadata"]["recovery_plan_sha256"] = "f" * 64
    elif change == "secret":
        wire["task"]["description"] = "Bearer " + "x" * 24
    elif change == "digest":
        wire["record_sha256"] = "f" * 64
    elif change == "base":
        wire["task"]["base_ref"] = "main"
    else:
        wire["authorization_sha256"] = "f" * 64
    with pytest.raises((RecoveryRejected, ValidationError)):
        changed = RecoveryTaskRecord.model_validate(wire)
        if change in ("base", "authorization"):
            changed = changed.model_copy(update={"record_sha256": changed.recompute_sha256()})
        changed.validate_binding(plan, decision)


def test_record_preserves_exact_approved_target_authority(tmp_path: Path) -> None:
    plan = authorized_plan(policy_fixture(tmp_path))
    decision = RecoveryAuthorization.create(approval(plan), Human().verify(approval(plan)))
    record = record_for(plan, decision)
    record.validate_binding(plan, decision)
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/recovery-task-record.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(record.to_wire())
    authority = plan.target_authorization
    assert authority is not None
    assert record.task.engineering_policy == authority.engineering_policy
    assert (
        record.task.interruption_continuation_policy == authority.interruption_continuation_policy
    )
    assert record.task.retry_policy == authority.source_retry_policy


@pytest.mark.parametrize("change", ["drop_engineering", "drop_continuation", "scope", "budget"])
def test_record_rejects_valid_but_unapproved_task_policy_changes(
    tmp_path: Path, change: str
) -> None:
    plan = authorized_plan(policy_fixture(tmp_path))
    decision = RecoveryAuthorization.create(approval(plan), Human().verify(approval(plan)))
    record = record_for(plan, decision)
    authority = plan.target_authorization
    assert authority is not None and authority.source_retry_policy is not None
    task = record.task
    if change == "drop_engineering":
        task = task.model_copy(update={"engineering_policy": None})
    elif change == "drop_continuation":
        task = task.model_copy(update={"interruption_continuation_policy": None})
    elif change == "scope":
        policy = authority.engineering_policy
        task = task.model_copy(
            update={
                "engineering_policy": policy.model_copy(
                    update={
                        "scope": policy.scope.model_copy(update={"project_id": "project_other"})
                    }
                )
            }
        )
    else:
        retry = authority.source_retry_policy.model_copy(update={"max_work_attempts": 5})
        task = task.model_copy(
            update={"retry_policy": retry, "max_attempts": retry.execution_limit}
        )
    changed = record.model_copy(update={"task": task})
    changed = changed.model_copy(update={"record_sha256": changed.recompute_sha256()})
    with pytest.raises(RecoveryRejected, match="authority differs"):
        changed.validate_binding(plan, decision)


def test_legacy_record_rejects_new_authority_not_in_approved_plan(tmp_path: Path) -> None:
    fixture = policy_fixture(tmp_path)
    plan = fixture.plan
    decision = RecoveryAuthorization.create(approval(plan), Human().verify(approval(plan)))
    record = record_for(plan, decision)
    before = record.model_dump_json()
    authority = authorized_plan(fixture).target_authorization
    assert authority is not None
    changed = record.model_copy(
        update={
            "task": record.task.model_copy(
                update={"engineering_policy": authority.engineering_policy}
            )
        }
    )
    changed = changed.model_copy(update={"record_sha256": changed.recompute_sha256()})
    with pytest.raises(RecoveryRejected, match="authority differs"):
        changed.validate_binding(plan, decision)
    assert record.model_dump_json() == before
    record.validate_binding(plan, decision)
