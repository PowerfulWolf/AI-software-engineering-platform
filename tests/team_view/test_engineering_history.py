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
    DeliveryProofMissing,
    DeliveryResolution,
    DeliveryResolutionKind,
    DeliveryWaitCollectionFailure,
    DeliveryWaitHandling,
    DeliveryWaitHandlingStatus,
    DeliveryWaitInvestigation,
    EngineeringDispositionRecord,
    delivery_wait_resolution_plan_sha256,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringAdmission,
    EngineeringCapability,
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    ExecutionBaselineBinding,
)
from ai_software_engineer.domain.native_verification import NativeVerificationWaitReason
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import (
    BaselineContinueAuthorization,
    BaselineOperatorAuthorization,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.verifier_preparation import (
    VerifierPreparationCheckpoint,
    VerifierPreparationIntent,
    VerifierPreparationObservation,
)
from ai_software_engineer.recovery.models import RecoveryRejected
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


def _policy_task() -> Task:
    task = make_task()
    policy = EngineeringPolicy.bounded_local(
        scope=_scope(task), principal=LocalOperatorPrincipal.trusted_local()
    )
    return Task.model_validate({**task.to_wire(), "engineering_policy": policy.to_wire()})


def _policy_decision(
    task: Task,
    proof: DeliveryWaitInvestigation,
    *,
    policy: EngineeringPolicy | None = None,
) -> DeliveryResolution:
    frozen = policy or task.engineering_policy
    assert frozen is not None
    kind = DeliveryResolutionKind.RETRY_FROM_CHECKPOINT
    admission = EngineeringAdmission.create(
        task_id=task.id,
        task_intent_sha256=task_intent_sha256(task),
        policy=frozen,
        policy_sha256=frozen.policy_sha256,
        plan_sha256=delivery_wait_resolution_plan_sha256(proof.proof_sha256, kind),
        facts_sha256=proof.proof_sha256,
        capabilities=(EngineeringCapability.DELIVERY_WAIT_RESOLUTION,),
        admission_number=1,
        admitted_at=proof.inspected_at + timedelta(seconds=1),
    )
    value = DeliveryResolution.model_validate(
        {
            **_decision(proof).to_wire(),
            "authorization_source": "organization_engineering_policy",
            "operator_principal": None,
            "engineering_admission": admission.to_wire(),
        }
    )
    return value.model_copy(update={"resolution_sha256": value.recompute_sha256()})


def _handling(
    proof: DeliveryWaitInvestigation,
    resolution: DeliveryResolution | None = None,
    *,
    status: DeliveryWaitHandlingStatus = "PLATFORM_ATTENTION",
    manual_resolution_allowed: bool = False,
    collection_failed: bool = False,
) -> DeliveryWaitHandling:
    value = DeliveryWaitHandling(
        task_id=proof.task_id,
        work_item_id=proof.work_item_id,
        disposition_sha256=proof.disposition_sha256,
        task_intent_sha256=proof.task_intent_sha256,
        source_revision=proof.source_revision,
        checkpoint_sequence=proof.checkpoint_sequence,
        investigation=proof,
        resolution=resolution,
        status="RESOLVED" if resolution is not None else status,
        summary="平台处理结果已保存, 尚未开始新的角色执行。",
        user_action="当前无需产品做业务决定。",
        recheck_when="工程事实发生变化后可重新核验。",
        manual_resolution_allowed=manual_resolution_allowed,
        collection_failed=collection_failed,
        handled_at=proof.inspected_at + timedelta(seconds=1),
        handling_sha256="0" * 64,
    )
    return value.model_copy(update={"handling_sha256": value.recompute_sha256()})


def _publish(
    sidecar: Path,
    proof: DeliveryWaitInvestigation,
    decision: DeliveryResolution | None = None,
    handling: DeliveryWaitHandling | None = None,
) -> None:
    records = KnowledgeRecordStore(sidecar / "state" / "delivery-waits")
    records.put("wait-investigations", proof.proof_sha256, proof)
    if decision is not None:
        records.put(
            "wait-resolutions",
            decision.work_item_id + ":" + decision.expected_disposition_sha256,
            decision,
        )
    if handling is not None:
        records.put("wait-handlings", handling.record_key, handling)


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


def test_policy_resolution_history_keeps_admission_source_without_claiming_a_human(
    tmp_path: Path,
) -> None:
    task = _policy_task()
    proof = _proof(task)
    decision = _policy_decision(task, proof)
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof, decision)
    before = _bytes(sidecar)

    history = engineering_history(sidecar, task, _scope(task), "delivery_history")

    assert len(history) == 2
    entry = next(item for item in history if item.details["kind"] == "delivery_wait_resolution")
    assert "平台按冻结工程策略" in entry.summary
    assert entry.details["authorization_source"] == "organization_engineering_policy"
    assert decision.engineering_admission is not None
    assert entry.details["admission_sha256"] == decision.engineering_admission.admission_sha256
    assert "operator_id" not in entry.details
    assert entry.source_sha256 == decision.resolution_sha256
    records = KnowledgeRecordStore(sidecar / "state" / "delivery-waits", read_only=True)
    assert (
        entry.source_uri
        == (
            records.root
            / records._name(
                "wait-resolutions", decision.work_item_id + ":" + proof.disposition_sha256
            )
        ).as_uri()
    )
    assert before == _bytes(sidecar)


