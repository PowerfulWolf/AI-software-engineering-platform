"""Repository-wide pytest safety hooks."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import closing
from urllib.parse import unquote, urlsplit, urlunsplit

import pytest

from tests.mysql_safety import require_isolated_mysql_test_database, reset_mysql_test_facts

# Real signals, service supervisors, wall-clock windows and process inspection: these
# files are reliable on their own but flaky under parallel load, so they run serially.
# Full suite: ``pytest -n auto -m "not serial"`` then ``pytest -m serial``.
_SERIAL_FILES = frozenset(
    {
        "tests/test_console_service_script.py",
        "tests/recovery/test_facts_window.py",
        "tests/manager/test_baseline_waiting_cancellation.py",
        "tests/recovery/test_preseed_reentry.py",
        "tests/manager/test_contained_unknown_budget_public.py",
        "tests/web_console/test_fault_retirement.py",
        "tests/web_console/test_controlled_host.py",
        "tests/recovery/test_window_task_builder.py",
        "tests/web_console/test_team_snapshot_coalescing.py",
        "tests/recovery/test_inherited_reapply_entry.py",
        "tests/manager/test_stopped_unknown_budget_public.py",
        "tests/knowledge/test_invocation_native.py",
    }
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    root = config.rootpath
    for item in items:
        if item.path.relative_to(root).as_posix() in _SERIAL_FILES:
            item.add_marker(pytest.mark.serial)


def pytest_configure(config: pytest.Config) -> None:
    """Give each pytest-xdist worker its own MySQL test database.

    The MySQL fixtures reset shared tables, so parallel workers must never share a
    database. Each worker uses ``test_ase_<base>_<worker>``, created on first use.
    """

    del config
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not worker or not dsn:
        return
    require_isolated_mysql_test_database(dsn)
    parsed = urlsplit(dsn)
    base = unquote(parsed.path.removeprefix("/"))
    database = f"test_ase_{base.removeprefix('test_')}_{worker}"[:64]
    from ai_software_engineer.store.mysql_repository import open_mysql_connection

    with closing(open_mysql_connection(dsn)) as connection, connection.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")
        connection.commit()
    os.environ["ASE_TEST_MYSQL_DSN"] = urlunsplit(parsed._replace(path="/" + database))


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


@pytest.fixture(autouse=True)
def no_upstream_transient_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production waits between transient upstream retries; tests run them back to back."""

    monkeypatch.setattr(
        "ai_software_engineer.multi_directory.service._TRANSIENT_BACKOFF_SECONDS",
        (0, 0, 0, 0, 0),
    )
    monkeypatch.setattr("ai_software_engineer.orchestration.retry.TRANSIENT_BACKOFF_SECONDS", ())
