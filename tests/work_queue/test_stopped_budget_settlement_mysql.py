"""Real SQL authority, idle fence and atomic exhausted stopped Task settlement."""

import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.domain import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import DeliveryWaitHandling, HandleDeliveryWait
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_wait import DeliveryWaitService
from ai_software_engineer.manager.stopped_budget_settlement import StoppedBudgetSettlementService
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.continuation_models import (
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, RoleQueueAdmission
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from tests.manager.test_completed_output_checkpoint import CompletedFixture, _outcome
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.work_queue.test_worker_mysql import TOKEN, claim_step

completed = completed_fixture
pytestmark = [
    pytest.mark.mysql,
    pytest.mark.parametrize("completed", ["stopped_provider_exhausted"], indirect=True),
]


@dataclass
class RealWait:
    repository: MySqlTaskRepository
    queue: MySqlRoleQueue
    entry: DeliveryWaitService
    command: HandleDeliveryWait


@pytest.fixture
def real_wait(completed: CompletedFixture, tmp_path: Path) -> Iterator[RealWait]:
    f = completed
    dsn = os.environ["ASE_TEST_MYSQL_DSN"]
    root = tmp_path / "mysql-state"
    with MySqlTaskRepository(dsn) as repository:
        repository.create(f.native.task)
        repository.record_attempt(f.task.id, 1)
        for event in f.native.repository.list_events(f.task.id):
            repository.append_event(event)
        task = repository.get(f.task.id)
        queue = MySqlRoleQueue(dsn)
        ready = f.queue.bound.model_copy(
            update={
                "work_item": f.queue.bound.work_item.model_copy(
                    update={"status": WorkItemStatus.READY}
                )
            }
        )
        queue.admit(
            RoleQueueAdmission(
                task_id=task.id,
                repository_id=ready.work_item.repository_id,
                allocation_sha256=ready.allocation_sha256,
                legacy_artifacts=(),
            ),
            ready,
        )
        claim = claim_step(queue, ready)
        now = datetime.now(UTC)
        start = DeliveryInvocationStart(
            work_item_id=ready.work_item.id,
            checkpoint_sequence=ready.boundary.checkpoint_sequence,
            request=f.native.request,
            lease_id=claim.lease.id,
            started_at=now,
            start_sha256="0" * 64,
        )
        start = start.model_copy(
            update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
        )
        capture_start = ExecutionCaptureStart.create(
            **{
                **f.capture_start.model_dump(mode="python", exclude={"start_sha256"}),
                "claim": claim,
                "started_at": now,
            }
        )
        process = subprocess.Popen(
            (sys.executable, "-c", "raise SystemExit(1)"), start_new_session=True
        )
        rc = process.wait(timeout=5)
        stop = ExecutionCaptureStop.create(
            task_id=task.id,
            run_id=start.request.run_id,
            capture_start_sha256=capture_start.start_sha256,
            output_present=False,
            original_error_code=f.outcome.result.error.code if f.outcome.result.error else None,
            process_stop=NativeProcessStop.create(
                process_id=process.pid,
                group_id=process.pid,
                returncode=rc,
                kind="failed",
                stopped_at=datetime.now(UTC),
            ),
        )
        invocation_records = KnowledgeRecordStore(root / "invocations")
        invocation_records.put("invocation-starts", ready.work_item.id, start)
        invocation_records.put(
            "invocation-outcomes", ready.work_item.id, _outcome(start, f.outcome.result)
        )
        (root / "continuations").mkdir(mode=0o700)
        ledger = FileContinuationStore.initialize(root / "continuations" / task.id, task_id=task.id)
        ledger.put_capture_start(capture_start)
        ledger.put_capture_stop(stop)
        assert f.queue.item.wait_disposition is not None
        disposition = decide_delivery_disposition(
            DeliveryFailureFacts.model_validate(
                {
                    **f.queue.item.wait_disposition.facts.to_wire(),
                    "classification": "TRANSIENT_INFRA",
                }
            )
        )
        item = queue.wait(
            ready.work_item.id,
            lease_id=claim.lease.id,
            owner_token=TOKEN,
            status=WorkItemStatus.WAITING_DEPENDENCY,
            reason=disposition.reason,
            disposition=disposition,
            now=datetime.now(UTC),
        )
        collector = DeliveryWaitFactCollector(
            sidecar_state=root,
            route_root=root / "routes",
            scope=f.collector.scope,
            expected_continuation_scope=f.native.scope,
            git=f.native.git,
            queue=queue,
        )
        entry = DeliveryWaitService(
            repository=repository,
            queue=queue,
            scope=f.collector.scope,
            sidecar_state=root,
            git=f.native.git,
            principal=LocalOperatorPrincipal.trusted_local(),
            consume=lambda resolution: None,
            stop_observer=collector.observe_stop,
            budget_settlement=StoppedBudgetSettlementService(
                repository=repository,
                queue=queue,
                records=KnowledgeRecordStore(root / "delivery-waits"),
                collector=collector,
                git=f.native.git,
                clock=lambda: datetime.now(UTC),
                idle_scope=lambda: queue.idle_task_scope(task.id),
            ),
        )
        command = HandleDeliveryWait(
            work_item_id=item.id,
            expected_disposition_sha256=disposition.disposition_sha256,
            expected_task_intent_sha256=disposition.facts.task_intent_sha256,
            expected_source_revision=disposition.facts.source_revision,
            expected_checkpoint_sequence=item.checkpoint_sequence,
        )
        yield RealWait(repository, queue, entry, command)


def test_atomic_sql_settlement_and_exact_replay(real_wait: RealWait) -> None:
    f = real_wait
    item = f.queue.get(f.command.work_item_id)
    before = f.repository.get(item.task_id)
    events = f.repository.list_events(before.id)
    claims = f.queue.claims_for_work_item(item.id)
    result = f.entry.handle(f.command)
    assert result.budget_settlement_sha256 is not None
    assert f.repository.get(before.id).status is TaskStatus.BLOCKED
    assert f.repository.list_events(before.id)[:-1] == events
    assert f.repository.get(before.id).retry_failures == before.retry_failures
    assert f.queue.get(item.id).status is WorkItemStatus.CLOSED
    assert f.queue.claims_for_work_item(item.id) == claims
    assert f.entry.handle(f.command) == result
    assert len(f.repository.list_events(before.id)) == len(events) + 1


def test_sql_failure_rolls_back_all_three_publications(
    real_wait: RealWait, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = real_wait
    item = f.queue.get(f.command.work_item_id)
    before = f.repository.get(item.task_id)
    events = f.repository.list_events(before.id)
    append = f.queue._append_event

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("test queue append failure")

    monkeypatch.setattr(f.queue, "_append_event", fail)
    with pytest.raises(RuntimeError, match="queue append failure"):
        f.entry.handle(f.command)
    assert f.repository.get(before.id) == before
    assert f.repository.list_events(before.id) == events
    assert f.queue.get(item.id) == item
    monkeypatch.setattr(f.queue, "_append_event", append)
    result = f.entry.handle(f.command)
    assert result.budget_settlement_sha256 is not None
    assert f.repository.get(before.id).status is TaskStatus.BLOCKED


def test_no_public_success_before_transaction_commits(real_wait: RealWait) -> None:
    f = real_wait
    settlement = f.entry.budget_settlement
    assert settlement is not None
    original = settlement.idle_scope

    @contextmanager
    def interrupted_commit() -> Iterator[DictCursor]:
        with original() as cursor:
            yield cursor
            raise RuntimeError("test failure immediately before commit")

    before = f.repository.get(f.queue.get(f.command.work_item_id).task_id)
    events = f.repository.list_events(before.id)
    settlement.idle_scope = interrupted_commit
    with pytest.raises(RuntimeError, match="before commit"):
        f.entry.handle(f.command)
    assert f.repository.get(before.id) == before
    assert f.repository.list_events(before.id) == events
    assert not f.entry.records.list("wait-handlings", DeliveryWaitHandling)
    settlement.idle_scope = original
    result = f.entry.handle(f.command)
    assert result.budget_settlement_sha256 is not None
    assert f.entry.records.list("wait-handlings", DeliveryWaitHandling) == (result,)
