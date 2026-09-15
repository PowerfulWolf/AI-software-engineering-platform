"""MySQL WorkQueue schema upgrade contracts without a live database."""

from collections.abc import Mapping

import pytest

from ai_software_engineer.work_queue.mysql import _ensure_current_queue_tables
from ai_software_engineer.work_queue.ports import QueueCorruption


class _SchemaCursor:
    def __init__(self, columns: Mapping[str, set[str]]) -> None:
        self._columns = columns
        self.statements: list[str] = []

    def execute(self, statement: str, _parameters: object = None) -> None:
        self.statements.append(" ".join(statement.split()))

    def fetchall(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {"TABLE_NAME": table, "COLUMN_NAME": column}
            for table, table_columns in self._columns.items()
            for column in sorted(table_columns)
        )


_ITEMS = {
    "id",
    "task_id",
    "repository_id",
    "role",
    "attempt",
    "checkpoint_sequence",
    "status",
    "priority",
    "risk_rank",
    "available_at",
    "payload_json",
    "version",
    "created_at",
    "updated_at",
}
_LEGACY_ITEMS = (_ITEMS - {"repository_id"}) | {"project_id"}
_CLAIMS = {
    "lease_id",
    "work_item_id",
    "task_id",
    "agent_id",
    "worker_id",
    "owner_token_sha256",
    "assignment_json",
    "lease_json",
    "model_selection_json",
    "capacity_units",
    "state",
    "acquired_at",
    "expires_at",
    "last_heartbeat_at",
    "ended_at",
}
_EVENTS = {
    "sequence",
    "work_item_id",
    "event_type",
    "from_status",
    "to_status",
    "lease_id",
    "payload_json",
    "occurred_at",
}
_CURRENT = {
    "work_queue_items": _ITEMS,
    "work_queue_claims": _CLAIMS,
    "work_queue_events": _EVENTS,
}
_LEGACY = {**_CURRENT, "work_queue_items": _LEGACY_ITEMS}


def test_fresh_work_queue_schema_is_created_without_a_legacy_rename() -> None:
    cursor = _SchemaCursor({})

    _ensure_current_queue_tables(cursor)

    assert not any(statement.startswith("RENAME TABLE") for statement in cursor.statements)
    assert sum(statement.startswith("CREATE TABLE") for statement in cursor.statements) == 3


def test_current_work_queue_schema_is_idempotent() -> None:
    cursor = _SchemaCursor(_CURRENT)

    _ensure_current_queue_tables(cursor)

    assert not any(statement.startswith("RENAME TABLE") for statement in cursor.statements)


def test_legacy_project_queue_is_archived_before_current_tables_are_created() -> None:
    cursor = _SchemaCursor(_LEGACY)

    _ensure_current_queue_tables(cursor)

    rename = next(
        statement for statement in cursor.statements if statement.startswith("RENAME TABLE")
    )
    assert "work_queue_items_legacy_project_v01" in rename
    assert "work_queue_claims_legacy_project_v01" in rename
    assert "work_queue_events_legacy_project_v01" in rename
    assert cursor.statements.index(rename) < next(
        index
        for index, statement in enumerate(cursor.statements)
        if statement.startswith("CREATE TABLE")
    )


def test_partial_or_mixed_work_queue_schema_fails_closed() -> None:
    mixed = {**_CURRENT, "work_queue_items": _LEGACY_ITEMS}
    mixed.pop("work_queue_events")

    with pytest.raises(QueueCorruption, match="ambiguous schema"):
        _ensure_current_queue_tables(_SchemaCursor(mixed))


def test_incomplete_work_queue_archive_fails_closed() -> None:
    columns = {
        **_CURRENT,
        "work_queue_items_legacy_project_v01": _LEGACY_ITEMS,
    }

    with pytest.raises(QueueCorruption, match="archive is incomplete"):
        _ensure_current_queue_tables(_SchemaCursor(columns))
