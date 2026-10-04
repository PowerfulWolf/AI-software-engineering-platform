"""Product deletion checks real Worker locks and retained native Task lineage."""

from __future__ import annotations

import fcntl
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import (
    ProductApprovalDecision,
    ProductSpecApproval,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.workforce import TaskLease
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
    ProjectDeliveryIntake,
)
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.multi_directory.deletion import (
    ProductionRequirementDeletionGuard,
    RequirementDeletionRejected,
)
from ai_software_engineer.multi_directory.models import ChildDelivery, JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.retirement import RequirementRetiredError
from ai_software_engineer.multi_directory.service import (
    CloseRequirement,
    CreateRequirement,
    DeleteRequirement,
    JointDeliveryService,
)
from ai_software_engineer.recovery import RecoveryRejected, RecoveryScope
from ai_software_engineer.recovery.native import NativeRecoverySourceReader, _parent
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.models import QueuedWorkItem
from tests.domain.factories import make_task
from tests.manager.test_joint_planner_feedback import _done_child
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_requirement_retirement import NOW, _service
from tests.work_queue.test_mysql_queue import queued_item


class _Queue:
    def __init__(self) -> None:
        self.leases: tuple[TaskLease, ...] = ()
        self.items: tuple[QueuedWorkItem, ...] = ()

    def list_active_leases(self, *, now: datetime) -> tuple[TaskLease, ...]:
        return tuple(lease for lease in self.leases if lease.expires_at > now)

    def items_for_task(self, task_id: str) -> tuple[QueuedWorkItem, ...]:
        return tuple(item for item in self.items if item.task_id == task_id)


def _delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, dsn: str = "unused"
) -> tuple[JointDeliveryService, JointCheckpoint, Path, Path, _Queue]:
    service, root = _service(tmp_path, monkeypatch)
    original = service.create(
        CreateRequirement(name="K1", repository_roots=(str(root),))
    ).checkpoint
    child = _done_child(original, 0)
    values = child.checkpoint.to_wire()
    values.update(
        stage=DeliveryStage.BLOCKED,
        task_status=TaskStatus.BLOCKED,
        next_action=DeliveryNextAction.REQUEST_HUMAN,
        failure_code=DeliveryFailureCode.CHECKPOINT_DRIFT,
        failure_summary="Interrupted and stopped",
        failed_stage=DeliveryStage.DELIVERING,
        candidate_revision=None,
    )
    native_checkpoint = ProjectDeliveryCheckpoint.create(**values)
    repository = service.project.repository_registry().discover()[0]
    native = FileProjectDeliveryCheckpointStore(repository.root / "state/project-deliveries")
    native.put_intake(
        ProjectDeliveryIntake.create(
            delivery_id=native_checkpoint.delivery_id,
            repository_id=repository.repository_id,
            repository_root=str(repository.repository_root),
            title="K1 child",
            requirement="Implement K1",
            submitted_at=NOW,
        )
    )
    native.put(native_checkpoint)
    blocked = service._save(
        original,
        stage=JointStage.BLOCKED,
        children=(ChildDelivery(unit_id=child.unit_id, checkpoint=native_checkpoint),),
        next_action="Stopped",
    )
    queue = _Queue()
    service.deletion_guard = ProductionRequirementDeletionGuard(service.project, queue, dsn)
    dirty = tmp_path / "retained-coder-worktree"
    dirty.mkdir()
    (dirty / "draft.txt").write_text("uncommitted business draft\n")
    return service, blocked, repository.root, dirty, queue


def _delete(service: JointDeliveryService, checkpoint: JointCheckpoint) -> None:
    service.delete_requirement(
        DeleteRequirement(
            delivery_id=checkpoint.delivery_id,
            expected_checkpoint_sha256=checkpoint.checkpoint_sha256,
        )
    )


def test_deletion_refuses_live_process_even_if_parent_and_task_are_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, sidecar, dirty, _ = _delivery(tmp_path, monkeypatch)
    task_id = blocked.children[0].checkpoint.task_id
    assert task_id is not None
    root = sidecar / "state/queue-worker-locks"
    root.mkdir()
    fd = os.open(
        root / (hashlib.sha256(task_id.encode()).hexdigest() + ".lock"),
        os.O_CREAT | os.O_RDWR,
        0o600,
    )
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RequirementDeletionRejected, match="进程正在运行"):
            _delete(service, blocked)
    finally:
        os.close(fd)
    assert not service.retirements.retirement().entries
    assert service.journal.current(blocked.delivery_id) == blocked
    assert (dirty / "draft.txt").read_text() == "uncommitted business draft\n"


def test_deletion_refuses_active_lease_and_unfinished_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, _, _, queue = _delivery(tmp_path, monkeypatch)
    task_id = blocked.children[0].checkpoint.task_id
    assert task_id is not None
    now = datetime.now(UTC)
    queue.leases = (
        TaskLease(
            id="lease_delete_test",
            assignment_id="assignment_delete_test",
            task_id=task_id,
            agent_id="agent_delete_test",
            acquired_at=now,
            expires_at=now + timedelta(minutes=1),
        ),
    )
    with pytest.raises(RequirementDeletionRejected, match="有效的工程执行许可"):
        _delete(service, blocked)
    queue.leases = ()
    queue.items = (queued_item().model_copy(update={"task_id": task_id}),)
    with pytest.raises(RequirementDeletionRejected, match="未结束的工程队列"):
        _delete(service, blocked)
    assert not service.retirements.retirement().entries


