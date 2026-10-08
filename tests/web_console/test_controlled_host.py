from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import uvicorn

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.web_console import host as host_module
from ai_software_engineer.web_console.host import ControlledConsoleServer, _SetupConsole
from ai_software_engineer.web_console.models import CreateRequirementIntent
from ai_software_engineer.web_console.service_lifecycle import (
    ServiceInstance,
    ServiceLifecycleError,
    ServiceLifecycleStore,
    ServiceShutdownAction,
    ServiceShutdownRequest,
    ServiceShutdownResult,
    ServiceState,
)
from ai_software_engineer.web_console.store import FileConsoleOperationStore
from ai_software_engineer.web_console.transport import create_console_app
from tests.web_console.controlled_host_fixture import Reader


def wait_for(predicate: Callable[[], bool], *, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    pytest.fail("controlled service fixture did not reach the expected state")


def unused_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def current_result(store: ServiceLifecycleStore) -> ServiceShutdownResult:
    result = store.read_result()
    assert result is not None
    return result


def test_bind_failure_occurs_before_starting_any_worker(tmp_path: Path) -> None:
    class CountingConsole(_SetupConsole):
        started = False

        def start(self) -> None:
            self.started = True

    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = int(occupied.getsockname()[1])
        console = CountingConsole()
        app = create_console_app(console, Reader(), team_id="team_fixture", port=port)
        server = ControlledConsoleServer(
            uvicorn.Config(app, host="127.0.0.1", port=port),
            lifecycle=ServiceLifecycleStore(tmp_path),
            instance=ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC)),
            coordinator=app.state.console_shutdown,
        )
        with pytest.raises(SystemExit):
            asyncio.run(server.serve())
        assert console.started is False
        assert not (tmp_path / "console-service-instance.json").exists()


def test_startup_record_failure_cannot_start_workers(tmp_path: Path) -> None:
    class CountingConsole(_SetupConsole):
        started = False

        def start(self) -> None:
            self.started = True

    target = tmp_path / "unrelated"
    target.write_text("retained")
    (tmp_path / "console-service-instance.json").symlink_to(target)
    port = unused_port()
    console = CountingConsole()
    app = create_console_app(console, Reader(), team_id="team_fixture", port=port)
    server = ControlledConsoleServer(
        uvicorn.Config(app, host="127.0.0.1", port=port),
        lifecycle=ServiceLifecycleStore(tmp_path),
        instance=ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC)),
        coordinator=app.state.console_shutdown,
    )
    with pytest.raises(ServiceLifecycleError):
        asyncio.run(server.serve())
    assert console.started is False
    assert target.read_text() == "retained"


def test_main_lifecycle_failure_uses_safe_error_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ProductionConfig.default()
    monkeypatch.setattr(
        host_module, "_load_console_config", lambda _: (config, tmp_path / "config")
    )
    app = create_console_app(_SetupConsole(), Reader(), team_id="team_fixture")
    monkeypatch.setattr(host_module, "production_console_app", lambda **_: app)
    monkeypatch.setenv("ASE_SERVICE_STATE_DIR", str(tmp_path))

    def fail(_: ControlledConsoleServer) -> None:
        raise ServiceLifecycleError("private content and local paths")

    monkeypatch.setattr(ControlledConsoleServer, "run", fail)
    with pytest.raises(SystemExit) as error:
        host_module.main()
    assert "服务生命周期记录不可用" in str(error.value)
    assert "private" not in str(error.value)


def test_ready_write_failure_keeps_server_and_write_gate_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_console_app(_SetupConsole(), Reader(), team_id="team_fixture")
    store = ServiceLifecycleStore(tmp_path)
    active = ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC))
    request = ServiceShutdownRequest.new(active, at=datetime.now(UTC))
    coordinator = app.state.console_shutdown
    server = ControlledConsoleServer(
        uvicorn.Config(app), lifecycle=store, instance=active, coordinator=coordinator
    )
    original = store.write_result

    def write(result: ServiceShutdownResult) -> None:
        if result.state is ServiceState.READY:
            raise OSError("private disk error")
        original(result)

    monkeypatch.setattr(store, "write_result", write)
    coordinator.begin_shutdown()
    asyncio.run(server._drain(request))
    assert server.should_exit is False
    assert current_result(store).state is ServiceState.DRAINING
    assert coordinator.cancel_shutdown().state.value == "REFUSED"
    with pytest.raises(RuntimeError, match="安全停止"):
        coordinator.write_gate.acquire_write()


def test_latched_failure_retry_is_immediate_refused_without_draining(tmp_path: Path) -> None:
    app = create_console_app(_SetupConsole(), Reader(), team_id="team_fixture")
    store = ServiceLifecycleStore(tmp_path)
    active = ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC))
    request = ServiceShutdownRequest.new(active, at=datetime.now(UTC))
    coordinator = app.state.console_shutdown
    server = ControlledConsoleServer(
        uvicorn.Config(app), lifecycle=store, instance=active, coordinator=coordinator
    )
    coordinator.begin_shutdown()
    coordinator.record_failure()
    server._start_request(request)
    assert current_result(store).state is ServiceState.REFUSED
    assert current_result(store).matches(request)
    assert server._draining is None
    assert server.should_exit is False


