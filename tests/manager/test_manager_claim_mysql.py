"""Dedicated test DB only: real owner fencing and immutable coordination records."""

import os
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest

from ai_software_engineer.manager.model_execution import (
    ManagerExecutionRejected,
    MySqlManagerClaimAuthority,
)
from ai_software_engineer.manager.model_store import MySqlManagerRecordStore
from tests.manager.test_manager_model_execution import Proposal, executor, invoke, ok
from tests.mysql_safety import require_isolated_mysql_test_database

pytestmark = pytest.mark.mysql


def test_manager_claim_serializes_and_fences_record_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    dsn = require_isolated_mysql_test_database(dsn)
    runner = executor(tmp_path)
    runner.scope = runner.scope.model_copy(update={"team_id": "team_manager_test_" + uuid4().hex})
    store = MySqlManagerRecordStore(dsn, runner.scope.team_id)
    authority = MySqlManagerClaimAuthority(dsn)
    proposal = Proposal(action="WAITING_HUMAN")
    with pytest.raises(ValueError, match="owned"):
        store.put("test", "absent-owner", proposal)
    with authority.claim(runner.scope, seconds=30) as guard:
        with pytest.raises(ManagerExecutionRejected), authority.claim(runner.scope, seconds=30):
            pytest.fail("second owner admitted")
        with guard.write_scope():
            store.put("test", "committed", proposal)
        with pytest.raises(RuntimeError, match="post-write loss"), guard.write_scope():
            store.put("test", "rolled-back", proposal)
            raise RuntimeError("post-write loss")
    assert store.find("test", "committed", Proposal) == proposal
    assert store.find("test", "rolled-back", Proposal) is None
    for fail_at in (1, 2):
        with authority.claim(runner.scope, seconds=30) as guard:
            original_check = guard.check
            checks = 0

            def lose_ownership(
                check: Callable[[], None] = original_check, fail_index: int = fail_at
            ) -> None:
                nonlocal checks
                checks += 1
                check()
                if checks == fail_index:
                    raise ManagerExecutionRejected("injected owner loss")

            monkeypatch.setattr(guard, "check", lose_ownership)
            with pytest.raises(ManagerExecutionRejected), guard.write_scope():
                store.put("test", f"fenced-{fail_at}", proposal)
        assert store.find("test", f"fenced-{fail_at}", Proposal) is None
    runner.authority = authority
    runner.store = store
    from unittest.mock import Mock

    client = Mock()
    client.complete.return_value = ok()
    assert invoke(runner, client)[0] == proposal
    runner.store = MySqlManagerRecordStore(dsn, runner.scope.team_id)
    assert invoke(runner, client)[0] == proposal
    client.complete.assert_called_once()
