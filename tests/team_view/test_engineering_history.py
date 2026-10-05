"""Engineering projections retain every exact record without changing durable facts."""

from datetime import timedelta
from importlib import import_module
from pathlib import Path

import pytest

from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    DeliveryWaitInvestigation,
    EngineeringDispositionRecord,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringScope,
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.native_verification import NativeVerificationWaitReason
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import BaselineOperatorAuthorization
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.verifier_preparation import (
    VerifierPreparationCheckpoint,
    VerifierPreparationIntent,
    VerifierPreparationObservation,
)
from ai_software_engineer.team_view.engineering_history import engineering_history
from ai_software_engineer.team_view.models import RoleQueueView, ScopeView, TaskView
from ai_software_engineer.team_view.reader import _with_execution_state
from tests.domain.factories import NOW, make_task


def _scope(task: Task) -> EngineeringScope:
    return EngineeringScope(
        team_id="team_history",
        project_id="project_history",
        repository_id="repository_history",
        repository_root=task.repository,
    )


def _proof(task: Task, number: int = 0) -> DeliveryWaitInvestigation:
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts(
            task_id=task.id,
            work_item_id="work_history",
            role=AgentRole.CODER,
            classification="EXECUTION_UNCERTAIN",
            source_revision=task.base_ref,
            task_intent_sha256=task_intent_sha256(task),
            checkpoint_sequence=2,
            budget_available=True,
        )
    )
    value = DeliveryWaitInvestigation(
        task_id=task.id,
        work_item_id="work_history",
        disposition=disposition,
        disposition_sha256=disposition.disposition_sha256,
        task_intent_sha256=task_intent_sha256(task),
        task_revision=2,
        task_snapshot_sha256=digest(task.to_wire()),
        source_revision=task.base_ref,
        checkpoint_sequence=2,
        step_sha256="b" * 64,
        retry_cause="local_execution_limit",
        permitted_resolutions=(DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,),
        next_action="已核验精确现场, 等待工程决定。",
        inspected_at=NOW + timedelta(seconds=number),
        proof_sha256="0" * 64,
    )
    return value.model_copy(update={"proof_sha256": value.recompute_sha256()})


def _decision(proof: DeliveryWaitInvestigation) -> DeliveryResolution:
    value = DeliveryResolution(
        task_id=proof.task_id,
        work_item_id=proof.work_item_id,
        expected_disposition_sha256=proof.disposition_sha256,
        expected_task_intent_sha256=proof.task_intent_sha256,
        expected_source_revision=proof.source_revision,
        expected_checkpoint_sequence=proof.checkpoint_sequence,
        task_revision=proof.task_revision,
        task_snapshot_sha256=proof.task_snapshot_sha256,
        step_sha256=proof.step_sha256,
        resolution_kind=DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
        proof_sha256=proof.proof_sha256,
        operator_principal=LocalOperatorPrincipal.trusted_local(),
        retry_cause=proof.retry_cause,
        submitted_at=proof.inspected_at + timedelta(seconds=1),
        resolution_sha256="0" * 64,
    )
    return value.model_copy(update={"resolution_sha256": value.recompute_sha256()})


def _publish(
    sidecar: Path, proof: DeliveryWaitInvestigation, decision: DeliveryResolution | None = None
) -> None:
    records = KnowledgeRecordStore(sidecar / "state" / "delivery-waits")
    records.put("wait-investigations", proof.proof_sha256, proof)
    if decision is not None:
        records.put(
            "wait-resolutions",
            decision.work_item_id + ":" + decision.expected_disposition_sha256,
            decision,
        )


def _bytes(sidecar: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in sidecar.rglob("*") if path.is_file()}


