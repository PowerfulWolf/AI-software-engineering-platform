"""Exercise MySQL isolation through real pytest setup, call and teardown phases."""

from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.store.mysql_repository import open_mysql_connection
from tests.team_view.test_live import (
    test_active_candidate_verification_is_visible_as_qa_work as leave_active_reservation,
)

pytest_plugins = ("pytester",)


@pytest.fixture
def mysql_pytester(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((str(root), str(root / "src"))))
    pytester.makeini("[pytest]\nmarkers = mysql: isolated MySQL integration test\n")
    pytester.makeconftest("from tests.conftest import *\n")
    return pytester


def assert_no_mysql_facts() -> None:
    with (
        closing(open_mysql_connection(os.environ["ASE_TEST_MYSQL_DSN"])) as connection,
        connection.cursor(DictCursor) as cursor,
    ):
        for table in (
            "verification_reservations",
            "dispatch_commits",
            "dispatch_workforce_snapshots",
            "state_events",
            "tasks",
            "work_queue_events",
            "work_queue_claims",
            "work_queue_items",
        ):
            cursor.execute(f"SELECT COUNT(*) AS count FROM {table}")
            row = cursor.fetchone()
            assert row is not None and row["count"] == 0, table


@pytest.mark.mysql
@pytest.mark.parametrize("outcome", ["pass", "call_failure", "setup_failure"])
def test_mysql_facts_do_not_survive_a_pytest_item(
    mysql_pytester: pytest.Pytester, outcome: str
) -> None:
    mysql_pytester.makepyfile(
        f"""
import os

import pytest

from ai_software_engineer.work_queue import MySqlPersistentWorkQueue, DispatcherTickStatus
from tests.team_view.test_live import (
    test_active_candidate_verification_is_visible_as_qa_work as leave_active_reservation,
)
from tests.work_queue.test_mysql_queue import dispatcher, queued_item, NOW

pytestmark = pytest.mark.mysql


@pytest.fixture
def populated_database(tmp_path):
    leave_active_reservation(tmp_path)
    queue = MySqlPersistentWorkQueue(os.environ["ASE_TEST_MYSQL_DSN"])
    queue.enqueue(queued_item())
    tick = dispatcher(queue, "worker_isolation").tick(now=NOW)
    assert tick.status is DispatcherTickStatus.DISPATCHED
    if {outcome!r} == "setup_failure":
        raise RuntimeError("intentional fixture failure")


def test_producer(populated_database):
    if {outcome!r} == "call_failure":
        raise RuntimeError("intentional test failure")
"""
    )

    result = mysql_pytester.runpytest_subprocess("-q", "--tb=short", timeout=90)

    result.assert_outcomes(
        passed=int(outcome == "pass"),
        failed=int(outcome == "call_failure"),
        errors=int(outcome == "setup_failure"),
    )
    if outcome != "pass":
        message = (
            "intentional fixture failure"
            if outcome == "setup_failure"
            else "intentional test failure"
        )
        assert message in result.stdout.str()
    # No subsequent pytest item has had an opportunity to hide missing teardown.
    assert_no_mysql_facts()


@pytest.mark.mysql
def test_mysql_setup_clears_facts_from_an_interrupted_session(
    mysql_pytester: pytest.Pytester, tmp_path: Path
) -> None:
    leave_active_reservation(tmp_path)
    with pytest.raises(AssertionError, match="verification_reservations"):
        assert_no_mysql_facts()
    mysql_pytester.makepyfile(
        """
import pytest
from tests.test_mysql_test_isolation import assert_no_mysql_facts

@pytest.mark.mysql
def test_first_item_sees_no_previous_facts():
    assert_no_mysql_facts()
"""
    )

    result = mysql_pytester.runpytest_subprocess("-q", "--tb=short", timeout=90)

    result.assert_outcomes(passed=1)


def test_mysql_guard_aborts_before_dependent_fixtures(
    mysql_pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASE_TEST_MYSQL_DSN", "mysql://ase:do-not-print@127.0.0.1/production")
    mysql_pytester.makepyfile(
        """
from pathlib import Path
import pytest

@pytest.fixture
def forbidden_fixture():
    Path("fixture-ran").touch()

@pytest.mark.mysql
def test_rejected(forbidden_fixture):
    pass
"""
    )

    result = mysql_pytester.runpytest_subprocess("-q", "--tb=short", timeout=30)

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert not (mysql_pytester.path / "fixture-ran").exists()
    output = result.stdout.str() + result.stderr.str()
    assert "production" in output
    assert "do-not-print" not in output
