"""Read one ended, never-invoked Coder claim before route-transition settlement.

This is a negative execution observation, not a Task outcome or permission to
discard a retained worktree. The caller must hold the exact Task process lock.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictInt, model_validator
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.fallback import model_route_root
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import Task, TaskId
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.capacity_input_reader import (
    CapacityInputReader,
    UninvokedClaimBoundary,
)
from ai_software_engineer.recovery.models import RecoveryScope
from ai_software_engineer.store.mysql_repository import (
    _decode_event,
    _decode_task,
    open_mysql_connection,
)
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    record_digest,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem, WorkItemId
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


class _ReadOnlyRoleQueue(MySqlRoleQueue):
    """Use queue verification ports without initializing production tables."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn


@dataclass(frozen=True, slots=True)
class UninvokedRouteClaimObservation:
    task: Task
    task_revision: int
    events: tuple[StateEvent, ...]
    task_event_history_sha256: str
    work_item: QueuedWorkItem
    step: QueuedRoleStep
    original_claim: QueueClaim
    current_claim_expires_at: datetime
    claim_ended_at: datetime
    claimed_sequence: int
    expired_sequence: int
    queue_event_history_sha256: str


class RouteTransitionSettlement(DomainModel):
    """One immutable old-Task ending with no invented Agent result or refund."""

    kind: Literal["route_transition_settlement"] = "route_transition_settlement"
    schema_version: Literal["v1"] = "v1"
    scope: RecoveryScope
    task: Task
    task_id: TaskId
    checkpoint_sha256: Sha256
    task_revision: StrictInt = Field(ge=1)
    task_sha256: Sha256
    task_event_history_sha256: Sha256
    work_item: QueuedWorkItem
    work_item_id: WorkItemId
    work_item_sha256: Sha256
    step_sha256: Sha256
    original_claim_sha256: Sha256
    claimed_sequence: StrictInt = Field(ge=1)
    expired_sequence: StrictInt = Field(ge=2)
    queue_event_history_sha256: Sha256
    execution_baseline_sha256: Sha256
    inventory_sha256: Sha256
    retained_capture_sha256: Sha256
    event: StateEvent
    settlement_sha256: Sha256

    @model_validator(mode="after")
    def require_exact_terminal_event(self) -> RouteTransitionSettlement:
        if (
            self.event.task_id != self.task_id
            or self.task.id != self.task_id
            or self.task.status is not TaskStatus.IMPLEMENTING
            or self.task_sha256 != digest(self.task.to_wire())
            or self.work_item.id != self.work_item_id
            or self.work_item.status is not WorkItemStatus.RETRY_SCHEDULED
            or self.work_item_sha256 != record_digest(self.work_item)
            or self.event.from_status is not TaskStatus.IMPLEMENTING
            or self.event.to_status is not TaskStatus.BLOCKED
            or self.event.artifact_ids
            or not self.event.reason.startswith("ROUTE_TRANSITION: ")
            or self.claimed_sequence >= self.expired_sequence
        ):
            raise ValueError("route-transition settlement requires one exact old Task ending")
        return self

    @classmethod
    def create(
        cls,
        observed: UninvokedRouteClaimObservation,
        event: StateEvent,
        *,
        scope: RecoveryScope,
        checkpoint_sha256: str,
        execution_baseline_sha256: str,
        inventory_sha256: str,
        retained_capture_sha256: str,
    ) -> RouteTransitionSettlement:
        result = cls(
            scope=scope,
            task=observed.task,
            task_id=observed.task.id,
            checkpoint_sha256=checkpoint_sha256,
            task_revision=observed.task_revision,
            task_sha256=digest(observed.task.to_wire()),
            task_event_history_sha256=observed.task_event_history_sha256,
            work_item=observed.work_item,
            work_item_id=observed.work_item.id,
            work_item_sha256=record_digest(observed.work_item),
            step_sha256=record_digest(observed.step),
            original_claim_sha256=record_digest(observed.original_claim),
            claimed_sequence=observed.claimed_sequence,
            expired_sequence=observed.expired_sequence,
            queue_event_history_sha256=observed.queue_event_history_sha256,
            execution_baseline_sha256=execution_baseline_sha256,
            inventory_sha256=inventory_sha256,
            retained_capture_sha256=retained_capture_sha256,
            event=event,
            settlement_sha256="0" * 64,
        )
        return result.model_copy(update={"settlement_sha256": result.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"settlement_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.settlement_sha256 != self.recompute_sha256():
            raise ValueError("route-transition settlement digest mismatch")

    def require_observation(self, observed: UninvokedRouteClaimObservation) -> None:
        if (
            self.task_id != observed.task.id
            or self.task != observed.task
            or self.scope.repository_root != observed.task.repository
            or self.task_revision != observed.task_revision
            or self.task_sha256 != digest(observed.task.to_wire())
            or self.task_event_history_sha256 != observed.task_event_history_sha256
            or self.work_item_id != observed.work_item.id
            or self.work_item != observed.work_item
            or self.work_item_sha256 != record_digest(observed.work_item)
            or self.step_sha256 != record_digest(observed.step)
            or self.original_claim_sha256 != record_digest(observed.original_claim)
            or self.claimed_sequence != observed.claimed_sequence
            or self.expired_sequence != observed.expired_sequence
            or self.queue_event_history_sha256 != observed.queue_event_history_sha256
            or self.event.attempt != observed.task.attempts
            or self.event.source_revision != observed.step.boundary.source_revision
            or self.event.occurred_at < observed.task.updated_at
        ):
            raise ValueError("route-transition settlement differs from complete claim facts")


def _time(value: object) -> datetime:
    if not isinstance(value, (datetime, str)):
        raise ValueError("uninvoked route claim time is missing")
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("uninvoked route claim time is not timezone-aware")
    return parsed


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise ValueError(f"uninvoked route claim {key} is missing")
    return value


class UninvokedRouteClaimReader:
    """Fresh before/after SQL and complete no-start scan under an existing Task lock."""

    def __init__(self, dsn: str, sidecar: Path) -> None:
        self.dsn, self.sidecar = dsn, sidecar
        self.queue = _ReadOnlyRoleQueue(dsn)

    def inspect(self, task_id: str, guard: WorkerExecutionGuard) -> UninvokedRouteClaimObservation:
        guard.check_task_scope(task_id)
        first = self._snapshot(task_id)
        CapacityInputReader(
            state=self.sidecar / "state",
            queue=self.queue,
            artifacts=FileArtifactStore(self.sidecar / "artifacts", read_only=True),
            route_root=model_route_root(self.sidecar),
            baselines=None,
        ).require_claim_not_started(
            UninvokedClaimBoundary(
                task_id=task_id,
                work_item_id=first.work_item.id,
                lease_id=first.original_claim.lease.id,
                role=AgentRole.CODER,
                attempt=first.work_item.attempt,
                checkpoint_sequence=first.work_item.checkpoint_sequence,
                dispatch_sequence=first.original_claim.work_item.dispatch_sequence,
                observed_at=first.claim_ended_at,
                run_id=None,
                context_manifest_id=None,
            )
        )
        guard.check_task_scope(task_id)
        if self._snapshot(task_id) != first:
            raise ValueError("uninvoked route claim changed during complete no-start scan")
        return first

    def _snapshot(self, task_id: str) -> UninvokedRouteClaimObservation:
        with (
            closing(open_mysql_connection(self.dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            cursor.execute(
                "SELECT id,payload_json,revision,status FROM tasks WHERE id=%s", (task_id,)
            )
            task_row = cursor.fetchone()
            if task_row is None:
                raise ValueError("uninvoked route Task is missing")
            task = _decode_task(task_id, _text(task_row, "payload_json"))
            revision = task_row["revision"]
            if (
                type(revision) is not int
                or revision < 1
                or task.status is not TaskStatus.IMPLEMENTING
                or task_row["status"] != task.status.value
            ):
                raise ValueError("uninvoked route Task is not the implementing checkpoint")
            cursor.execute(
                "SELECT event_id,revision,payload_json FROM state_events WHERE task_id=%s "
                "ORDER BY revision",
                (task_id,),
            )
            event_rows = tuple(cursor.fetchall())
            if tuple(row["revision"] for row in event_rows) != tuple(range(1, revision + 1)):
                raise ValueError("uninvoked route Task event history has a gap")
            events = tuple(_decode_event(_text(row, "payload_json")) for row in event_rows)
            task_history_sha256 = digest(
                tuple(
                    (row["event_id"], row["revision"], _text(row, "payload_json"))
                    for row in event_rows
                )
            )
            previous, previous_attempt = TaskStatus.NEW, 0
            for row, event in zip(event_rows, events, strict=True):
                if (
                    event.event_id != row["event_id"]
                    or event.task_id != task_id
                    or event.from_status is not previous
                    or event.attempt < max(previous_attempt, 1)
                    or event.attempt > task.attempts
                ):
                    raise ValueError("uninvoked route Task event chain differs")
                previous, previous_attempt = event.to_status, event.attempt
            if not events or previous is not TaskStatus.IMPLEMENTING:
                raise ValueError("uninvoked route Task has no implementing event")
            cursor.execute(
                "SELECT id,payload_json FROM work_queue_items WHERE task_id=%s ORDER BY id",
                (task_id,),
            )
            items = tuple(self.queue._decode_item(row) for row in cursor.fetchall())
            pending = tuple(item for item in items if item.status is not WorkItemStatus.CLOSED)
            if len(pending) != 1 or any(item.task_id != task_id for item in items):
                raise ValueError("uninvoked route Task has ambiguous open work")
            item = pending[0]
            if (
                item.role is not AgentRole.CODER
                or item.status is not WorkItemStatus.RETRY_SCHEDULED
                or item.attempt != task.attempts
                or item.checkpoint_sequence != revision
                or item.wait_disposition is not None
            ):
                raise ValueError("uninvoked route WorkItem is not the exact Coder retry")
            cursor.execute(
                "SELECT lease_id FROM work_queue_claims WHERE task_id=%s AND state='ACTIVE'",
                (task_id,),
            )
            if cursor.fetchone() is not None:
                raise ValueError("uninvoked route Task still has active execution authority")
            cursor.execute(
                "SELECT lease_id,work_item_id,task_id,state,acquired_at,last_heartbeat_at,"
                "expires_at,ended_at FROM work_queue_claims WHERE work_item_id=%s",
                (item.id,),
            )
            claim_rows = tuple(cursor.fetchall())
            if len(claim_rows) != 1:
                raise ValueError("uninvoked route WorkItem has ambiguous claims")
            row = claim_rows[0]
            lease_id = _text(row, "lease_id")
            if (
                row["state"] != "EXPIRED"
                or row["task_id"] != task_id
                or row["work_item_id"] != item.id
                or item.wait_reason != f"lease_expired:{lease_id}"
            ):
                raise ValueError("uninvoked route claim has no exact expiry")
            acquired = _time(row["acquired_at"])
            heartbeat = _time(row["last_heartbeat_at"])
            expires = _time(row["expires_at"])
            ended = _time(row["ended_at"])
            if not (acquired <= heartbeat <= expires <= ended <= datetime.now(UTC)):
                raise ValueError("uninvoked route claim end sequence is unsafe")
            cursor.execute(
                "SELECT sequence,event_type,from_status,to_status,lease_id,payload_json,"
                "occurred_at FROM work_queue_events WHERE work_item_id=%s ORDER BY sequence",
                (item.id,),
            )
            event_rows = tuple(cursor.fetchall())
            queue_history_sha256 = digest(
                tuple(
                    (
                        row["sequence"],
                        row["event_type"],
                        row["from_status"],
                        row["to_status"],
                        row["lease_id"],
                        _text(row, "payload_json"),
                        _time(row["occurred_at"]).isoformat(),
                    )
                    for row in event_rows
                )
            )
            claimed = tuple(
                row
                for row in event_rows
                if row["event_type"] == "CLAIMED" and row["lease_id"] == lease_id
            )
            if len(claimed) != 1 or not event_rows:
                raise ValueError("uninvoked route original claim event is missing")
            expired = event_rows[-1]
            payload = json.loads(_text(expired, "payload_json"))
            if (
                expired["event_type"] != "LEASE_EXPIRED"
                or expired["lease_id"] != lease_id
                or expired["from_status"] not in {"LEASED", "RUNNING"}
                or expired["to_status"] != WorkItemStatus.RETRY_SCHEDULED.value
                or type(claimed[0]["sequence"]) is not int
                or type(expired["sequence"]) is not int
                or claimed[0]["sequence"] >= expired["sequence"]
                or _time(expired["occurred_at"]) != ended
                or not isinstance(payload, dict)
                or set(payload) != {"work_item", "detail"}
                or payload["detail"] != {}
                or QueuedWorkItem.model_validate(payload["work_item"]) != item
            ):
                raise ValueError("uninvoked route expiry event differs from current work")
            connection.rollback()
        original = self.queue.original_claim_record(lease_id)
        if not original.has_immutable_snapshot:
            raise ValueError("uninvoked route claim lacks immutable original allocation")
        claim = original.claim
        if (
            claim.work_item.id != item.id
            or claim.work_item.task_id != task_id
            or claim.work_item.role is not AgentRole.CODER
            or claim.work_item.attempt != item.attempt
            or claim.work_item.checkpoint_sequence != item.checkpoint_sequence
            or claim.work_item.dispatch_sequence + 1 != item.dispatch_sequence
            or claim.lease.id != lease_id
            or claim.claimed_at != acquired
            or claim.lease.expires_at > expires
        ):
            raise ValueError("uninvoked route original claim differs from expired generation")
        step = self.queue.step_for_claim(claim)
        if (
            step.work_item.id != item.id
            or step.work_item.task_id != task_id
            or step.boundary.task_id != task_id
            or step.boundary.role is not AgentRole.CODER
            or step.boundary.attempt != item.attempt
            or step.boundary.checkpoint_sequence != revision
        ):
            raise ValueError("uninvoked route claimed step differs from Task checkpoint")
        return UninvokedRouteClaimObservation(
            task=task,
            task_revision=revision,
            events=events,
            task_event_history_sha256=task_history_sha256,
            work_item=item,
            step=step,
            original_claim=claim,
            current_claim_expires_at=expires,
            claim_ended_at=ended,
            claimed_sequence=claimed[0]["sequence"],
            expired_sequence=expired["sequence"],
            queue_event_history_sha256=queue_history_sha256,
        )