def test_policy_resolution_history_refuses_valid_admission_for_another_frozen_policy(
    tmp_path: Path,
) -> None:
    task = _policy_task()
    proof = _proof(task)
    assert task.engineering_policy is not None
    other_policy = task.engineering_policy.model_copy(update={"max_total_admissions": 13})
    decision = _policy_decision(task, proof, policy=other_policy)
    decision.validate_integrity()
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof, decision)
    before = _bytes(sidecar)

    with pytest.raises(RecoveryRejected, match="冻结范围与授权"):
        engineering_history(sidecar, task, _scope(task), "delivery_history")

    assert before == _bytes(sidecar)


def test_policy_resolution_history_refuses_another_registered_project_scope(
    tmp_path: Path,
) -> None:
    task = _policy_task()
    proof = _proof(task)
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof, _policy_decision(task, proof))
    before = _bytes(sidecar)
    other_scope = _scope(task).model_copy(update={"project_id": "project_other"})

    with pytest.raises(ValueError, match="Project scope"):
        engineering_history(sidecar, task, other_scope, "delivery_history")

    assert before == _bytes(sidecar)


def test_handling_history_keeps_all_records_and_links_the_shared_immutable_key(
    tmp_path: Path,
) -> None:
    task = make_task()
    sidecar = tmp_path / "sidecar"
    handlings = []
    for number in range(12):
        proof = _proof(task, number).model_copy(update={"step_sha256": digest({"step": number})})
        proof = proof.model_copy(update={"proof_sha256": proof.recompute_sha256()})
        handling = _handling(
            proof,
            manual_resolution_allowed=number % 2 == 0,
            collection_failed=number % 2 == 1,
        )
        handlings.append(handling)
        _publish(sidecar, proof, handling=handling)
    before = _bytes(sidecar)

    history = engineering_history(sidecar, task, _scope(task), "delivery_history")

    assert len(history) == 24
    projected = {entry.source_sha256: entry for entry in history}
    records = KnowledgeRecordStore(sidecar / "state" / "delivery-waits", read_only=True)
    for handling in handlings:
        entry = projected[handling.handling_sha256]
        assert entry.summary == handling.summary
        assert entry.details["status"] == handling.status
        assert entry.details["user_action"] == handling.user_action
        assert entry.details["recheck_when"] == handling.recheck_when
        assert entry.details["proof_sha256"] == handling.investigation.proof_sha256
        assert (
            entry.source_uri
            == (records.root / records._name("wait-handlings", handling.record_key)).as_uri()
        )
    assert before == _bytes(sidecar)


def test_handling_history_refuses_a_valid_report_stored_under_another_key(tmp_path: Path) -> None:
    task = make_task()
    proof = _proof(task)
    handling = _handling(proof)
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof)
    KnowledgeRecordStore(sidecar / "state" / "delivery-waits").put(
        "wait-handlings", "wrong-key", handling
    )
    before = _bytes(sidecar)

    with pytest.raises(KnowledgeError):
        engineering_history(sidecar, task, _scope(task), "delivery_history")
    assert before == _bytes(sidecar)


def test_capture_refusal_history_retains_safe_diagnosis_and_the_known_stop(tmp_path: Path) -> None:
    task = make_task()
    sidecar = tmp_path / "sidecar"
    proof = _proof(task).model_copy(
        update={
            "process_stop_sha256": "c" * 64,
            "missing": (
                DeliveryProofMissing.OUTCOME_UNKNOWN,
                DeliveryProofMissing.CHECKPOINT_UNAVAILABLE,
            ),
            "permitted_resolutions": (),
        }
    )
    proof = proof.model_copy(update={"proof_sha256": proof.recompute_sha256()})
    handling = _handling(proof, collection_failed=True).model_copy(
        update={"collection_failure": DeliveryWaitCollectionFailure.WORKSPACE_CAPTURE_REJECTED}
    )
    handling = handling.model_copy(update={"handling_sha256": handling.recompute_sha256()})
    _publish(sidecar, proof, handling=handling)
    before = _bytes(sidecar)
    history = engineering_history(sidecar, task, _scope(task), "delivery_history")
    entry = next(value for value in history if value.source_sha256 == handling.handling_sha256)
    assert entry.details["collection_failure"] == "WORKSPACE_CAPTURE_REJECTED"
    assert entry.details["collection_failed"] is True
    assert before == _bytes(sidecar)


