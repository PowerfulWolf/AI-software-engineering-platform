"""Controlled knowledge admission pauses must retain positive recovery facts."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents.execution import bind_execution_guard
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.structured import (
    FallbackStructuredModelClient,
    StructuredModelError,
    StructuredModelResult,
    StructuredModelRoute,
)
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.delivery_disposition import DeliveryDisposition
from ai_software_engineer.domain.delivery_resolution import DeliveryProofMissing
from ai_software_engineer.domain.enums import TeamRole, WorkItemStatus
from ai_software_engineer.knowledge.agents import KnowledgeConsultationService
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import KnowledgeRunBinding, KnowledgeSnapshot, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.context import FileRunContextBuilder
from ai_software_engineer.orchestration.retry import RetryingOrchestrator
from ai_software_engineer.service_pause import ServicePauseControl, ServicePauseRequested
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.models import QueueClaim
from ai_software_engineer.work_queue.worker import (
    DeliveryWaiting,
    WorkerDeliveryFailureControl,
    WorkerExecutionGuard,
    WorkerLease,
)
from tests.manager.test_delivery_wait import WaitQueue, service
from tests.manager.test_delivery_wait import native as native
from tests.orchestration.test_native_continuation import Fixture
from tests.orchestration.test_runner import _definitions


class _Queue(WaitQueue):
    """The queue port retains the real WorkItem/claim and records lease release."""

    token = "fixture-paused-knowledge-owner"

    def __init__(self, fixture: Fixture) -> None:
        super().__init__(fixture)
        self.original = self.original.model_copy(
            update={
                "lease": self.original.lease.model_copy(
                    update={"expires_at": datetime.now(UTC) + timedelta(hours=1)}
                )
            }
        )
        self.released = False

    @contextmanager
    def fence(self, claim: QueueClaim, owner_token: str) -> Iterator[None]:
        assert claim == self.original and owner_token == self.token and not self.released
        yield

    def wait(
        self,
        work_item_id: str,
        *,
        lease_id: str,
        owner_token: str,
        status: WorkItemStatus,
        reason: str,
        now: datetime,
        disposition: DeliveryDisposition,
    ) -> None:
        assert work_item_id == self.original.work_item.id
        assert lease_id == self.original.lease.id and owner_token == self.token
        assert not self.released
        self.item = self.item.model_copy(
            update={
                "status": status,
                "wait_reason": reason,
                "wait_disposition": disposition,
                "updated_at": now,
            }
        )
        self.released = True


class _UncalledProvider:
    """No candidate code, model or transport can run after admission was paused."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        self.calls += 1
        raise AssertionError("the controlled pause must prevent provider admission")


