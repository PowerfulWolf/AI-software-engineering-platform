"""Regression tests for the MySQL integration-test database guard."""

from __future__ import annotations

import pytest

from tests.mysql_safety import require_isolated_mysql_test_database, reset_mysql_test_facts


@pytest.mark.parametrize(
    "database",
    ("ase_self_iteration", "production", "staging_copy"),
)
def test_mysql_test_guard_rejects_non_test_database(database: str) -> None:
    dsn = f"mysql+pymysql://ase:secret@127.0.0.1:3307/{database}"

    with pytest.raises(pytest.UsageError, match=database):
        require_isolated_mysql_test_database(dsn)


@pytest.mark.parametrize(
    "database",
    ("ase_self_iteration_test", "test_ase", "platform_tests"),
)
def test_mysql_test_guard_accepts_explicit_test_database(database: str) -> None:
    dsn = f"mysql+pymysql://ase:secret@127.0.0.1:3307/{database}"

    assert require_isolated_mysql_test_database(dsn) == dsn


def test_mysql_test_guard_does_not_leak_credentials() -> None:
    dsn = "mysql+pymysql://ase:do-not-print@127.0.0.1:3307/production"

    with pytest.raises(pytest.UsageError) as caught:
        require_isolated_mysql_test_database(dsn)

    assert "do-not-print" not in str(caught.value)


def test_mysql_test_guard_does_not_echo_unsafe_database_text() -> None:
    dsn = "mysql+pymysql://ase:secret@127.0.0.1:3307/prod%0Asecret"

    with pytest.raises(pytest.UsageError) as caught:
        require_isolated_mysql_test_database(dsn)

    assert "prod" not in str(caught.value)
    assert "secret" not in str(caught.value)


def test_mysql_test_guard_bounds_malformed_dsn_error() -> None:
    dsn = "mysql+pymysql://ase:do-not-print@[invalid/production"

    with pytest.raises(pytest.UsageError, match="<invalid>") as caught:
        require_isolated_mysql_test_database(dsn)

    assert "do-not-print" not in str(caught.value)


def test_mysql_reset_rejects_non_test_database_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_connection(_dsn: str) -> None:
        pytest.fail("invalid test database must be rejected before connecting")

    monkeypatch.setattr("tests.mysql_safety.open_mysql_connection", forbidden_connection)

    with pytest.raises(pytest.UsageError, match="production"):
        reset_mysql_test_facts("mysql://ase:do-not-print@127.0.0.1/production")
