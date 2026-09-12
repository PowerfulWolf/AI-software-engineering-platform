"""Isolated lifecycle checks for the local ase-console service launcher."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "ase-console-service.sh"


def _launcher(tmp_path: Path, *, executable: bool = True) -> tuple[Path, dict[str, str]]:
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    launcher = scripts / SCRIPT.name
    shutil.copy2(SCRIPT, launcher)
    launcher.chmod(0o755)
    if executable:
        service = project / ".venv" / "bin" / "ase-console"
        service.parent.mkdir(parents=True)
        service.write_text(
            f"#!{sys.executable}\n"
            "import signal\n"
            "def raise_exit():\n"
            "    raise SystemExit(0)\n"
            "signal.signal(signal.SIGTERM, lambda *_: raise_exit())\n"
            "signal.pause()\n",
            encoding="utf-8",
        )
        service.chmod(0o755)
        test_bin = tmp_path / "bin"
        test_bin.mkdir()
        ps = test_bin / "ps"
        ps.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"${ASE_TEST_SERVICE_EXECUTABLE:?}\"\n",
            encoding="utf-8",
        )
        ps.chmod(0o755)
    environment = {
        **os.environ,
        "ASE_SERVICE_STATE_DIR": str(tmp_path / "state"),
    }
    if executable:
        environment["ASE_TEST_SERVICE_EXECUTABLE"] = str(service)
        environment["PATH"] = f"{test_bin}{os.pathsep}{environment['PATH']}"
    return launcher, environment


def _run(
    launcher: Path,
    environment: dict[str, str],
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (str(launcher), *arguments),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )


def test_service_launcher_starts_reports_and_stops_isolated_process(tmp_path: Path) -> None:
    launcher, environment = _launcher(tmp_path)

    try:
        started = _run(launcher, environment, "start")
        assert started.returncode == 0, started.stderr
        assert "ase-console started" in started.stdout
        assert _run(launcher, environment, "status").returncode == 0

        stopped = _run(launcher, environment, "stop")
        assert stopped.returncode == 0, stopped.stderr
        assert "ase-console stopped" in stopped.stdout
        assert _run(launcher, environment, "status").returncode == 1
    finally:
        _run(launcher, environment, "stop")


def test_service_launcher_rejects_invalid_invocations(tmp_path: Path) -> None:
    launcher, environment = _launcher(tmp_path, executable=False)

    missing_verb = _run(launcher, environment)
    assert missing_verb.returncode == 2
    assert "Usage:" in missing_verb.stderr

    missing_executable = _run(launcher, environment, "start")
    assert missing_executable.returncode == 2
    assert "uv sync" in missing_executable.stderr

    unsafe_environment = {**environment, "ASE_SERVICE_STATE_DIR": "relative/state"}
    unsafe_state = _run(launcher, unsafe_environment, "status")
    assert unsafe_state.returncode == 2
    assert "absolute path" in unsafe_state.stderr
