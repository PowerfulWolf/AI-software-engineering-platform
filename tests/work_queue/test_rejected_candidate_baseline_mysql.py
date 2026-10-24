"""Isolated MySQL crash-stock consumption keeps original output and frozen base."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.domain import Task, WorkItemStatus
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselinePurpose,
    ExecutionBaselineBinding,
)
from ai_software_engineer.git.baseline import GitExecutionBaselineAdapter
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionReservation,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.execution_baseline import ExecutionBaselineService
from ai_software_engineer.manager.rejected_candidate_output import RejectedCandidateOutputProof
from ai_software_engineer.manager.rejected_candidate_owner import (
    EXPIRED_OWNER_NAMESPACE,
    RejectedCandidateExpiredOwnerSettlement,
)
from ai_software_engineer.orchestration.continuation_models import (
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue.baseline import consume_baseline, consumptions
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim
from ai_software_engineer.work_queue.ports import QueueLeaseLost
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_execution_baseline import Collector
from tests.manager.test_rejected_candidate_baseline_production import (
    RejectedCandidateProductionFixture,
)
from tests.manager.test_rejected_candidate_baseline_production import (
    rejected_candidate_production as rejected_candidate_production,
)
from tests.orchestration.test_native_continuation import NOW
from tests.work_queue.test_mysql_queue import OWNER_TOKEN, dispatcher

pytestmark = pytest.mark.mysql


def _proof_with_actual_claim(
    original: RejectedCandidateOutputProof,
    claim: QueueClaim,
    step: QueuedRoleStep,
) -> RejectedCandidateOutputProof:
    """Queue-service contract inputs, independently rebound to a real allocation.

    The production collector's separate tests reopen its actual original ledger.
    This queue fixture observes real MySQL ownership plus the real Git/owned stop
    fixture; it does not rewrite any original invocation or ledger.
    """
    start = DeliveryInvocationStart.model_validate(
        {**original.outcome.start.to_wire(), "lease_id": claim.lease.id, "start_sha256": "0" * 64}
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    report = original.outcome.result.artifact
    assert report is not None
    report = report.model_copy(
        update={
            "producer": report.producer.model_copy(update={"agent_id": claim.assignment.agent_id})
        }
    )
    outcome = DeliveryInvocationOutcome(
        start=start,
        result=original.outcome.result.model_copy(update={"artifact": report}),
        outcome_sha256="0" * 64,
    )
    outcome = outcome.model_copy(
        update={
            "outcome_sha256": digest(outcome.model_dump(mode="json", exclude={"outcome_sha256"}))
        }
    )
    capture_start = ExecutionCaptureStart.create(
        **{
            **original.capture_start.model_dump(mode="python", exclude={"start_sha256"}),
            "claim": claim,
        }
    )
    capture_stop = ExecutionCaptureStop.create(
        **{
            **original.capture_stop.model_dump(mode="python", exclude={"observation_sha256"}),
            "capture_start_sha256": capture_start.start_sha256,
        }
    )
    return RejectedCandidateOutputProof.create(
        **{
            **original.model_dump(mode="python", exclude={"proof_sha256"}),
            "step": step,
            "outcome": outcome,
            "capture_start": capture_start,
            "capture_stop": capture_stop,
        }
    )


@dataclass
class RejectedQueueFixture:
    production: RejectedCandidateProductionFixture
    repository: MySqlTaskRepository
    queue: MySqlRoleQueue
    claim: QueueClaim
    plan: ExecutionBaselinePlan
    binding: ExecutionBaselineBinding

    def settle_expired_owner(self) -> bool:
        proof = self.plan.facts.rejected_candidate_output
        assert proof is not None
        guard = WorkerExecutionGuard()
        store = self.production.collector.inputs.store
        assert store is not None
        with guard.task_scope(self.production.root / "settlement-locks", self.binding.task_id):
            return self.queue.settle_rejected_candidate_expired_owner(
                task_id=self.binding.task_id,
                task_lock=guard,
                collect_current=lambda: proof,
                seal=store.put_expired_owner_settlement,
            )

    def release_crashed_owner(self) -> None:
        """Manufacture only the isolated historical crash shape, no item transition."""
        with (
            closing(open_mysql_connection(self.queue._dsn)) as connection,
            self.queue._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self.queue._lock_authority(cursor)
            self.queue._release_claim(
                cursor, self.claim.lease.id, state="EXPIRED", ended_at=NOW + timedelta(hours=1)
            )
        assert self.queue.get(self.claim.work_item.id).status is WorkItemStatus.RUNNING


@pytest.fixture
def rejected_queue(
    rejected_candidate_production: RejectedCandidateProductionFixture,
    tmp_path: Path,
) -> Iterator[RejectedQueueFixture]:
    f = rejected_candidate_production
    dsn = os.environ["ASE_TEST_MYSQL_DSN"]
    with MySqlTaskRepository(dsn) as repository:
        repository.create(f.native.task)
        repository.record_attempt(f.task.id, 1)
        for event in f.native.repository.list_events(f.task.id):
            repository.append_event(event)
        assert repository.get(f.task.id) == f.task
        queue = MySqlRoleQueue(dsn, clock=lambda: datetime.now(UTC))
        ready = f.queue.bound.work_item.model_copy(update={"status": WorkItemStatus.READY})
        step = f.queue.bound.model_copy(update={"work_item": ready})
        assert f.queue.queue_admission is not None
        queue.admit(f.queue.queue_admission, step)
        tick = dispatcher(queue, "worker_rejected_candidate_fixture").tick(now=NOW)
        assert tick.claim is not None
        claim = tick.claim
        queue.start(
            ready.id,
            lease_id=claim.lease.id,
            owner_token=OWNER_TOKEN,
            now=NOW + timedelta(seconds=1),
        )
        proof = _proof_with_actual_claim(f.proof(), claim, queue.step(ready.id))
        facts = f.facts()
        reservation = BaselineExecutionReservation(
            current_attempt=1,
            next_execution_attempt=2,
            retry_cause="rejected_candidate_output",
            original_run_id=proof.request.run_id,
            current_invocation_start_sha256=proof.outcome.start.start_sha256,
            current_invocation_outcome_sha256=proof.outcome.outcome_sha256,
            rejected_candidate_output_sha256=proof.proof_sha256,
        )
        facts = facts.model_copy(
            update={"rejected_candidate_output": proof, "continuation": reservation}
        )
        facts = facts.model_copy(
            update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
        )
        service = ExecutionBaselineService(
            store=FileExecutionBaselineStore(tmp_path / "mysql-queue-baseline-records"),
            git=GitExecutionBaselineAdapter(f.native.git),
            facts=Collector(facts, f.native.worktree),
        )
        plan = service.propose(None, purpose=BaselinePurpose.REJECTED_CANDIDATE_RESCUE)
        authority = BaselineOperatorAuthorization.for_plan(
            plan,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="isolated queue exact pause",
            submitted_at=datetime.now(UTC),
            continuation_mode=BaselineContinuationMode.PAUSE,
        )
        binding = service.execute(plan.plan_sha256, authority=authority)
        yield RejectedQueueFixture(f, repository, queue, claim, plan, binding)


def test_rejected_candidate_running_stock_closes_once_into_paused_normal_work(
    rejected_queue: RejectedQueueFixture,
) -> None:
    f = rejected_queue
    original = f.repository.get(f.binding.task_id)
    events = f.repository.list_events(original.id)
    outcome = f.plan.facts.rejected_candidate_output
    assert outcome is not None
    assert f.settle_expired_owner()
    with f.queue.idle_task_scope(original.id) as cursor:
        waiting = consume_baseline(f.queue, f.plan, f.binding, cursor=cursor)
    updated = f.repository.get(original.id)
    assert waiting.status is WorkItemStatus.WAITING_HUMAN
    assert waiting.wait_disposition is not None
    assert waiting.wait_disposition.facts.classification == "EXECUTION_BASELINE_PAUSED"
    assert waiting.parent_work_item_id == f.claim.work_item.id
    assert waiting.attempt == original.attempts + 1 == updated.attempts
    assert updated.base_ref == original.base_ref == f.binding.execution_base_ref
    assert updated.retry_failures == original.retry_failures
    assert f.repository.list_events(original.id) == events
    assert f.queue.get(f.claim.work_item.id).status is WorkItemStatus.CLOSED
    assert f.queue.step(waiting.id).boundary.source_revision == outcome.candidate_revision
    assert f.queue.list_schedulable(now=NOW + timedelta(days=1)) == ()
    assert consume_baseline(f.queue, f.plan, f.binding) == waiting
    assert len(consumptions(f.queue, original.id)) == 1
    assert f.repository.get(original.id) == updated
    assert outcome.outcome.result.status.value == "SUCCEEDED"


def test_settlement_preserves_heartbeat_expiry_and_is_idempotent(
    rejected_queue: RejectedQueueFixture,
) -> None:
    f = rejected_queue
    renewed_expiry = NOW + timedelta(hours=1)
    f.queue.renew(
        f.claim.work_item.id,
        lease_id=f.claim.lease.id,
        owner_token=OWNER_TOKEN,
        now=NOW + timedelta(seconds=2),
        expires_at=renewed_expiry,
    )
    task, item = f.repository.get(f.binding.task_id), f.queue.get(f.claim.work_item.id)
    assert f.settle_expired_owner()
    assert not f.settle_expired_owner()
    assert f.repository.get(task.id) == task and f.queue.get(item.id) == item
    store = f.production.collector.inputs.store
    assert store is not None
    records = store.records.list(EXPIRED_OWNER_NAMESPACE, RejectedCandidateExpiredOwnerSettlement)
    assert len(records) == 1
    record = records[0]
    record.validate_integrity()
    assert record.current_claim.lease.expires_at == renewed_expiry
    assert record.proof.original_claim.lease.expires_at == f.claim.lease.expires_at
    assert record.proof.outcome.result.status.value == "SUCCEEDED"
    with f.queue.idle_task_scope(task.id):
        pass


def test_valid_owner_is_not_settled_and_never_collects_proof(
    rejected_queue: RejectedQueueFixture,
) -> None:
    f = rejected_queue
    f.queue._clock = lambda: NOW + timedelta(seconds=10)
    with pytest.raises(QueueLeaseLost, match="有效租约"):
        f.settle_expired_owner()
    assert f.queue.get(f.claim.work_item.id).status is WorkItemStatus.RUNNING
    store = f.production.collector.inputs.store
    assert store is not None
    assert (
        store.records.list(EXPIRED_OWNER_NAMESPACE, RejectedCandidateExpiredOwnerSettlement) == ()
    )


def test_changed_second_proof_prevents_expiry_and_records_no_settlement(
    rejected_queue: RejectedQueueFixture,
) -> None:
    f = rejected_queue
    proof = f.plan.facts.rejected_candidate_output
    assert proof is not None
    guard = WorkerExecutionGuard()
    store = f.production.collector.inputs.store
    assert store is not None
    calls = 0

    def collect() -> RejectedCandidateOutputProof:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("fresh original stop changed")
        return proof

    with (
        guard.task_scope(f.production.root / "settlement-locks", f.binding.task_id),
        pytest.raises(ValueError, match="stop changed"),
    ):
        f.queue.settle_rejected_candidate_expired_owner(
            task_id=f.binding.task_id,
            task_lock=guard,
            collect_current=collect,
            seal=store.put_expired_owner_settlement,
        )
    assert calls == 2
    assert f.queue.get(f.claim.work_item.id).status is WorkItemStatus.RUNNING
    assert (
        store.records.list(EXPIRED_OWNER_NAMESPACE, RejectedCandidateExpiredOwnerSettlement) == ()
    )
    with pytest.raises(QueueLeaseLost), f.queue.idle_task_scope(f.binding.task_id):
        raise AssertionError("failed settlement cannot remove ACTIVE ownership")


def test_backward_confirmation_clock_cannot_settle_original_owner(
    rejected_queue: RejectedQueueFixture,
) -> None:
    f = rejected_queue
    now = datetime.now(UTC)
    times = iter((now, now - timedelta(seconds=1)))
    f.queue._clock = lambda: next(times)
    with pytest.raises(QueueLeaseLost, match="时钟回退"):
        f.settle_expired_owner()
    assert f.queue.get(f.claim.work_item.id).status is WorkItemStatus.RUNNING
    store = f.production.collector.inputs.store
    assert store is not None
    assert (
        store.records.list(EXPIRED_OWNER_NAMESPACE, RejectedCandidateExpiredOwnerSettlement) == ()
    )


def test_failed_durable_seal_does_not_release_the_original_owner(
    rejected_queue: RejectedQueueFixture,
) -> None:
    f = rejected_queue
    proof = f.plan.facts.rejected_candidate_output
    assert proof is not None
    guard = WorkerExecutionGuard()

    def reject_seal(record: RejectedCandidateExpiredOwnerSettlement) -> str:
        record.validate_integrity()
        raise ValueError("isolated durable seal failure")

    with (
        guard.task_scope(f.production.root / "settlement-locks", f.binding.task_id),
        pytest.raises(ValueError, match="durable seal failure"),
    ):
        f.queue.settle_rejected_candidate_expired_owner(
            task_id=f.binding.task_id,
            task_lock=guard,
            collect_current=lambda: proof,
            seal=reject_seal,
        )
    assert f.queue.get(f.claim.work_item.id).status is WorkItemStatus.RUNNING
    with pytest.raises(QueueLeaseLost), f.queue.idle_task_scope(f.binding.task_id):
        raise AssertionError("failed seal cannot remove ACTIVE ownership")


def test_expired_but_active_original_claim_still_prevents_consumption(
    rejected_queue: RejectedQueueFixture,
) -> None:
    f = rejected_queue
    before = f.repository.get(f.binding.task_id)
    with pytest.raises(QueueLeaseLost), f.queue.idle_task_scope(before.id):
        raise AssertionError("an ACTIVE claim cannot enter the idle scope")
    with pytest.raises(QueueLeaseLost):
        consume_baseline(f.queue, f.plan, f.binding)
    assert f.repository.get(before.id) == before
    assert f.queue.get(f.claim.work_item.id).status is WorkItemStatus.RUNNING
    assert consumptions(f.queue, before.id) == ()


def test_failed_fresh_revalidation_preserves_running_stock_and_budget(
    rejected_queue: RejectedQueueFixture,
) -> None:
    f = rejected_queue
    f.release_crashed_owner()
    before: Task = f.repository.get(f.binding.task_id)

    def reject() -> None:
        raise ValueError("fresh original stop or publication facts changed")

    with (
        f.queue.idle_task_scope(before.id) as cursor,
        pytest.raises(ValueError, match="facts changed"),
    ):
        consume_baseline(f.queue, f.plan, f.binding, cursor=cursor, validate_new_consumption=reject)
    assert f.repository.get(before.id) == before
    assert f.queue.get(f.claim.work_item.id).status is WorkItemStatus.RUNNING
    assert consumptions(f.queue, before.id) == ()
