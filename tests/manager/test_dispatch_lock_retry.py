"""Parallel dispatch retries authority-row lock contention instead of blocking."""

from __future__ import annotations

import pymysql
import pytest

from ai_software_engineer.manager import mysql_dispatch_authority as authority
from ai_software_engineer.manager.dispatch import DispatchStoreUnavailable


def _unavailable(code: int) -> DispatchStoreUnavailable:
    error = DispatchStoreUnavailable("MySQL dispatch transaction failed")
    error.__cause__ = pymysql.err.OperationalError(code, "lock")
    return error


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(authority.time, "sleep", lambda _: None)


@pytest.mark.parametrize("code", [1205, 1213])
def test_lock_contention_is_retried_until_it_clears(code: int) -> None:
    calls = []

    @authority._retry_lock_contention
    def commit() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise _unavailable(code)
        return "committed"

    assert commit() == "committed" and len(calls) == 3


def test_other_store_failures_are_not_retried() -> None:
    calls = []

    @authority._retry_lock_contention
    def commit() -> str:
        calls.append(1)
        raise _unavailable(2013)

    with pytest.raises(DispatchStoreUnavailable):
        commit()
    assert len(calls) == 1


def test_persistent_contention_still_fails_closed() -> None:
    calls = []

    @authority._retry_lock_contention
    def commit() -> str:
        calls.append(1)
        raise _unavailable(1205)

    with pytest.raises(DispatchStoreUnavailable):
        commit()
    assert len(calls) == len(authority._LOCK_RETRY_DELAYS) + 1
