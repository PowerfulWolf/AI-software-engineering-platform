"""Safe lease guard diagnostics do not retain database exceptions or widen authority."""

from datetime import UTC, datetime, timedelta
from threading import Thread
from typing import cast

import pytest

from ai_software_engineer.agents.execution import ExecutionAuthorityLost
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.ports import QueueConflict, QueueLeaseLost
from ai_software_engineer.work_queue.worker import WorkerLease
from tests.domain.factories import make_task
from tests.orchestration.test_native_continuation import claim


def _lease(queue: object = None) -> WorkerLease:
    lease = WorkerLease(cast(MySqlRoleQueue, queue), claim(make_task(), 1), "private-token")
    lease._expires_at = datetime.now(UTC) + timedelta(minutes=1)
    return lease


def test_local_expiry_is_a_sticky_safe_authority_fact() -> None:
    lease = _lease()
    lease._expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(QueueLeaseLost) as captured:
        lease.check()
    error = captured.value
    assert isinstance(error, ExecutionAuthorityLost)
    assert isinstance(error, QueueConflict)
    assert error.execution_abort_reason.to_wire() == {
        "kind": "lease_authority_unconfirmed",
        "detail": "local_expiry",
    }
    lease._expires_at = datetime.now(UTC) + timedelta(minutes=1)
    with pytest.raises(QueueLeaseLost) as repeated:
        lease.check()
    assert repeated.value.execution_abort_reason == error.execution_abort_reason


def test_renewal_exception_retains_only_fixed_detail() -> None:
    class FailedRenewal:
        def renew(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("mysql://operator:private-dsn-secret@localhost/private")

    lease = _lease(FailedRenewal())
    lease._ttl = timedelta(milliseconds=30)
    lease._heartbeat()
    with pytest.raises(QueueLeaseLost) as captured:
        lease.check()
    assert captured.value.execution_abort_reason.to_wire() == {
        "kind": "lease_authority_unconfirmed",
        "detail": "renewal_exception",
    }
    assert not any(isinstance(value, BaseException) for value in vars(lease).values())
    assert "private-dsn-secret" not in repr(vars(lease))
    assert "private-dsn-secret" not in str(captured.value)


def test_heartbeat_stop_timeout_has_its_own_safe_detail() -> None:
    class UnfinishedHeartbeat:
        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float) -> None:
            assert timeout == 35

    lease = _lease()
    lease._thread = cast(Thread, UnfinishedHeartbeat())
    with pytest.raises(QueueLeaseLost) as captured:
        lease.stop()
    assert captured.value.execution_abort_reason.detail == "heartbeat_stop_timeout"
    with pytest.raises(QueueLeaseLost):
        lease.check()


def test_unknown_lease_loss_does_not_fabricate_local_expiry_or_exception() -> None:
    lease = _lease()
    lease._lost.set()
    with pytest.raises(QueueLeaseLost) as captured:
        lease.check()
    assert captured.value.execution_abort_reason.to_wire() == {
        "kind": "lease_authority_unconfirmed"
    }
