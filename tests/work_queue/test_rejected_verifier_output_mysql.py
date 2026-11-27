"""RETRY_REJECTED_VERIFIER_OUTPUT is consumed once inside the Task/SQL fence."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.execution import SynchronousToolLoopStop
from ai_software_engineer.domain import AgentRole, RiskTier, Task, TaskStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryDisposition,
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    RejectedVerifierOutputEvidence,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.enums import WorkItemStatus
from ai_software_engineer.domain.retry_policy import DeliveryRetryPolicy
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.rejected_verifier_output import (
    VerifierRerunAdmissionRejected,
    VerifierStopUncertain,
    _require_stopped,
    verify_rejected_verifier_rerun_claim,
)
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
    _put,
    record_digest,
)
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from ai_software_engineer.work_queue.models import QueueArtifactReceipt, QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueConflict
from tests.agents.test_openai_compatible import _request
from tests.domain.factories import make_task
from tests.work_queue.test_worker_mysql import (
    ALLOCATION_SHA,
    REPOSITORY_ID,
    TOKEN,
    claim_step,
    dispatcher,
)

pytestmark = pytest.mark.mysql
SOURCE = "a" * 40
PLAN_ID = "art_plan_verifier_rerun"
IMPL_ID = "art_impl_verifier_rerun"
QA_ID = "art_qa_verifier_rerun"
PREVIOUS_RUN = "run_verifier_rejected"
PREVIOUS_CONTEXT = "ctx_" + "c" * 64
RERUN = DeliveryResolutionKind.RETRY_REJECTED_VERIFIER_OUTPUT


def reseal(resolution: DeliveryResolution, **updates: object) -> DeliveryResolution:
    updated = DeliveryResolution.model_validate({**resolution.to_wire(), **updates})
    return updated.model_copy(update={"resolution_sha256": updated.recompute_sha256()})


@dataclass
class VerifierWait:
    dsn: str
    repository: MySqlTaskRepository
    queue: MySqlRoleQueue
    step: QueuedRoleStep
    claim: QueueClaim
    disposition: DeliveryDisposition
    now: datetime

    @property
    def role(self) -> AgentRole:
        return self.step.boundary.role

    def evidence(self, **updates: object) -> RejectedVerifierOutputEvidence:
        original = self.queue.original_claim(self.claim.lease.id)
        reviewer = self.role is AgentRole.REVIEWER
        value: dict[str, object] = {
            "task_id": self.step.boundary.task_id,
            "work_item_id": self.step.work_item.id,
            "role": self.role,
            "candidate_revision": SOURCE,
            "plan_artifact_id": PLAN_ID,
            "plan_artifact_sha256": "1" * 64,
            "implementation_artifact_id": IMPL_ID,
            "implementation_artifact_sha256": "2" * 64,
            "accepted_qa_artifact_id": QA_ID if reviewer else None,
            "accepted_qa_artifact_sha256": "3" * 64 if reviewer else None,
            "original_lease_id": self.claim.lease.id,
            "original_claim_sha256": digest(original.to_wire()),
            "original_attempt": self.claim.work_item.attempt,
            "original_dispatch_sequence": self.claim.work_item.dispatch_sequence,
            "checkpoint_sequence": self.step.boundary.checkpoint_sequence,
            "previous_run_id": PREVIOUS_RUN,
            "previous_context_manifest_id": PREVIOUS_CONTEXT,
            "invocation_start_sha256": "4" * 64,
            "invocation_outcome_sha256": "5" * 64,
            "execution_stop_sha256": "6" * 64,
        }
        value.update(updates)
        return RejectedVerifierOutputEvidence.model_validate(value)

    def resolution(self, **updates: object) -> DeliveryResolution:
        task = self.repository.get(self.step.boundary.task_id)
        evidence = self.evidence(**updates)
        value = DeliveryResolution(
            task_id=task.id,
            work_item_id=self.step.work_item.id,
            expected_disposition_sha256=self.disposition.disposition_sha256,
            expected_task_intent_sha256=task_intent_sha256(task),
            expected_source_revision=evidence.candidate_revision,
            expected_checkpoint_sequence=self.step.boundary.checkpoint_sequence,
            task_revision=self.repository.current_revision(task.id),
            task_snapshot_sha256=digest(task.to_wire()),
            step_sha256=record_digest(self.step),
            resolution_kind=RERUN,
            proof_sha256="e" * 64,
            operator_principal=LocalOperatorPrincipal.trusted_local(),
            submitted_at=self.now + timedelta(seconds=3),
            resolution_sha256="0" * 64,
            rejected_verifier_output=evidence,
        )
        return value.model_copy(update={"resolution_sha256": value.recompute_sha256()})

    def count(self, sql: str, *params: object) -> int:
        with (
            closing(open_mysql_connection(self.dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(sql, params)
            row = cursor.fetchone()
            assert row is not None
            return int(row["total"])

    def resolution_events(self) -> int:
        return self.count(
            "SELECT COUNT(*) AS total FROM work_queue_events "
            "WHERE work_item_id=%s AND event_type='WAIT_RESOLVED'",
            self.step.work_item.id,
        )

    def items(self) -> int:
        return self.count(
            "SELECT COUNT(*) AS total FROM work_queue_items WHERE task_id=%s",
            self.step.boundary.task_id,
        )

    def put_accepted(self, artifact_id: str, sha256: str, work_item_id: str, run_id: str) -> None:
        record = AcceptedRoleArtifact(
            task_id=self.step.boundary.task_id,
            work_item_id=work_item_id,
            lease_id="lease_" + work_item_id,
            dispatch_sequence=0,
            checkpoint_sequence=self.step.boundary.checkpoint_sequence,
            run_id=run_id,
            context_manifest_id="ctx_" + "9" * 64,
            source_revision=SOURCE,
            receipt=QueueArtifactReceipt(artifact_id=artifact_id, sha256=sha256),
        )
        with closing(open_mysql_connection(self.dsn)) as connection:
            with connection.cursor(DictCursor) as cursor:
                _put(
                    cursor,
                    "work_queue_accepted_artifacts",
                    artifact_id,
                    self.step.boundary.task_id,
                    record,
                )
            connection.commit()


@pytest.fixture
def verifier(request: pytest.FixtureRequest) -> Iterator[VerifierWait]:
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    param = getattr(request, "param", AgentRole.QA)
    role, max_work = param if isinstance(param, tuple) else (param, 3)
    now = datetime.now(UTC)
    policy = DeliveryRetryPolicy(max_work_attempts=max_work)
    original = make_task()
    assert original.constraints is not None
    task = Task.model_validate(
        {
            **original.to_wire(),
            "repository": "/fixture/repository",
            "engineering_policy": EngineeringPolicy.bounded_local(
                scope=EngineeringScope(
                    team_id="team_test",
                    project_id="project_test",
                    repository_id=REPOSITORY_ID,
                    repository_root="/fixture/repository",
                ),
                principal=LocalOperatorPrincipal.trusted_local(),
            ).to_wire(),
            "max_attempts": policy.execution_limit,
            "retry_policy": policy.to_wire(),
            "constraints": {
                **original.constraints.to_wire(),
                "max_attempts": policy.execution_limit,
            },
        }
    )
    with MySqlTaskRepository(dsn) as repository:
        repository.create(task)
        repository.record_attempt(task.id, 1)
        phases: list[tuple[TaskStatus, str, tuple[str, ...]]] = [
            (TaskStatus.PLANNING, "planning", ()),
            (TaskStatus.IMPLEMENTING, "plan_validated", (PLAN_ID,)),
            (TaskStatus.QA, "candidate ready", (IMPL_ID,)),
        ]
        if role is AgentRole.REVIEWER:
            phases.append((TaskStatus.REVIEW, "qa_passed", (QA_ID,)))
        for index, (status, reason, artifact_ids) in enumerate(phases):
            repository.append_event(
                build_event(
                    repository.get(task.id),
                    status,
                    event_id=f"evt_verifier_rerun_{index}",
                    reason=reason,
                    artifact_ids=artifact_ids,
                    source_revision=SOURCE,
                    occurred_at=now + timedelta(microseconds=index),
                )
            )
        task = repository.get(task.id)
        revision = repository.current_revision(task.id)
        queue = MySqlRoleQueue(dsn, clock=lambda: now + timedelta(seconds=5))
        item = QueuedWorkItem(
            id="work_verifier_rerun_001",
            task_id=task.id,
            repository_id=REPOSITORY_ID,
            role=role,
            attempt=1,
            checkpoint_sequence=revision,
            repository_scopes=(task.repository,),
            status=WorkItemStatus.READY,
            preferred_agent_id=f"agent_{role.value}_001",
            priority=500,
            risk=RiskTier.NORMAL,
            required_capabilities=("delivery",),
            created_at=now,
            updated_at=now,
        )
        step = QueuedRoleStep(
            work_item=item,
            allocation_sha256=ALLOCATION_SHA,
            boundary=RoleRunBoundary(task.id, role, 1, revision, SOURCE),
        )
        queue.admit(
            RoleQueueAdmission(
                task_id=task.id,
                repository_id=REPOSITORY_ID,
                allocation_sha256=ALLOCATION_SHA,
                legacy_artifacts=(),
            ),
            step,
        )
        claim = claim_step(queue, step)
        disposition = decide_delivery_disposition(
            DeliveryFailureFacts(
                task_id=task.id,
                work_item_id=item.id,
                role=role,
                classification="INVALID_OUTPUT",
                source_revision=SOURCE,
                task_intent_sha256=task_intent_sha256(task),
                checkpoint_sequence=revision,
                budget_available=True,
            )
        )
        queue.wait(
            item.id,
            lease_id=claim.lease.id,
            owner_token=TOKEN,
            status=WorkItemStatus.WAITING_HUMAN,
            reason=disposition.reason,
            disposition=disposition,
            now=now + timedelta(seconds=2),
        )
        fixture = VerifierWait(dsn, repository, queue, step, claim, disposition, now)
        fixture.put_accepted(IMPL_ID, "2" * 64, "work_prior_coder", "run_prior_coder")
        if role is AgentRole.REVIEWER:
            fixture.put_accepted(QA_ID, "3" * 64, "work_prior_qa", "run_prior_qa")
        yield fixture


def _assert_unchanged(verifier: VerifierWait, before: Task, items: int) -> None:
    assert verifier.repository.get(before.id) == before
    assert verifier.resolution_events() == 0
    assert verifier.items() == items
    assert verifier.queue.get(verifier.step.work_item.id).status is WorkItemStatus.WAITING_HUMAN


@pytest.mark.parametrize("verifier", [AgentRole.QA, AgentRole.REVIEWER], indirect=True)
def test_resolve_verifier_rerun_creates_single_successor(verifier: VerifierWait) -> None:
    before = verifier.repository.get(verifier.step.boundary.task_id)
    publications = verifier.queue.accepted(before.id)
    events = verifier.repository.list_events(before.id)
    successor = verifier.queue.resolve_wait(verifier.resolution())
    assert successor.role is verifier.role
    assert successor.parent_work_item_id == verifier.step.work_item.id
    assert successor.attempt == before.attempts + 1
    assert successor.status is WorkItemStatus.READY
    assert verifier.queue.step(successor.id).boundary.source_revision == SOURCE
    assert verifier.queue.get(verifier.step.work_item.id).status is WorkItemStatus.CLOSED
    assert verifier.resolution_events() == 1
    after = verifier.repository.get(before.id)
    assert after.status is before.status and after.attempts == before.attempts + 1
    assert after.retry_failures == before.retry_failures
    assert verifier.queue.accepted(before.id) == publications
    assert verifier.repository.list_events(before.id) == events
    assert verifier.queue.rejected_verifier_retry(successor.id) == verifier.evidence()
    assert verifier.queue.rejected_verifier_retry(verifier.step.work_item.id) is None


def test_resolve_rejects_candidate_drift(verifier: VerifierWait) -> None:
    before = verifier.repository.get(verifier.step.boundary.task_id)
    items = verifier.items()
    drifts: tuple[dict[str, object], ...] = (
        {"candidate_revision": "b" * 40},
        {"implementation_artifact_sha256": "f" * 64},
        {"implementation_artifact_id": "art_impl_other"},
    )
    for drift in drifts:
        with pytest.raises(QueueConflict):
            verifier.queue.resolve_wait(verifier.resolution(**drift))
        _assert_unchanged(verifier, before, items)


def test_resolve_rejects_plan_drift(verifier: VerifierWait) -> None:
    before = verifier.repository.get(verifier.step.boundary.task_id)
    items = verifier.items()
    with pytest.raises(QueueConflict):
        verifier.queue.resolve_wait(verifier.resolution(plan_artifact_id="art_plan_other"))
    _assert_unchanged(verifier, before, items)
    decision = verifier.resolution()
    with pytest.raises(QueueConflict):
        verifier.queue.resolve_wait(reseal(decision, expected_task_intent_sha256="f" * 64))
    _assert_unchanged(verifier, before, items)


def test_resolve_rejects_stale_proof(verifier: VerifierWait) -> None:
    decision = verifier.resolution()
    task_id = verifier.step.boundary.task_id
    verifier.repository.record_attempt(task_id, 2)
    before = verifier.repository.get(task_id)
    items = verifier.items()
    with pytest.raises(QueueConflict):
        verifier.queue.resolve_wait(decision)
    _assert_unchanged(verifier, before, items)


@pytest.mark.parametrize("verifier", [(AgentRole.QA, 1)], indirect=True)
def test_resolve_rejects_exhausted_work_budget(verifier: VerifierWait) -> None:
    before = verifier.repository.get(verifier.step.boundary.task_id)
    # Transient allowance remains, but the ordinary work budget is spent.
    assert before.work_budget_exhausted and before.attempts < before.max_attempts
    items = verifier.items()
    with pytest.raises(QueueConflict):
        verifier.queue.resolve_wait(verifier.resolution())
    _assert_unchanged(verifier, before, items)


@pytest.mark.parametrize("verifier", [(AgentRole.QA, 2)], indirect=True)
def test_resolve_allows_last_work_attempt(verifier: VerifierWait) -> None:
    successor = verifier.queue.resolve_wait(verifier.resolution())
    task = verifier.repository.get(verifier.step.boundary.task_id)
    assert successor.attempt == 2 and task.attempts == 2
    assert task.work_budget_exhausted


def test_resolve_rejects_live_process(verifier: VerifierWait) -> None:
    before = verifier.repository.get(verifier.step.boundary.task_id)
    items = verifier.items()
    request = _request(AgentRole.QA, run_id=PREVIOUS_RUN, source_revision=SOURCE)
    start = cast(DeliveryInvocationStart, SimpleNamespace(request=request, started_at=verifier.now))
    with pytest.raises(ValueError):
        _require_stopped(None, start)
    foreign = SynchronousToolLoopStop.create(
        task_id=request.task_id,
        run_id=request.run_id,
        request_sha256="f" * 64,
        completed_operation_ids=(),
        kind="failed",
        stopped_at=verifier.now,
    )
    with pytest.raises(VerifierStopUncertain):
        _require_stopped(foreign, start)
    _assert_unchanged(verifier, before, items)


def test_resolve_rejects_active_claim(verifier: VerifierWait) -> None:
    before = verifier.repository.get(verifier.step.boundary.task_id)
    items = verifier.items()
    with closing(open_mysql_connection(verifier.dsn)) as connection:
        with connection.cursor(DictCursor) as cursor:
            cursor.execute(
                "UPDATE work_queue_claims SET state='ACTIVE' WHERE lease_id=%s",
                (verifier.claim.lease.id,),
            )
        connection.commit()
    with pytest.raises(QueueConflict):
        verifier.queue.resolve_wait(verifier.resolution())
    assert verifier.repository.get(before.id) == before
    assert verifier.resolution_events() == 0
    assert verifier.items() == items


def test_resolve_rejects_accepted_artifact_present(verifier: VerifierWait) -> None:
    before = verifier.repository.get(verifier.step.boundary.task_id)
    verifier.put_accepted(
        "art_qa_original_rejected", "7" * 64, verifier.step.work_item.id, PREVIOUS_RUN
    )
    items = verifier.items()
    with pytest.raises(QueueConflict):
        verifier.queue.resolve_wait(verifier.resolution())
    _assert_unchanged(verifier, before, items)


def test_resolve_rejects_non_engineering_authority(verifier: VerifierWait) -> None:
    before = verifier.repository.get(verifier.step.boundary.task_id)
    items = verifier.items()
    decision = verifier.resolution()
    wire: dict[str, Any] = decision.to_wire()
    for bad in (
        {**wire, "authorization_source": "organization_engineering_policy"},
        {key: value for key, value in wire.items() if key != "operator_principal"},
    ):
        with pytest.raises(ValidationError):
            DeliveryResolution.model_validate(bad)
    _assert_unchanged(verifier, before, items)


def test_verifier_rerun_decision_not_reusable_and_single_debit(verifier: VerifierWait) -> None:
    decision = verifier.resolution()
    successor = verifier.queue.resolve_wait(decision)
    attempts = verifier.repository.get(verifier.step.boundary.task_id).attempts
    assert verifier.queue.resolve_wait(decision) == successor
    assert verifier.repository.get(verifier.step.boundary.task_id).attempts == attempts
    assert verifier.resolution_events() == 1
    with pytest.raises(QueueConflict):
        verifier.queue.resolve_wait(
            reseal(decision, submitted_at=decision.submitted_at + timedelta(seconds=1))
        )
    assert verifier.repository.get(verifier.step.boundary.task_id).attempts == attempts
    assert verifier.resolution_events() == 1


@pytest.mark.parametrize("verifier", [AgentRole.QA, AgentRole.REVIEWER], indirect=True)
def test_verifier_rerun_fresh_identity(verifier: VerifierWait) -> None:
    successor = verifier.queue.resolve_wait(verifier.resolution())
    tick = dispatcher(verifier.queue).tick(
        now=successor.created_at + timedelta(seconds=1), work_item_id=successor.id
    )
    assert tick.claim is not None
    claim = tick.claim
    assert claim.lease.id != verifier.claim.lease.id
    assert claim.work_item.id != verifier.step.work_item.id
    evidence = verifier.queue.rejected_verifier_retry(successor.id)
    assert evidence is not None
    task = verifier.repository.get(verifier.step.boundary.task_id)
    accepted = verifier.queue.accepted(task.id)
    assert (
        verify_rejected_verifier_rerun_claim(
            evidence=evidence,
            claim=claim,
            task=task,
            accepted=accepted,
            run_id="run_verifier_rerun_fresh",
            context_manifest_id="ctx_" + "d" * 64,
        )
        == evidence
    )
    with pytest.raises(VerifierRerunAdmissionRejected):
        verify_rejected_verifier_rerun_claim(
            evidence=evidence, claim=claim, task=task, accepted=accepted, run_id=PREVIOUS_RUN
        )
    with pytest.raises(VerifierRerunAdmissionRejected):
        verify_rejected_verifier_rerun_claim(
            evidence=evidence,
            claim=claim,
            task=task,
            accepted=accepted,
            context_manifest_id=PREVIOUS_CONTEXT,
        )
