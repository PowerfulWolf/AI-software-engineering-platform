from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.web_console.core import ProjectConsole
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
    ServiceDraining,
    ServiceWriteGate,
    ShutdownState,
)
from ai_software_engineer.web_console.store import InMemoryConsoleOperationStore
from tests.web_console.test_core import _create_intent, _Executor

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def instance() -> ServiceInstance:
    return ServiceInstance.new(pid=os.getpid(), at=NOW)


def test_private_lifecycle_roundtrip_and_nonce_binding(tmp_path: Path) -> None:
    store = ServiceLifecycleStore(tmp_path)
    active = instance()
    request = ServiceShutdownRequest.new(active, at=NOW, timeout_seconds=20)
    result = ServiceShutdownResult.for_request(request, state=ServiceState.DRAINING, at=NOW)
    store.publish_instance(active)
    store.write_request(request)
    store.write_result(result)
    assert store.read_instance() == active
    assert store.read_request() == request
    assert store.read_result() == result
    assert request.matches(active)
    assert result.matches(request)
    assert not request.matches(instance())
    for name in store.FILENAMES:
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600


@pytest.mark.parametrize("name", ServiceLifecycleStore.FILENAMES)
def test_private_lifecycle_refuses_symlinks(tmp_path: Path, name: str) -> None:
    target = tmp_path / "outside.json"
    target.write_text("{}")
    (tmp_path / name).symlink_to(target)
    store = ServiceLifecycleStore(tmp_path)
    readers = {
        "console-service-instance.json": store.read_instance,
        "console-service-shutdown.request.json": store.read_request,
        "console-service-shutdown.result.json": store.read_result,
    }
    with pytest.raises(ServiceLifecycleError):
        readers[name]()
    assert target.read_text() == "{}"


def test_lifecycle_rejects_nonprivate_and_oversized_records(tmp_path: Path) -> None:
    store = ServiceLifecycleStore(tmp_path)
    path = tmp_path / "console-service-instance.json"
    path.write_text(instance().model_dump_json())
    path.chmod(0o644)
    with pytest.raises(ServiceLifecycleError):
        store.read_instance()
    path.chmod(0o600)
    path.write_bytes(b"x" * (ServiceLifecycleStore.MAX_BYTES + 1))
    with pytest.raises(ServiceLifecycleError):
        store.read_instance()


def test_lifecycle_rejects_replacing_symlink(tmp_path: Path) -> None:
    store = ServiceLifecycleStore(tmp_path)
    target = tmp_path / "outside.json"
    target.write_text("retained")
    (tmp_path / "console-service-instance.json").symlink_to(target)
    with pytest.raises(ServiceLifecycleError):
        store.publish_instance(instance())
    assert target.read_text() == "retained"


def test_index_resume_failure_cannot_publish_running_or_open_dispatch(tmp_path: Path) -> None:
    class FailingIndex:
        shutdown_failed = False

        def begin_shutdown(self) -> None:
            pass

        def close(self, *, timeout: float = 5.0) -> bool:
            return False

        def cancel_shutdown(self) -> None:
            raise RuntimeError("private thread resource failure")

    console = ProjectConsole(store=InMemoryConsoleOperationStore("team_test"), executor=_Executor())
    coordinator = ConsoleShutdownCoordinator(
        console=console, write_gate=ServiceWriteGate(), knowledge_worker=FailingIndex()
    )
    coordinator.begin_shutdown()
    assert coordinator.await_shutdown(0).state is ShutdownState.REFUSED
    recorded: list[str] = []

    def callback() -> None:
        recorded.append("RUNNING")

    assert coordinator.cancel_shutdown(before_resume=callback).state is ShutdownState.REFUSED
    assert recorded == []
    assert console.run_once() is None
    with pytest.raises(RuntimeError, match="安全停止"):
        console.submit(_create_intent(tmp_path), idempotency_key="after-index-resume-failure")
    with pytest.raises(ServiceDraining):
        coordinator.write_gate.acquire_write()


def test_latched_shutdown_failure_stays_refused_on_repeated_begin() -> None:
    console = ProjectConsole(store=InMemoryConsoleOperationStore("team_test"), executor=_Executor())
    coordinator = ConsoleShutdownCoordinator(console=console, write_gate=ServiceWriteGate())
    coordinator.begin_shutdown()
    coordinator.record_failure()
    for _ in range(3):
        assert coordinator.begin_shutdown().state is ShutdownState.REFUSED
        assert coordinator.shutdown_status().state is ShutdownState.REFUSED
        with pytest.raises(ServiceDraining):
            coordinator.write_gate.acquire_write()
    assert coordinator.await_shutdown(0).state is ShutdownState.REFUSED
    assert coordinator.cancel_shutdown().state is ShutdownState.REFUSED
