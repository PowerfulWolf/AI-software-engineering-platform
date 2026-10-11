"""Completed rejected output preserves publication and consumes one new work attempt."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.artifacts.store import seal_artifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    RejectedCoderOutputEvidence,
)
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.knowledge.preparation_retry import claim_identity_sha256
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.work_queue.ports import QueueConflict
from tests.domain.factories import make_coder_progress_artifact
from tests.work_queue.test_wait_resolution_mysql import (
    SOURCE,
    WaitingFixture,
    reseal,
)
from tests.work_queue.test_wait_resolution_mysql import (
    waiting as waiting,
)
from tests.work_queue.test_worker_mysql import TOKEN, dispatcher

pytestmark = [
    pytest.mark.mysql,
    pytest.mark.parametrize("waiting", [(AgentRole.CODER, "PLATFORM_BUG")], indirect=True),
]


def rejected_resolution(waiting: WaitingFixture) -> DeliveryResolution:
    task = waiting.repository.get(waiting.step.boundary.task_id)
    policy = task.engineering_policy
    assert policy is not None
    publication = next(
        item
        for item in waiting.queue.accepted(task.id)
        if item.work_item_id == waiting.step.work_item.id
    )
    evidence = RejectedCoderOutputEvidence(
        scope=policy.scope,
        requirement_id="requirement_rejected_fixture",
        task_id=task.id,
        work_item_id=waiting.step.work_item.id,
        original_lease_id=waiting.claim.lease.id,
        original_claim_sha256=claim_identity_sha256(waiting.claim),
        original_attempt=waiting.claim.work_item.attempt,
        original_dispatch_sequence=waiting.claim.work_item.dispatch_sequence,
        checkpoint_sequence=waiting.step.boundary.checkpoint_sequence,
        previous_run_id=publication.run_id,
        previous_context_manifest_id=publication.context_manifest_id,
        source_revision=waiting.step.boundary.source_revision,
        invocation_start_sha256="1" * 64,
        invocation_outcome_sha256="2" * 64,
        rejected_artifact_id=publication.receipt.artifact_id,
        rejected_artifact_sha256=publication.receipt.sha256,
        expected_sequence=waiting.claim.work_item.attempt,
        reported_sequence=9,
        process_stop_sha256="3" * 64,
        capture_sha256="4" * 64,
        workspace_inventory_sha256="5" * 64,
        checkpoint_sha256="6" * 64,
    )
    return reseal(
        reseal(
            waiting.resolution(DeliveryResolutionKind.RESUME_UNINVOKED),
            expected_source_revision=waiting.step.boundary.source_revision,
        ),
        resolution_kind=DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT,
        rejected_output=evidence.to_wire(),
    )


def test_rejected_retry_is_atomic_idempotent_and_keeps_original_publication(
    waiting: WaitingFixture,
) -> None:
    before = waiting.repository.get(waiting.step.boundary.task_id)
    publications = waiting.queue.accepted(before.id)
    events = waiting.repository.list_events(before.id)
    resolution = rejected_resolution(waiting)
    next_item = waiting.queue.resolve_wait(resolution)
    assert next_item.attempt == before.attempts + 1
    assert next_item.parent_work_item_id == waiting.step.work_item.id
    assert next_item.status is WorkItemStatus.READY
    after = waiting.repository.get(before.id)
    assert after.status is TaskStatus.IMPLEMENTING
    assert after.attempts == before.attempts + 1
    assert after.retry_failures == before.retry_failures
    assert waiting.queue.accepted(before.id) == publications
    assert waiting.repository.list_events(before.id) == events
    assert waiting.queue.resolve_wait(resolution) == next_item
    assert waiting.resolution_events() == 1
    assert waiting.queue.rejected_output_retry(next_item.id) == resolution.rejected_output
    assert waiting.queue.rejected_output_artifact_ids(before.id) == frozenset(
        (publications[0].receipt.artifact_id,)
    )
    assert waiting.queue.rejected_output_retry(waiting.step.work_item.id) is None


def test_second_rejected_round_preserves_first_consumed_publication(
    waiting: WaitingFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = rejected_resolution(waiting)
    next_item = waiting.queue.resolve_wait(first)
    step = waiting.queue.step(next_item.id)
    tick = dispatcher(waiting.queue).tick(
        now=next_item.created_at + timedelta(seconds=1), work_item_id=step.work_item.id
    )
    assert tick.claim is not None
    claim = tick.claim
    store = FileArtifactStore(tmp_path / "artifacts")
    progress = make_coder_progress_artifact()
    progress = progress.model_copy(
        update={
            "artifact_id": "art_progress_second",
            "task_id": next_item.task_id,
            "source_revision": SOURCE,
            "context_manifest_id": "ctx_" + "d" * 64,
            "producer": progress.producer.model_copy(
                update={"agent_id": claim.assignment.agent_id, "run_id": "run_second_rejected"}
            ),
            "content": progress.content.model_copy(update={"checkpoint_sequence": 9}),
        }
    )
    waiting.queue.accept_artifact(
        claim, TOKEN, store, seal_artifact(progress, validated_at=waiting.now)
    )
    task = waiting.repository.get(next_item.task_id)
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts.model_validate(
            {
                **waiting.disposition.facts.to_wire(),
                "work_item_id": next_item.id,
                "task_intent_sha256": task_intent_sha256(task),
            }
        )
    )
    waiting.queue.wait(
        next_item.id,
        lease_id=claim.lease.id,
        owner_token=TOKEN,
        status=WorkItemStatus.WAITING_HUMAN,
        reason=disposition.reason,
        disposition=disposition,
        now=next_item.created_at + timedelta(seconds=2),
    )
    second = replace(
        waiting,
        step=step,
        claim=claim,
        disposition=disposition,
        now=next_item.created_at,
    )
    monkeypatch.setattr(
        waiting.queue, "_clock", lambda: next_item.created_at + timedelta(seconds=3)
    )
    publications = waiting.queue.accepted(task.id)
    claims = waiting.queue.claims_for_work_item(next_item.id)
    events = waiting.repository.list_events(task.id)
    decision = rejected_resolution(second)
    successor = waiting.queue.resolve_wait(decision)
    assert successor.attempt == 3
    assert successor.checkpoint_sequence == step.boundary.checkpoint_sequence
    assert waiting.queue.accepted(task.id) == publications
    assert waiting.queue.claims_for_work_item(next_item.id) == claims
    assert waiting.repository.list_events(task.id) == events
    assert waiting.repository.get(task.id).retry_failures == task.retry_failures
    assert waiting.queue.rejected_output_artifact_ids(task.id) == frozenset(
        item.receipt.artifact_id for item in publications
    )
    assert waiting.queue.resolve_wait(decision) == successor
    assert second.resolution_events() == 1


@pytest.mark.parametrize("drift", ["claim", "scope", "publication"])
def test_rejected_retry_wrong_authority_rolls_back_every_fact(
    waiting: WaitingFixture, drift: str
) -> None:
    before = waiting.repository.get(waiting.step.boundary.task_id)
    decision = rejected_resolution(waiting)
    evidence = decision.rejected_output
    assert evidence is not None
    updates = (
        {"original_claim_sha256": "f" * 64}
        if drift == "claim"
        else {"rejected_artifact_sha256": "f" * 64}
        if drift == "publication"
        else {
            "scope": evidence.scope.model_copy(update={"repository_root": "/wrong/root"}).to_wire()
        }
    )
    decision = reseal(decision, rejected_output={**evidence.to_wire(), **updates})
    with pytest.raises(QueueConflict):
        waiting.queue.resolve_wait(decision)
    assert waiting.repository.get(before.id) == before
    assert waiting.resolution_events() == 0
    assert waiting.queue.get(waiting.step.work_item.id).status is WorkItemStatus.WAITING_HUMAN


def test_rejected_retry_cannot_withdraw_a_checkpoint_adopted_artifact(
    waiting: WaitingFixture,
) -> None:
    task = waiting.repository.get(waiting.step.boundary.task_id)
    publication = waiting.queue.accepted(task.id)[0]
    waiting.repository.append_event(
        build_event(
            task,
            TaskStatus.CONTINUE_REQUIRED,
            event_id="evt_rejected_already_adopted",
            reason="fixture_adoption",
            artifact_ids=(publication.receipt.artifact_id,),
            source_revision=SOURCE,
            occurred_at=waiting.now + timedelta(seconds=4),
        )
    )
    # Rejected evidence is still bound to the original checkpoint; no generic
    # withdrawal can roll back a real transition to a later checkpoint.
    with pytest.raises(QueueConflict):
        waiting.queue.resolve_wait(rejected_resolution(waiting))
    assert waiting.repository.get(task.id).status is TaskStatus.CONTINUE_REQUIRED
    assert waiting.resolution_events() == 0
