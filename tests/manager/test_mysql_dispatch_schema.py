"""MySQL dispatch schema upgrade contracts that do not require a live database."""

from collections.abc import Mapping

import pytest

from ai_software_engineer.manager.dispatch import DispatchCommitCorruption
from ai_software_engineer.manager.mysql_dispatch_authority import (
    _ensure_current_dispatch_tables,
)


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


_CURRENT = {
    "dispatch_workforce_snapshots": {
        "repository_id",
        "task_id",
        "payload_json",
        "snapshot_sha256",
    },
    "dispatch_commits": {
        "id",
        "repository_id",
        "task_id",
        "payload_json",
        "dispatch_sha256",
    },
    "verification_reservations": {
        "plan_sha256",
        "payload_json",
        "completion_sha256",
        "abandonment_sha256",
    },
}
_LEGACY = {
    **_CURRENT,
    "dispatch_workforce_snapshots": {
        "project_id",
        "task_id",
        "payload_json",
        "snapshot_sha256",
    },
    "dispatch_commits": {
        "id",
        "project_id",
        "task_id",
        "payload_json",
        "dispatch_sha256",
    },
}


def test_fresh_dispatch_schema_is_created_without_a_legacy_rename() -> None:
    cursor = _SchemaCursor({})

    _ensure_current_dispatch_tables(cursor)

    assert not any(statement.startswith("RENAME TABLE") for statement in cursor.statements)
    assert sum(statement.startswith("CREATE TABLE") for statement in cursor.statements) == 3


def test_current_dispatch_schema_is_idempotent() -> None:
    cursor = _SchemaCursor(_CURRENT)

    _ensure_current_dispatch_tables(cursor)

    assert not any(statement.startswith("RENAME TABLE") for statement in cursor.statements)


def test_legacy_verification_schema_adds_distinct_abandonment_column() -> None:
    columns = {
        **_CURRENT,
        "verification_reservations": {
            "plan_sha256",
            "payload_json",
            "completion_sha256",
        },
    }

    cursor = _SchemaCursor(columns)
    _ensure_current_dispatch_tables(cursor)

    assert any(
        statement.startswith("ALTER TABLE verification_reservations")
        and "ADD COLUMN abandonment_sha256" in statement
        for statement in cursor.statements
    )


def test_legacy_project_dispatch_tables_are_preserved_before_current_tables_are_created() -> None:
    cursor = _SchemaCursor(_LEGACY)

    _ensure_current_dispatch_tables(cursor)

    rename = next(
        statement for statement in cursor.statements if statement.startswith("RENAME TABLE")
    )
    assert "dispatch_workforce_snapshots_legacy_project_v01" in rename
    assert "dispatch_commits_legacy_project_v01" in rename
    assert "verification_reservations_legacy_project_v01" not in rename
    assert cursor.statements.index(rename) < next(
        index
        for index, statement in enumerate(cursor.statements)
        if statement.startswith("CREATE TABLE")
    )


def test_legacy_dispatch_schema_before_verification_reservations_is_supported() -> None:
    cursor = _SchemaCursor(
        {
            "dispatch_workforce_snapshots": _LEGACY["dispatch_workforce_snapshots"],
            "dispatch_commits": _LEGACY["dispatch_commits"],
        }
    )

    _ensure_current_dispatch_tables(cursor)

    rename = next(
        statement for statement in cursor.statements if statement.startswith("RENAME TABLE")
    )
    assert "dispatch_workforce_snapshots_legacy_project_v01" in rename
    assert "dispatch_commits_legacy_project_v01" in rename
    assert any(
        "CREATE TABLE IF NOT EXISTS verification_reservations" in statement
        for statement in cursor.statements
    )


def test_partial_or_mixed_dispatch_schema_fails_closed() -> None:
    mixed = {**_CURRENT, "dispatch_commits": _LEGACY["dispatch_commits"]}

    with pytest.raises(DispatchCommitCorruption, match="ambiguous schema"):
        _ensure_current_dispatch_tables(_SchemaCursor(mixed))


def test_incomplete_legacy_archive_fails_closed() -> None:
    columns = {
        **_CURRENT,
        "dispatch_commits_legacy_project_v01": _LEGACY["dispatch_commits"],
    }

    with pytest.raises(DispatchCommitCorruption, match="archive is incomplete"):
        _ensure_current_dispatch_tables(_SchemaCursor(columns))
