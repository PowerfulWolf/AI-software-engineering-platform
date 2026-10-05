"""Frozen scope, shared budgets and restart-safe policy receipts without live services."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.domain.engineering_authority import (
    EngineeringAdmission,
    EngineeringCapability,
    EngineeringGrant,
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.prerequisite_repair import (
    PrerequisiteRepairPlan,
    PrerequisiteRepairRequest,
)
from ai_software_engineer.domain.task import Task
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.engineering_authority import EngineeringAuthority
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.recovery.entry import ExplicitRecoveryHuman
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryRejected,
    RecoveryScope,
)
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.verification_admission import ExplicitVerificationHuman
from tests.domain.factories import NOW, make_task


def engineering_fixture(tmp_path: Path) -> tuple[Task, FileRecoveryStore, EngineeringAuthority]:
    repository = str(tmp_path / "project")
    policy = EngineeringPolicy.bounded_local(
        scope=EngineeringScope(
            team_id="team_test",
            project_id="project_test",
            repository_id="repository_test",
            repository_root=repository,
        ),
        principal=LocalOperatorPrincipal.trusted_local(),
    )
    task = Task.model_validate(
        {**make_task().to_wire(), "repository": repository, "engineering_policy": policy.to_wire()}
    )
    scope = RecoveryScope(
        team_id="team_test",
        repository_id="repository_test",
        delivery_id="delivery_test",
        repository_root=repository,
    )
    ledger = tmp_path / "ledger"
    ledger.mkdir(mode=0o700)
    return (
        task,
        FileRecoveryStore.initialize(tmp_path / "recovery", scope=scope),
        EngineeringAuthority(ledger),
    )


def admit(
    authority: EngineeringAuthority,
    task: Task,
    store: FileRecoveryStore,
    identity: str = "a" * 64,
    *,
    at: datetime = NOW,
) -> EngineeringAdmission:
    return authority.admit(
        task=task,
        store=store,
        plan_sha256=identity,
        facts_sha256=identity,
        capabilities=(EngineeringCapability.VERIFICATION_REFRESH,),
        at=at,
    )


def test_policy_receipt_replays_after_restart_and_preserves_human_semantics(tmp_path: Path) -> None:
    task, store, authority = engineering_fixture(tmp_path)
    receipt = admit(authority, task, store)
    assert receipt.authorization_source == "organization_engineering_policy"
    assert "decision" not in receipt.to_wire() and "command" not in receipt.to_wire()
    reopened = FileRecoveryStore(store._root, scope=store._scope)
    assert admit(EngineeringAuthority(authority.ledger_root), task, reopened) == receipt
    assert len(reopened.list_engineering_admissions()) == 1
    schema = json.loads(Path("schemas/engineering-authority.schema.json").read_text())
    Draft202012Validator(schema).validate(receipt.to_wire())
    assert task.engineering_policy is not None
    Draft202012Validator(schema).validate(task.engineering_policy.to_wire())


def test_shared_budget_counts_other_scoped_stores_and_rejects_drift(tmp_path: Path) -> None:
    task, first, authority = engineering_fixture(tmp_path)
    second = FileRecoveryStore.initialize(tmp_path / "other-recovery", scope=first._scope)
    records = [
        admit(authority, task, first, "a" * 64),
        admit(authority, task, second, "b" * 64),
        admit(authority, task, first, "c" * 64),
    ]
    assert [record.admission_number for record in records] == [1, 2, 3]
    with pytest.raises(RecoveryRejected, match="预算"):
        admit(authority, task, second, "d" * 64)
    changed = task.model_copy(update={"description": "changed business scope"})
    with pytest.raises(RecoveryRejected, match="冻结"):
        admit(authority, changed, first)
    with pytest.raises(RecoveryRejected, match="能力"):
        authority.admit(
            task=task,
            store=first,
            plan_sha256="a" * 64,
            facts_sha256="f" * 64,
            capabilities=(EngineeringCapability.VERIFICATION_REFRESH,),
            at=NOW,
        )


def test_ledger_published_before_local_failure_resumes_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, store, authority = engineering_fixture(tmp_path)
    publish = store.put_engineering_admission
    monkeypatch.setattr(
        store, "put_engineering_admission", Mock(side_effect=RuntimeError("stopped"))
    )
    with pytest.raises(RuntimeError, match="stopped"):
        admit(authority, task, store)
    monkeypatch.setattr(store, "put_engineering_admission", publish)
    receipt = admit(EngineeringAuthority(authority.ledger_root), task, store)
    assert receipt.admission_number == 1
    assert len(store.list_engineering_admissions()) == 1


def test_legacy_policy_absence_and_unknown_capability_do_not_gain_authority(tmp_path: Path) -> None:
    task, store, authority = engineering_fixture(tmp_path)
    legacy = Task.model_validate(
        {key: value for key, value in task.to_wire().items() if key != "engineering_policy"}
    )
    assert "engineering_policy" not in legacy.to_wire()
    with pytest.raises(RecoveryRejected, match="旧任务"):
        admit(authority, legacy, store)
    assert not store.list_engineering_admissions()
    assert list(authority.ledger_root.iterdir()) == []
    with pytest.raises(ValidationError):
        EngineeringGrant(capability="install_toolchain", max_admissions=3)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "paths,denied",
    [
        (("src/feature.py",), ()),
        (("src/feature/**",), ()),
        (("outside/change.py",), ()),
        (("src/feature/**",), ("src/feature/secret.py",)),
    ],
)
def test_prerequisite_repair_cannot_expand_scope(
    tmp_path: Path,
    paths: tuple[str, ...],
    denied: tuple[str, ...],
) -> None:
    task, _, _ = engineering_fixture(tmp_path)
    assert task.constraints is not None
    task = task.model_copy(
        update={
            "constraints": task.constraints.model_copy(
                update={
                    "allowed_paths": ("src/**", "tests/**"),
                    "denied_paths": denied,
                }
            )
        }
    )
    plan = PrerequisiteRepairPlan(
        repository_root=task.repository,
        delivery_id="delivery_test",
        source_task_id=task.id,
        source_plan_sha256="a" * 64,
        completion_sha256="b" * 64,
        incident_sha256="c" * 64,
        native_checkpoint_sha256="d" * 64,
        candidate_revision="e" * 40,
        target_base_revision="f" * 40,
        target_preparation_sha256="1" * 64,
        request=PrerequisiteRepairRequest(
            objective="Fix the original verification prerequisite", write_paths=paths
        ),
        created_at=NOW,
        plan_sha256="0" * 64,
    )
    if paths[0].startswith("outside") or denied:
        with pytest.raises(RecoveryRejected, match="范围"):
            EngineeringAuthority.require_in_scope_repair(task, plan)
    else:
        EngineeringAuthority.require_in_scope_repair(task, plan)


def test_product_identity_cannot_grant_engineering_policy_or_human_recovery() -> None:
    product = LocalOperatorPrincipal(operator_id="operator:product", duties=(OperatorDuty.PRODUCT,))
    scope = EngineeringScope(
        team_id="team_test",
        project_id="project_test",
        repository_id="repository_test",
        repository_root="/test/project",
    )
    with pytest.raises(ValueError, match="ENGINEERING"):
        EngineeringPolicy.bounded_local(scope=scope, principal=product)
    command = RecoveryApprovalCommand(
        operation_id="op_engineering_test",
        plan_sha256="a" * 64,
        approval_reference="exact-human",
        submitted_at=NOW,
    )
    for verifier in (
        ExplicitRecoveryHuman("a" * 64, product),
        ExplicitVerificationHuman("a" * 64, product),
    ):
        with pytest.raises(ValueError, match="ENGINEERING"):
            verifier.verify(command)
    engineer = LocalOperatorPrincipal(
        operator_id="operator:engineer", duties=(OperatorDuty.ENGINEERING,)
    )
    decision = ExplicitVerificationHuman("a" * 64, engineer).verify(command)
    assert decision.operator_id == engineer.operator_id
    with pytest.raises(ValueError, match="PRODUCT"):
        engineer.require_duty(OperatorDuty.PRODUCT)


def test_public_host_rejects_product_only_manual_engineering_action_before_runtime_open() -> None:
    host = object.__new__(TeamHost)
    host._operator_principal = LocalOperatorPrincipal(
        operator_id="operator:product", duties=(OperatorDuty.PRODUCT,)
    )
    runtime = Mock(side_effect=AssertionError("runtime must not open"))
    host._runtime = runtime  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="ENGINEERING"):
        host.resume_delivery(
            ResumeProjectDelivery(
                delivery_id="delivery_test",
                approved_plan_sha256="a" * 64,
                approval_reference="exact-engineering-decision",
            )
        )
    runtime.assert_not_called()
