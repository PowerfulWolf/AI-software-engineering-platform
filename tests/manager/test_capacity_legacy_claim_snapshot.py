"""Legacy capacity keeps raw exact claim authority after heartbeat renewal."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.agents.structured_observation import (
    StructuredExecutionAdmission,
    StructuredHttpRoundTripReceipt,
)
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.knowledge.invocation import (
    KnowledgeExecutionRecord,
    KnowledgeInvocationIntent,
    KnowledgeInvocationOutcome,
)
from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
from ai_software_engineer.manager.knowledge_invocation_proof import read_capacity_claim_snapshot
from ai_software_engineer.work_queue.claim_snapshot import OriginalClaimRecord
from ai_software_engineer.work_queue.models import QueueClaim
from tests.manager.test_baseline_knowledge_claim_proof import Facts, knowledge_failure
from tests.orchestration.test_native_continuation import NOW


def _marker(facts: Facts) -> ContextCapacityReceipt:
    context = FileContextStore(facts.collector.state.parent / "contexts", read_only=True).get(
        facts.intent.binding.context_manifest_id
    )
    request = AgentRequest(
        task_id=facts.task.id,
        run_id="run_capacity_legacy",
        role=facts.item.role,
        attempt=facts.item.attempt,
        source_revision=facts.intent.binding.source_revision,
        context_manifest_id=context.context_id,
        input_artifact_ids=(),
        permissions=facts.collector.permissions,
        output_schema="schemas/coder-output.schema.json",
        timeout_seconds=30,
    )
    value = ContextCapacityReceipt(
        origin="final_input",
        task_id=facts.task.id,
        task_sha256=digest(facts.task.to_wire()),
        task_intent_sha256=task_intent_sha256(facts.task),
        task_revision=facts.item.checkpoint_sequence,
        work_item_id=facts.item.id,
        lease_id=facts.claim.lease.id,
        assignment_id=facts.claim.assignment.id,
        claim_sha256=digest(facts.claim.to_wire()),
        dispatch_sequence=facts.item.dispatch_sequence,
        checkpoint_sequence=facts.item.checkpoint_sequence,
        role=facts.item.role,
        attempt=facts.item.attempt,
        source_revision=request.source_revision,
        context_manifest_id=context.context_id,
        context_sha256=digest(context.to_wire()),
        max_input_tokens=context.budget.max_input_tokens,
        context_input_tokens=context.budget.used_input_tokens,
        final_input_tokens=context.budget.max_input_tokens + 1,
        request=request,
        observed_at=NOW + timedelta(seconds=5),
        receipt_sha256="0" * 64,
    )
    return value.model_copy(
        update={"receipt_sha256": digest(value.model_dump(mode="json", exclude={"receipt_sha256"}))}
    )


def _historical(facts: Facts, monkeypatch: pytest.MonkeyPatch) -> QueueClaim:
    value = facts.claim.model_copy(
        update={
            "lease": facts.claim.lease.model_copy(
                update={"expires_at": facts.claim.lease.expires_at + timedelta(seconds=15)}
            )
        }
    )
    monkeypatch.setattr(facts.collector.queue, "original_claim", lambda _: value)
    return value


def _read(facts: Facts, marker: ContextCapacityReceipt, historical: QueueClaim) -> QueueClaim:
    collector = facts.collector
    marker = marker.model_copy(
        update={
            "receipt_sha256": digest(marker.model_dump(mode="json", exclude={"receipt_sha256"}))
        }
    )
    return read_capacity_claim_snapshot(
        state=collector.state,
        task=facts.task,
        marker=marker,
        historical=historical,
        scope=collector.scope,
        requirement_id=collector.requirement_id,
        queue=collector.queue,
        require_step=collector._require_step,
    )


def test_returned_only_knowledge_seals_original_raw_capacity_without_failure_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = knowledge_failure(tmp_path, returned=True)
    historical = _historical(facts, monkeypatch)
    marker = _marker(facts)
    records = KnowledgeRecordStore(facts.collector.state / "delivery-preflight")
    records.put("context-capacity-receipts", marker.receipt_sha256, marker)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    assert marker.claim_sha256 != digest(historical.to_wire())
    assert _read(facts, marker, historical) == facts.claim
    assert facts.collector._knowledge_markers(facts.task, facts.item, (historical,)) == ()
    reader = facts.collector._capacity_input_reader()
    step = facts.collector.queue.step_for_claim(historical)
    reader.require_identity(facts.task, marker, historical, step)
    reader.require_context(facts.task, marker, historical)
    reader.require_not_started(marker)
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}


def test_new_immutable_claim_mismatch_cannot_acquire_legacy_snapshot_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = knowledge_failure(tmp_path, returned=True)
    historical = _historical(facts, monkeypatch)
    monkeypatch.setattr(
        facts.collector.queue,
        "original_claim_record",
        lambda _: OriginalClaimRecord(historical, has_immutable_snapshot=True),
    )
    marker = _marker(facts)
    records = KnowledgeRecordStore(facts.collector.state / "delivery-preflight")
    records.put("context-capacity-receipts", marker.receipt_sha256, marker)
    with pytest.raises(ValueError, match="禁止用知识快照覆盖"):
        facts.collector._capacity_input_reader().require_identity(
            facts.task, marker, historical, facts.collector.queue.step_for_claim(historical)
        )


@pytest.mark.parametrize("changed_snapshot", [False, True])
def test_completed_phases_require_one_identical_original_claim_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_snapshot: bool
) -> None:
    facts = knowledge_failure(tmp_path, returned=True)
    historical = _historical(facts, monkeypatch)
    sealed = historical if changed_snapshot else facts.claim
    intent = KnowledgeInvocationIntent.create(
        binding=facts.intent.binding,
        phase="intent",
        request_sha256="d" * 64,
        timeout_seconds=2,
        claim=sealed,
        created_at=NOW + timedelta(seconds=1),
    )
    old_admission = facts.outcome.executions[0].observation
    assert isinstance(old_admission, StructuredExecutionAdmission)
    admission = StructuredExecutionAdmission.create(
        observation_id="c" * 32,
        call=old_admission.call.model_copy(
            update={"phase": "knowledge_intent", "request_sha256": intent.request_sha256}
        ),
        execution_kind="http",
        transport_request_sha256="f" * 64,
        timeout_seconds=2,
        admitted_at=NOW + timedelta(seconds=2),
    )
    stop = StructuredHttpRoundTripReceipt.create(
        admission=admission,
        outcome="returned",
        http_status=200,
        response_body_sha256="e" * 64,
        completed_at=NOW + timedelta(seconds=3),
    )
    executions = tuple(
        KnowledgeExecutionRecord.create(intent_sha256=intent.intent_sha256, observation=value)
        for value in (admission, stop)
    )
    outcome = KnowledgeInvocationOutcome.create(
        intent=intent,
        state="RETURNED",
        result=facts.outcome.result,
        executions=executions,
        completed_at=NOW + timedelta(seconds=4),
    )
    key = intent.binding.run_id + ":intent"
    facts.records.put("knowledge-invocation-intents", key, intent)
    facts.records.put("knowledge-invocation-outcomes", key, outcome)
    for execution in executions:
        facts.records.put("knowledge-execution-records", execution.record_sha256, execution)
    if changed_snapshot:
        with pytest.raises(ValueError, match="不同版本"):
            _read(facts, _marker(facts), historical)
    else:
        assert _read(facts, _marker(facts), historical) == facts.claim


@pytest.mark.parametrize(
    "problem",
    [
        "raw_sha",
        "worker",
        "claim_time",
        "no_outcome",
        "no_observation",
        "foreign_requirement",
        "after_capacity",
    ],
)
def test_legacy_capacity_refuses_missing_or_mismatched_exact_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    facts = knowledge_failure(tmp_path, returned=True)
    historical = _historical(facts, monkeypatch)
    marker = _marker(facts)
    if problem == "raw_sha":
        marker = marker.model_copy(update={"claim_sha256": digest(historical.to_wire())})
    elif problem == "worker":
        historical = historical.model_copy(update={"worker_id": "worker_foreign_identity"})
        monkeypatch.setattr(facts.collector.queue, "original_claim", lambda _: historical)
    elif problem == "claim_time":
        historical = historical.model_copy(
            update={"claimed_at": historical.claimed_at + timedelta(microseconds=1)}
        )
        monkeypatch.setattr(facts.collector.queue, "original_claim", lambda _: historical)
    elif problem == "foreign_requirement":
        facts.collector.requirement_id = "delivery_foreign"
    elif problem == "after_capacity":
        marker = marker.model_copy(
            update={"observed_at": facts.outcome.completed_at - timedelta(microseconds=1)}
        )
    elif problem == "no_outcome":
        (
            facts.records.root
            / facts.records._name(
                "knowledge-invocation-outcomes", facts.intent.binding.run_id + ":assessment"
            )
        ).unlink()
    elif problem == "no_observation":
        (
            facts.records.root
            / facts.records._name(
                "knowledge-execution-records", facts.outcome.executions[0].record_sha256
            )
        ).unlink()
    with pytest.raises((ValueError, KnowledgeError)):
        _read(facts, marker, historical)
