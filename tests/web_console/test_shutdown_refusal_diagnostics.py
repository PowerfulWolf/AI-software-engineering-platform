from __future__ import annotations

import asyncio
import json
import os
import runpy
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
import uvicorn
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.web_console.core import ProjectConsole
from ai_software_engineer.web_console.host import ControlledConsoleServer
from ai_software_engineer.web_console.service_lifecycle import (
    ConsoleShutdownCoordinator,
    ServiceInstance,
    ServiceLifecycleError,
    ServiceLifecycleStore,
    ServiceShutdownRequest,
    ServiceShutdownResult,
    ServiceState,
)
from ai_software_engineer.web_console.shutdown import (
    ServiceWriteGate,
    ShutdownRefusal,
    ShutdownResult,
    ShutdownState,
)
from ai_software_engineer.web_console.store import InMemoryConsoleOperationStore
from tests.web_console.test_core import _Executor


class _UnconfirmedOwned:
    shutdown_failed = True

    def operation_scope(self, operation_id: str) -> AbstractContextManager[None]:
        return nullcontext()

    def await_stopped(self, timeout_seconds: float) -> bool:
        return False


def test_owned_refusal_survives_coordinator_and_repeated_begin() -> None:
    console = ProjectConsole(store=InMemoryConsoleOperationStore("team_test"), executor=_Executor())
    coordinator = ConsoleShutdownCoordinator(
        console=console, write_gate=ServiceWriteGate(), owned_processes=_UnconfirmedOwned()
    )
    coordinator.begin_shutdown()
    result = coordinator.await_shutdown(0)
    assert result.state is ShutdownState.REFUSED
    refusal = getattr(result, "refusal", None)
    assert refusal is not None, "真实执行核验拒绝不能在coordinator边界丢失原因"
    assert refusal.component == "OWNED_PROCESSES"
    assert refusal.reason == "UNCONFIRMED"
    assert coordinator.begin_shutdown().refusal == refusal
    assert coordinator.shutdown_status().refusal == refusal
    assert coordinator.cancel_shutdown().refusal == refusal


def _console() -> ProjectConsole:
    return ProjectConsole(store=InMemoryConsoleOperationStore("team_test"), executor=_Executor())


def test_actual_writer_timeout_has_count_and_later_ready_clears_diagnostic() -> None:
    gate = ServiceWriteGate()
    writer = gate.acquire_write()
    coordinator = ConsoleShutdownCoordinator(console=_console(), write_gate=gate)
    coordinator.begin_shutdown()
    result = coordinator.await_shutdown(0)
    assert result.refusal == ShutdownRefusal(
        component="WRITE_GATE", reason="TIMEOUT", active_count=1
    )
    writer.release()
    ready = coordinator.await_shutdown(0)
    assert ready.state is ShutdownState.READY
    assert ready.refusal is None


@pytest.mark.parametrize("failed", [False, True])
def test_index_wait_and_unknown_save_are_distinct(failed: bool) -> None:
    class Index:
        shutdown_failed = failed

        def begin_shutdown(self) -> None:
            pass

        def close(self, *, timeout: float = 5.0) -> bool:
            return False

        def cancel_shutdown(self) -> None:
            pass

    coordinator = ConsoleShutdownCoordinator(
        console=_console(), write_gate=ServiceWriteGate(), knowledge_worker=Index()
    )
    coordinator.begin_shutdown()
    refusal = coordinator.await_shutdown(0).refusal
    assert refusal == ShutdownRefusal(
        component="KNOWLEDGE_INDEX", reason="UNCONFIRMED" if failed else "TIMEOUT"
    )
    if failed:
        assert coordinator.begin_shutdown().refusal == refusal


