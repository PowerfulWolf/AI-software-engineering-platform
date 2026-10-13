"""Stop checks for product deletion without erasing immutable engineering facts."""

from __future__ import annotations

import fcntl
import hashlib
import os
from collections.abc import Iterator
from contextlib import AbstractContextManager, ExitStack, closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from pymysql.cursors import DictCursor

from ai_software_engineer.domain.enums import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.task import Task
from ai_software_engineer.domain.workforce import TaskLease
from ai_software_engineer.manager.delivery_checkpoint import (
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.multi_directory.cancellation import (
    FileRequirementCancellationStore,
    RequirementCancellationAction,
    RequirementCancellationQueue,
    RequirementCancellationRejected,
    RequirementCancellationService,
    RequirementCancellationTarget,
)
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.store.mysql_repository import (
    MySqlTaskRepository,
    _decode_task,
    open_mysql_connection,
)
from ai_software_engineer.work_queue.models import QueuedWorkItem


class RequirementDeletionRejected(ValueError):
    """An active or unverifiable delivery cannot be deleted from the product view."""


class RequirementDeletionGuard(Protocol):
    def protect(self, checkpoint: JointCheckpoint) -> AbstractContextManager[None]: ...


@runtime_checkable
class RequirementWaitingCloseGuard(Protocol):
    def protect_waiting_close(
        self, checkpoint: JointCheckpoint
    ) -> AbstractContextManager[None]: ...


class RequirementExecutionQueue(Protocol):
    def items_for_task(self, task_id: str) -> tuple[QueuedWorkItem, ...]: ...
    def list_active_leases(self, *, now: datetime) -> tuple[TaskLease, ...]: ...


class ProductionRequirementDeletionGuard:
    """Hold existing Task process locks while checking durable execution facts."""

    def __init__(
        self, project: ProjectWorkspace, queue: RequirementExecutionQueue, dsn: str
    ) -> None:
        self.project, self.queue, self._dsn = project, queue, dsn

    def protect(self, checkpoint: JointCheckpoint) -> AbstractContextManager[None]:
        return self._protect(checkpoint, action="DELETE_REQUIREMENT")

    def protect_waiting_close(self, checkpoint: JointCheckpoint) -> AbstractContextManager[None]:
        return self._protect(checkpoint, action="CLOSE_REQUIREMENT")

    @contextmanager
    def _protect(
        self, checkpoint: JointCheckpoint, *, action: RequirementCancellationAction
    ) -> Iterator[None]:
        targets = self._targets(checkpoint)
        with ExitStack() as stack:
            for task_id, (sidecar, _) in sorted(targets.items()):
                stack.enter_context(_task_lock(sidecar / "state/queue-worker-locks", task_id))
            if self._targets(checkpoint) != targets:
                raise RequirementDeletionRejected("工程执行记录已变化, 请刷新需求后再删除。")
            self._require_no_leases(targets)
            if action == "CLOSE_REQUIREMENT":
                if not targets or not isinstance(self.queue, RequirementCancellationQueue):
                    raise RequirementDeletionRejected("未配置完整工程执行停止校验, 暂不能关闭。")
                self._settle_cancelled(checkpoint, targets, action=action)
            elif targets and isinstance(self.queue, RequirementCancellationQueue):
                tasks = self._read_tasks(targets)
                needs_settlement = any(
                    task.status not in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}
                    for task in tasks.values()
                ) or any(
                    item.status is not WorkItemStatus.CLOSED
                    for task_id in targets
                    for item in self.queue.items_for_task(task_id)
                )
                if needs_settlement:
                    self._settle_cancelled(checkpoint, targets, action=action)
                else:
                    self._require_cancellation_history(checkpoint, targets)
            self._require_inactive(targets)
            yield

    def _settle_cancelled(
        self,
        checkpoint: JointCheckpoint,
        targets: dict[str, tuple[Path, str]],
        *,
        action: RequirementCancellationAction,
    ) -> None:
        assert isinstance(self.queue, RequirementCancellationQueue)
        self._require_no_leases(targets)
        # Read and validate every historical Task owner before opening a writer.
        tasks = self._read_tasks(targets)
        repositories = {
            repo.root: repo.repository_id for repo in self.project.repository_registry().discover()
        }
        inventory = tuple(
            RequirementCancellationTarget(task=tasks[task_id], repository_id=repositories[sidecar])
            for task_id, (sidecar, _) in sorted(targets.items())
        )
        records = FileRequirementCancellationStore(
            self.project.requirements_root / checkpoint.delivery_id
        )
        try:
            with MySqlTaskRepository(self._dsn) as repository:
                RequirementCancellationService(repository, self.queue, records).cancel(
                    checkpoint, inventory, action=action
                )
        except RequirementCancellationRejected as error:
            raise RequirementDeletionRejected(str(error)) from error

    def _require_cancellation_history(
        self, checkpoint: JointCheckpoint, targets: dict[str, tuple[Path, str]]
    ) -> None:
        try:
            receipt = FileRequirementCancellationStore(
                self.project.requirements_root / checkpoint.delivery_id
            ).find()
        except RequirementCancellationRejected as error:
            raise RequirementDeletionRejected(str(error)) from error
        if receipt is None:
            return
        history = JointJournal(self.project.requirements_root, read_only=True).history(
            checkpoint.delivery_id
        )
        bound = next(
            (value for value in history if value.checkpoint_sha256 == receipt.checkpoint_sha256),
            None,
        )
        if (
            bound is None
            or (
                receipt.team_id,
                receipt.team_manifest_sha256,
                receipt.project_id,
                receipt.project_manifest_sha256,
                receipt.delivery_id,
            )
            != (
                checkpoint.team_id,
                checkpoint.team_manifest_sha256,
                checkpoint.project_id,
                checkpoint.project_manifest_sha256,
                checkpoint.delivery_id,
            )
            or {value.task.id: value.task.repository for value in receipt.tasks}
            != {task_id: root for task_id, (_, root) in targets.items()}
        ):
            raise RequirementDeletionRejected("需求取消记录的归属或历史范围无法核验。")
        repositories = {
            repo.root: repo.repository_id for repo in self.project.repository_registry().discover()
        }
        if any(
            value.repository_id != repositories[targets[value.task.id][0]]
            for value in receipt.tasks
        ):
            raise RequirementDeletionRejected("需求取消记录的仓库归属无法核验。")
        if receipt.human_action.action == "DELETE_REQUIREMENT" and bound.stage not in {
            JointStage.BLOCKED,
            JointStage.CLOSED,
        }:
            raise RequirementDeletionRejected("需求删除取消记录没有对应的停止历史。")
        if receipt.human_action.action == "CLOSE_REQUIREMENT" and (
            bound.stage is not JointStage.DELIVERING
            or not any(
                value.stage is JointStage.CLOSED
                and value.previous_checkpoint_sha256 == bound.checkpoint_sha256
                for value in history
            )
        ):
            raise RequirementDeletionRejected("需求关闭取消记录没有对应的完成历史。")

    def _targets(self, checkpoint: JointCheckpoint) -> dict[str, tuple[Path, str]]:
        self.project.validate_current()
        repositories = {
            repo.repository_id: repo for repo in self.project.repository_registry().discover()
        }
        journal = JointJournal(self.project.requirements_root, read_only=True)
        history = journal.history(checkpoint.delivery_id)
        if not history or history[-1] != checkpoint:
            raise RequirementDeletionRejected("需求记录已变化, 请刷新后再删除。")
        targets: dict[str, tuple[Path, str]] = {}
        child_histories: dict[tuple[str, str], tuple[ProjectDeliveryCheckpoint, ...]] = {}
        for record in history:
            for child in record.children:
                repository = repositories.get(child.checkpoint.repository_id)
                if (
                    repository is None
                    or str(repository.repository_root) != child.checkpoint.repository_root
                ):
                    raise RequirementDeletionRejected("需求的仓库归属无法核验, 暂不能删除。")
                key = (repository.repository_id, child.checkpoint.delivery_id)
                child_history = child_histories.get(key)
                if child_history is None:
                    native = FileProjectDeliveryCheckpointStore(
                        repository.root / "state/project-deliveries", read_only=True
                    )
                    child_history = native.list(child.checkpoint.delivery_id)
                    child_histories[key] = child_history
                if child.checkpoint not in child_history:
                    raise RequirementDeletionRejected("需求的子交付记录无法核验, 暂不能删除。")
                for item in child_history:
                    if item.task_id is None:
                        continue
                    target = (repository.root, str(repository.repository_root))
                    if item.task_id in targets and targets[item.task_id] != target:
                        raise RequirementDeletionRejected("执行任务的仓库归属不一致, 暂不能删除。")
                    targets[item.task_id] = target
        return targets

    def _require_inactive(self, targets: dict[str, tuple[Path, str]]) -> None:
        if not targets:
            return
        self._require_no_leases(targets)
        repository_ids = {
            repo.root: repo.repository_id for repo in self.project.repository_registry().discover()
        }
        for task_id, (sidecar, repository_root) in targets.items():
            items = self.queue.items_for_task(task_id)
            if any(item.status is not WorkItemStatus.CLOSED for item in items):
                raise RequirementDeletionRejected("需求仍有未结束的工程队列, 请先停止执行后删除。")
            if any(
                item.task_id != task_id
                or item.repository_id != repository_ids[sidecar]
                or item.repository_scopes != (repository_root,)
                for item in items
            ):
                raise RequirementDeletionRejected("需求的工程队列归属无法核验, 暂不能删除。")
        for task in self._read_tasks(targets).values():
            if task.status not in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}:
                raise RequirementDeletionRejected("需求的工程任务尚未终止, 请先停止执行后删除。")

    def _require_no_leases(self, targets: dict[str, tuple[Path, str]]) -> None:
        now = datetime.now(UTC)
        if any(lease.task_id in targets for lease in self.queue.list_active_leases(now=now)):
            raise RequirementDeletionRejected("需求仍有有效的工程执行许可, 请等待执行停止后删除。")

    def _read_tasks(self, targets: dict[str, tuple[Path, str]]) -> dict[str, Task]:
        tasks: dict[str, Task] = {}
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            for task_id, (_, repository_root) in targets.items():
                cursor.execute("SELECT id,payload_json,status FROM tasks WHERE id=%s", (task_id,))
                row = cursor.fetchone()
                if (
                    row is None
                    or not isinstance(row["id"], str)
                    or not isinstance(row["payload_json"], str)
                ):
                    raise RequirementDeletionRejected("需求的执行任务快照无法核验, 暂不能删除。")
                task = _decode_task(row["id"], row["payload_json"])
                if (
                    task.id != task_id
                    or task.repository != repository_root
                    or task.status.value != row["status"]
                ):
                    raise RequirementDeletionRejected(
                        "需求的执行任务归属或状态不一致, 暂不能删除。"
                    )
                tasks[task_id] = task
        return tasks


@contextmanager
def _task_lock(root: Path, task_id: str) -> Iterator[None]:
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise RequirementDeletionRejected("工程执行锁路径无法安全核验, 暂不能删除。")
    root.mkdir(parents=True, exist_ok=True)
    path = root / (hashlib.sha256(task_id.encode()).hexdigest() + ".lock")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RequirementDeletionRejected(
                "需求仍有工程进程正在运行, 请等待停止后删除。"
            ) from error
        yield
    finally:
        os.close(fd)


__all__ = [
    "ProductionRequirementDeletionGuard",
    "RequirementDeletionGuard",
    "RequirementDeletionRejected",
    "RequirementWaitingCloseGuard",
]
