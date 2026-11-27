"""Verifier rerun dispatches only the rejected role on the unchanged candidate.

These queue-level delivery tests reuse the real MySQL verifier wait fixture. A fake
adapter counts invocations per role; the simulated worker invokes it only for a
claim the Dispatcher actually issues and only after the successor admission check.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pytest

from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.domain.enums import WorkItemStatus
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.rejected_verifier_output import (
    VerifierRerunAdmissionRejected,
    verify_rejected_verifier_rerun_claim,
)
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.work_queue.models import QueueClaim
from tests.work_queue import test_rejected_verifier_output_mysql as mysql_fixture
from tests.work_queue.test_worker_mysql import dispatcher

pytestmark = pytest.mark.mysql
verifier = mysql_fixture.verifier
VerifierWait = mysql_fixture.VerifierWait


class CountingAdapter:
    def __init__(self) -> None:
        self.calls: Counter[AgentRole] = Counter()
        self.inputs: list[tuple[str, ...]] = []

    def invoke(self, role: AgentRole, inputs: tuple[str, ...]) -> None:
        self.calls[role] += 1
        self.inputs.append(inputs)


def _rerun(wait: mysql_fixture.VerifierWait, adapter: CountingAdapter) -> QueueClaim:
    successor = wait.queue.resolve_wait(wait.resolution())
    tick = dispatcher(wait.queue).tick(
        now=successor.created_at + timedelta(seconds=1), work_item_id=successor.id
    )
    assert tick.claim is not None
    claim = tick.claim
    evidence = wait.queue.rejected_verifier_retry(claim.work_item.id)
    assert evidence is not None
    task = wait.repository.get(claim.work_item.task_id)
    accepted = wait.queue.accepted(task.id)
    verify_rejected_verifier_rerun_claim(
        evidence=evidence,
        claim=claim,
        task=task,
        accepted=accepted,
        run_id="run_verifier_rerun_delivery",
        context_manifest_id="ctx_" + "e" * 64,
    )
    inputs = (evidence.implementation_artifact_id,) + (
        (evidence.accepted_qa_artifact_id,) if evidence.accepted_qa_artifact_id else ()
    )
    adapter.invoke(claim.work_item.role, inputs)
    return claim


def test_qa_rerun_only_invokes_qa_on_same_candidate(
    verifier: mysql_fixture.VerifierWait,
) -> None:
    adapter = CountingAdapter()
    before = verifier.repository.get(verifier.step.boundary.task_id)
    items = verifier.items()
    claim = _rerun(verifier, adapter)
    assert adapter.calls == Counter({AgentRole.QA: 1})
    assert verifier.items() == items + 1
    step = verifier.queue.step(claim.work_item.id)
    assert step.boundary.source_revision == mysql_fixture.SOURCE
    after = verifier.repository.get(before.id)
    assert after.attempts == before.attempts + 1
    assert after.status is TaskStatus.QA


@pytest.mark.parametrize("verifier", [AgentRole.REVIEWER], indirect=True)
def test_reviewer_rerun_only_invokes_reviewer_with_accepted_qa(
    verifier: mysql_fixture.VerifierWait,
) -> None:
    adapter = CountingAdapter()
    claim = _rerun(verifier, adapter)
    assert claim.work_item.role is AgentRole.REVIEWER
    assert adapter.calls == Counter({AgentRole.REVIEWER: 1})
    assert adapter.inputs == [(mysql_fixture.IMPL_ID, mysql_fixture.QA_ID)]
    assert verifier.repository.get(claim.work_item.task_id).status is TaskStatus.REVIEW


@pytest.mark.parametrize("verifier", [AgentRole.QA, AgentRole.REVIEWER], indirect=True)
@pytest.mark.parametrize("positive", [True, False])
def test_verifier_rerun_normal_downstream_routing(
    verifier: mysql_fixture.VerifierWait, positive: bool
) -> None:
    adapter = CountingAdapter()
    claim = _rerun(verifier, adapter)
    task_id = claim.work_item.task_id
    role = claim.work_item.role
    if positive:
        targets = (
            [TaskStatus.REVIEW, TaskStatus.DONE] if role is AgentRole.QA else [TaskStatus.DONE]
        )
    else:
        targets = [TaskStatus.IMPLEMENTING]
    for index, target in enumerate(targets):
        verifier.repository.append_event(
            build_event(
                verifier.repository.get(task_id),
                target,
                event_id=f"evt_verifier_rerun_route_{index}",
                reason="rerun routed",
                artifact_ids=(f"art_rerun_route_{index}",),
                source_revision=mysql_fixture.SOURCE,
                occurred_at=verifier.now + timedelta(seconds=10 + index),
            )
        )
    assert verifier.repository.get(task_id).status is targets[-1]


def test_verifier_rerun_preserves_original_failure_records(
    verifier: mysql_fixture.VerifierWait,
) -> None:
    task_id = verifier.step.boundary.task_id
    events = verifier.repository.list_events(task_id)
    accepted = verifier.queue.accepted(task_id)
    original_claim = digest(verifier.queue.original_claim(verifier.claim.lease.id).to_wire())
    original = verifier.queue.get(verifier.step.work_item.id)
    before = verifier.repository.get(task_id)
    claim = _rerun(verifier, CountingAdapter())
    assert verifier.repository.list_events(task_id)[: len(events)] == events
    assert verifier.queue.accepted(task_id) == accepted
    assert (
        digest(verifier.queue.original_claim(verifier.claim.lease.id).to_wire()) == original_claim
    )
    closed = verifier.queue.get(verifier.step.work_item.id)
    assert closed.status is WorkItemStatus.CLOSED
    # Closing consumes the wait like every other rerun: the disposition column is
    # cleared, while the original failure stays in events and the sealed decision.
    assert original.wait_disposition is not None and closed.wait_disposition is None
    assert verifier.repository.get(task_id).retry_failures == before.retry_failures
    # A consumed decision cannot admit the old identity again.
    evidence = verifier.queue.rejected_verifier_retry(claim.work_item.id)
    assert evidence is not None
    with pytest.raises(VerifierRerunAdmissionRejected):
        verify_rejected_verifier_rerun_claim(
            evidence=evidence,
            claim=claim,
            task=verifier.repository.get(task_id),
            accepted=verifier.queue.accepted(task_id),
            run_id=evidence.previous_run_id,
        )
