"""Exact stopped-failure decisions must remain human intervention in ADR replay."""

from datetime import UTC, datetime

import pytest

from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode, BaselinePurpose
from ai_software_engineer.evaluation import (
    AdrStatus,
    EvaluationEngine,
    EvaluationEventConflict,
    EvaluationTraceBuilder,
    FileEvaluationEventStore,
    HumanAction,
    HumanActionEvent,
)
from ai_software_engineer.knowledge.audit import KnowledgeHumanActionRecorder
from ai_software_engineer.manager.baseline_models import BaselineOperatorAuthorization
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.legacy_audit import EngineeringHumanActionRecorder
from tests.evaluation.factories import make_case_started
from tests.manager.test_completed_output_checkpoint import CompletedFixture
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.manager.test_stopped_failure_retry import service_for

completed = completed_fixture


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
def test_stopped_failure_decision_has_exact_idempotent_human_event_and_ineligible_adr(
    completed: CompletedFixture,
) -> None:
    f = completed
    root = f.root / "audit-baselines"
    service = service_for(f)
    service.store = FileExecutionBaselineStore(root / f.task.id)
    plan = service.propose(None, purpose=BaselinePurpose.STOPPED_FAILURE_RETRY)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="接受失败原因未知并消费一次普通工作额度",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_stopped_failure_retry=True,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    history = f.sealed_bytes()
    events = FileEvaluationEventStore(f.root / "audit-evaluations")
    started = make_case_started().model_copy(
        update={
            "task_id": f.task.id,
            "base_revision": f.task.base_ref,
            "occurred_at": f.task.created_at,
        }
    )
    events.append(started)
    recorder = EngineeringHumanActionRecorder(KnowledgeHumanActionRecorder(()), root)
    recorder.record(f.task, started.case_id, events)
    recorder.record(f.task, started.case_id, events)
    actions = tuple(
        event
        for event in events.list_for_case(started.case_id)
        if isinstance(event, HumanActionEvent)
    )
    assert len(actions) == 1
    event = actions[0]
    assert event.event_id == "evalevt_failure_" + binding.binding_sha256[:32]
    assert event.action is HumanAction.SUPPLY_EVIDENCE
    assert event.occurred_at == authority.submitted_at
    assert (
        event.evidence_uri
        == (
            service.store.root
            / service.store.records._name("baseline-authorities", plan.plan_sha256)
        )
        .absolute()
        .as_uri()
    )
    assert event.note is not None
    assert "原因" in event.note and "未知" in event.note and "普通工作额度" in event.note
    assert "已修复" not in event.note and "前提" not in event.note
    assert all(path.read_bytes() == body for path, body in history.items())
    trace = EvaluationTraceBuilder(
        repository=f.native.repository,
        artifact_store=f.native.artifacts,
        event_store=events,
    ).build(started.case_id)
    evaluated = EvaluationEngine().evaluate((trace,)).cases[0]
    assert evaluated.adr.status is AdrStatus.INELIGIBLE
    assert "HUMAN_INTERVENTION" in evaluated.adr.reasons
    conflicting = FileEvaluationEventStore(f.root / "audit-conflict")
    conflicting.append(started)
    original_event = event.model_copy(update={"note": "Existing conflicting audit fact."})
    conflicting.append(original_event)
    with pytest.raises(EvaluationEventConflict):
        recorder.record(f.task, started.case_id, conflicting)
    assert conflicting.get(event.event_id) == original_event


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
@pytest.mark.parametrize(
    "tamper",
    [
        "plan_proof",
        "binding_proof",
        "authority_confirmation",
        "authority_digest",
        "authority_missing",
    ],
)
def test_stopped_failure_audit_refuses_tampered_recovery_facts_before_event(
    completed: CompletedFixture,
    tamper: str,
) -> None:
    import json

    f = completed
    root = f.root / "audit-baselines"
    service = service_for(f)
    service.store = FileExecutionBaselineStore(root / f.task.id)
    plan = service.propose(None, purpose=BaselinePurpose.STOPPED_FAILURE_RETRY)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact audit fixture",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_stopped_failure_retry=True,
    )
    service.execute(plan.plan_sha256, authority=authority)
    category, identity = (
        ("baseline-plans", plan.plan_sha256)
        if tamper == "plan_proof"
        else ("baseline-bindings", f"{f.task.id}:1")
        if tamper == "binding_proof"
        else ("baseline-authorities", plan.plan_sha256)
    )
    target = service.store.root / service.store.records._name(category, identity)
    if tamper == "authority_missing":
        target.unlink()
        events = FileEvaluationEventStore(f.root / "audit-evaluations")
        recorder = EngineeringHumanActionRecorder(KnowledgeHumanActionRecorder(()), root)
        with pytest.raises((ValueError, RuntimeError)):
            recorder.record(f.task, "case_stopped_failure_audit", events)
        assert not events.list_for_case("case_stopped_failure_audit")
        return
    envelope = json.loads(target.read_text())
    payload = envelope["record"]
    # This is an explicitly test-owned corrupt ledger. No recovery input may
    # produce an audit fact while its proof/authorization cannot be revalidated.
    if tamper == "plan_proof":
        payload["facts"]["stopped_failure"]["proof_sha256"] = "a" * 64
    elif tamper == "binding_proof":
        payload["stopped_failure_sha256"] = "b" * 64
    elif tamper == "authority_confirmation":
        payload.pop("confirm_stopped_failure_retry")
    else:
        payload["authorization_sha256"] = "c" * 64
    from ai_software_engineer.knowledge.models import digest

    if tamper == "binding_proof":
        payload["binding_sha256"] = digest(
            {key: value for key, value in payload.items() if key != "binding_sha256"}
        )
    elif tamper == "authority_confirmation":
        payload["authorization_sha256"] = digest(
            {key: value for key, value in payload.items() if key != "authorization_sha256"}
        )
    envelope["sha256"] = digest(payload)
    target.write_text(json.dumps(envelope))
    events = FileEvaluationEventStore(f.root / "audit-evaluations")
    recorder = EngineeringHumanActionRecorder(KnowledgeHumanActionRecorder(()), root)
    with pytest.raises((ValueError, RuntimeError)):
        recorder.record(f.task, "case_stopped_failure_audit", events)
    assert not events.list_for_case("case_stopped_failure_audit")