def test_owned_timeout_is_retryable_only_after_real_port_reports_empty() -> None:
    class PendingOwned(_UnconfirmedOwned):
        shutdown_failed = False
        empty = False

        def await_stopped(self, timeout_seconds: float) -> bool:
            return self.empty

    owned = PendingOwned()
    coordinator = ConsoleShutdownCoordinator(
        console=_console(), write_gate=ServiceWriteGate(), owned_processes=owned
    )
    coordinator.begin_shutdown()
    refusal = coordinator.await_shutdown(0).refusal
    assert refusal == ShutdownRefusal(component="OWNED_PROCESSES", reason="TIMEOUT")
    owned.empty = True
    assert coordinator.await_shutdown(0).state is ShutdownState.READY


def test_component_exception_retains_phase_without_private_error() -> None:
    class BrokenOwned(_UnconfirmedOwned):
        def await_stopped(self, timeout_seconds: float) -> bool:
            raise OSError("private-provider-secret-and-path")

    coordinator = ConsoleShutdownCoordinator(
        console=_console(), write_gate=ServiceWriteGate(), owned_processes=BrokenOwned()
    )
    coordinator.begin_shutdown()
    result = coordinator.await_shutdown(0)
    assert result.refusal == ShutdownRefusal(component="OWNED_PROCESSES", reason="COMPONENT_ERROR")
    assert "private" not in result.model_dump_json()
    assert coordinator.begin_shutdown().refusal == result.refusal


def test_cancel_keeps_console_first_unconfirmed_reason_before_owned_failure() -> None:
    class UnsavedConsole(ProjectConsole):
        def await_shutdown(self, timeout: float) -> ShutdownResult:
            return ShutdownResult(
                state=ShutdownState.REFUSED,
                safe_summary="操作最终记录未核验。",
                refusal=ShutdownRefusal(component="CONSOLE", reason="UNCONFIRMED", active_count=0),
            )

    console = UnsavedConsole(store=InMemoryConsoleOperationStore("team_test"), executor=_Executor())
    coordinator = ConsoleShutdownCoordinator(
        console=console, write_gate=ServiceWriteGate(), owned_processes=_UnconfirmedOwned()
    )
    coordinator.begin_shutdown()
    first = coordinator.await_shutdown(0).refusal
    assert first is not None and first.component == "CONSOLE"
    assert coordinator.cancel_shutdown().refusal == first
    assert coordinator.begin_shutdown().refusal == first


def test_new_unconfirmed_cause_replaces_an_earlier_retriable_timeout() -> None:
    gate = ServiceWriteGate()
    writer = gate.acquire_write()
    coordinator = ConsoleShutdownCoordinator(
        console=_console(), write_gate=gate, owned_processes=_UnconfirmedOwned()
    )
    coordinator.begin_shutdown()
    assert coordinator.await_shutdown(0).refusal == ShutdownRefusal(
        component="WRITE_GATE", reason="TIMEOUT", active_count=1
    )
    writer.release()
    refusal = coordinator.cancel_shutdown().refusal
    assert refusal == ShutdownRefusal(component="OWNED_PROCESSES", reason="UNCONFIRMED")
    assert coordinator.begin_shutdown().refusal == refusal


def test_startup_watcher_uses_one_state_and_refusal_snapshot(tmp_path: Path) -> None:
    class ChangingCoordinator(ConsoleShutdownCoordinator):
        reads = 0

        def shutdown_status(self) -> ShutdownResult:
            self.reads += 1
            if self.reads == 1:
                return ShutdownResult(state=ShutdownState.DRAINING, safe_summary="正在收尾。")
            return ShutdownResult(
                state=ShutdownState.REFUSED,
                safe_summary="拒绝替换。",
                refusal=ShutdownRefusal(component="OWNED_PROCESSES", reason="UNCONFIRMED"),
            )

    coordinator = ChangingCoordinator(console=_console(), write_gate=ServiceWriteGate())
    active = ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC))
    request = ServiceShutdownRequest.new(active, at=datetime.now(UTC))
    store = ServiceLifecycleStore(tmp_path)
    server = ControlledConsoleServer(
        uvicorn.Config("unused:app"), lifecycle=store, instance=active, coordinator=coordinator
    )
    publish = server._publish

    def end_after_one_publish(
        request: ServiceShutdownRequest,
        state: ServiceState,
        *,
        refusal: ShutdownRefusal | None = None,
    ) -> None:
        publish(request, state, refusal=refusal)
        server.started = True

    server._publish = end_after_one_publish  # type: ignore[method-assign]
    asyncio.run(server._watch_startup_drain(request))
    assert coordinator.reads == 1
    result = store.read_result()
    assert result is not None and result.state is ServiceState.DRAINING
    assert result.refusal is None


