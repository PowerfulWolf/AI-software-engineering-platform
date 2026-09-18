"""Isolated lifecycle checks for the local ase-console service launcher."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

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
            'elif [ -f "$record.foreign" ]; then\n'
            '    cat "$record.foreign"\n'
            'elif [ -f "${ASE_SERVICE_STATE_DIR}/ase-console-supervisor.pid" ] && '
            '[ "$(sed -n \'1p\' "${ASE_SERVICE_STATE_DIR}/ase-console-supervisor.pid")" '
            '= "$candidate_pid" ]; then\n'
            "    supervisor_script=$(sed -n '2p' "
            '"${ASE_SERVICE_STATE_DIR}/ase-console-supervisor.pid")\n'
            "    printf '%s supervise\\n' \"$supervisor_script\"\n"
            "else\n"
            "    :\n"
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


def test_service_launcher_never_signals_live_foreign_supervisor_pid(tmp_path: Path) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    state.mkdir()
    supervisor_record = state / "ase-console-supervisor.pid"
    foreign = subprocess.Popen(
        (sys.executable, "-c", "import signal; signal.pause()"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    supervisor_record.write_text(f"{foreign.pid}\n{launcher}\n", encoding="utf-8")
    process_directory = Path(environment["ASE_TEST_PROCESS_DIRECTORY"])
    process_directory.mkdir()
    (process_directory / f"{foreign.pid}.command.foreign").touch()
    (process_directory / f"{foreign.pid}.command.foreign").write_text(
        f"foreign-wrapper --note {launcher} supervise --not-managed\n",
        encoding="utf-8",
    )

    try:
        stopped = _run(launcher, environment, "stop")

        assert stopped.returncode == 1
        assert "supervisor PID does not identify" in stopped.stderr
        assert foreign.poll() is None
        assert supervisor_record.is_file()
    finally:
        foreign.terminate()
        foreign.wait(timeout=5)


def test_service_supervisor_excludes_a_second_owner(tmp_path: Path) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    state.mkdir()
    first = subprocess.Popen(
        (str(launcher), "supervise"),
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    second: subprocess.CompletedProcess[str] | None = None
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not (state / "ase-console-supervisor.pid").exists():
            time.sleep(0.05)
        second = _run(launcher, environment, "supervise")
        assert second.returncode == 1
        assert "another ase-console supervisor" in second.stderr
        assert first.poll() is None
    finally:
        first.terminate()
        first.wait(timeout=5)


def test_service_supervisor_does_not_reclaim_owner_during_lock_publication(
    tmp_path: Path,
) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    state.mkdir()
    barrier_bin = tmp_path / "barrier-bin"
    barrier_bin.mkdir()
    reached = tmp_path / "lock-created"
    release = tmp_path / "release-lock-owner"
    real_mkdir = shutil.which("mkdir")
    assert real_mkdir is not None
    mkdir = barrier_bin / "mkdir"
    mkdir.write_text(
        "#!/bin/sh\n"
        '"${ASE_TEST_REAL_MKDIR:?}" "$@"\n'
        "status=$?\n"
        'if [ "$status" -eq 0 ] && '
        '[ "${1:-}" = "${ASE_SERVICE_STATE_DIR}/ase-console-supervisor.lock" ]; then\n'
        '    : >"${ASE_TEST_LOCK_REACHED:?}"\n'
        '    while [ ! -e "${ASE_TEST_LOCK_RELEASE:?}" ]; do sleep 0.02; done\n'
        "fi\n"
        'exit "$status"\n',
        encoding="utf-8",
    )
    mkdir.chmod(0o755)
    environment.update(
        {
            "ASE_TEST_REAL_MKDIR": real_mkdir,
            "ASE_TEST_LOCK_REACHED": str(reached),
            "ASE_TEST_LOCK_RELEASE": str(release),
            "PATH": f"{barrier_bin}{os.pathsep}{environment['PATH']}",
        }
    )
    first = subprocess.Popen(
        (str(launcher), "supervise"),
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not reached.exists():
            time.sleep(0.02)
        assert reached.exists()

        second = _run(launcher, environment, "supervise")

        assert second.returncode == 1
        assert "another ase-console supervisor" in second.stderr
        assert first.poll() is None
        release.touch()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not (state / "ase-console-supervisor.pid").exists():
            time.sleep(0.02)
        assert (state / "ase-console-supervisor.pid").is_file()
        assert first.poll() is None
    finally:
        release.touch()
        first.terminate()
        first.wait(timeout=5)


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


def test_service_supervisor_consumes_one_configuration_apply_request(
    tmp_path: Path,
) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    request_id = "configuration_apply_" + "a" * 32

    try:
        started = _run(launcher, environment, "start")
        assert started.returncode == 0, started.stderr
        original_pid = (state / "ase-console.pid").read_text().splitlines()[0]
        assert (state / "ase-console-supervisor.pid").is_file()
        (state / "configuration-apply.json").write_text(
            json.dumps(
                {
                    "request_id": request_id,
                    "safe_summary": "Configuration apply is in progress.",
                    "status": "PENDING",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (state / "configuration-apply.request").write_text(request_id + "\n", encoding="ascii")

        deadline = time.monotonic() + 6
        result: dict[str, str] = {}
        while time.monotonic() < deadline:
            result = json.loads((state / "configuration-apply.json").read_text())
            if result["status"] != "PENDING":
                break
            time.sleep(0.1)

        assert result["status"] == "SUCCEEDED"
        assert result["safe_summary"] == "Configuration was applied."
        restarted_pid = (state / "ase-console.pid").read_text().splitlines()[0]
        assert restarted_pid != original_pid
        assert not (state / "configuration-apply.request").exists()

        # A terminal request identity is consumed without restarting again.
        (state / "configuration-apply.request").write_text(request_id + "\n", encoding="ascii")
        time.sleep(0.6)
        assert (state / "ase-console.pid").read_text().splitlines()[0] == restarted_pid
    finally:
        _run(launcher, environment, "stop")


@pytest.mark.parametrize(
    "state_body",
    [
        None,
        "not-json\n",
        json.dumps(
            {
                "request_id": "configuration_apply_" + "b" * 32,
                "safe_summary": "Configuration apply is in progress.",
                "status": "PENDING",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        json.dumps(
            {
                "request_id": "configuration_apply_" + "a" * 32,
                "safe_summary": "Configuration was applied.",
                "status": "SUCCEEDED",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\nextra\n",
    ],
)
def test_service_supervisor_never_signals_child_for_invalid_apply_state(
    tmp_path: Path, state_body: str | None
) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    request_id = "configuration_apply_" + "a" * 32

    try:
        started = _run(launcher, environment, "start")
        assert started.returncode == 0, started.stderr
        original_pid = (state / "ase-console.pid").read_text().splitlines()[0]
        if state_body is not None:
            (state / "configuration-apply.json").write_text(state_body, encoding="utf-8")
        (state / "configuration-apply.request").write_text(request_id + "\n", encoding="ascii")

        time.sleep(0.7)

        assert (state / "ase-console.pid").read_text().splitlines()[0] == original_pid
        assert (state / "configuration-apply.request").is_file()
    finally:
        _run(launcher, environment, "stop")


def test_restart_preserves_replacement_supervisor_record_and_applyability(
    tmp_path: Path,
) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    request_id = "configuration_apply_" + "d" * 32

    try:
        assert _run(launcher, environment, "start").returncode == 0
        for _ in range(2):
            restarted = _run(launcher, environment, "restart")
            assert restarted.returncode == 0, restarted.stderr
            assert (state / "ase-console-supervisor.pid").is_file()
        original_pid = (state / "ase-console.pid").read_text().splitlines()[0]
        (state / "configuration-apply.json").write_text(
            json.dumps(
                {
                    "request_id": request_id,
                    "safe_summary": "Configuration apply is in progress.",
                    "status": "PENDING",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (state / "configuration-apply.request").write_text(request_id + "\n", encoding="ascii")
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            result = json.loads((state / "configuration-apply.json").read_text())
            if result["status"] != "PENDING":
                break
            time.sleep(0.1)
        assert result["status"] == "SUCCEEDED"
        assert (state / "ase-console.pid").read_text().splitlines()[0] != original_pid
    finally:
        _run(launcher, environment, "stop")


def test_service_supervisor_never_signals_child_for_symlink_apply_state(
    tmp_path: Path,
) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    request_id = "configuration_apply_" + "e" * 32
    external = tmp_path / "external-state.json"
    external.write_text("{}\n", encoding="utf-8")

    try:
        assert _run(launcher, environment, "start").returncode == 0
        original_pid = (state / "ase-console.pid").read_text().splitlines()[0]
        (state / "configuration-apply.json").symlink_to(external)
        (state / "configuration-apply.request").write_text(request_id + "\n", encoding="ascii")
        time.sleep(0.7)
        assert (state / "ase-console.pid").read_text().splitlines()[0] == original_pid
        assert (state / "configuration-apply.request").is_file()
    finally:
        (state / "configuration-apply.json").unlink(missing_ok=True)
        _run(launcher, environment, "stop")


def test_service_supervisor_does_not_retain_removed_runtime_value(tmp_path: Path) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    config = tmp_path / "config" / "config.json"
    config.parent.mkdir()
    runtime_environment = config.parent / "runtime.env"
    capture = tmp_path / "captured-dsn"
    environment["ASE_CONFIG"] = str(config)
    environment["ASE_TEST_ENV_CAPTURE"] = str(capture)
    runtime_environment.write_text("ASE_MYSQL_DSN='initial-secret'\n", encoding="utf-8")
    request_id = "configuration_apply_" + "b" * 32

    try:
        started = _run(launcher, environment, "start")
        assert started.returncode == 0, started.stderr
        assert capture.read_text(encoding="utf-8") == "initial-secret"
        runtime_environment.unlink()
        (state / "configuration-apply.json").write_text(
            json.dumps(
                {
                    "request_id": request_id,
                    "safe_summary": "Configuration apply is in progress.",
                    "status": "PENDING",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (state / "configuration-apply.request").write_text(request_id + "\n", encoding="ascii")

        deadline = time.monotonic() + 6
        result: dict[str, str] = {}
        while time.monotonic() < deadline:
            result = json.loads((state / "configuration-apply.json").read_text())
            if result["status"] != "PENDING":
                break
            time.sleep(0.1)

        assert result["status"] == "SUCCEEDED"
        assert capture.read_text(encoding="utf-8") == "missing"
        assert "initial-secret" not in (state / "configuration-apply.json").read_text()
    finally:
        _run(launcher, environment, "stop")


def test_service_supervisor_records_safe_failure_without_rolling_back_runtime(
    tmp_path: Path,
) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    service = launcher.parents[1] / ".venv" / "bin" / "ase-console"
    config = tmp_path / "config" / "config.json"
    config.parent.mkdir()
    runtime_environment = config.parent / "runtime.env"
    runtime_body = "ASE_MYSQL_DSN='mysql+pymysql://user:secret@db/database'\n"
    runtime_environment.write_text(runtime_body, encoding="utf-8")
    environment["ASE_CONFIG"] = str(config)
    request_id = "configuration_apply_" + "c" * 32

    try:
        started = _run(launcher, environment, "start")
        assert started.returncode == 0, started.stderr
        service.write_text(f"#!{sys.executable}\nraise SystemExit(1)\n", encoding="utf-8")
        service.chmod(0o755)
        (state / "configuration-apply.json").write_text(
            json.dumps(
                {
                    "request_id": request_id,
                    "safe_summary": "Configuration apply is in progress.",
                    "status": "PENDING",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (state / "configuration-apply.request").write_text(request_id + "\n", encoding="ascii")

        deadline = time.monotonic() + 6
        result: dict[str, str] = {}
        while time.monotonic() < deadline:
            result = json.loads((state / "configuration-apply.json").read_text())
            if result["status"] != "PENDING":
                break
            time.sleep(0.1)

        assert result["status"] == "FAILED"
        assert result["safe_summary"].startswith("Configuration remains saved")
        assert "secret" not in json.dumps(result)
        assert runtime_environment.read_text(encoding="utf-8") == runtime_body
    finally:
        _run(launcher, environment, "stop")


def test_service_supervisor_reconciles_claimed_pending_request_as_failed(
    tmp_path: Path,
) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    state.mkdir()
    request_id = "configuration_apply_" + "f" * 32
    (state / "configuration-apply.json").write_text(
        json.dumps(
            {
                "request_id": request_id,
                "safe_summary": "Configuration apply is in progress.",
                "status": "PENDING",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        assert _run(launcher, environment, "start").returncode == 0
        deadline = time.monotonic() + 3
        result: dict[str, str] = {}
        while time.monotonic() < deadline:
            result = json.loads((state / "configuration-apply.json").read_text())
            if result["status"] == "FAILED":
                break
            time.sleep(0.05)
        assert result["status"] == "FAILED"
        assert "Configuration remains saved" in result["safe_summary"]
    finally:
        _run(launcher, environment, "stop")


@pytest.mark.parametrize("runtime_kind", ["malformed", "symlink"])
def test_service_supervisor_records_failure_when_runtime_environment_cannot_load(
    tmp_path: Path, runtime_kind: str
) -> None:
    launcher, environment = _launcher(tmp_path)
    state = Path(environment["ASE_SERVICE_STATE_DIR"])
    config = tmp_path / "config" / "config.json"
    config.parent.mkdir()
    runtime_environment = config.parent / "runtime.env"
    environment["ASE_CONFIG"] = str(config)
    request_id = "configuration_apply_" + "9" * 32

    try:
        assert _run(launcher, environment, "start").returncode == 0
        if runtime_kind == "malformed":
            runtime_environment.write_text("ASE_MYSQL_DSN='unterminated\n", encoding="utf-8")
        else:
            external = tmp_path / "external-runtime.env"
            external.write_text("ASE_MYSQL_DSN='secret'\n", encoding="utf-8")
            runtime_environment.symlink_to(external)
        (state / "configuration-apply.json").write_text(
            json.dumps(
                {
                    "request_id": request_id,
                    "safe_summary": "Configuration apply is in progress.",
                    "status": "PENDING",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (state / "configuration-apply.request").write_text(request_id + "\n", encoding="ascii")
        deadline = time.monotonic() + 4
        result: dict[str, str] = {}
        while time.monotonic() < deadline:
            result = json.loads((state / "configuration-apply.json").read_text())
            if result["status"] != "PENDING":
                break
            time.sleep(0.05)
        assert result["status"] == "FAILED"
        supervisor_pid = int((state / "ase-console-supervisor.pid").read_text().splitlines()[0])
        os.kill(supervisor_pid, 0)
    finally:
        _run(launcher, environment, "stop")