def test_controlled_pause_during_knowledge_preparation_has_exact_recovery_evidence(
    native: Fixture, tmp_path: Path
) -> None:
    queue = _Queue(native)
    state = tmp_path / "sidecar" / "state"
    records = KnowledgeRecordStore(state.parent / "knowledge" / "runs")
    frozen = KnowledgeSnapshot.create(
        team_id=native.scope.team_id,
        project_id=native.scope.project_id,
        requirement_id=native.task.id,
        repository_ids=(queue.item.repository_id,),
        documents=(),
    )
    records.put("snapshots", frozen.snapshot_sha256, frozen)
    current = native.repository.get(native.task.id)
    context = FileRunContextBuilder(
        Path(current.repository),
        context_store=FileContextStore(state.parent / "contexts"),
        claim_context=lambda: ContextSource(
            source_id="execution.claim",
            uri="claim://" + queue.original.lease.id,
            content=json.dumps(
                {
                    "task_id": current.id,
                    "work_item_id": queue.item.id,
                    "lease_id": queue.original.lease.id,
                    "assignment_id": queue.original.assignment.id,
                    "dispatch_sequence": queue.item.dispatch_sequence,
                    "role": queue.item.role.value,
                    "attempt": queue.item.attempt,
                    "checkpoint_sequence": queue.item.checkpoint_sequence,
                }
            ),
            roles=(AgentRole.CODER,),
            required=True,
        ),
    ).build(
        current,
        _definitions()[AgentRole.CODER],
        attempt=queue.item.attempt,
        candidate_revision=queue.bound.boundary.source_revision,
    )
    bound = KnowledgeRunBinding(
        run_id="run_knowledge_" + digest((context.context_id, frozen.snapshot_sha256))[:32],
        task_id=native.task.id,
        role=TeamRole.CODER,
        team_id=frozen.team_id,
        project_id=frozen.project_id,
        requirement_id=frozen.requirement_id,
        repository_ids=frozen.repository_ids,
        source_revision=queue.bound.boundary.source_revision,
        context_manifest_id=context.context_id,
        snapshot_sha256=frozen.snapshot_sha256,
    )
    provider = _UncalledProvider()
    client = FallbackStructuredModelClient(
        (StructuredModelRoute(provider="fixture", model="fixture", client=provider),),
        role=bound.role,
    )
    consultation = KnowledgeConsultationService(
        client,
        records,
        invocation_journal=KnowledgeInvocationJournal(records, claimed=lambda: queue.original),
    )
    lease = WorkerLease(cast(MySqlRoleQueue, queue), queue.original, queue.token)
    guard = WorkerExecutionGuard()
    guard.lease = lease
    failure_control = WorkerDeliveryFailureControl(guard)
    runner = RetryingOrchestrator.__new__(RetryingOrchestrator)
    runner._repository = native.repository
    runner._delivery_failure_control = failure_control
    before = native.repository.get(native.task.id)
    events_before = native.repository.list_events(native.task.id)
    draft = native.worktree.path / "src" / "app.py"
    draft.write_text("VALUE = 'preserved Coder draft'\n", encoding="utf-8")
    draft_before = draft.read_bytes()
    pause = ServicePauseControl(grace_seconds=0)
    pause.request(request_id="pause_fixture", instance_id="instance_fixture")
    try:
        with (
            pytest.raises(DeliveryWaiting),
            pause.operation_scope("operation_fixture"),
            bind_execution_guard(guard),
        ):
            with pytest.raises(StructuredModelError) as failure:
                consultation.consult(bound, frozen, {}, timeout_seconds=2)
            assert failure.value.code is AgentErrorCode.SERVICE_PAUSED
            with pytest.raises(ServicePauseRequested) as paused:
                runner._knowledge_failure(before, failure.value)
            # This is the actual Worker's SERVICE_PAUSED branch, using its real
            # lease and failure control; the only fake port is the queue store.
            failure_control.wait(
                before,
                classification="SERVICE_PAUSED",
                reason="fixture controlled knowledge pause",
                source_revision=queue.bound.boundary.source_revision,
                artifact_ids=paused.value.evidence_ids,
            )
    finally:
        lease.stop()
        guard.lease = None

    lane = KnowledgeRecordStore(
        records.root / "invocations" / invocation_lane_sha256(bound), read_only=True
    )
    outcome = lane.get(
        "knowledge-invocation-outcomes", bound.run_id + ":intent", KnowledgeInvocationOutcome
    )
    outcome.validate_integrity()
    assert outcome.state == "FAILED" and outcome.failure is not None
    assert outcome.failure.code is AgentErrorCode.SERVICE_PAUSED
    assert outcome.intent.claim == queue.original and outcome.intent.binding == bound
    assert provider.calls == 0
    assert queue.released and queue.item.status is WorkItemStatus.WAITING_DEPENDENCY
    assert native.repository.get(native.task.id) == before
    assert native.repository.list_events(native.task.id) == events_before
    assert draft.read_bytes() == draft_before

    entry = service(native, queue, state)
    entry.artifacts = FileArtifactStore(state.parent / "artifacts")
    entry.knowledge_requirement_id = frozen.requirement_id
    entry.clock = lambda: datetime.now(UTC)
    proof = entry.inspect(queue.command())
    # A generic error plus an empty execution list is deliberately insufficient:
    # the real pause path must seal positive exact admission/knowledge evidence
    # before this investigation can offer a recoverable engineering decision.
    assert DeliveryProofMissing.INVOCATION_UNRECORDED not in proof.missing, (
        "controlled knowledge admission pause lost its trusted recovery receipt; "
        f"executions={len(outcome.executions)}, evidence={paused.value.evidence_ids}, "
        f"missing={proof.missing}"
    )
    assert paused.value.evidence_ids
    assert proof.permitted_resolutions
    assert not queue.consumed
