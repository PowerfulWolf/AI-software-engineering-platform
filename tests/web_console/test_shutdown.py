from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from pydantic import ValidationError

from ai_software_engineer.web_console.shutdown import (
    ServiceDraining,
    ServiceWriteGate,
    ShutdownResult,
    ShutdownState,
)


def test_gate_refuses_new_writes_and_waits_for_existing_writer() -> None:
    gate = ServiceWriteGate()
    lease = gate.acquire_write()
    assert gate.begin_shutdown().state is ShutdownState.DRAINING
    with pytest.raises(ServiceDraining, match="安全停止"):
        gate.acquire_write()
    refused = gate.await_shutdown(0)
    assert refused.state is ShutdownState.REFUSED
    assert refused.active_writes == 1
    lease.release()
    assert gate.await_shutdown(0).state is ShutdownState.READY
    assert gate.begin_shutdown().state is ShutdownState.READY
    with pytest.raises(ServiceDraining):
        gate.acquire_write()


def test_retained_worker_keeps_write_live_after_http_caller_releases() -> None:
    gate = ServiceWriteGate()
    with gate.enter() as request:
        gate.begin_shutdown()
        worker = request.retain()
        assert gate.shutdown_status().active_writes == 2
    assert gate.await_shutdown(0).state is ShutdownState.REFUSED
    assert gate.shutdown_status().active_writes == 1
    worker.release()
    worker.release()
    assert gate.await_shutdown(0).state is ShutdownState.READY
    with pytest.raises(RuntimeError, match="released"):
        request.retain()


def test_writer_failure_releases_scope_without_suppressing_error() -> None:
    gate = ServiceWriteGate()
    with pytest.raises(ValueError, match="bad input"), gate.enter():
        raise ValueError("bad input")
    gate.begin_shutdown()
    assert gate.await_shutdown(0).state is ShutdownState.READY


def test_gate_cancel_resumes_admission_and_wakes_shutdown_waiter() -> None:
    gate = ServiceWriteGate()
    writer = gate.acquire_write()
    gate.begin_shutdown()
    started = Event()

    def await_ready() -> ShutdownResult:
        started.set()
        return gate.await_shutdown(1)

    with ThreadPoolExecutor(max_workers=1) as pool:
        wait = pool.submit(await_ready)
        assert started.wait(1)
        assert gate.cancel_shutdown().state is ShutdownState.RUNNING
        assert wait.result(timeout=1).state is ShutdownState.RUNNING
    with gate.enter():
        assert gate.shutdown_status().active_writes == 2
    writer.release()
    gate.begin_shutdown()
    assert gate.await_shutdown(0).state is ShutdownState.READY


def test_readiness_requires_explicit_shutdown_request() -> None:
    gate = ServiceWriteGate()
    assert gate.await_shutdown(0).state is ShutdownState.RUNNING
    assert gate.shutdown_status().state is ShutdownState.RUNNING


@pytest.mark.parametrize("timeout", [-1, float("inf"), float("nan")])
def test_gate_rejects_invalid_deadline(timeout: float) -> None:
    gate = ServiceWriteGate()
    with pytest.raises(ValueError):
        gate.await_shutdown(timeout)


def test_shutdown_result_rejects_unknown_or_negative_facts() -> None:
    with pytest.raises(ValidationError):
        ShutdownResult.model_validate({"state": "STOPPED", "safe_summary": "Unsupported"})
    with pytest.raises(ValidationError):
        ShutdownResult(state=ShutdownState.READY, safe_summary="Ready", active_writes=-1)
    with pytest.raises(ValidationError):
        ShutdownResult(state=ShutdownState.READY, safe_summary="Ready", active_operations=1)
