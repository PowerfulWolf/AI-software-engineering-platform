"""Guard revocation seals only safe real native-stop facts beyond the owner fence."""

import fcntl
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents import CodexCliAgentAdapter, CodexInvocationResult
from ai_software_engineer.agents.codex_cli import (
    SubprocessCodexCommandRunner,
    _classify_cli_failure,
    _failure_diagnostic,
)
from ai_software_engineer.agents.execution import ExecutionAbortReason
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.owned_sessions import require_recorded_session_empty
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.ports import QueueLeaseLost
from ai_software_engineer.work_queue.worker import WorkerLease
from tests.agents.test_openai_compatible import StaticPromptBuilder
from tests.git.test_worktree import _git
from tests.orchestration.test_native_continuation import Fixture, Guard


def test_only_trusted_guard_reason_distinguishes_revocation_from_a_signal() -> None:
    signalled = CodexInvocationResult(returncode=-15, stderr="Error: unauthorized")
    assert _classify_cli_failure(signalled) == (AgentErrorCode.PROVIDER_ERROR, False)
    assert "cause=INTERRUPTED" in _failure_diagnostic(signalled)
    revoked = CodexInvocationResult(
        returncode=-15,
        stderr="Error: unauthorized",
        execution_abort_reason=ExecutionAbortReason(detail="renewal_exception"),
    )
    assert _classify_cli_failure(revoked) == (AgentErrorCode.WORK_INTERRUPTED, False)
    assert "cause=LEASE_AUTHORITY_UNCONFIRMED" in _failure_diagnostic(revoked)


def test_expired_guard_stops_real_native_process_and_seals_safe_fact_only(tmp_path: Path) -> None:
    descriptor = os.open(tmp_path / "original.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    guard = Guard(descriptor)
    fixture = Fixture(tmp_path, guard)
    lease = WorkerLease(cast(MySqlRoleQueue, object()), fixture.claim, "private-owner-token")
    # This test starts no heartbeat or database. A real local expiry removes the
    # native runner's authority while its original Task lock remains held.
    lease._expires_at = datetime.now(UTC) + timedelta(minutes=1)
    draft = fixture.worktree.path / "src/app.py"
    original_check = guard.check

    def check() -> None:
        original_check()
        if draft.read_text() == "VALUE = 27\n":
            lease._expires_at = datetime.now(UTC) - timedelta(seconds=1)
        lease.check()

    guard.check = check  # type: ignore[method-assign]

    class FixtureRunner(SubprocessCodexCommandRunner):
        def run_observed(
            self,
            argv: tuple[str, ...],
            *,
            cwd: Path,
            environment: Mapping[str, str],
            stdin: str,
            timeout_seconds: float,
            observer: Callable[[CodexInvocationResult], None],
        ) -> CodexInvocationResult:
            return super().run_observed(
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import time; "
                    "Path('src/app.py').write_text('VALUE = 27\\n'); time.sleep(10)",
                ),
                cwd=cwd,
                environment=environment,
                stdin=stdin,
                timeout_seconds=timeout_seconds,
                observer=observer,
            )

    before_task = fixture.repository.get(fixture.task.id)
    before_events = fixture.repository.list_events(fixture.task.id)
    original_head = _git(fixture.worktree.path, "rev-parse", "HEAD")
    adapter = CodexCliAgentAdapter(
        workspace_root=fixture.worktree.path,
        model="offline-native-fixture",
        agent_id="agent_native_coder",
        agent_version="v1",
        prompt_builder=StaticPromptBuilder(),
        environment={"PATH": os.environ["PATH"]},
        runner=FixtureRunner(guard),
        execution_guard=guard,
        interruption_control=fixture.service(),
    )
    try:
        with pytest.raises(QueueLeaseLost):
            adapter.run(fixture.request)
        stop = fixture.store.capture_stop(fixture.request.run_id)
        stop.validate_integrity()
        assert stop.process_stop.returncode < 0
        assert stop.process_stop.kind == "failed"
        proof = stop.process_stop.session_proof
        assert proof is not None
        require_recorded_session_empty(proof)
        assert stop.execution_abort_reason is not None
        assert stop.execution_abort_reason.kind == "lease_authority_unconfirmed"
        assert stop.execution_abort_reason.detail == "local_expiry"
        assert stop.original_error_code is AgentErrorCode.WORK_INTERRUPTED
        assert stop.cause is None and not stop.output_present
        assert draft.read_text() == "VALUE = 27\n"
        inventory = capture_mutation_inventory(fixture.worktree.path)
        assert tuple(item.path for item in inventory.files if item.path == "src/app.py")
        assert _git(fixture.worktree.path, "rev-parse", "HEAD") == original_head
        assert fixture.repository.get(fixture.task.id) == before_task
        assert fixture.repository.list_events(fixture.task.id) == before_events
        assert fixture.store.receipts_for_task(fixture.task.id) == ()
        assert not adapter._results, "lost authority must not publish or cache a result"
    finally:
        fixture.repository.close()
        os.close(descriptor)
