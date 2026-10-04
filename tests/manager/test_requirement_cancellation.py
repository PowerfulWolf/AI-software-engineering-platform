"""Explicit deletion cancels stopped legacy work with exact, replayable receipts."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import jsonschema
import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.domain import Task, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.workforce import TaskLease
from ai_software_engineer.multi_directory.cancellation import (
    FileRequirementCancellationStore,
    RequirementCancellationReceipt,
    RequirementCancellationRejected,
    RequirementCancellationService,
    RequirementCancellationTarget,
)
from ai_software_engineer.multi_directory.deletion import (
    ProductionRequirementDeletionGuard,
    RequirementDeletionRejected,
)
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.orchestration.state_machine import TERMINAL_STATUSES, apply_event
from ai_software_engineer.store.mysql_repository import MySqlTaskRepository
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.models import QueuedWorkItem
from tests.domain.factories import make_task
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_requirement_deletion import _delete, _delivery
from tests.work_queue.test_mysql_queue import queued_item


class _Cursor:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository
        self.task_id = ""

    def execute(self, query: str, parameters: tuple[str]) -> None:
        self.task_id = parameters[0]

    def fetchone(self) -> dict[str, object]:
        task = self.repository.get(self.task_id)
        return {
            "id": task.id,
            "payload_json": task.model_dump_json(),
            "status": self.repository.indexed_status.get(task.id, task.status.value),
            "revision": self.repository.current_revision(task.id),
        }


class _Repository:
    def __init__(self, *tasks: Task) -> None:
        self.tasks = {task.id: task for task in tasks}
        self.events: dict[str, tuple[StateEvent, ...]] = {task.id: () for task in tasks}
        self.indexed_status: dict[str, str] = {}
        self.mutation_fence: Callable[[DictCursor, str], None] | None = None
        self.before_append: Callable[[], None] | None = None

    def get(self, task_id: str) -> Task:
        return self.tasks[task_id]

    def list_events(self, task_id: str) -> tuple[StateEvent, ...]:
        return self.events[task_id]

    def current_revision(self, task_id: str) -> int:
        return len(self.events[task_id])

    def append_event(self, event: StateEvent) -> None:
        if self.before_append is not None:
            callback, self.before_append = self.before_append, None
            callback()
        cursor = cast(DictCursor, _Cursor(self))
        assert self.mutation_fence is not None
        self.mutation_fence(cursor, event.task_id)
        if event in self.events[event.task_id]:
            return
        self.tasks[event.task_id] = apply_event(self.get(event.task_id), event)
        self.events[event.task_id] = (*self.events[event.task_id], event)
        self.mutation_fence(cursor, event.task_id)

    def close(self) -> None:
        pass

    def __enter__(self) -> _Repository:
        return self

    def __exit__(self, *_args: object) -> None:
        pass


class _Queue:
    def __init__(self, *items: QueuedWorkItem) -> None:
        self.items = {item.id: item for item in items}
        self.leases: tuple[TaskLease, ...] = ()
        self.receipts: dict[str, str] = {}
        self.close_calls = 0
        self.fail_close: bool = False
        self.fail_close_on_call: int | None = None

    def items_for_task(self, task_id: str) -> tuple[QueuedWorkItem, ...]:
        return tuple(item for item in self.items.values() if item.task_id == task_id)

    def list_active_leases(self, *, now: datetime) -> tuple[TaskLease, ...]:
        return tuple(lease for lease in self.leases if lease.expires_at > now)

    def cancellation_fence(self, cursor: DictCursor, task_id: str) -> None:
        if any(
            lease.task_id == task_id for lease in self.list_active_leases(now=datetime.now(UTC))
        ):
            raise RequirementCancellationRejected("有效执行许可禁止取消。")

    def verify_cancelled_inventory(
        self,
        cursor: DictCursor,
        task: Task,
        expected_items: tuple[QueuedWorkItem, ...],
        *,
        cancellation_sha256: str,
        now: datetime,
    ) -> tuple[QueuedWorkItem, ...]:
        actual = tuple(sorted(self.items_for_task(task.id), key=lambda item: item.id))
        if len(actual) != len(expected_items):
            raise RequirementCancellationRejected("工程队列范围已变化。")
        for before, after in zip(expected_items, actual, strict=True):
            if before == after:
                continue
            closed = before.model_copy(
                update={
                    "status": WorkItemStatus.CLOSED,
                    "updated_at": now,
                    "wait_reason": None,
                    "available_at": None,
                }
            )
            if after != closed or self.receipts.get(before.id) != cancellation_sha256:
                raise RequirementCancellationRejected("工程队列事实已变化。")
        return actual

    def close_cancelled_task(
        self,
        task: Task,
        *,
        expected_items: tuple[QueuedWorkItem, ...],
        cancellation_sha256: str,
        now: datetime,
    ) -> tuple[QueuedWorkItem, ...]:
        self.close_calls += 1
        if self.fail_close or self.close_calls == self.fail_close_on_call:
            self.fail_close = False
            self.fail_close_on_call = None
            raise RuntimeError("crash before queue settlement")
        assert task.status in TERMINAL_STATUSES
        actual = self.verify_cancelled_inventory(
            cast(DictCursor, None),
            task,
            expected_items,
            cancellation_sha256=cancellation_sha256,
            now=now,
        )
        for item in actual:
            if item.status is not WorkItemStatus.CLOSED:
                self.items[item.id] = item.model_copy(
                    update={
                        "status": WorkItemStatus.CLOSED,
                        "updated_at": now,
                        "wait_reason": None,
                        "available_at": None,
                    }
                )
                self.receipts[item.id] = cancellation_sha256
        return self.items_for_task(task.id)


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, status: TaskStatus = TaskStatus.IMPLEMENTING
) -> tuple[
    JointCheckpoint,
    _Repository,
    _Queue,
    RequirementCancellationService,
    tuple[RequirementCancellationTarget, ...],
]:
    service, checkpoint, _, _, _ = _delivery(tmp_path, monkeypatch)
    child = checkpoint.children[0].checkpoint
    assert child.task_id is not None
    task = make_task().model_copy(
        update={
            "id": child.task_id,
            "repository": child.repository_root,
            "status": status,
            "attempts": 1,
        }
    )
    item = queued_item().model_copy(
        update={
            "task_id": task.id,
            "repository_id": child.repository_id,
            "repository_scopes": (task.repository,),
            "status": WorkItemStatus.RETRY_SCHEDULED,
            "available_at": datetime.now(UTC),
            "wait_reason": "lease_expired",
        }
    )
    repository, queue = _Repository(task), _Queue(item)
    store = FileRequirementCancellationStore(
        service.project.requirements_root / checkpoint.delivery_id
    )
    cancellation = RequirementCancellationService(repository, queue, store)
    return (
        checkpoint,
        repository,
        queue,
        cancellation,
        (RequirementCancellationTarget(task=task, repository_id=child.repository_id),),
    )


def test_exact_cancellation_preserves_old_snapshot_and_closes_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint, repository, queue, service, targets = _fixture(tmp_path, monkeypatch)
    original = targets[0].task
    receipt = service.cancel(checkpoint, targets)
    assert receipt.human_action.action == "DELETE_REQUIREMENT"
    assert receipt.human_action.actor == "operator:local-console"
    assert receipt.tasks[0].task == original
    assert repository.get(original.id).status is TaskStatus.BLOCKED
    assert len(repository.list_events(original.id)) == 1
    assert receipt.uri in repository.list_events(original.id)[0].reason
    assert repository.list_events(original.id)[0].artifact_ids == ()
    assert all(item.status is WorkItemStatus.CLOSED for item in queue.items.values())
    assert service.records.path == service.records.requirement_root / "cancellations/receipt.json"
    assert not (service.records.requirement_root / "cancellation.json").exists()
    schema = json.loads(Path("schemas/requirement-cancellation.schema.json").read_text())
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        receipt.model_dump(mode="json")
    )


@pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED])
def test_terminal_task_keeps_snapshot_and_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: TaskStatus
) -> None:
    checkpoint, repository, _, service, targets = _fixture(tmp_path, monkeypatch, status=status)
    service.cancel(checkpoint, targets)
    assert repository.get(targets[0].task.id) == targets[0].task
    assert repository.list_events(targets[0].task.id) == ()


def test_new_task_uses_existing_failed_edge_without_new_state_machine_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint, repository, _, service, targets = _fixture(
        tmp_path, monkeypatch, status=TaskStatus.NEW
    )
    service.cancel(checkpoint, targets)
    assert repository.get(targets[0].task.id).status is TaskStatus.FAILED


def test_task_event_before_queue_crash_restarts_without_duplicate_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint, repository, queue, service, targets = _fixture(tmp_path, monkeypatch)
    queue.fail_close = True
    with pytest.raises(RuntimeError, match="crash before queue"):
        service.cancel(checkpoint, targets)
    original_bytes = service.records.path.read_bytes()
    assert len(repository.list_events(targets[0].task.id)) == 1
    restarted = RequirementCancellationService(
        repository, queue, FileRequirementCancellationStore(service.records.requirement_root)
    )
    receipt = restarted.cancel(checkpoint, targets)
    assert service.records.path.read_bytes() == original_bytes
    assert len(repository.list_events(targets[0].task.id)) == 1
    restarted.cancel(checkpoint, targets)
    assert service.records.path.read_bytes() == original_bytes
    assert queue.receipts == {item.id: receipt.cancellation_sha256 for item in queue.items.values()}
    assert len(repository.list_events(targets[0].task.id)) == 1


def test_receipt_only_crash_can_replay_and_other_snapshot_drift_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint, repository, _, service, targets = _fixture(tmp_path, monkeypatch)
    repository.before_append = lambda: (_ for _ in ()).throw(RuntimeError("after receipt"))
    with pytest.raises(RuntimeError, match="after receipt"):
        service.cancel(checkpoint, targets)
    assert repository.get(targets[0].task.id) == targets[0].task
    repository.tasks[targets[0].task.id] = targets[0].task.model_copy(update={"attempts": 2})
    with pytest.raises(RequirementCancellationRejected, match="任务或事件已变化"):
        service.cancel(checkpoint, targets)
    repository.tasks[targets[0].task.id] = targets[0].task
    service.cancel(checkpoint, targets)
    assert len(repository.list_events(targets[0].task.id)) == 1


def test_multi_task_partial_settlement_replays_closed_first_queue_and_open_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint, repository, queue, service, targets = _fixture(tmp_path, monkeypatch)
    second = targets[0].task.model_copy(update={"id": "task_second_cancel"})
    repository.tasks[second.id] = second
    repository.events[second.id] = ()
    item = next(iter(queue.items.values())).model_copy(
        update={"id": "work_second_cancel", "task_id": second.id}
    )
    queue.items[item.id] = item
    complete_scope = (
        *targets,
        RequirementCancellationTarget(task=second, repository_id=targets[0].repository_id),
    )
    queue.fail_close_on_call = 2
    with pytest.raises(RuntimeError, match="crash before queue"):
        service.cancel(checkpoint, complete_scope)
    assert queue.items_for_task(targets[0].task.id)[0].status is WorkItemStatus.CLOSED
    assert queue.items_for_task(second.id)[0].status is WorkItemStatus.RETRY_SCHEDULED
    first_receipt = service.records.path.read_bytes()
    service.cancel(checkpoint, complete_scope)
    assert service.records.path.read_bytes() == first_receipt
    assert all(item.status is WorkItemStatus.CLOSED for item in queue.items.values())
    assert all(len(events) == 1 for events in repository.events.values())


def test_late_claim_is_rejected_and_preserved_without_task_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint, repository, queue, service, targets = _fixture(tmp_path, monkeypatch)
    now = datetime.now(UTC)
    lease = TaskLease(
        id="lease_cancel_race",
        assignment_id="assignment_cancel_race",
        task_id=targets[0].task.id,
        agent_id="agent_cancel_race",
        acquired_at=now,
        expires_at=now + timedelta(minutes=1),
    )
    repository.before_append = lambda: setattr(queue, "leases", (lease,))
    with pytest.raises(RequirementCancellationRejected, match="有效执行许可"):
        service.cancel(checkpoint, targets)
    assert queue.leases == (lease,)
    assert repository.list_events(targets[0].task.id) == ()
    assert queue.close_calls == 0


def test_spoofed_closed_queue_without_receipt_event_cannot_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint, repository, queue, service, targets = _fixture(tmp_path, monkeypatch)
    service.cancel(checkpoint, targets)
    queue.receipts.clear()
    with pytest.raises(RequirementCancellationRejected, match="工程队列事实已变化"):
        service.cancel(checkpoint, targets)
    assert len(repository.list_events(targets[0].task.id)) == 1


@pytest.mark.parametrize("change", ["scope", "indexed_status", "queue"])
def test_late_mutation_is_rejected_by_fence_before_task_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    checkpoint, repository, queue, service, targets = _fixture(tmp_path, monkeypatch)
    task_id = targets[0].task.id

    def mutate() -> None:
        if change == "indexed_status":
            repository.indexed_status[task_id] = "QA"
        else:
            item = next(iter(queue.items.values()))
            update: dict[str, object] = (
                {"id": "work_extra_drift"} if change == "scope" else {"priority": 1}
            )
            changed = item.model_copy(update=update)
            queue.items[changed.id] = changed

    repository.before_append = mutate
    with pytest.raises(RequirementCancellationRejected):
        service.cancel(checkpoint, targets)
    assert repository.get(task_id) == targets[0].task
    assert repository.list_events(task_id) == ()
    assert queue.close_calls == 0


def test_all_scope_preflight_precedes_receipt_or_any_task_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint, repository, queue, service, targets = _fixture(tmp_path, monkeypatch)
    second = targets[0].task.model_copy(update={"id": "task_second_cancel"})
    repository.tasks[second.id] = second
    repository.events[second.id] = ()
    bad_item = next(iter(queue.items.values())).model_copy(
        update={
            "id": "work_second_cancel",
            "task_id": second.id,
            "repository_id": "repository_wrong",
        }
    )
    queue.items[bad_item.id] = bad_item
    with pytest.raises(RequirementCancellationRejected, match="归属无法核验"):
        service.cancel(
            checkpoint,
            (
                *targets,
                RequirementCancellationTarget(task=second, repository_id=targets[0].repository_id),
            ),
        )
    assert not service.records.path.exists()
    assert all(not events for events in repository.events.values())


def test_receipt_wrong_checkpoint_cannot_be_reused_or_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint, _, _, service, targets = _fixture(tmp_path, monkeypatch)
    receipt = service.cancel(checkpoint, targets)
    original_bytes = service.records.path.read_bytes()
    with pytest.raises(RequirementCancellationRejected, match="归属或范围已变化"):
        service.cancel(checkpoint.model_copy(update={"checkpoint_sha256": "f" * 64}), targets)
    changed = RequirementCancellationReceipt.seal(
        **{
            **receipt.model_dump(mode="json", exclude={"cancellation_sha256"}),
            "project_manifest_sha256": "f" * 64,
        }
    )
    with pytest.raises(RequirementCancellationRejected, match="已有取消记录"):
        service.records.put(changed)
    assert service.records.path.read_bytes() == original_bytes


def test_public_delete_settles_legacy_task_and_preserves_checkpoint_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform, checkpoint, _, dirty, _ = _delivery(tmp_path, monkeypatch)
    child = checkpoint.children[0].checkpoint
    assert child.task_id is not None
    task = make_task().model_copy(
        update={
            "id": child.task_id,
            "repository": child.repository_root,
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 1,
        }
    )
    item = queued_item().model_copy(
        update={
            "task_id": task.id,
            "repository_id": child.repository_id,
            "repository_scopes": (task.repository,),
            "status": WorkItemStatus.RETRY_SCHEDULED,
            "wait_reason": "lease_expired",
            "available_at": datetime.now(UTC),
        }
    )
    repository, queue = _Repository(task), _Queue(item)
    guard = ProductionRequirementDeletionGuard(platform.project, queue, "unused")
    monkeypatch.setattr(
        guard,
        "_read_tasks",
        lambda targets: {task_id: repository.get(task_id) for task_id in targets},
    )
    monkeypatch.setattr(
        "ai_software_engineer.multi_directory.deletion.MySqlTaskRepository", lambda dsn: repository
    )
    platform.deletion_guard = guard
    history = platform.journal.history(checkpoint.delivery_id)
    _delete(platform, checkpoint)
    assert platform.journal.history(checkpoint.delivery_id) == history
    assert platform.retirements.entry(checkpoint.delivery_id) is not None
    assert repository.get(task.id).status is TaskStatus.BLOCKED
    assert (dirty / "draft.txt").read_text() == "uncommitted business draft\n"
    _delete(platform, checkpoint)
    assert len(repository.list_events(task.id)) == 1


def test_production_guard_rejects_valid_lease_before_writer_or_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform, checkpoint, _, _, _ = _delivery(tmp_path, monkeypatch)
    child = checkpoint.children[0].checkpoint
    assert child.task_id is not None
    queue = _Queue()
    now = datetime.now(UTC)
    queue.leases = (
        TaskLease(
            id="lease_cancel_active",
            assignment_id="assignment_cancel_active",
            task_id=child.task_id,
            agent_id="agent_cancel_active",
            acquired_at=now,
            expires_at=now + timedelta(minutes=1),
        ),
    )
    platform.deletion_guard = ProductionRequirementDeletionGuard(platform.project, queue, "unused")
    with pytest.raises(RequirementDeletionRejected, match="有效的工程执行许可"):
        _delete(platform, checkpoint)
    assert not platform.retirements.retirement().entries
    assert not (
        platform.project.requirements_root / checkpoint.delivery_id / "cancellations"
    ).exists()


@pytest.mark.mysql
def test_public_delete_real_queue_settles_nonterminal_and_retains_immutable_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mysql_dsn: str
) -> None:
    platform, checkpoint, sidecar, dirty, _ = _delivery(tmp_path, monkeypatch, dsn=mysql_dsn)
    child = checkpoint.children[0].checkpoint
    assert child.task_id is not None
    task = make_task().model_copy(
        update={
            "id": child.task_id,
            "repository": child.repository_root,
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 1,
        }
    )
    with MySqlTaskRepository(mysql_dsn) as repository:
        repository.create(task)
    queue = MySqlRoleQueue(mysql_dsn)
    queue.enqueue(
        queued_item().model_copy(
            update={
                "task_id": task.id,
                "repository_id": child.repository_id,
                "repository_scopes": (task.repository,),
                "status": WorkItemStatus.RETRY_SCHEDULED,
                "wait_reason": "lease_expired",
                "available_at": datetime.now(UTC),
            }
        )
    )
    platform.deletion_guard = ProductionRequirementDeletionGuard(platform.project, queue, mysql_dsn)
    parent_history = platform.journal.history(checkpoint.delivery_id)
    native_bytes = tuple(
        (p.name, p.read_bytes())
        for p in sorted((sidecar / "state/project-deliveries" / child.delivery_id).glob("*.json"))
    )
    _delete(platform, checkpoint)
    _delete(platform, checkpoint)
    assert platform.journal.history(checkpoint.delivery_id) == parent_history
    assert (
        tuple(
            (p.name, p.read_bytes())
            for p in sorted(
                (sidecar / "state/project-deliveries" / child.delivery_id).glob("*.json")
            )
        )
        == native_bytes
    )
    assert (dirty / "draft.txt").read_text() == "uncommitted business draft\n"
    assert platform.retirements.entry(checkpoint.delivery_id) is not None
    assert platform.retirements.retired_delivery_ids(platform.journal) == frozenset(
        {checkpoint.delivery_id}
    )
    receipt = FileRequirementCancellationStore(
        platform.project.requirements_root / checkpoint.delivery_id
    ).find()
    assert receipt is not None and receipt.tasks[0].task == task
    assert all(item.status is WorkItemStatus.CLOSED for item in queue.items_for_task(task.id))
    with MySqlTaskRepository(mysql_dsn) as repository:
        assert repository.get(task.id).status is TaskStatus.BLOCKED
        events = repository.list_events(task.id)
        assert len(events) == 1
        assert receipt.uri in events[0].reason
