"""Exact user withdrawal settles stopped execution without running an Agent."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self, runtime_checkable

from pydantic import AwareDatetime, Field, StrictInt, model_validator
from pymysql.cursors import DictCursor

from ai_software_engineer.domain.enums import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.identity import ProjectId, RepositoryId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.task import Task
from ai_software_engineer.domain.workforce import TaskLease
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId, Sha256
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.orchestration.state_machine import (
    TERMINAL_STATUSES,
    apply_event,
    build_event,
)
from ai_software_engineer.store.mysql_repository import _decode_task
from ai_software_engineer.store.repository import StoreCorruption, StoreError
from ai_software_engineer.work_queue.models import QueuedWorkItem
from ai_software_engineer.work_queue.ports import (
    QueueConflict,
    QueueCorruption,
    QueueError,
    QueueLeaseLost,
)

_MAX_RECEIPT_BYTES = 8_000_000


class RequirementCancellationRejected(ValueError):
    """Stopped work or its exact user withdrawal cannot be verified."""


@runtime_checkable
class RequirementCancellationQueue(Protocol):
    def items_for_task(self, task_id: str) -> tuple[QueuedWorkItem, ...]: ...
    def list_active_leases(self, *, now: datetime) -> tuple[TaskLease, ...]: ...
    def cancellation_fence(self, cursor: DictCursor, task_id: str) -> None: ...
    def close_cancelled_task(
        self,
        task: Task,
        *,
        cancellation_sha256: str,
        now: datetime,
        expected_items: tuple[QueuedWorkItem, ...],
    ) -> tuple[QueuedWorkItem, ...]: ...

    def verify_cancelled_inventory(
        self,
        cursor: DictCursor,
        task: Task,
        *,
        expected_items: tuple[QueuedWorkItem, ...],
        cancellation_sha256: str,
        now: datetime,
    ) -> tuple[QueuedWorkItem, ...]: ...


class CancellationTaskRepository(Protocol):
    mutation_fence: Callable[[DictCursor, str], None] | None

    def get(self, task_id: str) -> Task: ...
    def list_events(self, task_id: str) -> tuple[StateEvent, ...]: ...
    def current_revision(self, task_id: str) -> int: ...
    def append_event(self, event: StateEvent) -> None: ...
    def close(self) -> None: ...


class RequirementCancellationTarget(DomainModel):
    task: Task
    repository_id: RepositoryId


class CancellationTaskInventory(DomainModel):
    """The original Task and queue facts, before any cancellation writes."""

    task: Task
    repository_id: RepositoryId
    task_snapshot_sha256: Sha256
    state_revision: Annotated[StrictInt, Field(ge=0)]
    state_events_sha256: Sha256
    source_revision: NonEmptyStr
    queue_items: tuple[QueuedWorkItem, ...]
    queue_inventory_sha256: Sha256

    @model_validator(mode="after")
    def validate_inventory(self) -> Self:
        if self.task_snapshot_sha256 != _digest(self.task.to_wire()):
            raise ValueError("取消任务快照摘要不匹配。")
        if self.queue_inventory_sha256 != _digest([item.to_wire() for item in self.queue_items]):
            raise ValueError("取消队列摘要不匹配。")
        identities = tuple(item.id for item in self.queue_items)
        if identities != tuple(sorted(identities)) or len(set(identities)) != len(identities):
            raise ValueError("取消队列必须按唯一身份排序。")
        if any(
            item.task_id != self.task.id
            or item.repository_id != self.repository_id
            or item.repository_scopes != (self.task.repository,)
            for item in self.queue_items
        ):
            raise ValueError("取消队列与任务的仓库归属不一致。")
        return self


class RequirementCancellationHumanAction(DomainModel):
    """The explicit product deletion command, never an Agent approval."""

    kind: Literal["HumanActionEvent"] = "HumanActionEvent"
    action: Literal["DELETE_REQUIREMENT"] = "DELETE_REQUIREMENT"
    actor: Literal["operator:local-console"] = "operator:local-console"
    project_id: ProjectId
    requirement_id: DeliveryId
    expected_checkpoint_sha256: Sha256
    requested_at: AwareDatetime


class RequirementCancellationReceipt(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    team_id: TeamId
    team_manifest_sha256: Sha256
    project_id: ProjectId
    project_manifest_sha256: Sha256
    delivery_id: DeliveryId
    checkpoint_sha256: Sha256
    human_action: RequirementCancellationHumanAction
    tasks: tuple[CancellationTaskInventory, ...]
    cancellation_sha256: Sha256

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        identities = tuple(item.task.id for item in self.tasks)
        if identities != tuple(sorted(identities)) or len(set(identities)) != len(identities):
            raise ValueError("取消执行任务必须按唯一身份排序。")
        if (
            self.human_action.project_id != self.project_id
            or self.human_action.requirement_id != self.delivery_id
            or self.human_action.expected_checkpoint_sha256 != self.checkpoint_sha256
        ):
            raise ValueError("用户删除意图与取消范围不一致。")
        return self

    @classmethod
    def seal(cls, **values: object) -> RequirementCancellationReceipt:
        provisional = cls.model_validate({**values, "cancellation_sha256": "0" * 64})
        return provisional.model_copy(
            update={"cancellation_sha256": provisional.recompute_digest()}
        )

    def recompute_digest(self) -> str:
        return _digest(self.model_dump(mode="json", exclude={"cancellation_sha256"}))

    def validate_integrity(self) -> None:
        if self.cancellation_sha256 != self.recompute_digest():
            raise RequirementCancellationRejected("需求取消记录摘要不匹配。")

    @property
    def uri(self) -> str:
        return (
            f"project://{self.project_id}/requirements/{self.delivery_id}/cancellations/receipt.json"
            f"#{self.cancellation_sha256}"
        )


class FileRequirementCancellationStore:
    """Publish one immutable cancellation receipt, retaining it across restarts."""

    def __init__(self, requirement_root: Path) -> None:
        self.requirement_root = requirement_root
        self.root = requirement_root / "cancellations"
        self.path = self.root / "receipt.json"
        _safe_path(self.path)

    def find(self) -> RequirementCancellationReceipt | None:
        _safe_path(self.path)
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise RequirementCancellationRejected("需求取消记录不是普通文件。")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                content = stream.read(_MAX_RECEIPT_BYTES + 1)
            if len(content) > _MAX_RECEIPT_BYTES:
                raise RequirementCancellationRejected("需求取消记录超出容量限制。")
            record = RequirementCancellationReceipt.model_validate_json(content)
            record.validate_integrity()
            return record
        except ValueError as error:
            raise RequirementCancellationRejected("需求取消记录无法校验。") from error
        finally:
            os.close(fd)

    def put(self, record: RequirementCancellationReceipt) -> RequirementCancellationReceipt:
        record.validate_integrity()
        _safe_path(self.path)
        if not self.requirement_root.is_dir():
            raise RequirementCancellationRejected("需求的历史目录不存在。")
        self.root.mkdir(exist_ok=True)
        content = record.model_dump_json(indent=2).encode()
        if len(content) > _MAX_RECEIPT_BYTES:
            raise RequirementCancellationRejected("需求取消记录超出容量限制。")
        fd, name = tempfile.mkstemp(prefix=".cancellation.", dir=self.root)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.path, follow_symlinks=False)
            except FileExistsError as error:
                existing = self.find()
                if existing != record:
                    raise RequirementCancellationRejected(
                        "已有取消记录与本次删除不一致。"
                    ) from error
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        return record


class RequirementCancellationService:
    """Audit then settle every stopped Task, allowing only exact partial replay."""

    def __init__(
        self,
        repository: CancellationTaskRepository,
        queue: RequirementCancellationQueue,
        records: FileRequirementCancellationStore,
    ) -> None:
        self.repository, self.queue, self.records = repository, queue, records

    def cancel(
        self,
        checkpoint: JointCheckpoint,
        targets: tuple[RequirementCancellationTarget, ...],
    ) -> RequirementCancellationReceipt:
        try:
            return self._cancel(checkpoint, targets)
        except QueueLeaseLost as error:
            raise RequirementCancellationRejected(
                "工程执行许可已变化或尚未释放, 删除未完成, 请等待执行停止后重试。"
            ) from error
        except (QueueCorruption, StoreCorruption) as error:
            raise RequirementCancellationRejected(
                "工程记录校验失败, 删除未完成, 请检查保留的任务和队列记录。"
            ) from error
        except QueueConflict as error:
            raise RequirementCancellationRejected(
                "工程队列或任务事实与取消记录不一致, 删除未完成, 请刷新后检查执行记录。"
            ) from error
        except (QueueError, StoreError) as error:
            raise RequirementCancellationRejected(
                "工程记录暂时无法安全更新, 删除未完成, 请稍后重试。"
            ) from error

    def _cancel(
        self,
        checkpoint: JointCheckpoint,
        targets: tuple[RequirementCancellationTarget, ...],
    ) -> RequirementCancellationReceipt:
        if checkpoint.stage not in {JointStage.BLOCKED, JointStage.CLOSED}:
            raise RequirementCancellationRejected("仅能撤销已经停止的需求执行。")
        identities = tuple(target.task.id for target in targets)
        if len(set(identities)) != len(identities):
            raise RequirementCancellationRejected("需求取消范围包含重复任务。")
        targets = tuple(sorted(targets, key=lambda item: item.task.id))
        self._require_no_lease(identities)
        receipt = self.records.find()
        if receipt is None:
            inventory = tuple(self._inventory(target) for target in targets)
            receipt = RequirementCancellationReceipt.seal(
                team_id=checkpoint.team_id,
                team_manifest_sha256=checkpoint.team_manifest_sha256,
                project_id=checkpoint.project_id,
                project_manifest_sha256=checkpoint.project_manifest_sha256,
                delivery_id=checkpoint.delivery_id,
                checkpoint_sha256=checkpoint.checkpoint_sha256,
                human_action=RequirementCancellationHumanAction(
                    project_id=checkpoint.project_id,
                    requirement_id=checkpoint.delivery_id,
                    expected_checkpoint_sha256=checkpoint.checkpoint_sha256,
                    requested_at=datetime.now(UTC),
                ),
                tasks=inventory,
            )
        self._require_scope(receipt, checkpoint, targets)
        # Validate the complete scope before publishing a receipt or mutating any Task.
        for original in receipt.tasks:
            self._require_current(receipt, original)
        self._require_no_lease(identities)
        self.records.put(receipt)
        previous_fence = self.repository.mutation_fence
        try:
            for original in receipt.tasks:
                self._require_current(receipt, original)
                event = self._event(receipt, original)
                if event is not None:
                    self.repository.mutation_fence = self._mutation_fence(receipt, original)
                    self.repository.append_event(event)
                current = self.repository.get(original.task.id)
                self.queue.close_cancelled_task(
                    current,
                    cancellation_sha256=receipt.cancellation_sha256,
                    now=receipt.human_action.requested_at,
                    expected_items=original.queue_items,
                )
        finally:
            self.repository.mutation_fence = previous_fence
        return receipt

    def _inventory(self, target: RequirementCancellationTarget) -> CancellationTaskInventory:
        task = self.repository.get(target.task.id)
        if task != target.task:
            raise RequirementCancellationRejected("执行任务快照已变化, 请刷新后再删除。")
        events = self.repository.list_events(task.id)
        revision = self.repository.current_revision(task.id)
        if revision != len(events):
            raise RequirementCancellationRejected("执行任务事件与快照版本不一致。")
        items = tuple(sorted(self.queue.items_for_task(task.id), key=lambda item: item.id))
        try:
            return CancellationTaskInventory(
                task=task,
                repository_id=target.repository_id,
                task_snapshot_sha256=_digest(task.to_wire()),
                state_revision=revision,
                state_events_sha256=_digest([event.to_wire() for event in events]),
                source_revision=events[-1].source_revision if events else task.base_ref,
                queue_items=items,
                queue_inventory_sha256=_digest([item.to_wire() for item in items]),
            )
        except ValueError as error:
            raise RequirementCancellationRejected("取消队列与执行任务的归属无法核验。") from error

    def _require_scope(
        self,
        receipt: RequirementCancellationReceipt,
        checkpoint: JointCheckpoint,
        targets: tuple[RequirementCancellationTarget, ...],
    ) -> None:
        receipt.validate_integrity()
        for name in (
            "team_id",
            "team_manifest_sha256",
            "project_id",
            "project_manifest_sha256",
            "delivery_id",
            "checkpoint_sha256",
        ):
            if getattr(receipt, name) != getattr(checkpoint, name):
                raise RequirementCancellationRejected("需求取消记录的归属或范围已变化。")
        if len(receipt.tasks) != len(targets) or any(
            original.task.id != target.task.id
            or original.task.repository != target.task.repository
            or original.repository_id != target.repository_id
            for original, target in zip(receipt.tasks, targets, strict=True)
        ):
            raise RequirementCancellationRejected("需求取消记录的执行任务范围已变化。")

    def _require_current(
        self, receipt: RequirementCancellationReceipt, original: CancellationTaskInventory
    ) -> None:
        current = self.repository.get(original.task.id)
        events = self.repository.list_events(original.task.id)
        revision = self.repository.current_revision(original.task.id)
        event = self._event(receipt, original)
        baseline = (
            revision == original.state_revision
            and current == original.task
            and _digest([value.to_wire() for value in events]) == original.state_events_sha256
        )
        cancelled = (
            event is not None
            and revision == original.state_revision + 1
            and current == apply_event(original.task, event)
            and len(events) == revision
            and events[-1] == event
            and _digest([value.to_wire() for value in events[:-1]]) == original.state_events_sha256
        )
        if not baseline and not cancelled:
            raise RequirementCancellationRejected("取消期间执行任务或事件已变化, 请检查工程记录。")
        items = tuple(sorted(self.queue.items_for_task(original.task.id), key=lambda item: item.id))
        if len(items) != len(original.queue_items):
            raise RequirementCancellationRejected("取消期间工程队列范围已变化。")
        for before, after in zip(original.queue_items, items, strict=True):
            if before == after:
                continue
            expected = before.model_copy(
                update={
                    "status": WorkItemStatus.CLOSED,
                    "updated_at": receipt.human_action.requested_at,
                    "wait_reason": None,
                    "available_at": None,
                }
            )
            if (not baseline or original.task.status in TERMINAL_STATUSES) and after == expected:
                continue
            raise RequirementCancellationRejected("取消期间工程队列事实已变化。")

    @staticmethod
    def _event(
        receipt: RequirementCancellationReceipt, original: CancellationTaskInventory
    ) -> StateEvent | None:
        if original.task.status in TERMINAL_STATUSES:
            return None
        # NEW has no BLOCKED edge; cancellation uses its existing FAILED edge.
        target_status = (
            TaskStatus.FAILED if original.task.status is TaskStatus.NEW else TaskStatus.BLOCKED
        )
        return build_event(
            original.task,
            target_status,
            event_id="evt_cancel_" + _digest((receipt.cancellation_sha256, original.task.id))[:40],
            reason="用户已明确删除该需求, 终止保留的旧工程执行; 取消记录: " + receipt.uri,
            source_revision=original.source_revision,
            attempt=max(1, original.task.attempts),
            occurred_at=receipt.human_action.requested_at,
        )

    def _mutation_fence(
        self, receipt: RequirementCancellationReceipt, original: CancellationTaskInventory
    ) -> Callable[[DictCursor, str], None]:
        event = self._event(receipt, original)
        assert event is not None
        expected = apply_event(original.task, event)

        def check(cursor: DictCursor, task_id: str) -> None:
            if task_id != original.task.id:
                raise RequirementCancellationRejected("取消写入超出了已批准的任务范围。")
            self.queue.cancellation_fence(cursor, task_id)
            self.queue.verify_cancelled_inventory(
                cursor,
                original.task,
                expected_items=original.queue_items,
                cancellation_sha256=receipt.cancellation_sha256,
                now=receipt.human_action.requested_at,
            )
            cursor.execute(
                "SELECT id,payload_json,status,revision FROM tasks WHERE id=%s FOR UPDATE",
                (task_id,),
            )
            row = cursor.fetchone()
            if (
                row is None
                or not isinstance(row["id"], str)
                or not isinstance(row["payload_json"], str)
            ):
                raise RequirementCancellationRejected("取消写入无法核验任务快照。")
            task = _decode_task(row["id"], row["payload_json"])
            if task.status.value != row["status"]:
                raise RequirementCancellationRejected("取消写入发现任务索引与快照状态不一致。")
            if not (
                (task == original.task and row["revision"] == original.state_revision)
                or (task == expected and row["revision"] == original.state_revision + 1)
            ):
                raise RequirementCancellationRejected("取消写入期间任务快照已变化。")

        return check

    def _require_no_lease(self, task_ids: tuple[str, ...]) -> None:
        if any(
            lease.task_id in task_ids
            for lease in self.queue.list_active_leases(now=datetime.now(UTC))
        ):
            raise RequirementCancellationRejected("需求仍有有效的工程执行许可, 暂不能取消。")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _safe_path(path: Path) -> None:
    if any(value.is_symlink() for value in (path, *path.parents)):
        raise RequirementCancellationRejected("需求取消记录路径无法安全核验。")
