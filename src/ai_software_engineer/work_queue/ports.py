"""Ports and stable failures for the organization WorkQueue."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from ai_software_engineer.domain.enums import WorkItemStatus
from ai_software_engineer.domain.workforce import (
    ModelSelection,
    RoleAssignment,
    TaskLease,
)
from ai_software_engineer.work_queue.models import (
    LeaseWorkerId,
    QueueArtifactReceipt,
    QueueClaim,
    QueueCompletion,
    QueuedWorkItem,
    WorkItemId,
)


class QueueError(RuntimeError):
    """Base failure for durable queue operations."""


class QueueNotFound(QueueError):
    """A requested queue identity does not exist."""


class QueueConflict(QueueError):
    """Current queue state, Lease ownership or replay identity changed."""


class QueueCorruption(QueueError):
    """Persisted queue facts do not satisfy their typed contract."""


class PersistentWorkQueue(Protocol):
    """Durable queue boundary consumed by Dispatcher and worker lifecycle code."""

    def enqueue(self, item: QueuedWorkItem) -> QueuedWorkItem: ...

    def get(self, work_item_id: WorkItemId | str) -> QueuedWorkItem: ...

    def list_schedulable(
        self, *, now: datetime, limit: int = 100
    ) -> tuple[QueuedWorkItem, ...]: ...

    def list_active_leases(self, *, now: datetime) -> tuple[TaskLease, ...]: ...

    def list_assignments(self) -> tuple[RoleAssignment, ...]: ...

    def claim(
        self,
        item: QueuedWorkItem,
        *,
        assignment: RoleAssignment,
        lease: TaskLease,
        model_selection: ModelSelection,
        worker_id: LeaseWorkerId | str,
        owner_token: str,
        agent_capacity: int,
        now: datetime,
    ) -> QueueClaim: ...

    def start(
        self,
        work_item_id: WorkItemId | str,
        *,
        lease_id: str,
        owner_token: str,
        now: datetime,
    ) -> QueuedWorkItem: ...

    def renew(
        self,
        work_item_id: WorkItemId | str,
        *,
        lease_id: str,
        owner_token: str,
        now: datetime,
        expires_at: datetime,
    ) -> TaskLease: ...

    def complete(
        self,
        work_item_id: WorkItemId | str,
        *,
        lease_id: str,
        owner_token: str,
        artifacts: Sequence[QueueArtifactReceipt],
        next_work_item: QueuedWorkItem | None,
        now: datetime,
    ) -> QueueCompletion: ...

    def wait(
        self,
        work_item_id: WorkItemId | str,
        *,
        lease_id: str,
        owner_token: str,
        status: WorkItemStatus,
        reason: str,
        now: datetime,
    ) -> QueuedWorkItem: ...

    def retry(
        self,
        work_item_id: WorkItemId | str,
        *,
        lease_id: str,
        owner_token: str,
        reason: str,
        now: datetime,
        available_at: datetime,
    ) -> QueuedWorkItem: ...

    def make_ready(self, work_item_id: WorkItemId | str, *, now: datetime) -> QueuedWorkItem: ...

    def reclaim_expired(
        self, *, now: datetime, retry_at: datetime
    ) -> tuple[QueuedWorkItem, ...]: ...


__all__ = [
    "PersistentWorkQueue",
    "QueueConflict",
    "QueueCorruption",
    "QueueError",
    "QueueNotFound",
]
