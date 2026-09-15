"""Repository-wide pytest safety hooks."""

from __future__ import annotations

import os

import pytest

from tests.mysql_safety import require_isolated_mysql_test_database


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Reject a production-like MySQL DSN before any MySQL fixture can run."""

    if item.get_closest_marker("mysql") is None:
        return
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if dsn:
        try:
            require_isolated_mysql_test_database(dsn)
        except pytest.UsageError as error:
            pytest.exit(str(error), returncode=4)