def test_complete_engineering_history_is_read_only_and_keeps_actor_and_source(
    tmp_path: Path,
) -> None:
    task = make_task().model_copy(update={"status": TaskStatus.IMPLEMENTING, "attempts": 1})
    sidecar = tmp_path / "sidecar"
    proofs = tuple(_proof(task, number) for number in range(10))
    for proof in proofs:
        _publish(sidecar, proof)
    decision = _decision(proofs[-1])
    _publish(sidecar, proofs[-1], decision)
    before = _bytes(sidecar)

    history = engineering_history(sidecar, task, _scope(task), "delivery_history")

    assert len(history) == 11
    assert history[-1].details["operator_id"] == "operator:local-console"
    assert history[-1].details["authorization_source"] == "engineering_operator_decision"
    assert history[-1].source_sha256 == decision.resolution_sha256
    assert before == _bytes(sidecar)


def test_projected_secrets_are_redacted_without_rewriting_proof_or_decision(tmp_path: Path) -> None:
    task = make_task()
    proof = _proof(task).model_copy(update={"next_action": "诊断 token=private-value 请查看"})
    proof = proof.model_copy(update={"proof_sha256": proof.recompute_sha256()})
    decision = _decision(proof).model_copy(
        update={
            "operator_principal": LocalOperatorPrincipal(
                operator_id="operator token=private-actor",
                duties=(OperatorDuty.ENGINEERING,),
            ),
        }
    )
    decision = decision.model_copy(update={"resolution_sha256": decision.recompute_sha256()})
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof, decision)
    before = _bytes(sidecar)

    history = engineering_history(sidecar, task, _scope(task), "delivery_history")

    assert "private-value" not in history[0].summary
    assert "REDACTED" in history[0].summary
    assert "private-actor" not in str(history[1].details)
    assert history[0].source_sha256 == proof.proof_sha256
    assert before == _bytes(sidecar)


@pytest.mark.parametrize(
    "field", ["expected_source_revision", "task_snapshot_sha256", "step_sha256"]
)
def test_decision_with_valid_hash_but_another_exact_proof_is_refused(
    tmp_path: Path, field: str
) -> None:
    task = make_task()
    proof = _proof(task)
    decision = _decision(proof).model_copy(
        update={field: "f" * (40 if field == "expected_source_revision" else 64)}
    )
    decision = decision.model_copy(update={"resolution_sha256": decision.recompute_sha256()})
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof, decision)
    with pytest.raises(ValueError, match="exact investigation"):
        engineering_history(sidecar, task, _scope(task), "delivery_history")


def test_corrupt_or_symlinked_engineering_record_is_refused(tmp_path: Path) -> None:
    task = make_task()
    proof = _proof(task)
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof)
    path = next((sidecar / "state" / "delivery-waits").glob("wait-investigations-*.json"))
    original = path.read_bytes()
    path.write_bytes(original + b"broken")
    with pytest.raises(KnowledgeError):
        engineering_history(sidecar, task, _scope(task), "delivery_history")
    path.unlink()
    replacement = tmp_path / "outside.json"
    replacement.write_bytes(original)
    path.symlink_to(replacement)
    with pytest.raises(KnowledgeError):
        engineering_history(sidecar, task, _scope(task), "delivery_history")


def test_native_execution_phases_do_not_become_qa_verdicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ports = import_module("tests.manager.test_native_verification")
    fixture = ports._fixture(tmp_path)
    ports._fake_ports(monkeypatch, fixture)
    provider = fixture.bind()
    assert provider is not None
    provider.evidence_for(fixture.request, fixture.root, fixture.guard)
    sidecar = tmp_path / "sidecar"
    assert fixture.task.engineering_policy is not None
    scope = fixture.task.engineering_policy.scope
    before = _bytes(sidecar)

    history = engineering_history(sidecar, fixture.task, scope, "delivery_native_001")

    assert {entry.details["phase"] for entry in history} == {"STARTED", "COMPLETED"}
    assert all("PASS" not in entry.summary for entry in history)
    assert before == _bytes(sidecar)
    with pytest.raises(ValueError, match="Task or authority"):
        engineering_history(sidecar, fixture.task, scope, "delivery_foreign")


