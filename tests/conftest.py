"""Repository-wide pytest safety hooks."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from tests.mysql_safety import require_isolated_mysql_test_database, reset_mysql_test_facts


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


@pytest.fixture(autouse=True)
def isolated_mysql_facts(request: pytest.FixtureRequest) -> Iterator[None]:
    """Bound persistent facts to one test, including failed fixture/test bodies."""

    if request.node.get_closest_marker("mysql") is None:
        yield
        return
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    reset_mysql_test_facts(dsn)
    try:
        yield
    finally:
        reset_mysql_test_facts(dsn)