def test_deletion_holds_all_historical_task_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, sidecar, _, _ = _delivery(tmp_path, monkeypatch)
    guard = service.deletion_guard
    assert isinstance(guard, ProductionRequirementDeletionGuard)
    task_id = blocked.children[0].checkpoint.task_id
    assert task_id is not None
    native = FileProjectDeliveryCheckpointStore(sidecar / "state/project-deliveries")
    source = blocked.children[0].checkpoint
    successor = ProjectDeliveryCheckpoint.create(
        **{
            **source.to_wire(),
            "sequence": 2,
            "previous_checkpoint_sha256": source.checkpoint_sha256,
            "task_id": "task_new_successor",
            "checkpointed_at": datetime.now(UTC),
        }
    )
    native.put(successor)
    target_ids = guard._targets(blocked)
    assert set(target_ids) == {task_id, "task_new_successor"}


def test_deleted_native_child_cannot_bypass_parent_or_fall_back_to_standalone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    service.retirements.retire(blocked, reason="deleted", retired_at=NOW)
    child = blocked.children[0].checkpoint
    approval = ProductSpecApproval(
        id="product_approval_" + "a" * 64,
        request_id="request_delete_child",
        repository_id=child.repository_id,
        product_spec_id="product_spec_delete_child",
        product_spec_sha256="a" * 64,
        decision=ProductApprovalDecision.APPROVED,
        operator_id="human",
        rationale="fixture",
        decided_at=NOW,
        approval_sha256="b" * 64,
    )
    with pytest.raises(RequirementRetiredError, match="需求已删除"):
        _parent(service.team, child, approval)
    unrelated = ProjectDeliveryCheckpoint.create(
        **{**child.to_wire(), "delivery_id": "delivery_unrelated_child"}
    )
    assert _parent(service.team, unrelated, approval) == (None, None)
    config = ProductionConfig(
        platform_root=service.team.manifest.platform_root,
        team_id=service.team.manifest.team_id,
        team_name=service.team.manifest.name,
        model_routes=ProductionConfig.default().model_routes,
    )
    reader = NativeRecoverySourceReader(config, {})
    scope = RecoveryScope(
        team_id=service.team.manifest.team_id,
        repository_id=child.repository_id,
        delivery_id=child.delivery_id,
        repository_root=child.repository_root,
    )
    with pytest.raises(RecoveryRejected, match="需求已删除"):
        reader.inspect(
            scope, failed_run_id="run_deleted_child", failed_context_id="ctx_" + "a" * 64
        )
    with pytest.raises(RecoveryRejected, match="需求已删除"):
        reader.discover_failed_coder(scope)


def test_public_native_continue_refuses_deleted_parent_before_recovery_controller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    service.retirements.retire(blocked, reason="deleted", retired_at=NOW)
    host = object.__new__(TeamHost)
    monkeypatch.setattr(
        host, "_resolve_project_id", lambda project_id, delivery_id=None: blocked.project_id
    )
    monkeypatch.setattr(host, "_runtime", lambda project_id: SimpleNamespace(requirements=service))

    def no_controller(*args: object, **kwargs: object) -> None:
        raise AssertionError("Deleted Requirement must never construct a recovery controller")

    monkeypatch.setattr(host, "_resume_controller", no_controller)
    with pytest.raises(RequirementRetiredError, match="需求已删除"):
        host.resume_delivery(
            ResumeProjectDelivery(delivery_id=blocked.children[0].checkpoint.delivery_id),
            project_id=blocked.project_id,
        )


@pytest.mark.mysql
@pytest.mark.parametrize("closed", [False, True])
def test_public_deletion_preserves_task_native_history_and_dirty_code(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch, closed: bool
) -> None:
    service, blocked, sidecar, dirty, queue = _delivery(tmp_path, monkeypatch, dsn=mysql_dsn)
    task_id = blocked.children[0].checkpoint.task_id
    assert task_id is not None
    task = make_task().model_copy(
        update={
            "id": task_id,
            "status": TaskStatus.BLOCKED,
            "repository": blocked.children[0].checkpoint.repository_root,
        }
    )
    with MySqlTaskRepository(mysql_dsn) as repository:
        repository.create(task)
    queue.items = (
        queued_item().model_copy(update={"task_id": task_id, "status": WorkItemStatus.CLOSED}),
    )
    checkpoint = (
        service.close_requirement(
            CloseRequirement(
                delivery_id=blocked.delivery_id,
                expected_checkpoint_sha256=blocked.checkpoint_sha256,
            )
        ).checkpoint
        if closed
        else blocked
    )
    before = service.journal.history(checkpoint.delivery_id)
    native = FileProjectDeliveryCheckpointStore(
        sidecar / "state/project-deliveries", read_only=True
    )
    native_history = native.list(blocked.children[0].checkpoint.delivery_id)
    _delete(service, checkpoint)
    _delete(service, checkpoint)
    assert service.journal.history(checkpoint.delivery_id) == before
    assert native.list(blocked.children[0].checkpoint.delivery_id) == native_history
    assert (dirty / "draft.txt").read_text() == "uncommitted business draft\n"
    with MySqlTaskRepository(mysql_dsn) as repository:
        assert repository.get(task_id) == task
        assert repository.list_events(task_id) == ()
    assert service.retirements.entry(checkpoint.delivery_id) is not None


@pytest.mark.mysql
def test_deletion_refuses_nonterminal_durable_task(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch, dsn=mysql_dsn)
    task_id = blocked.children[0].checkpoint.task_id
    assert task_id is not None
    with MySqlTaskRepository(mysql_dsn) as repository:
        repository.create(
            make_task().model_copy(
                update={
                    "id": task_id,
                    "status": TaskStatus.IMPLEMENTING,
                    "repository": blocked.children[0].checkpoint.repository_root,
                }
            )
        )
    with pytest.raises(RequirementDeletionRejected, match="工程任务尚未终止"):
        _delete(service, blocked)
    assert not service.retirements.retirement().entries