def test_legacy_handling_store_key_survives_absent_baseline_extension(tmp_path: Path) -> None:
    task = make_task()
    proof = _proof(task)
    handling = _handling(proof)
    # Reproduce the published pre-baseline-extension identity, including the
    # original nullable proof fields. Only the newly added absent field is absent.
    facts = proof.model_dump(
        mode="json", exclude={"proof_sha256", "inspected_at", "prerequisite_receipt_sha256"}
    )
    facts["disposition"]["facts"].pop("execution_baseline_sha256", None)
    legacy_key = digest(
        {
            "binding": {
                "work_item_id": proof.work_item_id,
                "expected_disposition_sha256": proof.disposition_sha256,
                "expected_task_intent_sha256": proof.task_intent_sha256,
                "expected_source_revision": proof.source_revision,
                "expected_checkpoint_sequence": proof.checkpoint_sequence,
            },
            "facts": facts,
            "manual_resolution_allowed": handling.manual_resolution_allowed,
            "collection_failed": handling.collection_failed,
        }
    )
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof)
    records = KnowledgeRecordStore(sidecar / "state" / "delivery-waits")
    records.put("wait-handling-proofs", legacy_key, proof)
    records.put("wait-handlings", legacy_key, handling)
    before = _bytes(sidecar)

    history = engineering_history(sidecar, task, _scope(task), "delivery_history")

    assert handling.record_key == legacy_key
    assert len(history) == 2
    entry = next(item for item in history if item.source_sha256 == handling.handling_sha256)
    assert entry.source_uri == (records.root / records._name("wait-handlings", legacy_key)).as_uri()
    assert before == _bytes(sidecar)


def test_handling_history_still_requires_its_independent_original_proof(tmp_path: Path) -> None:
    task = make_task()
    proof = _proof(task)
    handling = _handling(proof)
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof, handling=handling)
    records = KnowledgeRecordStore(sidecar / "state" / "delivery-waits")
    (records.root / records._name("wait-investigations", proof.proof_sha256)).unlink()
    before = _bytes(sidecar)

    with pytest.raises(KnowledgeError, match="RECORD_NOT_FOUND"):
        engineering_history(sidecar, task, _scope(task), "delivery_history")

    assert before == _bytes(sidecar)


def test_handling_redaction_keeps_sealed_report_and_hash_unchanged(tmp_path: Path) -> None:
    task = make_task()
    proof = _proof(task)
    handling = _handling(proof).model_copy(
        update={
            "summary": "处理 token=private-summary 已保存",
            "user_action": "无需提供 token=private-action",
            "recheck_when": "记录 token=private-recheck 更新后重新核验",
        }
    )
    handling = handling.model_copy(update={"handling_sha256": handling.recompute_sha256()})
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof, handling=handling)
    before = _bytes(sidecar)

    history = engineering_history(sidecar, task, _scope(task), "delivery_history")

    entry = next(item for item in history if item.details["kind"] == "delivery_wait_handling")
    assert "private-summary" not in entry.summary and "REDACTED" in entry.summary
    assert "private-action" not in str(entry.details)
    assert "private-recheck" not in str(entry.details)
    assert entry.source_sha256 == handling.handling_sha256
    assert before == _bytes(sidecar)


def test_resolved_handling_history_keeps_its_exact_policy_resolution(tmp_path: Path) -> None:
    task = _policy_task()
    proof = _proof(task)
    decision = _policy_decision(task, proof)
    handling = _handling(proof, decision)
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof, decision, handling)
    before = _bytes(sidecar)

    history = engineering_history(sidecar, task, _scope(task), "delivery_history")

    assert len(history) == 3
    entry = next(item for item in history if item.details["kind"] == "delivery_wait_handling")
    assert entry.details["status"] == "RESOLVED"
    assert entry.details["proof_sha256"] == decision.proof_sha256
    assert entry.source_sha256 == handling.handling_sha256
    assert before == _bytes(sidecar)