def test_real_host_publishes_same_refusal_for_new_request_and_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ServiceLifecycleStore(tmp_path)
    active = ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC))
    coordinator = ConsoleShutdownCoordinator(
        console=_console(), write_gate=ServiceWriteGate(), owned_processes=_UnconfirmedOwned()
    )
    server = ControlledConsoleServer(
        uvicorn.Config("unused:app"), lifecycle=store, instance=active, coordinator=coordinator
    )
    request = ServiceShutdownRequest.new(active, at=datetime.now(UTC))
    store.write_request(request)
    coordinator.begin_shutdown()
    asyncio.run(server._drain(request))
    first = store.read_result()
    assert first is not None and first.refusal is not None
    assert first.matches(request)
    assert server.should_exit is False
    assert store.read_instance() is not None

    latest = ServiceShutdownRequest.new(active, at=datetime.now(UTC))
    store.write_request(latest)
    server._start_request(latest)
    second = store.read_result()
    assert second is not None and second.matches(latest)
    assert second.refusal == first.refusal
    assert server.should_exit is False

    script = Path(__file__).resolve().parents[2] / "scripts" / "ase-console-lifecycle.py"
    namespace = runpy.run_path(str(script))
    wait = cast(Callable[[ServiceLifecycleStore, int, str], None], namespace["wait"])
    with pytest.raises(ServiceLifecycleError, match="重复等待不能补齐事实"):
        wait(store, active.pid, latest.request_id)
    monkeypatch.setenv("ASE_SERVICE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [str(script), "status", str(active.pid)])
    assert cast(Callable[[], int], namespace["main"])() == 0
    assert "服务拥有的执行进程与记录" in capsys.readouterr().out


def test_legacy_wire_omits_optional_diagnostic_and_schema_accepts_both() -> None:
    active = ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC))
    request = ServiceShutdownRequest.new(active, at=datetime.now(UTC))
    legacy = ServiceShutdownResult.for_request(
        request, state=ServiceState.REFUSED, at=datetime.now(UTC)
    )
    assert "refusal" not in legacy.to_wire()
    assert ServiceShutdownResult.model_validate(legacy.to_wire()) == legacy
    current = ServiceShutdownResult.for_request(
        request,
        state=ServiceState.REFUSED,
        at=datetime.now(UTC),
        refusal=ShutdownRefusal(component="OWNED_PROCESSES", reason="UNCONFIRMED"),
    )
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "schemas"
            / "console-service-shutdown-result.schema.json"
        ).read_text()
    )
    for value in (legacy, current):
        Draft202012Validator(schema).validate(value.to_wire())
        assert ServiceShutdownResult.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("state", [ServiceState.READY, ServiceState.RUNNING, ServiceState.DRAINING])
def test_diagnostic_cannot_be_attached_to_nonrefused_state(state: ServiceState) -> None:
    active = ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC))
    request = ServiceShutdownRequest.new(active, at=datetime.now(UTC))
    with pytest.raises(ValidationError, match="only explain REFUSED"):
        ServiceShutdownResult.for_request(
            request,
            state=state,
            at=datetime.now(UTC),
            refusal=ShutdownRefusal(component="CONSOLE", reason="UNCONFIRMED"),
        )