def test_terminal_engineering_reason_is_visible_without_reopening_task(tmp_path: Path) -> None:
    task = make_task().model_copy(update={"status": TaskStatus.BLOCKED})
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts(
            task_id=task.id,
            role=AgentRole.QA,
            classification="ENGINEERING_AUTHORIZATION",
            source_revision=task.base_ref,
            task_intent_sha256=task_intent_sha256(task),
            checkpoint_sequence=3,
            budget_available=True,
        )
    )
    record = EngineeringDispositionRecord(
        delivery_id="delivery_history",
        native_checkpoint_sha256="a" * 64,
        source_task_id=task.id,
        source_task_status=TaskStatus.BLOCKED,
        source_task_snapshot_sha256=digest(task.to_wire()),
        repository_root=task.repository,
        plan_sha256="b" * 64,
        rejection_code="LEGACY_AUTHORITY",
        disposition=disposition,
        recorded_at=NOW,
        record_sha256="0" * 64,
    )
    record = record.model_copy(update={"record_sha256": record.recompute_sha256()})
    sidecar = tmp_path / "sidecar"
    root = sidecar / "state" / "recovery"
    root.mkdir(parents=True)
    path = root / ("engineering-disposition-" + record.record_sha256 + ".json")
    path.write_text(record.model_dump_json(), encoding="utf-8")
    before = _bytes(sidecar)
    history = engineering_history(sidecar, task, _scope(task), "delivery_history")
    view = _with_execution_state(
        TaskView(
            id="delivery_history",
            project_id="project_history",
            request_id="delivery_history",
            task_id=task.id,
            title="历史需求",
            scope=ScopeView(root=task.repository, selected_paths=(".",)),
            status=task.status.value,
            checkpoint_stage="BLOCKED",
            terminal=True,
            last_activity=NOW,
            next_action="旧恢复文字",
            timeline=history,
        )
    )
    assert view.status == "BLOCKED" and view.terminal
    assert view.execution is not None and view.execution.state == "STOPPED"
    assert view.execution.reason_code == "ENGINEERING_AUTHORIZATION"
    assert view.execution.responsibility == "engineering"
    assert view.blocker == disposition.reason and view.next_action == disposition.next_action
    assert before == _bytes(sidecar)
    with pytest.raises(ValueError, match="source Task facts"):
        engineering_history(sidecar, task, _scope(task), "delivery_foreign")


def test_missing_engineering_history_creates_no_directory(tmp_path: Path) -> None:
    task = make_task()
    sidecar = tmp_path / "missing"
    assert engineering_history(sidecar, task, _scope(task), "delivery_history") == ()
    assert not sidecar.exists()


def test_engineering_wait_projects_actual_prerequisite_detail_and_keeps_checkpoint() -> None:
    task = make_task()
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts(
            task_id=task.id,
            work_item_id="work_prerequisite",
            role=AgentRole.CODER,
            classification="ENVIRONMENT_UNAVAILABLE",
            source_revision=task.base_ref,
            task_intent_sha256=task_intent_sha256(task),
            checkpoint_sequence=1,
            budget_available=True,
        )
    ).model_copy(update={"detail": "测试入口 tests/test_delivery.py 尚不存在, 需要工程团队处理。"})
    view = _with_execution_state(
        TaskView(
            id="delivery_history",
            project_id="project_history",
            request_id="request_history",
            task_id=task.id,
            title=task.title,
            scope=ScopeView(root=task.repository, selected_paths=(".",)),
            status="IMPLEMENTING",
            checkpoint_stage="DELIVERING",
            terminal=False,
            last_activity=NOW,
            next_action="旧展示",
            role_queue=(
                RoleQueueView(
                    work_item_id="work_prerequisite",
                    role=AgentRole.CODER,
                    attempt=1,
                    status=WorkItemStatus.WAITING_HUMAN,
                    wait_disposition=disposition,
                    wait_disposition_sha256=disposition.disposition_sha256,
                ),
            ),
        )
    )
    assert view.execution is not None and view.execution.state == "WAITING"
    assert disposition.reason in view.execution.reason
    assert disposition.detail is not None
    assert disposition.detail in view.execution.reason
    assert view.execution.responsibility == "engineering"
    assert view.status == "IMPLEMENTING" and not view.terminal
    assert view.blocker == view.execution.reason