def test_resolved_handling_history_refuses_another_frozen_admission_policy(tmp_path: Path) -> None:
    task = _policy_task()
    proof = _proof(task)
    assert task.engineering_policy is not None
    other_policy = task.engineering_policy.model_copy(update={"max_total_admissions": 13})
    decision = _policy_decision(task, proof, policy=other_policy)
    handling = _handling(proof, decision)
    handling.validate_integrity()
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof, decision, handling)
    before = _bytes(sidecar)

    with pytest.raises(RecoveryRejected, match="冻结范围与授权"):
        engineering_history(sidecar, task, _scope(task), "delivery_history")

    assert before == _bytes(sidecar)


def test_resolved_handling_history_refuses_another_project_scope(tmp_path: Path) -> None:
    task = _policy_task()
    proof = _proof(task)
    decision = _policy_decision(task, proof)
    handling = _handling(proof, decision)
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof, decision, handling)
    before = _bytes(sidecar)

    with pytest.raises(ValueError, match="Project scope"):
        engineering_history(
            sidecar,
            task,
            _scope(task).model_copy(update={"project_id": "project_other"}),
            "delivery_history",
        )

    assert before == _bytes(sidecar)


def test_resolved_handling_history_refuses_a_retry_cause_changed_after_investigation(
    tmp_path: Path,
) -> None:
    task = make_task()
    proof = _proof(task)
    decision = _decision(proof)
    changed_proof = proof.model_copy(update={"retry_cause": "provider_transient"})
    changed_proof = changed_proof.model_copy(
        update={"proof_sha256": changed_proof.recompute_sha256()}
    )
    decision = decision.model_copy(update={"proof_sha256": changed_proof.proof_sha256})
    decision = decision.model_copy(update={"resolution_sha256": decision.recompute_sha256()})
    handling = _handling(changed_proof, decision)
    handling.validate_integrity()
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, changed_proof, handling=handling)
    before = _bytes(sidecar)

    with pytest.raises(ValueError, match="exact investigation"):
        engineering_history(sidecar, task, _scope(task), "delivery_history")

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
    monkeypatch: pytest.MonkeyPatch,
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
    original = FileExecutionBaselineStore.bindings_for_task
    calls = [0]

    def counted(
        current: FileExecutionBaselineStore, task_id: str
    ) -> tuple[ExecutionBaselineBinding, ...]:
        calls[0] += 1
        return original(current, task_id)

    monkeypatch.setattr(FileExecutionBaselineStore, "bindings_for_task", counted)
    before = _bytes(sidecar)
    history = engineering_history(sidecar, task, fixture.collector.facts.scope, "delivery_history")
    assert len(history) == 3
    assert history[0].details["operator_id"] == "operator:local-console"
    assert history[1].details["kind"] == "baseline_operation_start"
    assert history[2].details["execution_source_revision"] == binding.execution_source_revision
    assert history[2].details["branch_name"] == task.branch_name
    assert before == _bytes(sidecar)
    assert calls[0] == 1, "one history projection must not repeat all binding checks"


@pytest.mark.parametrize("changed_source", [False, True])
def test_paused_baseline_history_records_continue_decision_without_inventing_execution(
    tmp_path: Path, changed_source: bool
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
        reference="更新代码后保持暂停",
        submitted_at=NOW,
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = fixture.service.execute(plan.plan_sha256, authority=authority)
    continuation = BaselineContinueAuthorization.create(
        scope=binding.scope,
        task_id=task.id,
        task_intent_sha256=task_intent_sha256(task),
        task_revision=plan.facts.task_revision,
        work_item_id=plan.facts.work_item_id,
        execution_baseline_sha256=binding.binding_sha256,
        expected_source_revision="d" * 40 if changed_source else binding.execution_source_revision,
        checkpoint_sequence=plan.facts.task_revision,
        expected_disposition_sha256="e" * 64,
        inventory_sha256=binding.after_inventory_sha256,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="明确继续已保存的版本",
        submitted_at=NOW + timedelta(seconds=1),
    )
    store.records.put("baseline-continuations", binding.binding_sha256, continuation)
    before = _bytes(sidecar)
    if changed_source:
        with pytest.raises(ValueError, match="精确保留进度"):
            engineering_history(sidecar, task, binding.scope, "delivery_history")
    else:
        history = engineering_history(sidecar, task, binding.scope, "delivery_history")
        assert len(history) == 4
        paused = next(entry for entry in history if entry.details["kind"] == binding.kind)
        decision = next(entry for entry in history if entry.details["kind"] == continuation.kind)
        assert "保持暂停" in paused.summary
        assert "后续执行记录确认启动与验收" in decision.summary
        assert decision.details["source_revision"] == binding.execution_source_revision
        assert "已启动" not in decision.summary and "已通过" not in decision.summary
    assert before == _bytes(sidecar)
