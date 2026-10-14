"""Console pause completes real execution and final saves before permitting restart."""

import os
import sys
from pathlib import Path
from threading import Event

import pytest

from ai_software_engineer.agents.codex_cli import SubprocessCodexCommandRunner
from ai_software_engineer.owned_processes import HostOwnedProcessRegistry
from ai_software_engineer.service_pause import (
    PausedProcessReceipt,
    ServicePauseControl,
    ServicePauseRequested,
)
from ai_software_engineer.web_console import (
    ConsoleCommandResult,
    ConsoleIntent,
    ConsoleOperationStatus,
    InMemoryConsoleOperationStore,
    ProjectConsole,
)
from ai_software_engineer.web_console.service_lifecycle import ConsoleShutdownCoordinator
from ai_software_engineer.web_console.shutdown import ServiceWriteGate, ShutdownState
from tests.web_console.test_core import _create_intent


@pytest.mark.parametrize("save_fails", [False, True])
def test_native_pause_requires_real_stop_and_saved_operation_before_ready(
    tmp_path: Path,
    save_fails: bool,
) -> None:
    saved: list[PausedProcessReceipt] = []
    entered = Event()

    def save(receipt: PausedProcessReceipt) -> None:
        if save_fails:
            raise OSError("fixture stop store unavailable")
        saved.append(receipt)

    control = ServicePauseControl(grace_seconds=0.01, persist_stop=save)
    registry = HostOwnedProcessRegistry()

    class Executor:
        def execute(self, intent: ConsoleIntent) -> ConsoleCommandResult:
            entered.set()
            result = SubprocessCodexCommandRunner().run(
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import time; "
                    "Path('started').write_text('yes'); time.sleep(60)",
                ),
                cwd=tmp_path,
                environment={"PATH": os.defpath},
                stdin="",
                timeout_seconds=60,
            )
            assert result.process_stop is not None and result.process_stop.kind == "service_pause"
            raise ServicePauseRequested()

    console = ProjectConsole(
        store=InMemoryConsoleOperationStore("team_test"),
        executor=Executor(),
        pause_control=control,
        operation_scope=registry.operation_scope,
    )
    operation = console.submit(_create_intent(tmp_path), idempotency_key="pause-native")
    console.start()
    assert entered.wait(2)
    for _ in range(200):
        if (tmp_path / "started").exists():
            break
        entered.wait(0.01) if not entered.is_set() else Event().wait(0.01)
    assert (tmp_path / "started").exists()
    coordinator = ConsoleShutdownCoordinator(
        console=console,
        write_gate=ServiceWriteGate(),
        owned_processes=registry,
    )
    coordinator.begin_shutdown()
    outcome = coordinator.await_shutdown(5)
    if save_fails:
        assert outcome.state is ShutdownState.REFUSED
        assert not saved
    else:
        assert outcome.state is ShutdownState.READY
        assert len(saved) == 1
        saved[0].validate_integrity()
        final = console.get(operation.operation_id)
        assert (
            final.status is ConsoleOperationStatus.FAILED and final.error_code == "SERVICE_PAUSED"
        )
        assert not registry.snapshot()
        with pytest.raises(ProcessLookupError):
            os.kill(saved[0].process_stop.process_id, 0)
    console.close(timeout=1)
