"""An interrupted invocation never regains authority from its old approval."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from ai_software_engineer.domain.workforce import TaskLease
from ai_software_engineer.recovery.interruption_records import RecoveryInterruptionPlan
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryAuthorization,
    RecoveryRejected,
    VerifiedRecoveryDecision,
)
from ai_software_engineer.recovery.store import FileRecoveryStore
from tests.recovery.test_authorization import make_plan


def plan_fixture(tmp_path: Path) -> RecoveryInterruptionPlan:
    recovery = make_plan(tmp_path / "project")
    plan = RecoveryInterruptionPlan(
        scope=recovery.source.scope,
        recovery_plan_sha256=recovery.plan_sha256,
        authorization_sha256="a" * 64,
        seed_record_sha256="b" * 64,
        invocation_record_sha256="c" * 64,
        task_id="task_interrupted",
        task_sha256="d" * 64,
        events_sha256="e" * 64,
        task_revision=2,
        dispatch_sha256="f" * 64,
        work_item_id="work_interrupted",
        dispatch_sequence=0,
        expired_lease=TaskLease(
            id="lease_interrupted",
            assignment_id="assignment_interrupted",
            task_id="task_interrupted",
            agent_id="agent_coder",
            acquired_at=recovery.created_at - timedelta(minutes=2),
            expires_at=recovery.created_at - timedelta(minutes=1),
        ),
        created_at=recovery.created_at,
        plan_sha256="0" * 64,
    )
    return plan.model_copy(update={"plan_sha256": plan.recompute_sha256()})


def test_interruption_plan_and_exact_authorization_are_immutable(tmp_path: Path) -> None:
    plan = plan_fixture(tmp_path)
    store = FileRecoveryStore.initialize(tmp_path / "records", scope=plan.scope)
    store.put_interruption_plan(plan)
    assert store.get_interruption_plan(plan.recovery_plan_sha256) == plan
    command = RecoveryApprovalCommand(
        operation_id="op_interruption",
        plan_sha256=plan.plan_sha256,
        approval_reference="exact-user-approval",
        submitted_at=plan.created_at,
    )
    authorization = RecoveryAuthorization.create(
        command,
        VerifiedRecoveryDecision(
            plan_sha256=plan.plan_sha256,
            approval_reference=command.approval_reference,
            approved=True,
            operator_id="operator",
            rationale="One replacement invocation",
            decided_at=plan.created_at,
        ),
    )
    store.put_interruption_authorization(plan.recovery_plan_sha256, authorization)
    schema = json.loads(Path("schemas/recovery-interruption.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(plan.to_wire())
    validator.validate(authorization.to_wire())
    assert store.get_interruption_authorization(plan.recovery_plan_sha256) == authorization
    with pytest.raises((RecoveryRejected, ValueError)):
        store.put_interruption_authorization(
            plan.recovery_plan_sha256,
            authorization.model_copy(
                update={
                    "command": command.model_copy(update={"plan_sha256": plan.recovery_plan_sha256})
                }
            ),
        )
    changed = plan.model_copy(update={"task_revision": 3})
    changed = changed.model_copy(update={"plan_sha256": changed.recompute_sha256()})
    with pytest.raises(RecoveryRejected):
        store.put_interruption_plan(changed)


def test_interruption_plan_rejects_live_lease_and_digest_drift(tmp_path: Path) -> None:
    plan = plan_fixture(tmp_path)
    with pytest.raises(RecoveryRejected, match="digest"):
        plan.model_copy(update={"task_revision": 8}).validate_integrity()
    live = plan.model_copy(update={"created_at": plan.expired_lease.acquired_at})
    live = live.model_copy(update={"plan_sha256": live.recompute_sha256()})
    with pytest.raises(RecoveryRejected, match="expired"):
        live.validate_integrity()
