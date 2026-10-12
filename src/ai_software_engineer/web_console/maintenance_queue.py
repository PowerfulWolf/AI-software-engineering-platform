"""Complete read-only maintenance inventory; never constructs a queue or Host."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from contextlib import closing
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator
from pymysql.cursors import DictCursor

from ai_software_engineer.config.production import ProductionConfig
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.enums import WorkItemStatus
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.workforce import ModelSelection, RoleAssignment, TaskLease
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.team_workspace import discover_team_workspaces
from ai_software_engineer.work_queue.models import QueuedWorkItem
from ai_software_engineer.work_queue.mysql import (
    _CLAIM_COLUMNS,
    _EVENT_COLUMNS,
    _ITEM_COLUMNS,
    _LEGACY_ITEM_COLUMNS,
    _LEGACY_TABLES,
    _RISK_RANK,
)

from .store import FileConsoleOperationStore

Count = Annotated[StrictInt, Field(ge=0)]
_UNSAFE = frozenset(
    {
        WorkItemStatus.READY,
        WorkItemStatus.RETRY_SCHEDULED,
        WorkItemStatus.LEASED,
        WorkItemStatus.RUNNING,
    }
)


class MaintenanceQueueInventory(DomainModel):
    inventory_sha256: Sha256
    team_manifest_sha256: Sha256
    queue_scope: Literal["SELECTED_DATABASE_ALL_ROWS"] = "SELECTED_DATABASE_ALL_ROWS"
    operation_count: Count
    work_item_count: Count
    claim_count: Count
    waiting_work_item_count: Count
    blocked_operation_ids: tuple[NonEmptyStr, ...] = ()
    blocked_work_item_ids: tuple[NonEmptyStr, ...] = ()
    active_lease_ids: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def complete_counts(self) -> Self:
        for values in (
            self.blocked_operation_ids,
            self.blocked_work_item_ids,
            self.active_lease_ids,
        ):
            ensure_unique(values, "maintenance blockers")
        if (
            len(self.blocked_operation_ids) > self.operation_count
            or len(self.blocked_work_item_ids) + self.waiting_work_item_count > self.work_item_count
            or len(self.active_lease_ids) > self.claim_count
        ):
            raise ValueError("maintenance inventory counts mismatch")
        return self

    @property
    def idle(self) -> bool:
        return not (
            self.blocked_operation_ids or self.blocked_work_item_ids or self.active_lease_ids
        )


class _ItemRow(DomainModel):
    id: str
    task_id: str
    repository_id: str
    role: str
    attempt: int
    checkpoint_sequence: int
    status: str
    version: int
    priority: int
    risk_rank: int
    available_at: str | None
    created_at: str
    updated_at: str
    payload_json: str

    def item(self) -> QueuedWorkItem:
        value = QueuedWorkItem.model_validate_json(self.payload_json)
        if (
            value.id,
            value.task_id,
            value.repository_id,
            value.role.value,
            value.attempt,
            value.checkpoint_sequence,
            value.status.value,
        ) != (
            self.id,
            self.task_id,
            self.repository_id,
            self.role,
            self.attempt,
            self.checkpoint_sequence,
            self.status,
        ):
            raise ValueError("maintenance queue identity mismatch")
        if (
            self.version < 0
            or self.priority != value.priority
            or self.risk_rank != _RISK_RANK[value.risk.value]
            or (
                datetime.fromisoformat(self.available_at) if self.available_at is not None else None
            )
            != value.available_at
            or datetime.fromisoformat(self.created_at) != value.created_at
            or datetime.fromisoformat(self.updated_at) != value.updated_at
        ):
            raise ValueError("invalid queue indexed facts")
        return value


class _ClaimRow(DomainModel):
    lease_id: str
    work_item_id: str
    task_id: str
    agent_id: str
    worker_id: str
    owner_token_sha256: Sha256
    assignment_json: str
    lease_json: str
    model_selection_json: str
    capacity_units: int
    state: Literal["ACTIVE", "RELEASED", "EXPIRED"]
    acquired_at: str
    expires_at: str
    last_heartbeat_at: str
    ended_at: str | None

    def require_item(self, item: QueuedWorkItem) -> None:
        assignment = RoleAssignment.model_validate_json(self.assignment_json)
        lease = TaskLease.model_validate_json(self.lease_json)
        selection = ModelSelection.model_validate_json(self.model_selection_json)
        heartbeat = datetime.fromisoformat(self.last_heartbeat_at)
        if (
            (assignment.task_id, assignment.repository_id, assignment.role, assignment.attempt)
            != (item.task_id, item.repository_id, item.role, item.attempt)
            or assignment.lease_id != lease.id
            or assignment.id != lease.assignment_id
            or self.lease_id != lease.id
            or self.work_item_id != item.id
            or self.task_id != item.task_id
            or lease.task_id != item.task_id
            or self.agent_id != assignment.agent_id
            or lease.agent_id != assignment.agent_id
            or lease.capacity_units != assignment.capacity_units
            or self.capacity_units != lease.capacity_units
            or selection.selected_at > lease.acquired_at
            or datetime.fromisoformat(self.acquired_at) != lease.acquired_at
            or datetime.fromisoformat(self.expires_at) != lease.expires_at
            or heartbeat.tzinfo is None
            or not lease.acquired_at <= heartbeat < lease.expires_at
            or (self.state == "ACTIVE") != (self.ended_at is None)
        ):
            raise ValueError("maintenance claim identity mismatch")
        if self.ended_at is not None:
            ended = datetime.fromisoformat(self.ended_at)
            if ended.tzinfo is None or ended < lease.acquired_at:
                raise ValueError("maintenance claim end mismatch")


class _DatabaseIdentity(DomainModel):
    database_name: NonEmptyStr
    server_name: NonEmptyStr
    server_port: Annotated[StrictInt, Field(gt=0, le=65535)]


class _SchemaColumn(DomainModel):
    table_name: NonEmptyStr
    column_name: NonEmptyStr


def _require_queue_schema(cursor: DictCursor) -> tuple[_SchemaColumn, ...]:
    names = (*_LEGACY_TABLES, *_LEGACY_TABLES.values())
    placeholders = ",".join("%s" for _ in names)
    cursor.execute(
        "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
        "AND TABLE_NAME IN (" + placeholders + ") ORDER BY TABLE_NAME,COLUMN_NAME",
        names,
    )
    rows = tuple(_SchemaColumn.model_validate(row) for row in cursor.fetchall())
    columns: dict[str, set[str]] = {}
    for row in rows:
        current = columns.setdefault(row.table_name, set())
        if row.table_name not in names or row.column_name in current:
            raise ValueError("unexpected queue schema row")
        current.add(row.column_name)
    expected = {
        "work_queue_items": _ITEM_COLUMNS,
        "work_queue_claims": _CLAIM_COLUMNS,
        "work_queue_events": _EVENT_COLUMNS,
    }
    for name, required in expected.items():
        if frozenset(columns.get(name, set())) != required:
            raise ValueError("incomplete current queue schema")
    archives = tuple(bool(columns.get(name)) for name in _LEGACY_TABLES.values())
    if any(archives):
        if not all(archives):
            raise ValueError("incomplete legacy queue schema")
        for name, archive in _LEGACY_TABLES.items():
            required = _LEGACY_ITEM_COLUMNS if name == "work_queue_items" else expected[name]
            if frozenset(columns[archive]) != required:
                raise ValueError("invalid legacy queue schema")
    return rows


def observe_maintenance_queue(
    config: ProductionConfig, environment: Mapping[str, str]
) -> MaintenanceQueueInventory:
    teams = discover_team_workspaces(config.platform_root)
    if len(teams) != 1 or teams[0].manifest.team_id != config.team_id:
        raise ValueError("maintenance Team identity unavailable")
    team = teams[0]
    operations = FileConsoleOperationStore(
        team.directory("work-items") / "console-operations", team_id=config.team_id, read_only=True
    ).list_current()
    digest = hashlib.sha256()
    digest.update(team.manifest.manifest_sha256.encode())
    blocked_operations = []
    for operation in sorted(operations, key=lambda value: value.operation_id):
        digest.update(operation.operation_sha256.encode())
        if not operation.terminal:
            blocked_operations.append(operation.operation_id)
    with closing(open_mysql_connection(config.require_mysql_dsn(environment))) as connection:
        try:
            with connection.cursor(DictCursor) as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                for column in _require_queue_schema(cursor):
                    digest.update(column.model_dump_json().encode())
                cursor.execute(
                    "SELECT DATABASE() AS database_name, @@hostname AS server_name, "
                    "@@port AS server_port"
                )
                identity = _DatabaseIdentity.model_validate(cursor.fetchone())
                digest.update(identity.model_dump_json().encode())
                cursor.execute(
                    "SELECT id,task_id,repository_id,role,attempt,checkpoint_sequence,"
                    "status,version,priority,risk_rank,available_at,created_at,updated_at,"
                    "payload_json "
                    "FROM work_queue_items ORDER BY id"
                )
                items = {}
                blocked_items = []
                waiting = 0
                for row in cursor.fetchall():
                    typed = _ItemRow.model_validate(row)
                    item = typed.item()
                    if item.id in items:
                        raise ValueError("duplicate queue item")
                    items[item.id] = item
                    digest.update(typed.model_dump_json().encode())
                    if item.status in _UNSAFE:
                        blocked_items.append(item.id)
                    elif item.status in {
                        WorkItemStatus.WAITING_HUMAN,
                        WorkItemStatus.WAITING_DEPENDENCY,
                    }:
                        waiting += 1
                cursor.execute(
                    "SELECT lease_id,work_item_id,task_id,agent_id,worker_id,"
                    "owner_token_sha256,assignment_json,lease_json,model_selection_json,capacity_units,state,acquired_at,"
                    "expires_at,last_heartbeat_at,ended_at FROM work_queue_claims "
                    "ORDER BY lease_id"
                )
                active = []
                seen = set()
                for row in cursor.fetchall():
                    claim = _ClaimRow.model_validate(row)
                    if claim.lease_id in seen or claim.work_item_id not in items:
                        raise ValueError("orphan or duplicate claim")
                    seen.add(claim.lease_id)
                    claim.require_item(items[claim.work_item_id])
                    digest.update(claim.model_dump_json().encode())
                    if claim.state == "ACTIVE":
                        active.append(claim.lease_id)
        finally:
            connection.rollback()
    return MaintenanceQueueInventory(
        inventory_sha256=digest.hexdigest(),
        team_manifest_sha256=team.manifest.manifest_sha256,
        operation_count=len(operations),
        work_item_count=len(items),
        claim_count=len(seen),
        waiting_work_item_count=waiting,
        blocked_operation_ids=tuple(blocked_operations),
        blocked_work_item_ids=tuple(blocked_items),
        active_lease_ids=tuple(active),
    )
