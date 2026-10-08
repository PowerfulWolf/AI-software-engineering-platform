"""Standalone isolated Console fixture; never constructs a production Host."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from ai_software_engineer.agents.codex_cli import SubprocessCodexCommandRunner
from ai_software_engineer.owned_processes import HostOwnedProcessRegistry
from ai_software_engineer.team_view.models import TeamSnapshot
from ai_software_engineer.web_console.core import ProjectConsole
from ai_software_engineer.web_console.host import ControlledConsoleServer
from ai_software_engineer.web_console.models import ConsoleCommandResult, ConsoleIntent
from ai_software_engineer.web_console.service_lifecycle import (
    ServiceInstance,
    ServiceLifecycleError,
    ServiceLifecycleStore,
    ServiceState,
)
from ai_software_engineer.web_console.store import FileConsoleOperationStore
from ai_software_engineer.web_console.transport import create_console_app


class Reader:
    def snapshot(self, project_id: str | None = None) -> TeamSnapshot:
        return TeamSnapshot(as_of=datetime.now(UTC), team_id="team_fixture", team_name="Fixture")


class Executor:
    def __init__(self, root: Path) -> None:
        self.root = root

    def execute(self, intent: ConsoleIntent) -> ConsoleCommandResult:
        command = (
            "from pathlib import Path; import os,time; "
            "Path('native.pid').write_text(str(os.getpid())); "
            "exec(\"while not Path('release').exists():\\n time.sleep(.01)\"); print('finished')"
        )
        result = SubprocessCodexCommandRunner().run(
            (sys.executable, "-c", command),
            cwd=self.root,
            environment={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            stdin="",
            timeout_seconds=60,
        )
        payload = {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "timed_out": result.timed_out,
            "process_stop": result.process_stop.to_wire() if result.process_stop else None,
        }
        with (self.root / "actual-outcome.json").open("w") as stream:
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        return ConsoleCommandResult(
            project_id="project_fixture", stage="FINISHED", next_action="Fixture finished."
        )


def main() -> None:
    root = Path(sys.argv[1])
    port = int(sys.argv[2])
    registry = HostOwnedProcessRegistry()
    failure_mode = len(sys.argv) > 3 and sys.argv[3] == "running-write-failure"

    class HeldStartupConsole(ProjectConsole):
        def start(self) -> None:
            super().start()
            if failure_mode:
                deadline = time.monotonic() + 3
                while not (root / "native.pid").exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert (root / "native.pid").exists()

    class FaultStore(ServiceLifecycleStore):
        def publish_instance(self, value: ServiceInstance) -> None:
            if failure_mode and value.state is ServiceState.RUNNING:
                raise ServiceLifecycleError("fixture live identity write failed")
            super().publish_instance(value)

    console = HeldStartupConsole(
        store=FileConsoleOperationStore(root / "operations", team_id="team_fixture"),
        executor=Executor(root),
        operation_scope=registry.operation_scope,
    )
    app = create_console_app(
        console, Reader(), team_id="team_fixture", port=port, owned_processes=registry
    )
    ControlledConsoleServer(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"),
        lifecycle=FaultStore(root),
        instance=ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC)),
        coordinator=app.state.console_shutdown,
    ).run()


if __name__ == "__main__":
    main()
