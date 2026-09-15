"""Fail-closed guard for integration tests that mutate a MySQL database."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

import pytest


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
