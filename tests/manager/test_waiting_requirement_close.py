"""Exact user close settles stopped engineering waits before product deletion."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest

from ai_software_engineer.domain import AgentRole, Task, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    DeliveryResponsibility,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.workforce import TaskLease
from ai_software_engineer.manager.delivery import DeliveryCheckpointStale
from ai_software_engineer.multi_directory.cancellation import (
    FileRequirementCancellationStore,
    RequirementCancellationReceipt,
)
from ai_software_engineer.multi_directory.deletion import (
    ProductionRequirementDeletionGuard,
    RequirementDeletionRejected,
    _task_lock,
)
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.service import (
    CloseRequirement,
    JointDeliveryService,
    RestartRequirement,
)
from ai_software_engineer.orchestration.state_machine import apply_event, build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
)
from ai_software_engineer.work_queue.models import QueuedWorkItem
from tests.domain.factories import make_task
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_requirement_cancellation import _Queue, _Repository
from tests.manager.test_requirement_deletion import _delete, _delivery
from tests.work_queue.test_mysql_queue import queued_item


def _waiting_item(task: Task, repository_id: str, *, revision: int = 2) -> QueuedWorkItem:
    item = queued_item().model_copy(
        update={
            "task_id": task.id,
            "repository_id": repository_id,
            "repository_scopes": (task.repository,),
            "checkpoint_sequence": revision,
            "status": WorkItemStatus.WAITING_DEPENDENCY,
            "available_at": None,
        }
    )
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts(
            task_id=task.id,
            work_item_id=item.id,
            role=item.role,
            classification="ENVIRONMENT_UNAVAILABLE",
            task_intent_sha256=task_intent_sha256(task),
            source_revision=task.base_ref,
            checkpoint_sequence=revision,
            budget_available=True,
        )
    )
    return QueuedWorkItem.model_validate(
        {
            **item.to_wire(),
            "wait_disposition": disposition.to_wire(),
            "wait_reason": disposition.reason,
        }
    )


def _implementing(task: Task) -> tuple[Task, tuple[StateEvent, ...]]:
    current = task.model_copy(update={"status": TaskStatus.NEW})
    events = []
    for index, status in enumerate((TaskStatus.PLANNING, TaskStatus.IMPLEMENTING)):
        event = build_event(
            current,
            status,
            event_id=f"evt_wait_close_{index}",
            source_revision=task.base_ref,
            reason="fixture state transition",
            occurred_at=task.updated_at + timedelta(seconds=index + 1),
        )
        current = apply_event(current, event)
        events.append(event)
    return current, tuple(events)


def _waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[JointDeliveryService, JointCheckpoint, _Repository, _Queue, Path]:
    platform, blocked, sidecar, _, _ = _delivery(tmp_path, monkeypatch)
    checkpoint = platform._save(
        blocked, stage=JointStage.DELIVERING, next_action="Engineering wait"
    )
    child = checkpoint.children[0].checkpoint
    assert child.task_id is not None
    task = make_task().model_copy(
        update={
            "id": child.task_id,
            "repository": child.repository_root,
            "base_ref": "a" * 40,
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 1,
        }
    )
    task, events = _implementing(task)
    repository, queue = _Repository(task), _Queue(_waiting_item(task, child.repository_id))
    repository.events[task.id] = events
    guard = ProductionRequirementDeletionGuard(platform.project, queue, "unused")
    monkeypatch.setattr(
        guard, "_read_tasks", lambda targets: {key: repository.get(key) for key in targets}
    )
    monkeypatch.setattr(
        "ai_software_engineer.multi_directory.deletion.MySqlTaskRepository", lambda dsn: repository
    )
    platform.deletion_guard = guard
    return platform, checkpoint, repository, queue, sidecar


def _close(platform: JointDeliveryService, checkpoint: JointCheckpoint) -> JointCheckpoint:
    return platform.close_requirement(
        CloseRequirement(
            delivery_id=checkpoint.delivery_id,
            expected_checkpoint_sha256=checkpoint.checkpoint_sha256,
        )
    ).checkpoint


def test_waiting_close_then_delete_uses_new_digest_and_preserves_close_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform, checkpoint, repository, queue, _ = _waiting(tmp_path, monkeypatch)
    task = next(iter(repository.tasks.values()))
    item = next(iter(queue.items.values()))
    closed = _close(platform, checkpoint)
    assert closed.stage is JointStage.CLOSED
    assert closed.previous_checkpoint_sha256 == checkpoint.checkpoint_sha256
    assert repository.get(task.id).status is TaskStatus.BLOCKED
    assert len(repository.events[task.id]) == 3
    assert all(value.status is WorkItemStatus.CLOSED for value in queue.items.values())
    assert all(value.wait_disposition is None for value in queue.items.values())
    records = FileRequirementCancellationStore(
        platform.project.requirements_root / checkpoint.delivery_id
    )
    receipt = records.find()
    assert receipt is not None
    assert receipt.checkpoint_sha256 == checkpoint.checkpoint_sha256
    assert receipt.human_action.action == "CLOSE_REQUIREMENT"
    assert receipt.tasks[0].task == task
    assert receipt.tasks[0].queue_items == (item,)
    assert "关闭" in repository.events[task.id][-1].reason
    schema = json.loads(Path("schemas/requirement-cancellation.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(receipt.to_wire())
    before = records.path.read_bytes()
    with pytest.raises(DeliveryCheckpointStale, match="checkpoint"):
        _delete(platform, checkpoint)
    _delete(platform, closed)
    _delete(platform, closed)
    assert records.path.read_bytes() == before
    assert platform.retirements.entry(closed.delivery_id) is not None
    assert len(repository.events[task.id]) == 3


@pytest.mark.parametrize("crash", ["receipt", "queue", "checkpoint"])
def test_waiting_close_partial_replay_keeps_receipt_and_single_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, crash: str
) -> None:
    platform, checkpoint, repository, queue, _ = _waiting(tmp_path, monkeypatch)
    if crash == "receipt":
        repository.before_append = lambda: (_ for _ in ()).throw(RuntimeError("injected crash"))
    elif crash == "queue":
        queue.fail_close = True
    else:
        original_save = platform._save

        def fail_save(*args: object, **kwargs: object) -> JointCheckpoint:
            raise RuntimeError("injected crash")

        monkeypatch.setattr(platform, "_save", fail_save)
    with pytest.raises(RuntimeError):
        _close(platform, checkpoint)
    records = FileRequirementCancellationStore(
        platform.project.requirements_root / checkpoint.delivery_id
    )
    before = records.path.read_bytes()
    assert platform.journal.current(checkpoint.delivery_id) == checkpoint
    if crash == "checkpoint":
        monkeypatch.setattr(platform, "_save", original_save)
    closed = _close(platform, checkpoint)
    assert closed.stage is JointStage.CLOSED
    assert records.path.read_bytes() == before
    assert len(next(iter(repository.events.values()))) == 3
    assert all(item.status is WorkItemStatus.CLOSED for item in queue.items.values())


@pytest.mark.parametrize(
    "status",
    [
        WorkItemStatus.READY,
        WorkItemStatus.RETRY_SCHEDULED,
        WorkItemStatus.LEASED,
        WorkItemStatus.RUNNING,
        WorkItemStatus.CLOSED,
    ],
)
def test_nonwaiting_delivery_cannot_be_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: WorkItemStatus
) -> None:
    platform, checkpoint, repository, queue, _ = _waiting(tmp_path, monkeypatch)
    item = next(iter(queue.items.values()))
    queue.items[item.id] = item.model_copy(
        update={
            "status": status,
            "wait_disposition": None,
            "wait_reason": "retry" if status is WorkItemStatus.RETRY_SCHEDULED else None,
        }
    )
    with pytest.raises(RequirementDeletionRejected):
        _close(platform, checkpoint)
    assert platform.journal.current(checkpoint.delivery_id) == checkpoint
    assert all(len(events) == 2 for events in repository.events.values())
    assert not (
        platform.project.requirements_root / checkpoint.delivery_id / "cancellations"
    ).exists()


@pytest.mark.parametrize(
    "drift", ["missing", "product", "intent", "source", "checkpoint", "role", "attempt"]
)
def test_stale_or_unverified_engineering_wait_cannot_be_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    platform, checkpoint, repository, queue, _ = _waiting(tmp_path, monkeypatch)
    item = next(iter(queue.items.values()))
    disposition = item.wait_disposition
    assert disposition is not None
    if drift == "missing":
        replacement = None
    elif drift == "product":
        replacement = disposition.model_copy(
            update={"responsibility": DeliveryResponsibility.PRODUCT}
        )
    elif drift == "attempt":
        replacement = disposition
        item = item.model_copy(update={"attempt": item.attempt + 1})
    else:
        updates: dict[str, dict[str, object]] = {
            "intent": {"task_intent_sha256": "b" * 64},
            "source": {"source_revision": "b" * 40},
            "checkpoint": {"checkpoint_sequence": 3},
            "role": {"role": AgentRole.REVIEWER},
        }
        update = updates[drift]
        if drift == "role":
            item = item.model_copy(update={"role": AgentRole.REVIEWER})
        facts = disposition.facts.model_copy(update=update)
        replacement = disposition.model_copy(
            update={"facts": facts, "source_facts_sha256": facts.facts_sha256}
        )
    queue.items[item.id] = item.model_copy(update={"wait_disposition": replacement})
    with pytest.raises(RequirementDeletionRejected):
        _close(platform, checkpoint)
    assert all(len(events) == 2 for events in repository.events.values())
    assert platform.journal.current(checkpoint.delivery_id) == checkpoint


@pytest.mark.parametrize("live", ["lease", "process", "late_lease"])
def test_waiting_close_rejects_live_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live: str
) -> None:
    platform, checkpoint, repository, queue, sidecar = _waiting(tmp_path, monkeypatch)
    task = next(iter(repository.tasks.values()))
    now = datetime.now(UTC)
    lease = TaskLease(
        id="lease_wait_close",
        assignment_id="assignment_wait_close",
        task_id=task.id,
        agent_id="agent_wait_close",
        acquired_at=now,
        expires_at=now + timedelta(minutes=1),
    )
    if live == "lease":
        queue.leases = (lease,)
    elif live == "late_lease":
        repository.before_append = lambda: setattr(queue, "leases", (lease,))
    if live == "process":
        with (
            _task_lock(sidecar / "state/queue-worker-locks", task.id),
            pytest.raises(RequirementDeletionRejected),
        ):
            _close(platform, checkpoint)
    else:
        with pytest.raises(RequirementDeletionRejected):
            _close(platform, checkpoint)
    assert all(len(events) == 2 for events in repository.events.values())
    assert platform.journal.current(checkpoint.delivery_id) == checkpoint


def test_missing_waiting_close_capability_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform, checkpoint, repository, _, _ = _waiting(tmp_path, monkeypatch)
    platform.deletion_guard = None
    with pytest.raises(ValueError, match="停止校验"):
        _close(platform, checkpoint)
    assert all(len(events) == 2 for events in repository.events.values())
    assert platform.journal.current(checkpoint.delivery_id) == checkpoint


def test_waiting_receipt_replay_rejects_queue_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform, checkpoint, repository, queue, _ = _waiting(tmp_path, monkeypatch)
    repository.before_append = lambda: (_ for _ in ()).throw(RuntimeError("after receipt"))
    with pytest.raises(RuntimeError):
        _close(platform, checkpoint)
    item = next(iter(queue.items.values()))
    queue.items[item.id] = item.model_copy(update={"priority": item.priority + 1})
    with pytest.raises(RequirementDeletionRejected, match="队列事实已变化"):
        _close(platform, checkpoint)
    assert all(len(events) == 2 for events in repository.events.values())


def test_cancellation_schema_matches_complete_current_model() -> None:
    schema = json.loads(Path("schemas/requirement-cancellation.schema.json").read_text())
    schema.pop("$id", None)
    schema.pop("$schema", None)
    assert schema == RequirementCancellationReceipt.model_json_schema()


@pytest.mark.parametrize("drift", ["corrupt", "owner"])
def test_delete_after_close_rejects_corrupt_or_foreign_cancellation_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    platform, checkpoint, _, _, _ = _waiting(tmp_path, monkeypatch)
    closed = _close(platform, checkpoint)
    records = FileRequirementCancellationStore(
        platform.project.requirements_root / checkpoint.delivery_id
    )
    receipt = records.find()
    assert receipt is not None
    if drift == "corrupt":
        records.path.write_text("{")
    else:
        action = receipt.human_action.model_copy(update={"project_id": "project_other"})
        changed = RequirementCancellationReceipt.seal(
            **{
                **receipt.to_wire(),
                "project_id": "project_other",
                "human_action": action,
            }
        )
        records.path.write_text(changed.model_dump_json())
    with pytest.raises(RequirementDeletionRejected):
        _delete(platform, closed)
    assert platform.retirements.entry(closed.delivery_id) is None


def test_cancelled_waiting_requirement_requires_new_identity_instead_of_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform, checkpoint, repository, queue, _ = _waiting(tmp_path, monkeypatch)
    closed = _close(platform, checkpoint)
    with pytest.raises(ValueError, match="工程执行已按关闭决定取消"):
        platform.restart_requirement(
            RestartRequirement(
                delivery_id=closed.delivery_id,
                expected_checkpoint_sha256=closed.checkpoint_sha256,
            )
        )
    assert platform.journal.current(closed.delivery_id) == closed
    assert all(task.status is TaskStatus.BLOCKED for task in repository.tasks.values())
    assert all(item.status is WorkItemStatus.CLOSED for item in queue.items.values())


@pytest.mark.mysql
@pytest.mark.parametrize("interrupt", [False, True])
def test_public_waiting_close_with_real_mysql_queue_and_partial_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mysql_dsn: str, interrupt: bool
) -> None:
    platform, blocked, sidecar, dirty, _ = _delivery(tmp_path, monkeypatch, dsn=mysql_dsn)
    checkpoint = platform._save(
        blocked, stage=JointStage.DELIVERING, next_action="Engineering wait"
    )
    child = checkpoint.children[0].checkpoint
    assert child.task_id is not None
    original = make_task().model_copy(
        update={
            "id": child.task_id,
            "repository": child.repository_root,
            "base_ref": "a" * 40,
            "attempts": 1,
        }
    )
    task, events = _implementing(original)
    with MySqlTaskRepository(mysql_dsn) as repository:
        repository.create(original)
        for event in events:
            repository.append_event(event)
    queue = MySqlRoleQueue(mysql_dsn)
    item = _waiting_item(task, child.repository_id)
    step = QueuedRoleStep(
        work_item=item,
        boundary=RoleRunBoundary(task.id, AgentRole.CODER, item.attempt, 2, task.base_ref),
        allocation_sha256="a" * 64,
    )
    queue.admit(
        RoleQueueAdmission(
            task_id=task.id,
            repository_id=child.repository_id,
            allocation_sha256=step.allocation_sha256,
            legacy_artifacts=(),
        ),
        step,
    )
    platform.deletion_guard = ProductionRequirementDeletionGuard(platform.project, queue, mysql_dsn)
    native_root = sidecar / "state/project-deliveries" / child.delivery_id
    native_before = tuple(
        (path.name, path.read_bytes()) for path in sorted(native_root.glob("*.json"))
    )
    original_close = queue.close_cancelled_task
    if interrupt:

        def fail_queue(*args: object, **kwargs: object) -> tuple[QueuedWorkItem, ...]:
            raise RuntimeError("injected before queue settlement")

        monkeypatch.setattr(queue, "close_cancelled_task", fail_queue)
        with pytest.raises(RuntimeError, match="before queue settlement"):
            _close(platform, checkpoint)
        assert platform.journal.current(checkpoint.delivery_id) == checkpoint
        monkeypatch.setattr(queue, "close_cancelled_task", original_close)
    closed = _close(platform, checkpoint)
    records = FileRequirementCancellationStore(
        platform.project.requirements_root / checkpoint.delivery_id
    )
    before = records.path.read_bytes()
    _delete(platform, closed)
    assert records.path.read_bytes() == before
    assert (
        tuple((path.name, path.read_bytes()) for path in sorted(native_root.glob("*.json")))
        == native_before
    )
    assert (dirty / "draft.txt").read_text() == "uncommitted business draft\n"
    assert all(
        item.status is WorkItemStatus.CLOSED and item.wait_disposition is None
        for item in queue.items_for_task(task.id)
    )
    with MySqlTaskRepository(mysql_dsn) as repository:
        assert repository.get(task.id).status is TaskStatus.BLOCKED
        assert len(repository.list_events(task.id)) == 3
