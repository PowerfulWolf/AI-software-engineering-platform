"""Stop checks for product deletion without erasing immutable engineering facts."""

from __future__ import annotations

import fcntl
import hashlib
import os
from collections.abc import Iterator
from contextlib import AbstractContextManager, ExitStack, closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

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
    RequirementCancellationQueue,
    RequirementCancellationRejected,
    RequirementCancellationService,
    RequirementCancellationTarget,
)
from ai_software_engineer.multi_directory.models import JointCheckpoint
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


class RequirementExecutionQueue(Protocol):
    def items_for_task(self, task_id: str) -> tuple[QueuedWorkItem, ...]: ...
    def list_active_leases(self, *, now: datetime) -> tuple[TaskLease, ...]: ...


class ProductionRequirementDeletionGuard:
    """Hold existing Task process locks while checking durable execution facts."""

    def __init__(
        self, project: ProjectWorkspace, queue: RequirementExecutionQueue, dsn: str
    ) -> None:
        self.project, self.queue, self._dsn = project, queue, dsn

    @contextmanager
    def protect(self, checkpoint: JointCheckpoint) -> Iterator[None]:
        targets = self._targets(checkpoint)
        with ExitStack() as stack:
            for task_id, (sidecar, _) in sorted(targets.items()):
                stack.enter_context(_task_lock(sidecar / "state/queue-worker-locks", task_id))
            if self._targets(checkpoint) != targets:
                raise RequirementDeletionRejected("工程执行记录已变化, 请刷新需求后再删除。")
            if targets and isinstance(self.queue, RequirementCancellationQueue):
                self._settle_cancelled(checkpoint, targets)
            self._require_inactive(targets)
            yield

    def _settle_cancelled(
        self, checkpoint: JointCheckpoint, targets: dict[str, tuple[Path, str]]
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
                    checkpoint, inventory
                )
        except RequirementCancellationRejected as error:
            raise RequirementDeletionRejected(str(error)) from error

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
        for task_id in targets:
            if any(
                item.status is not WorkItemStatus.CLOSED
                for item in self.queue.items_for_task(task_id)
            ):
                raise RequirementDeletionRejected("需求仍有未结束的工程队列, 请先停止执行后删除。")
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
]
