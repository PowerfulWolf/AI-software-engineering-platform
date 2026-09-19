"""Fail-closed guard for integration tests that mutate a MySQL database."""

from __future__ import annotations

import re
from contextlib import closing
from urllib.parse import unquote, urlsplit

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.store.mysql_repository import open_mysql_connection

# Child rows precede their parents. Authority lock rows and unrelated tables survive.
_MUTABLE_FACT_TABLES = (
    "work_queue_accepted_artifacts",
    "work_queue_steps",
    "work_queue_admissions",
    "work_queue_events",
    "work_queue_claims",
    "work_queue_items",
    "verification_reservations",
    "dispatch_commits",
    "dispatch_workforce_snapshots",
    "state_events",
    "tasks",
)


def require_isolated_mysql_test_database(dsn: str) -> str:
    """Return *dsn* only when its database name is explicitly test-scoped.

    Several MySQL integration fixtures reset shared allocation and queue tables.  A
    dedicated database is therefore a correctness boundary, not just a convention.
    Never include the DSN in an error because it may contain credentials.
    """

    try:
        parsed = urlsplit(dsn)
    except ValueError:
        raise pytest.UsageError(
            "ASE_TEST_MYSQL_DSN must name a dedicated test database; refused database '<invalid>'"
        ) from None
    database = unquote(parsed.path.removeprefix("/"))
    valid_name = re.fullmatch(r"[A-Za-z0-9_-]+", database) is not None
    test_scoped = database.startswith("test_") or database.endswith(("_test", "_tests"))
    if parsed.scheme not in {"mysql", "mysql+pymysql"} or not valid_name or not test_scoped:
        safe_name = database if valid_name else "<invalid>"
        raise pytest.UsageError(
            "ASE_TEST_MYSQL_DSN must name a dedicated test database "
            f"(test_*, *_test, or *_tests); refused database {safe_name!r}"
        )
    return dsn


def reset_mysql_test_facts(dsn: str) -> None:
    """Clear known mutable facts in a dedicated serial pytest database.

    Schema initialization remains the responsibility of the real stores. Separate
    pytest processes/workers must receive separate databases.
    """

    require_isolated_mysql_test_database(dsn)
    with closing(open_mysql_connection(dsn)) as connection:
        try:
            with connection.cursor(DictCursor) as cursor:
                cursor.execute(
                    "SELECT TABLE_NAME FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE()"
                )
                present = {row["TABLE_NAME"] for row in cursor.fetchall()}
                for table in _MUTABLE_FACT_TABLES:
                    if table in present:
                        cursor.execute(f"DELETE FROM {table}")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