def test_unused_verifier_preparation_is_history_and_not_an_invocation_or_verdict(
    tmp_path: Path,
) -> None:
    ports = import_module("tests.manager.test_native_verification")
    fixture = ports._fixture(tmp_path)
    task: Task = fixture.task
    intent = VerifierPreparationIntent.create(
        work_item_id=fixture.claim.work_item.id,
        lease_id=fixture.claim.lease.id,
        task_id=task.id,
        task_snapshot_sha256=digest(task.to_wire()),
        checkpoint_sequence=0,
        dispatch_sequence=fixture.claim.work_item.dispatch_sequence,
        request=fixture.request,
        request_sha256=digest(fixture.request.to_wire()),
        started_at=NOW,
    )
    marker = VerifierPreparationCheckpoint.create(
        work_item_id=fixture.claim.work_item.id,
        lease_id=fixture.claim.lease.id,
        task_id=task.id,
        task_snapshot_sha256=digest(task.to_wire()),
        checkpoint_sequence=0,
        dispatch_sequence=fixture.claim.work_item.dispatch_sequence,
        wait_dispatch_sequence=fixture.claim.work_item.dispatch_sequence,
        wait_lease_id=fixture.claim.lease.id,
        intent_sha256=intent.intent_sha256,
        source_revision=fixture.request.source_revision,
        run_id=fixture.request.run_id,
        role=fixture.request.role,
        attempt=1,
        context_manifest_id=fixture.request.context_manifest_id,
        request_sha256=digest(fixture.request.to_wire()),
        request=fixture.request,
        result="WAIT",
        observation=VerifierPreparationObservation(native_execution_state="NOT_STARTED"),
        failure_reason=NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE,
        checked_at=NOW,
    )
    sidecar = tmp_path / "sidecar"
    KnowledgeRecordStore(sidecar / "state" / "delivery-preflight").put(
        "verifier-preparation-intents",
        f"{intent.work_item_id}:{intent.checkpoint_sequence}:{intent.dispatch_sequence}",
        intent,
    )
    KnowledgeRecordStore(sidecar / "state" / "delivery-preflight").put(
        "verifier-preparations",
        marker.checkpoint_sha256,
        marker,
    )
    before = _bytes(sidecar)
    assert task.engineering_policy is not None
    history = engineering_history(
        sidecar, task, task.engineering_policy.scope, "delivery_native_001"
    )
    assert len(history) == 2
    preparation = next(
        entry for entry in history if entry.details["kind"] == "verifier_preparation_checkpoint"
    )
    assert preparation.details["native_execution_state"] == "NOT_STARTED"
    assert "模型调用前" not in preparation.summary or "通过" not in preparation.summary
    assert before == _bytes(sidecar)


def test_baseline_history_validates_real_actor_start_and_complete_same_branch_binding(
    tmp_path: Path,
) -> None:
    ports = import_module("tests.manager.test_execution_baseline")
    fixture = ports.setup(tmp_path)
    task: Task = fixture.collector.facts.task
    sidecar = tmp_path / "sidecar"
    store = FileExecutionBaselineStore(sidecar / "state" / "execution-baselines" / task.id)
    fixture.service.store = store
    plan = fixture.service.propose(fixture.target)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="原分支基线决定",
        submitted_at=NOW,
    )
    binding = fixture.service.execute(plan.plan_sha256, authority=authority)
    before = _bytes(sidecar)
    history = engineering_history(sidecar, task, fixture.collector.facts.scope, "delivery_history")
    assert len(history) == 3
    assert history[0].details["operator_id"] == "operator:local-console"
    assert history[1].details["kind"] == "baseline_operation_start"
    assert history[2].details["execution_source_revision"] == binding.execution_source_revision
    assert history[2].details["branch_name"] == task.branch_name
    assert before == _bytes(sidecar)
