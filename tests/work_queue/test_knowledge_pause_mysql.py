"""Isolated SQL fences for a prospective knowledge admission refusal decision."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

import pytest

from ai_software_engineer.domain.delivery_disposition import (
    DeliveryDisposition,
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import DeliveryResolutionKind
from ai_software_engineer.domain.enums import AgentRole, WorkItemStatus
from ai_software_engineer.domain.knowledge_preparation_pause import (
    KnowledgePreparationPauseEvidence,
)
from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.models import QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueError
from tests.work_queue.test_wait_resolution_mysql import WaitingFixture, reseal
from tests.work_queue.test_wait_resolution_mysql import waiting as waiting
from tests.work_queue.test_worker_mysql import claim_step

pytestmark = pytest.mark.mysql


@pytest.fixture(autouse=True)
def admission_pause_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the real queue writer to publish SERVICE_PAUSED before releasing its claim."""
    real_wait = MySqlRoleQueue.wait

    def pause_wait(
        self: MySqlRoleQueue,
        work_item_id: str,
        *,
        lease_id: str,
        owner_token: str,
        status: WorkItemStatus,
        reason: str,
        now: datetime,
        disposition: DeliveryDisposition | None = None,
    ) -> QueuedWorkItem:
        assert disposition is not None
        paused = decide_delivery_disposition(
            DeliveryFailureFacts.model_validate(
                {
                    **disposition.facts.to_wire(),
                    "classification": "SERVICE_PAUSED",
                    "evidence_ids": ["knowledge-pause://" + "c" * 64],
                }
            )
        )
        return real_wait(
            self,
            work_item_id,
            lease_id=lease_id,
            owner_token=owner_token,
            status=WorkItemStatus.WAITING_DEPENDENCY,
            reason=paused.reason,
            now=now,
            disposition=paused,
        )

    monkeypatch.setattr(MySqlRoleQueue, "wait", pause_wait)


def paused_decision(waiting: WaitingFixture) -> KnowledgePreparationPauseEvidence:
    task = waiting.repository.get(waiting.step.boundary.task_id)
    policy = task.engineering_policy
    assert policy is not None
    disposition = waiting.queue.get(waiting.step.work_item.id).wait_disposition
    assert disposition is not None
    waiting.disposition = disposition
    original = waiting.queue.original_claim(waiting.claim.lease.id)
    return KnowledgePreparationPauseEvidence(
        scope=policy.scope,
        requirement_id="delivery_knowledge_pause",
        delivery_requirement_id="delivery_knowledge_pause",
        task_id=task.id,
        role=cast(
            Literal[AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER], waiting.step.work_item.role
        ),
        work_item_id=waiting.step.work_item.id,
        original_lease_id=original.lease.id,
        original_claim_sha256=claim_identity_sha256(original),
        original_attempt=original.work_item.attempt,
        original_dispatch_sequence=original.work_item.dispatch_sequence,
        checkpoint_sequence=original.work_item.checkpoint_sequence,
        previous_run_id="run_knowledge_pause",
        previous_context_manifest_id="ctx_" + "a" * 64,
        source_revision=waiting.step.boundary.source_revision,
        snapshot_sha256="b" * 64,
        phase="intent",
        intent_sha256="d" * 64,
        outcome_sha256="c" * 64,
        request_sha256="e" * 64,
        proof_mode="pre_admission_refusal",
        pre_admission_pause_sha256="f" * 64,
        execution_record_sha256s=(),
    )


def test_exact_pause_resumes_one_dispatch_without_task_budget_or_event_change(
    waiting: WaitingFixture,
) -> None:
    pause = paused_decision(waiting)
    decision = reseal(
        waiting.resolution(DeliveryResolutionKind.RESUME_UNINVOKED),
        knowledge_pause=pause.to_wire(),
    )
    task = waiting.repository.get(decision.task_id)
    events = waiting.repository.list_events(task.id)
    next_item = waiting.queue.resolve_wait(decision)
    assert next_item.id == waiting.claim.work_item.id
    assert next_item.dispatch_sequence == waiting.claim.work_item.dispatch_sequence + 1
    assert next_item.attempt == waiting.claim.work_item.attempt
    assert next_item.status is WorkItemStatus.READY
    assert waiting.repository.get(task.id) == task
    assert waiting.repository.list_events(task.id) == events
    assert waiting.queue.resolve_wait(decision) == next_item
    assert waiting.resolution_events() == 1
    fresh = claim_step(waiting.queue, waiting.queue.step(next_item.id))
    assert fresh.lease.id != waiting.claim.lease.id
    assert fresh.work_item.dispatch_sequence == next_item.dispatch_sequence
    assert fresh.work_item.attempt == waiting.claim.work_item.attempt
    assert waiting.repository.get(task.id) == task


@pytest.mark.parametrize(
    "changed",
    ["lease", "claim", "dispatch", "attempt", "scope", "missing"],
)
def test_pause_rejects_changed_original_ownership_without_mutation(
    waiting: WaitingFixture,
    changed: Literal["lease", "claim", "dispatch", "attempt", "scope", "missing"],
) -> None:
    pause = paused_decision(waiting)
    wire = pause.to_wire()
    if changed == "lease":
        wire["original_lease_id"] = "lease_unknown_pause"
    elif changed == "claim":
        wire["original_claim_sha256"] = "9" * 64
    elif changed == "dispatch":
        wire["original_dispatch_sequence"] = pause.original_dispatch_sequence + 1
    elif changed == "attempt":
        wire["original_attempt"] = pause.original_attempt + 1
    elif changed == "scope":
        wire["scope"] = {**pause.scope.to_wire(), "project_id": "project_foreign"}
    decision = reseal(
        waiting.resolution(DeliveryResolutionKind.RESUME_UNINVOKED),
        knowledge_pause=None if changed == "missing" else wire,
    )
    before = waiting.queue.get(decision.work_item_id)
    task = waiting.repository.get(decision.task_id)
    with pytest.raises((QueueError, ValueError)):
        waiting.queue.resolve_wait(decision)
    assert waiting.queue.get(before.id) == before
    assert waiting.repository.get(task.id) == task
    assert waiting.resolution_events() == 0
