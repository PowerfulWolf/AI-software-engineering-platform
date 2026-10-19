"""A positive knowledge refusal resumes only its exact uninvoked current claim."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest

from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.structured_observation import (
    StructuredCallIdentity,
    StructuredExecutionAdmission,
    StructuredHttpRoundTripReceipt,
    StructuredNativeNotStartedReceipt,
)
from ai_software_engineer.agents.structured_pause import StructuredPreAdmissionPauseReceipt
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolutionKind,
    ResolveDeliveryWait,
)
from ai_software_engineer.domain.enums import TeamRole, WorkItemStatus
from ai_software_engineer.knowledge.invocation import (
    KnowledgeExecutionRecord,
    KnowledgeInvocationFailure,
    KnowledgeInvocationIntent,
    KnowledgeInvocationOutcome,
    KnowledgeInvocationResult,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import KnowledgeRunBinding, KnowledgeSnapshot, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_wait import DeliveryWaitRejected, DeliveryWaitService
from ai_software_engineer.orchestration.context import FileRunContextBuilder
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from tests.manager.test_delivery_wait import WaitQueue, service
from tests.manager.test_delivery_wait import native as native
from tests.orchestration.test_native_continuation import Fixture
from tests.orchestration.test_runner import _definitions


@dataclass(frozen=True)
class PausedFacts:
    entry: DeliveryWaitService
    queue: WaitQueue
    records: KnowledgeRecordStore
    lane: KnowledgeRecordStore
    outcome: KnowledgeInvocationOutcome


def paused_facts(
    native: Fixture,
    state: Path,
    *,
    receipt: bool = True,
    native_closed: bool = False,
    phase: Literal["intent", "assessment"] = "intent",
) -> PausedFacts:
    queue = WaitQueue(native)
    task = native.repository.get(native.task.id)
    context = FileRunContextBuilder(
        Path(task.repository),
        context_store=FileContextStore(state.parent / "contexts"),
        claim_context=lambda: ContextSource(
            source_id="execution.claim",
            uri="claim://" + queue.original.lease.id,
            content=json.dumps(
                {
                    "task_id": task.id,
                    "work_item_id": queue.item.id,
                    "lease_id": queue.original.lease.id,
                    "assignment_id": queue.original.assignment.id,
                    "dispatch_sequence": queue.item.dispatch_sequence,
                    "role": queue.item.role.value,
                    "attempt": queue.item.attempt,
                    "checkpoint_sequence": queue.item.checkpoint_sequence,
                }
            ),
            roles=(queue.item.role,),
            required=True,
        ),
    ).build(
        task,
        _definitions()[queue.item.role],
        attempt=task.attempts,
        candidate_revision=queue.bound.boundary.source_revision,
    )
    entry = service(native, queue, state)
    records = KnowledgeRecordStore(state.parent / "knowledge/runs")
    snapshot = KnowledgeSnapshot.create(
        team_id=entry.scope.team_id,
        project_id=entry.scope.project_id,
        requirement_id=task.id,
        repository_ids=(queue.item.repository_id,),
    )
    records.put("snapshots", snapshot.snapshot_sha256, snapshot)
    binding = KnowledgeRunBinding(
        run_id="run_knowledge_" + digest((context.context_id, snapshot.snapshot_sha256))[:32],
        role=TeamRole.CODER,
        task_id=task.id,
        team_id=snapshot.team_id,
        project_id=snapshot.project_id,
        repository_ids=snapshot.repository_ids,
        requirement_id=snapshot.requirement_id,
        source_revision=context.source_revision,
        context_manifest_id=context.context_id,
        snapshot_sha256=snapshot.snapshot_sha256,
    )
    now = datetime.now(UTC)
    intent = KnowledgeInvocationIntent.create(
        binding=binding,
        phase=phase,
        request_sha256="a" * 64,
        timeout_seconds=2,
        claim=queue.original,
        created_at=now,
    )
    refusal = StructuredPreAdmissionPauseReceipt.create(
        origin="fallback_before_route",
        request_sha256=intent.request_sha256,
        timeout_seconds=intent.timeout_seconds,
        phase="knowledge_" + phase,
        role=binding.role,
        invocation_id="b" * 32,
        operation_id="operation_pause_consumer",
        pause_request_id="pause_consumer",
        pause_instance_id="instance_consumer",
        pause_requested_at=now,
        refused_at=now + timedelta(microseconds=1),
    )
    executions: tuple[KnowledgeExecutionRecord, ...] = ()
    if native_closed:
        admission = StructuredExecutionAdmission.create(
            observation_id="c" * 32,
            call=StructuredCallIdentity(
                invocation_id="d" * 32,
                route_index=1,
                provider="codex",
                model="fixture",
                reasoning_effort="medium",
                role=binding.role,
                phase="knowledge_intent" if phase == "intent" else "knowledge_assessment",
                request_sha256=intent.request_sha256,
            ),
            execution_kind="native",
            transport_request_sha256="e" * 64,
            timeout_seconds=intent.timeout_seconds,
            admitted_at=now,
        )
        not_started = StructuredNativeNotStartedReceipt.create(
            admission=admission,
            failure_kind="service_pause_admission_closed",
            failed_at=now + timedelta(microseconds=1),
        )
        executions = tuple(
            KnowledgeExecutionRecord.create(
                intent_sha256=intent.intent_sha256, observation=observation
            )
            for observation in (admission, not_started)
        )
    outcome = KnowledgeInvocationOutcome.create(
        intent=intent,
        state="FAILED",
        failure=KnowledgeInvocationFailure(
            code=AgentErrorCode.SERVICE_PAUSED,
            safe_message="controlled admission pause",
            transient=False,
        ),
        pre_admission_pause=refusal if receipt and not native_closed else None,
        executions=executions,
        completed_at=now + timedelta(microseconds=2),
    )
    lane = KnowledgeRecordStore(records.root / "invocations" / invocation_lane_sha256(binding))
    lane.put("knowledge-invocation-intents", binding.run_id + ":" + phase, intent)
    if receipt and not native_closed:
        lane.put("structured-admission-pauses", refusal.receipt_sha256, refusal)
    for execution in executions:
        lane.put("knowledge-execution-records", execution.record_sha256, execution)
    lane.put("knowledge-invocation-outcomes", binding.run_id + ":" + phase, outcome)
    records.put("knowledge-pause-intents", outcome.outcome_sha256, intent)
    assert queue.item.wait_disposition is not None
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts.model_validate(
            {
                **queue.item.wait_disposition.facts.to_wire(),
                "classification": "SERVICE_PAUSED",
                "evidence_ids": ["knowledge-pause://" + outcome.outcome_sha256],
            }
        )
    )
    queue.item = queue.item.model_copy(
        update={
            "status": WorkItemStatus.WAITING_DEPENDENCY,
            "wait_disposition": disposition,
            "wait_reason": disposition.reason,
        }
    )
    entry.artifacts = FileArtifactStore(state.parent / "artifacts")
    entry.knowledge_requirement_id = binding.requirement_id
    return PausedFacts(entry, queue, records, lane, outcome)


@pytest.mark.parametrize("native_closed", [False, True])
def test_positive_pause_has_exact_public_proof_and_same_attempt_decision(
    native: Fixture, tmp_path: Path, native_closed: bool
) -> None:
    facts = paused_facts(native, tmp_path / "sidecar/state", native_closed=native_closed)
    before = native.repository.get(native.task.id)
    events = native.repository.list_events(native.task.id)
    proof = facts.entry.inspect(facts.queue.command())
    assert proof.permitted_resolutions == (DeliveryResolutionKind.RESUME_UNINVOKED,)
    assert not proof.missing
    assert proof.knowledge_pause is not None
    assert proof.knowledge_pause.original_lease_id == facts.queue.original.lease.id
    assert proof.knowledge_pause.outcome_sha256 == facts.outcome.outcome_sha256
    assert proof.knowledge_pause.proof_mode == (
        "native_admission_closed" if native_closed else "pre_admission_refusal"
    )
    assert proof.original_run_id == facts.outcome.intent.binding.run_id
    assert native.repository.get(native.task.id) == before
    assert native.repository.list_events(native.task.id) == events
    assert not facts.queue.consumed
    decision = facts.entry.resolve(
        ResolveDeliveryWait.model_validate(
            {
                **facts.queue.command().to_wire(),
                "proof_sha256": proof.proof_sha256,
                "resolution_kind": DeliveryResolutionKind.RESUME_UNINVOKED,
                "submitted_at": datetime.now(UTC),
            }
        )
    )
    assert decision.knowledge_pause == proof.knowledge_pause
    assert decision.retry_cause is None and decision.retry_failure is None
    assert facts.queue.consumed == [decision]
    assert native.repository.get(native.task.id) == before


@pytest.mark.parametrize("missing", ["receipt", "index", "context", "snapshot", "empty"])
def test_pause_requires_independent_positive_records(
    native: Fixture, tmp_path: Path, missing: str
) -> None:
    facts = paused_facts(native, tmp_path / "sidecar/state", receipt=missing != "empty")
    binding = facts.outcome.intent.binding
    if missing == "receipt":
        assert facts.outcome.pre_admission_pause is not None
        (
            facts.lane.root
            / KnowledgeRecordStore._name(
                "structured-admission-pauses", facts.outcome.pre_admission_pause.receipt_sha256
            )
        ).unlink()
    elif missing == "index":
        (
            facts.records.root
            / KnowledgeRecordStore._name("knowledge-pause-intents", facts.outcome.outcome_sha256)
        ).unlink()
    elif missing == "context":
        (
            facts.records.root.parent.parent / "contexts" / (binding.context_manifest_id + ".json")
        ).unlink()
    elif missing == "snapshot":
        (
            facts.records.root / KnowledgeRecordStore._name("snapshots", binding.snapshot_sha256)
        ).unlink()
    proof = facts.entry.inspect(facts.queue.command())
    assert not proof.permitted_resolutions
    assert proof.knowledge_pause is None
    assert not facts.queue.consumed


def test_another_run_name_cannot_hide_main_invocation_for_same_claim(
    native: Fixture, tmp_path: Path
) -> None:
    facts = paused_facts(native, tmp_path / "sidecar/state")
    start = DeliveryInvocationStart(
        work_item_id="work_alias_main",
        checkpoint_sequence=facts.queue.item.checkpoint_sequence,
        lease_id=facts.queue.original.lease.id,
        request=native.request,
        started_at=datetime.now(UTC),
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    KnowledgeRecordStore(facts.entry.sidecar_state / "invocations").put(
        "invocation-starts", start.work_item_id, start
    )
    proof = facts.entry.inspect(facts.queue.command())
    assert not proof.permitted_resolutions and proof.knowledge_pause is None


def test_pending_other_phase_of_same_claim_is_not_hidden_by_pause(
    native: Fixture, tmp_path: Path
) -> None:
    facts = paused_facts(native, tmp_path / "sidecar/state")
    intent = facts.outcome.intent
    pending = KnowledgeInvocationIntent.create(
        **intent.model_dump(exclude={"intent_sha256", "phase"}), phase="assessment"
    )
    facts.lane.put("knowledge-invocation-intents", pending.binding.run_id + ":assessment", pending)
    proof = facts.entry.inspect(facts.queue.command())
    assert not proof.permitted_resolutions and proof.knowledge_pause is None


def test_sealed_unconsumed_pause_decision_reopens_independent_receipt(
    native: Fixture, tmp_path: Path
) -> None:
    facts = paused_facts(native, tmp_path / "sidecar/state")
    proof = facts.entry.inspect(facts.queue.command())
    command = ResolveDeliveryWait.model_validate(
        {
            **facts.queue.command().to_wire(),
            "proof_sha256": proof.proof_sha256,
            "resolution_kind": DeliveryResolutionKind.RESUME_UNINVOKED,
            "submitted_at": datetime.now(UTC),
        }
    )
    consumed = facts.entry.consume

    def crash_before_sql(_: object) -> None:
        raise RuntimeError("fixture crash before queue consumption")

    facts.entry.consume = crash_before_sql
    with pytest.raises(RuntimeError, match="fixture crash"):
        facts.entry.resolve(command)
    assert not facts.queue.consumed
    facts.entry.consume = consumed
    assert facts.outcome.pre_admission_pause is not None
    (
        facts.lane.root
        / KnowledgeRecordStore._name(
            "structured-admission-pauses", facts.outcome.pre_admission_pause.receipt_sha256
        )
    ).unlink()
    with pytest.raises(DeliveryWaitRejected, match="尚未消费"):
        facts.entry.resolve(command)
    assert not facts.queue.consumed


@pytest.mark.parametrize("returned", [False, True])
def test_prior_phase_requires_complete_independent_returned_execution(
    native: Fixture, tmp_path: Path, returned: bool
) -> None:
    facts = paused_facts(native, tmp_path / "sidecar/state", phase="assessment")
    later = facts.outcome.intent
    earlier = KnowledgeInvocationIntent.create(
        **later.model_dump(exclude={"intent_sha256", "phase", "created_at"}),
        phase="intent",
        created_at=later.created_at - timedelta(seconds=3),
    )
    admission = StructuredExecutionAdmission.create(
        observation_id="8" * 32,
        call=StructuredCallIdentity(
            invocation_id="7" * 32,
            route_index=1,
            provider="fixture",
            model="fixture",
            reasoning_effort="medium",
            role=earlier.binding.role,
            phase="knowledge_intent",
            request_sha256=earlier.request_sha256,
        ),
        execution_kind="http",
        transport_request_sha256="6" * 64,
        timeout_seconds=earlier.timeout_seconds,
        admitted_at=earlier.created_at,
    )
    receipt = StructuredHttpRoundTripReceipt.create(
        admission=admission,
        outcome="returned",
        http_status=200 if returned else 503,
        response_body_sha256="5" * 64,
        completed_at=earlier.created_at + timedelta(seconds=1),
    )
    executions = tuple(
        KnowledgeExecutionRecord.create(intent_sha256=earlier.intent_sha256, observation=value)
        for value in (admission, receipt)
    )
    outcome = KnowledgeInvocationOutcome.create(
        intent=earlier,
        state="RETURNED" if returned else "FAILED",
        result=KnowledgeInvocationResult(payload={"queries": []}, duration_ms=0)
        if returned
        else None,
        failure=None
        if returned
        else KnowledgeInvocationFailure(
            code=AgentErrorCode.PROVIDER_UNAVAILABLE,
            safe_message="fixture prior failure",
            transient=True,
        ),
        executions=executions,
        completed_at=earlier.created_at + timedelta(seconds=2),
    )
    facts.lane.put("knowledge-invocation-intents", earlier.binding.run_id + ":intent", earlier)
    facts.lane.put("knowledge-invocation-outcomes", earlier.binding.run_id + ":intent", outcome)
    for execution in executions:
        facts.lane.put("knowledge-execution-records", execution.record_sha256, execution)
    proof = facts.entry.inspect(facts.queue.command())
    assert bool(proof.permitted_resolutions) is returned
    assert (proof.knowledge_pause is not None) is returned
