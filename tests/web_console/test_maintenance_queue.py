"""Read-only complete queue observation never initializes, claims or rewrites work."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from ai_software_engineer.config.production import (
    ModelProviderKind,
    ProductionConfig,
    ProviderRouteConfig,
)
from ai_software_engineer.domain.enums import WorkItemStatus
from ai_software_engineer.domain.workforce import RoleAssignment, TaskLease
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import maintenance_queue as module
from ai_software_engineer.web_console.store import FileConsoleOperationStore
from ai_software_engineer.work_queue.models import QueuedWorkItem
from ai_software_engineer.work_queue.mysql import _CLAIM_COLUMNS, _EVENT_COLUMNS, _ITEM_COLUMNS
from tests.web_console.test_core import _create_intent
from tests.work_queue.test_mysql_queue import NOW, queued_item


class _Cursor:
    def __init__(self, items: list[dict[str, object]], claims: list[dict[str, object]]) -> None:
        self.items, self.claims = items, claims
        self.sql: list[str] = []
        self.rows: list[dict[str, object]] = []

    def execute(self, sql: str, parameters: tuple[str, ...] | None = None) -> None:
        self.sql.append(sql)
        assert sql.startswith(("SELECT", "SET TRANSACTION", "START TRANSACTION"))
        if "information_schema.COLUMNS" in sql:
            self.rows = [
                {"table_name": name, "column_name": column}
                for name, columns in {
                    "work_queue_items": _ITEM_COLUMNS,
                    "work_queue_claims": _CLAIM_COLUMNS,
                    "work_queue_events": _EVENT_COLUMNS,
                }.items()
                for column in sorted(columns)
            ]
        elif "FROM work_queue_items" in sql:
            self.rows = self.items
        elif "FROM work_queue_claims" in sql:
            self.rows = self.claims
        else:
            self.rows = [
                {"database_name": "ase_test", "server_name": "fixture", "server_port": 3306}
            ]

    def fetchone(self) -> dict[str, object]:
        return self.rows[0]

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self.value = cursor
        self.rolled_back = self.closed = False

    @contextmanager
    def cursor(self, kind: type[DictCursor]) -> Iterator[_Cursor]:
        assert kind is DictCursor
        yield self.value

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _row(status: WorkItemStatus = WorkItemStatus.CLOSED) -> dict[str, object]:
    waiting = status in {
        WorkItemStatus.WAITING_HUMAN,
        WorkItemStatus.WAITING_DEPENDENCY,
        WorkItemStatus.RETRY_SCHEDULED,
    }
    value = queued_item().model_copy(
        update={
            "status": status,
            "wait_reason": "fixture_wait" if waiting else None,
            "available_at": NOW + timedelta(days=1)
            if status is WorkItemStatus.RETRY_SCHEDULED
            else None,
        }
    )
    return {
        "id": value.id,
        "task_id": value.task_id,
        "repository_id": value.repository_id,
        "role": value.role.value,
        "attempt": value.attempt,
        "checkpoint_sequence": value.checkpoint_sequence,
        "status": status.value,
        "version": 0,
        "priority": value.priority,
        "risk_rank": 1,
        "available_at": value.available_at.isoformat() if value.available_at else None,
        "created_at": value.created_at.isoformat(),
        "updated_at": value.updated_at.isoformat(),
        "payload_json": value.model_dump_json(),
    }


def _claim(row: dict[str, object], *, state: str = "ACTIVE") -> dict[str, object]:
    item = QueuedWorkItem.model_validate_json(str(row["payload_json"]))
    assignment = RoleAssignment(
        id="assignment_test_001",
        repository_id=item.repository_id,
        task_id=item.task_id,
        agent_id="agent_test_001",
        role=item.role,
        attempt=item.attempt,
        lease_id="lease_test_001",
        assigned_at=NOW,
    )
    lease = TaskLease(
        id=assignment.lease_id,
        assignment_id=assignment.id,
        task_id=item.task_id,
        agent_id=assignment.agent_id,
        acquired_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    return {
        "lease_id": lease.id,
        "work_item_id": item.id,
        "task_id": item.task_id,
        "agent_id": assignment.agent_id,
        "worker_id": "worker_test_001",
        "owner_token_sha256": "a" * 64,
        "assignment_json": assignment.model_dump_json(),
        "lease_json": lease.model_dump_json(),
        "model_selection_json": (
            '{"policy_id":"model_policy_test_001","policy_version":"v1",'
            '"provider":"codex","model":"gpt-6.1-sol","tier":"standard",'
            '"reasons":["default"],"selected_at":"2026-09-08T13:00:00Z"}'
        ),
        "capacity_units": 1,
        "state": state,
        "acquired_at": NOW.isoformat(),
        "expires_at": lease.expires_at.isoformat(),
        "last_heartbeat_at": NOW.isoformat(),
        "ended_at": None if state == "ACTIVE" else (NOW + timedelta(seconds=40)).isoformat(),
    }


def _observe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cursor: _Cursor
) -> module.MaintenanceQueueInventory:
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-6.1-sol", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    TeamWorkspace.initialize(config.platform_root, team_id=config.team_id, name=config.team_name)
    connection = _Connection(cursor)
    monkeypatch.setattr(module, "open_mysql_connection", lambda dsn: cast(Connection, connection))
    try:
        return module.observe_maintenance_queue(config, {config.database.dsn_env: "fixture"})
    finally:
        assert connection.rolled_back and connection.closed
        assert "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY" in cursor.sql
        assert all("LIMIT" not in sql for sql in cursor.sql)


@pytest.mark.parametrize("status", list(WorkItemStatus))
def test_every_queue_status_is_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: WorkItemStatus
) -> None:
    inventory = _observe(tmp_path, monkeypatch, _Cursor([_row(status)], []))
    assert inventory.work_item_count == 1
    assert inventory.idle == (
        status
        in {WorkItemStatus.CLOSED, WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
    )


def test_expired_active_claim_still_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row()
    inventory = _observe(tmp_path, monkeypatch, _Cursor([row], [_claim(row)]))
    assert inventory.active_lease_ids == ("lease_test_001",)
    assert not inventory.idle


@pytest.mark.parametrize("corruption", ["status", "identity", "orphan", "lease", "unknown_claim"])
def test_corruption_is_not_treated_as_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    row = _row()
    claim = _claim(row, state="RELEASED")
    if corruption == "status":
        row["status"] = "UNKNOWN"
    elif corruption == "identity":
        row["task_id"] = "task_other_001"
    elif corruption == "orphan":
        claim["work_item_id"] = "work_other_001"
    elif corruption == "lease":
        claim["lease_id"] = "lease_other_001"
    else:
        claim["state"] = "UNKNOWN"
    with pytest.raises(ValueError):
        _observe(tmp_path, monkeypatch, _Cursor([row], [claim]))


def test_all_operations_checked_and_future_retry_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # More than a page of terminal history must not hide one pending Operation.
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-6.1-sol", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    store = FileConsoleOperationStore(
        team.directory("work-items") / "console-operations", team_id=config.team_id
    )
    for index in range(101):
        store.submit(
            intent=_create_intent(tmp_path), idempotency_key=f"terminal-{index}", requested_at=NOW
        )
        running = store.claim_next(at=NOW)
        assert running is not None
        store.fail(
            running.operation_id,
            expected=running.operation_sha256,
            error_code="TEST_STOP",
            error_summary="fixture stopped",
            at=NOW,
        )
    operation = store.submit(
        intent=_create_intent(tmp_path), idempotency_key="maintenance-test", requested_at=NOW
    )
    row = _row(WorkItemStatus.RETRY_SCHEDULED)
    item = QueuedWorkItem.model_validate_json(str(row["payload_json"]))
    row["available_at"] = (NOW + timedelta(days=3650)).isoformat()
    row["payload_json"] = item.model_copy(
        update={"available_at": NOW + timedelta(days=3650)}
    ).model_dump_json()
    inventory = _observe(tmp_path, monkeypatch, _Cursor([row], []))
    assert inventory.operation_count == 102
    assert inventory.blocked_operation_ids == (operation.operation_id,)
    assert inventory.blocked_work_item_ids == (item.id,)
    assert not inventory.idle


@pytest.mark.parametrize(
    "damage", ["missing_events", "missing_selection", "mixed", "partial_archive"]
)
def test_partial_schema_is_refused_readonly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    class Damaged(_Cursor):
        def execute(self, sql: str, parameters: tuple[str, ...] | None = None) -> None:
            super().execute(sql, parameters)
            if "information_schema.COLUMNS" not in sql:
                return
            if damage == "missing_events":
                self.rows = [row for row in self.rows if row["table_name"] != "work_queue_events"]
            elif damage == "missing_selection":
                self.rows = [
                    row for row in self.rows if row["column_name"] != "model_selection_json"
                ]
            elif damage == "mixed":
                self.rows.append({"table_name": "work_queue_items", "column_name": "project_id"})
            else:
                self.rows.append(
                    {"table_name": "work_queue_items_legacy_project_v01", "column_name": "id"}
                )

    with pytest.raises(ValueError, match="schema"):
        _observe(tmp_path, monkeypatch, Damaged([], []))
