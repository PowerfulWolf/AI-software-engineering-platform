"""Explicit requirement deletion closes abandoned work without executing a Run."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.domain import AgentRole, RiskTier, Task, TaskStatus, WorkItemStatus
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
    WorkforceFacts,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueConflict, QueueCorruption
from tests.domain.factories import make_task
from tests.work_queue.test_mysql_queue import OWNER_TOKEN, dispatcher

pytestmark = pytest.mark.mysql

NOW = datetime(2026, 10, 5, 5, 0, tzinfo=UTC)
BEFORE = NOW - timedelta(minutes=1)
CANCELLATION_SHA = "c" * 64
REPOSITORY_ID = "repository_cancellation_test"


@pytest.fixture
def mysql_dsn() -> str:
    value = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not value:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    return value


@pytest.fixture
def queue(mysql_dsn: str) -> MySqlRoleQueue:
    return MySqlRoleQueue(mysql_dsn, clock=lambda: NOW)


@pytest.fixture
def repository(mysql_dsn: str) -> Iterator[MySqlTaskRepository]:
    with MySqlTaskRepository(mysql_dsn) as store:
        yield store


def _task(status: TaskStatus = TaskStatus.BLOCKED) -> Task:
    return make_task().model_copy(
        update={
            "repository": "/fixture/repository",
            "status": status,
            "attempts": 1,
            "updated_at": BEFORE,
        }
    )


def _item(task: Task, *, checkpoint: int = 0, scope: str | None = None) -> QueuedWorkItem:
    return QueuedWorkItem(
        id=f"work_cancellation_coder_{checkpoint}",
        task_id=task.id,
        repository_id=REPOSITORY_ID,
        role=AgentRole.CODER,
        attempt=1,
        checkpoint_sequence=checkpoint,
        repository_scopes=(scope or task.repository,),
        status=WorkItemStatus.READY,
        priority=750,
        risk=RiskTier.NORMAL,
        required_capabilities=("delivery",),
        created_at=NOW - timedelta(minutes=30),
        updated_at=NOW - timedelta(minutes=30),
    )


def _admit(queue: MySqlRoleQueue, task: Task) -> QueuedWorkItem:
    item = _item(task)
    queue.admit(
        RoleQueueAdmission(
            task_id=task.id,
            repository_id=REPOSITORY_ID,
            allocation_sha256="a" * 64,
            legacy_artifacts=(),
        ),
        QueuedRoleStep(
            work_item=item,
            boundary=RoleRunBoundary(task.id, AgentRole.CODER, 1, 0, task.base_ref),
            allocation_sha256="a" * 64,
        ),
    )
    return item


def _claim(queue: MySqlRoleQueue, *, now: datetime = BEFORE) -> QueueClaim:
    tick = dispatcher(queue, "worker_requirement_cancel").tick(now=now)
    assert tick.claim is not None
    return tick.claim


def _facts(mysql_dsn: str) -> dict[str, tuple[Mapping[str, object], ...]]:
    with (
        closing(open_mysql_connection(mysql_dsn)) as connection,
        connection.cursor(DictCursor) as cursor,
    ):
        facts: dict[str, tuple[Mapping[str, object], ...]] = {}
        for table in ("work_queue_items", "work_queue_claims", "work_queue_events"):
            cursor.execute(f"SELECT * FROM {table}")
            facts[table] = tuple(cursor.fetchall())
        return facts


def test_cancel_retry_preserves_history_and_replays_without_new_claim(
    mysql_dsn: str, queue: MySqlRoleQueue, repository: MySqlTaskRepository
) -> None:
    task = _task()
    repository.create(task)
    item = _admit(queue, task)
    claim = _claim(queue)
    retry = queue.retry(
        item.id,
        lease_id=claim.lease.id,
        owner_token=OWNER_TOKEN,
        reason="旧执行因提供方中断等待重试",
        now=BEFORE + timedelta(seconds=1),
        available_at=NOW + timedelta(minutes=5),
    )
    before = _facts(mysql_dsn)
    result = queue.close_cancelled_task(
        task, expected_items=(retry,), cancellation_sha256=CANCELLATION_SHA, now=NOW
    )
    assert len(result) == 1
    assert result[0].status is WorkItemStatus.CLOSED
    assert result[0].wait_reason is None and result[0].available_at is None
    assert result[0].dispatch_sequence == retry.dispatch_sequence
    assert queue.list_schedulable(now=NOW + timedelta(hours=1)) == ()
    after = _facts(mysql_dsn)
    assert after["work_queue_claims"] == before["work_queue_claims"]
    assert after["work_queue_events"][:-1] == before["work_queue_events"]
    last = after["work_queue_events"][-1]
    assert last["event_type"] == "REQUIREMENT_CANCELLED"
    assert last["from_status"] == "RETRY_SCHEDULED"
    assert isinstance(last["payload_json"], str)
    payload = json.loads(last["payload_json"])
    assert payload["detail"]["cancellation_sha256"] == CANCELLATION_SHA
    assert payload["detail"]["previous_work_item"] == retry.to_wire()
    reopened = MySqlRoleQueue(mysql_dsn, clock=lambda: NOW + timedelta(seconds=1))
    assert (
        reopened.close_cancelled_task(
            task, expected_items=(retry,), cancellation_sha256=CANCELLATION_SHA, now=NOW
        )
        == result
    )
    assert _facts(mysql_dsn) == after
    assert repository.get(task.id) == task
    assert repository.list_events(task.id) == ()


@pytest.mark.parametrize("status", [TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.DONE])
def test_all_terminal_task_states_accept_cancellation(
    queue: MySqlRoleQueue, repository: MySqlTaskRepository, status: TaskStatus
) -> None:
    task = _task(status)
    repository.create(task)
    item = _admit(queue, task)
    result = queue.close_cancelled_task(
        task, expected_items=(item,), cancellation_sha256=CANCELLATION_SHA, now=NOW
    )
    assert all(item.status is WorkItemStatus.CLOSED for item in result)
    assert queue.list_assignments() == ()
    assert repository.get(task.id) == task


@pytest.mark.parametrize("wrong_snapshot", [False, True])
def test_nonterminal_or_changed_task_snapshot_refuses_without_mutation(
    mysql_dsn: str,
    queue: MySqlRoleQueue,
    repository: MySqlTaskRepository,
    wrong_snapshot: bool,
) -> None:
    task = _task(TaskStatus.BLOCKED if wrong_snapshot else TaskStatus.IMPLEMENTING)
    repository.create(task)
    item = _admit(queue, task)
    supplied = (
        task.model_copy(update={"repository": "/other/repository"}) if wrong_snapshot else task
    )
    before = _facts(mysql_dsn)
    with pytest.raises(QueueConflict):
        queue.close_cancelled_task(
            supplied, expected_items=(item,), cancellation_sha256=CANCELLATION_SHA, now=NOW
        )
    assert _facts(mysql_dsn) == before
    assert repository.get(task.id) == task


def test_valid_lease_refuses_queue_close_and_task_mutation(
    mysql_dsn: str, queue: MySqlRoleQueue, repository: MySqlTaskRepository
) -> None:
    task = _task()
    repository.create(task)
    _admit(queue, task)
    _claim(queue)
    expected = queue.items_for_task(task.id)
    before = _facts(mysql_dsn)
    with pytest.raises(QueueConflict, match="有效执行租约"):
        queue.close_cancelled_task(
            task, expected_items=expected, cancellation_sha256=CANCELLATION_SHA, now=NOW
        )
    repository.mutation_fence = queue.cancellation_fence
    with pytest.raises(QueueConflict, match="有效执行租约"):
        repository.record_attempt(task.id, 2)
    assert repository.get(task.id) == task
    assert _facts(mysql_dsn) == before


def test_expired_owner_is_fenced_without_claiming_a_successor(
    mysql_dsn: str, queue: MySqlRoleQueue, repository: MySqlTaskRepository
) -> None:
    task = _task()
    repository.create(task)
    _admit(queue, task)
    claim = _claim(queue, now=NOW - timedelta(minutes=15))
    assert claim.lease.expires_at == NOW
    before = _facts(mysql_dsn)
    closed = queue.close_cancelled_task(
        task,
        expected_items=(claim.work_item,),
        cancellation_sha256=CANCELLATION_SHA,
        now=NOW,
    )
    after = _facts(mysql_dsn)
    assert len(after["work_queue_claims"]) == len(before["work_queue_claims"]) == 1
    assert after["work_queue_claims"][0]["state"] == "EXPIRED"
    assert after["work_queue_claims"][0]["ended_at"] == NOW.isoformat()
    assert closed[0].status is WorkItemStatus.CLOSED
    assert closed[0].dispatch_sequence == claim.work_item.dispatch_sequence
    assert queue.list_active_leases(now=NOW) == ()
    assert queue.list_schedulable(now=NOW) == ()
    with pytest.raises(QueueConflict):
        queue.start(closed[0].id, lease_id=claim.lease.id, owner_token=OWNER_TOKEN, now=NOW)


def test_wrong_repository_scope_rolls_back_all_queue_items(
    mysql_dsn: str, queue: MySqlRoleQueue, repository: MySqlTaskRepository
) -> None:
    task = _task()
    repository.create(task)
    item = _admit(queue, task)
    queue.enqueue(_item(task, checkpoint=1, scope="/other/repository"))
    before = _facts(mysql_dsn)
    with pytest.raises(QueueCorruption, match="任务仓库"):
        queue.close_cancelled_task(
            task, expected_items=(item,), cancellation_sha256=CANCELLATION_SHA, now=NOW
        )
    assert _facts(mysql_dsn) == before


def test_different_cancellation_receipt_cannot_replace_first_fact(
    mysql_dsn: str, queue: MySqlRoleQueue, repository: MySqlTaskRepository
) -> None:
    task = _task()
    repository.create(task)
    item = _admit(queue, task)
    queue.close_cancelled_task(
        task, expected_items=(item,), cancellation_sha256=CANCELLATION_SHA, now=NOW
    )
    before = _facts(mysql_dsn)
    with pytest.raises(QueueConflict, match="另一份删除凭据"):
        queue.close_cancelled_task(
            task, expected_items=(item,), cancellation_sha256="d" * 64, now=NOW
        )
    assert _facts(mysql_dsn) == before


def test_cancellation_fence_allows_audited_task_end_after_expiry(
    mysql_dsn: str, queue: MySqlRoleQueue, repository: MySqlTaskRepository
) -> None:
    task = _task(TaskStatus.IMPLEMENTING)
    repository.create(task)
    _admit(queue, task)
    _claim(queue, now=NOW - timedelta(minutes=15))
    expected = queue.items_for_task(task.id)
    repository.mutation_fence = queue.cancellation_fence
    event = build_event(
        task,
        TaskStatus.BLOCKED,
        event_id="evt_requirement_cancelled",
        reason=f"用户删除需求, 停止旧交付; 取消凭据 {CANCELLATION_SHA}",
        source_revision=task.base_ref,
        attempt=task.attempts,
        occurred_at=NOW,
    )
    repository.append_event(event)
    terminal = repository.get(task.id)
    assert terminal.status is TaskStatus.BLOCKED
    assert repository.list_events(task.id) == (event,)
    queue.close_cancelled_task(
        terminal, expected_items=expected, cancellation_sha256=CANCELLATION_SHA, now=NOW
    )
    assert repository.list_events(task.id) == (event,)
    assert len(_facts(mysql_dsn)["work_queue_claims"]) == 1


def test_external_valid_lease_refuses_cancellation_fence(
    mysql_dsn: str, queue: MySqlRoleQueue, repository: MySqlTaskRepository
) -> None:
    task = _task()
    repository.create(task)
    _admit(queue, task)
    claim = _claim(queue)
    queue.retry(
        claim.work_item.id,
        lease_id=claim.lease.id,
        owner_token=OWNER_TOKEN,
        reason="已停止队列, 但仍需核对旧执行器",
        now=BEFORE + timedelta(seconds=1),
        available_at=NOW + timedelta(minutes=1),
    )
    external = MySqlRoleQueue(
        mysql_dsn,
        clock=lambda: NOW,
        capacity_reader=lambda cursor, now: WorkforceFacts(leases=(claim.lease,)),
    )
    repository.mutation_fence = external.cancellation_fence
    before = _facts(mysql_dsn)
    with pytest.raises(QueueConflict, match="有效执行租约"):
        repository.record_attempt(task.id, 2)
    with pytest.raises(QueueConflict, match="有效执行租约"):
        external.close_cancelled_task(
            task,
            expected_items=queue.items_for_task(task.id),
            cancellation_sha256=CANCELLATION_SHA,
            now=NOW,
        )
    assert repository.get(task.id) == task
    assert _facts(mysql_dsn) == before


def _drift_inventory(
    queue: MySqlRoleQueue, task: Task, *, additional_item: bool
) -> tuple[QueuedWorkItem, ...]:
    item = _admit(queue, task)
    if additional_item:
        queue.enqueue(_item(task, checkpoint=1))
        return (item,)
    claim = _claim(queue)
    original = queue.retry(
        item.id,
        lease_id=claim.lease.id,
        owner_token=OWNER_TOKEN,
        reason="旧运行等待重试",
        now=BEFORE + timedelta(seconds=1),
        available_at=NOW + timedelta(minutes=1),
    )
    queue.make_ready(item.id, now=BEFORE + timedelta(seconds=2))
    return (original,)


@pytest.mark.parametrize("additional_item", [False, True])
def test_queue_close_refuses_inventory_drift_after_receipt(
    mysql_dsn: str,
    queue: MySqlRoleQueue,
    repository: MySqlTaskRepository,
    additional_item: bool,
) -> None:
    task = _task()
    repository.create(task)
    expected = _drift_inventory(queue, task, additional_item=additional_item)
    before = _facts(mysql_dsn)
    with pytest.raises(QueueConflict, match="删除凭据封存后的队列"):
        queue.close_cancelled_task(
            task, expected_items=expected, cancellation_sha256=CANCELLATION_SHA, now=NOW
        )
    assert _facts(mysql_dsn) == before
    assert repository.get(task.id) == task


@pytest.mark.parametrize("additional_item", [False, True])
def test_task_cancellation_fence_refuses_unclaimed_inventory_drift(
    mysql_dsn: str,
    queue: MySqlRoleQueue,
    repository: MySqlTaskRepository,
    additional_item: bool,
) -> None:
    task = _task(TaskStatus.IMPLEMENTING)
    repository.create(task)
    expected = _drift_inventory(queue, task, additional_item=additional_item)

    def fence(cursor: DictCursor, task_id: str) -> None:
        assert task_id == task.id
        queue.cancellation_fence(cursor, task_id)
        queue.verify_cancelled_inventory(
            cursor, task, expected, cancellation_sha256=CANCELLATION_SHA, now=NOW
        )

    repository.mutation_fence = fence
    event = build_event(
        task,
        TaskStatus.BLOCKED,
        event_id="evt_cancel_drift_refused",
        reason="用户请求删除旧需求",
        source_revision=task.base_ref,
        attempt=task.attempts,
        occurred_at=NOW,
    )
    before = _facts(mysql_dsn)
    with pytest.raises(QueueConflict, match="删除凭据封存后的队列"):
        repository.append_event(event)
    assert repository.get(task.id) == task
    assert repository.list_events(task.id) == ()
    assert repository.current_revision(task.id) == 0
    assert _facts(mysql_dsn) == before


def test_closed_successor_requires_the_same_receipt_event(
    mysql_dsn: str, queue: MySqlRoleQueue, repository: MySqlTaskRepository
) -> None:
    task = _task()
    repository.create(task)
    _admit(queue, task)
    claim = _claim(queue)
    queue.complete(
        claim.work_item.id,
        lease_id=claim.lease.id,
        owner_token=OWNER_TOKEN,
        artifacts=(),
        next_work_item=None,
        now=NOW,
    )
    before = _facts(mysql_dsn)
    with pytest.raises(QueueConflict, match="删除凭据封存后的队列事实"):
        queue.close_cancelled_task(
            task,
            expected_items=(claim.work_item,),
            cancellation_sha256=CANCELLATION_SHA,
            now=NOW,
        )
    assert _facts(mysql_dsn) == before