def test_real_signal_drain_keeps_reads_and_durable_native_outcome(tmp_path: Path) -> None:
    port = unused_port()
    store = ServiceLifecycleStore(tmp_path)
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "tests.web_console.controlled_host_fixture",
            str(tmp_path),
            str(port),
        ),
        cwd=Path(__file__).resolve().parents[2],
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        wait_for(lambda: store.read_instance() is not None)
        active = store.read_instance()
        assert active is not None and active.pid == process.pid
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=3) as client:
            response = client.post(
                "/api/v1/operations",
                json={
                    "idempotency_key": "native-fixture-operation",
                    "intent": {
                        "action": "CREATE_REQUIREMENT",
                        "project_id": "project_fixture",
                        "name": "Fixture",
                        "repository_roots": [str(tmp_path)],
                    },
                },
            )
            assert response.status_code == 202
            operation_id = response.json()["operation_id"]
            wait_for(lambda: (tmp_path / "native.pid").exists())
            request = ServiceShutdownRequest.new(active, at=datetime.now(UTC), timeout_seconds=0.2)
            store.write_request(request)
            process.send_signal(signal.SIGTERM)
            wait_for(lambda: store.read_result() is not None)
            assert process.poll() is None
            process.send_signal(signal.SIGINT)
            process.send_signal(signal.SIGTERM)
            assert client.get("/api/v1/console").status_code == 200
            assert client.post("/api/v1/admin/directories/select").status_code == 503
            wait_for(lambda: current_result(store).state is ServiceState.REFUSED)
            result = store.read_result()
            assert result is not None and result.matches(request)
            assert process.poll() is None
            assert not (tmp_path / "actual-outcome.json").exists()
            resumed = ServiceShutdownRequest.new(
                active, at=datetime.now(UTC), action=ServiceShutdownAction.RESUME
            )
            store.write_request(resumed)
            wait_for(lambda: current_result(store).matches(resumed))
            assert current_result(store).state is ServiceState.RUNNING
            (tmp_path / "release").touch()
            wait_for(lambda: (tmp_path / "actual-outcome.json").exists())
            wait_for(
                lambda: (
                    client.get(f"/api/v1/operations/{operation_id}").json()["status"] == "SUCCEEDED"
                )
            )
            retry = ServiceShutdownRequest.new(active, at=datetime.now(UTC), timeout_seconds=3)
            store.write_request(retry)
            wait_for(lambda: current_result(store).matches(retry))
            wait_for(lambda: current_result(store).state is ServiceState.READY)
        assert process.wait(timeout=5) == 0
        outcome = json.loads((tmp_path / "actual-outcome.json").read_text())
        assert outcome["returncode"] == 0
        assert outcome["timed_out"] is False
        assert outcome["process_stop"] is not None
        assert outcome["stdout"] == "finished\n"
        saved = FileConsoleOperationStore(tmp_path / "operations", team_id="team_fixture")
        assert saved.get(operation_id).status == "SUCCEEDED"
    finally:
        (tmp_path / "release").touch()
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_running_identity_write_failure_preserves_real_operation_and_listener(
    tmp_path: Path,
) -> None:
    operations = FileConsoleOperationStore(tmp_path / "operations", team_id="team_fixture")
    operation = operations.submit(
        intent=CreateRequirementIntent(
            project_id="project_fixture", name="Fixture", repository_roots=(str(tmp_path),)
        ),
        idempotency_key="queued-before-running-write-failure",
        requested_at=datetime.now(UTC),
    )
    port = unused_port()
    store = ServiceLifecycleStore(tmp_path)
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "tests.web_console.controlled_host_fixture",
            str(tmp_path),
            str(port),
            "running-write-failure",
        ),
        cwd=Path(__file__).resolve().parents[2],
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        wait_for(lambda: (tmp_path / "native.pid").exists())
        wait_for(lambda: store.read_result() is not None)
        assert current_result(store).state is ServiceState.REFUSED
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=3) as client:
            assert client.get("/api/v1/console").status_code == 200
            assert client.post("/api/v1/admin/directories/select").status_code == 503
            assert process.poll() is None
            assert not (tmp_path / "actual-outcome.json").exists()
            (tmp_path / "release").touch()
            wait_for(lambda: operations.get(operation.operation_id).status.value == "SUCCEEDED")
            assert process.poll() is None
            assert current_result(store).state is ServiceState.REFUSED
            outcome = json.loads((tmp_path / "actual-outcome.json").read_text())
            assert outcome["process_stop"] is not None and outcome["timed_out"] is False
    finally:
        (tmp_path / "release").touch()
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
