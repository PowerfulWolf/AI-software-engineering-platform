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
            "import os\n"
            "import signal\n"
            "from pathlib import Path\n"
            "capture = os.environ.get('ASE_TEST_ENV_CAPTURE')\n"
            "if capture:\n"
            "    Path(capture).write_text(os.environ.get('ASE_MYSQL_DSN', 'missing'))\n"
            "process_directory = os.environ.get('ASE_TEST_PROCESS_DIRECTORY')\n"
            "if process_directory:\n"
            "    process_path = Path(process_directory)\n"
            "    process_path.mkdir(parents=True, exist_ok=True)\n"
            "    command_path = process_path / f'{os.getpid()}.command'\n"
            "    command_path.write_text(str(Path(__file__).resolve()))\n"
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
            "#!/bin/sh\n"
            "candidate_pid=''\n"
            'while [ "$#" -gt 0 ]; do\n'
            "    if [ \"$1\" = '-p' ]; then\n"
            "        shift\n"
            "        candidate_pid=${1:-}\n"
            "        break\n"
            "    fi\n"
            "    shift\n"
            "done\n"
            "record=${ASE_TEST_PROCESS_DIRECTORY:-}/${candidate_pid}.command\n"
            'if [ -n "$candidate_pid" ] && [ -f "$record" ]; then\n'
            '    cat "$record"\n'
            "else\n"
            "    printf '%s\\n' \"${ASE_TEST_SERVICE_EXECUTABLE:?}\"\n"
            "fi\n",
            encoding="utf-8",
        )
        ps.chmod(0o755)
    environment = {
        **os.environ,
        "ASE_SERVICE_STATE_DIR": str(tmp_path / "state"),
    }
    if executable:
        environment["ASE_TEST_SERVICE_EXECUTABLE"] = str(service)
        environment["ASE_TEST_PROCESS_DIRECTORY"] = str(tmp_path / "processes")
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


def test_service_launcher_restart_recovers_from_dead_pid_record(tmp_path: Path) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    state.mkdir()
    pid_file = state / "ase-console.pid"
    dead_pid = "99999999"
    pid_file.write_text(dead_pid + "\n", encoding="utf-8")

    try:
        restarted = _run(launcher, environment, "restart")

        assert restarted.returncode == 0, restarted.stderr
        assert "removed stale PID" in restarted.stdout
        assert "ase-console started" in restarted.stdout
        assert pid_file.read_text(encoding="utf-8").strip() != dead_pid
        assert _run(launcher, environment, "status").returncode == 0
    finally:
        _run(launcher, environment, "stop")


def test_service_launcher_restart_never_signals_live_foreign_pid(tmp_path: Path) -> None:
    launcher, environment = _launcher(tmp_path)
    environment["PATH"] = os.environ["PATH"]
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    state.mkdir()
    pid_file = state / "ase-console.pid"
    foreign = subprocess.Popen(
        (sys.executable, "-c", "import signal; signal.pause()"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid_file.write_text(f"{foreign.pid}\n", encoding="utf-8")

    try:
        restarted = _run(launcher, environment, "restart")

        assert restarted.returncode == 1
        assert "does not identify this project's ase-console" in restarted.stderr
        assert foreign.poll() is None
        assert pid_file.read_text(encoding="utf-8").strip() == str(foreign.pid)
    finally:
        foreign.terminate()
        foreign.wait(timeout=5)


def test_service_launcher_restart_hands_off_managed_process_between_checkouts(
    tmp_path: Path,
) -> None:
    old_launcher, old_environment = _launcher(tmp_path / "old")
    new_launcher, new_environment = _launcher(tmp_path / "new")
    shared_state = tmp_path / "shared-state"
    shared_processes = tmp_path / "shared-processes"
    old_environment.update(
        {
            "ASE_SERVICE_STATE_DIR": str(shared_state),
            "ASE_TEST_PROCESS_DIRECTORY": str(shared_processes),
        }
    )
    new_environment.update(
        {
            "ASE_SERVICE_STATE_DIR": str(shared_state),
            "ASE_TEST_PROCESS_DIRECTORY": str(shared_processes),
        }
    )

    try:
        started = _run(old_launcher, old_environment, "start")
        assert started.returncode == 0, started.stderr

        restarted = _run(new_launcher, new_environment, "restart")

        assert restarted.returncode == 0, restarted.stderr
        assert "ase-console stopped" in restarted.stdout
        assert "ase-console started" in restarted.stdout
        pid_record = (shared_state / "ase-console.pid").read_text(encoding="utf-8").splitlines()
        assert pid_record[1] == str(new_launcher.parents[1] / ".venv" / "bin" / "ase-console")
        assert _run(new_launcher, new_environment, "status").returncode == 0
    finally:
        _run(old_launcher, old_environment, "stop")
        _run(new_launcher, new_environment, "stop")


def test_service_launcher_recognizes_same_project_relative_console_command(
    tmp_path: Path,
) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    processes = Path(environment["ASE_TEST_PROCESS_DIRECTORY"])

    try:
        started = _run(launcher, environment, "start")
        assert started.returncode == 0, started.stderr
        pid = (state / "ase-console.pid").read_text(encoding="utf-8").splitlines()[0]
        project = launcher.parents[1]
        (processes / f"{pid}.command").write_text(
            f"{project}/.venv/bin/python3 .venv/bin/ase-console\n",
            encoding="utf-8",
        )

        restarted = _run(launcher, environment, "restart")

        assert restarted.returncode == 0, restarted.stderr
        assert "ase-console stopped" in restarted.stdout
        assert "ase-console started" in restarted.stdout
        assert _run(launcher, environment, "status").returncode == 0
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


def test_service_launcher_loads_runtime_environment_next_to_config(tmp_path: Path) -> None:
    launcher, environment = _launcher(tmp_path)
    config = tmp_path / "config" / "production.json"
    config.parent.mkdir()
    config.write_text("{}", encoding="utf-8")
    dsn = "mysql+pymysql://user:password@127.0.0.1:3307/database"
    (config.parent / "runtime.env").write_text(
        f"# managed\nASE_MYSQL_DSN='{dsn}'\n", encoding="utf-8"
    )
    capture = tmp_path / "captured.txt"
    environment.update(
        {
            "ASE_CONFIG": str(config),
            "ASE_TEST_ENV_CAPTURE": str(capture),
        }
    )

    try:
        started = _run(launcher, environment, "start")
        assert started.returncode == 0, started.stderr
        assert capture.read_text(encoding="utf-8") == dsn
    finally:
        _run(launcher, environment, "stop")
