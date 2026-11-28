"""Real isolated fault retirement authorizes only persistent inspection mode."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.web_console import fault_retirement as module
from ai_software_engineer.web_console.fault_retirement import (
    FaultRetirementError,
    execute_fault_retirement,
)
from ai_software_engineer.web_console.service_lifecycle import (
    ServiceInstance,
    ServiceLifecycleStore,
    ServiceShutdownRequest,
    ServiceShutdownResult,
    ServiceState,
)


@contextmanager
def _host(
    tmp_path: Path, *, supervisor: bool = False
) -> Iterator[tuple[dict[str, str], subprocess.Popen[bytes]]]:
    root = tmp_path / "state"
    root.mkdir(mode=0o700, exist_ok=True)
    entry = tmp_path / "checkout" / ".venv" / "bin" / "ase-console"
    entry.parent.mkdir(parents=True, exist_ok=True)
    if not (entry.parent / "python").exists():
        (entry.parent / "python").symlink_to(sys.executable)
    entry.write_text("import sys\nprint('ready', flush=True)\nsys.stdin.buffer.read()\n")
    entry.chmod(0o600)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "platform_root": str(tmp_path / "platform"),
                "model_routes": [
                    {"provider": "codex", "model": "gpt-6.1-sol", "kind": "codex_cli"}
                ],
            }
        )
    )
    env = {"ASE_SERVICE_STATE_DIR": str(root), "ASE_CONFIG": str(config)}
    log = root / "ase-console.log"
    log.write_bytes(b"full original log\n")
    child = subprocess.Popen(
        [str(entry.parent / "python"), str(entry)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={"PATH": os.defpath},
        cwd=tmp_path,
    )
    controller = None
    try:
        assert child.stdout is not None
        assert child.stdout.readline() == b"ready\n"
        now = datetime.now(UTC)
        instance = ServiceInstance.new(pid=child.pid, at=now)
        request = ServiceShutdownRequest.new(instance, at=now)
        refused = instance.with_state(ServiceState.REFUSED, at=now)
        store = ServiceLifecycleStore(root)
        store.publish_instance(refused)
        store.write_request(request)
        store.write_result(
            ServiceShutdownResult.for_request(request, state=ServiceState.REFUSED, at=now)
        )
        (root / "ase-console.pid").write_text(f"{child.pid}\n{entry}\n")
        (root / "ase-console.pid").chmod(0o644)
        if supervisor:
            script = tmp_path / "ase-console-service.sh"
            script.write_text("#!/bin/sh\ntrap 'exit 0' TERM\nwhile :; do sleep 0.05; done\n")
            script.chmod(0o700)
            with log.open("ab") as output:
                controller = subprocess.Popen(
                    ["/bin/sh", str(script), "supervise"],
                    stdout=output,
                    stderr=output,
                    start_new_session=True,
                    env={"PATH": os.defpath},
                )
            (root / "ase-console-supervisor.pid").write_text(f"{controller.pid}\n{script}\n")
            threading.Thread(target=controller.wait, daemon=True).start()
        os.kill(child.pid, signal.SIGSTOP)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = subprocess.run(
                ["/bin/ps", "-p", str(child.pid), "-o", "state="], capture_output=True, check=False
            )
            if state.stdout.strip().startswith(b"T"):
                break
        else:
            pytest.fail("test child did not actually freeze")
        threading.Thread(target=child.wait, daemon=True).start()
        yield env, child
    finally:
        for process in (child, controller):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        if child.stdin:
            child.stdin.close()
        if child.stdout:
            child.stdout.close()


def _execute(env: dict[str, str], digest: str) -> module.FaultRetirementReceipt:
    return execute_fault_retirement(env, plan_sha256=digest, confirm_fault_retirement=True)


def _cli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    project = Path(__file__).parents[2]
    return subprocess.run(
        [sys.executable, str(project / "scripts" / "ase-console-lifecycle.py"), *args],
        env={
            **env,
            "PATH": os.defpath,
            "PYTHONPATH": str(project / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


@pytest.mark.parametrize(
    "fault",
    ("empty_rc1", "rc2", "stderr", "missing_access", "bad_field", "writer", "wrong_probe_fd"),
)
def test_log_survey_needs_actual_positive_probe_and_complete_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    tmp_path.chmod(0o700)
    real = subprocess.run

    def run(
        argv: tuple[str, ...],
        *,
        stdin: int,
        capture_output: bool,
        env: dict[str, str],
        shell: bool,
        timeout: float,
        check: bool,
    ) -> subprocess.CompletedProcess[bytes]:
        result = real(
            argv,
            stdin=stdin,
            capture_output=capture_output,
            env=env,
            shell=shell,
            timeout=timeout,
            check=check,
        )
        if argv[0] != "/usr/sbin/lsof":
            return result
        stdout = result.stdout
        stderr = result.stderr
        code = result.returncode
        if fault == "empty_rc1":
            stdout, code = b"", 1
        elif fault == "rc2":
            code = 2
        elif fault == "stderr":
            stderr = b"incomplete survey"
        elif fault == "bad_field":
            stdout += b"zunknown\n"
        elif fault == "wrong_probe_fd":
            rows = stdout.decode().splitlines()
            rows = ["f999999" if row.startswith("f") else row for row in rows]
            stdout = ("\n".join(rows) + "\n").encode()
        else:
            # A new file boundary must erase the sentinel's access value.
            stdout += (
                "f9998\n"
                + ("aw\n" if fault == "writer" else "")
                + "n"
                + str(tmp_path / "ase-console.log")
                + "\n"
            ).encode()
        return subprocess.CompletedProcess(argv, code, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", run)
    # Bound simulated persistent writer waiting; real subprocess execution remains.
    if fault in {"writer", "missing_access"}:
        real_clock = time.monotonic
        counter = 0

        def advance_clock() -> float:
            nonlocal counter
            counter += 1
            return real_clock() + (4 if counter > 1 else 0)

        monkeypatch.setattr(time, "monotonic", advance_clock)
    with pytest.raises(FaultRetirementError):
        module._require_no_log_writers(tmp_path)


@pytest.mark.parametrize(
    "name,model",
    (
        ("console-fault-retirement-plan", module.FaultRetirementPlan),
        ("console-fault-retirement-receipt", module.FaultRetirementReceipt),
        ("console-fault-retirement-intent", module.TerminationIntent),
        ("console-fault-retirement-signal", module.SignalSent),
        ("console-inspection", module.InspectionMarker),
    ),
)
def test_fault_retirement_schema_parity(name: str, model: type[module._Record]) -> None:
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas" / (name + ".schema.json")).read_text()
    )
    assert schema.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert schema.pop("$id").endswith(f"/{name}.schema.json")
    assert schema == model.model_json_schema()


@pytest.mark.parametrize("mode", ["inspection", "invalid"])
def test_status_explicit_mode_without_marker(tmp_path: Path, mode: str) -> None:
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    store = ServiceLifecycleStore(root)
    instance = ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC))
    store.publish_instance(instance)
    before = (root / "console-service-instance.json").read_bytes()
    env = {"ASE_SERVICE_STATE_DIR": str(root), "ASE_CONSOLE_MODE": mode}
    result = _cli(env, "status", str(instance.pid))
    if mode == "inspection":
        assert result.returncode == 0
        assert "仅可查看记录" in result.stdout
        assert "可以接收新操作" not in result.stdout
        assert _cli(env, "launch-mode").stdout.strip() == mode
    else:
        assert result.returncode != 0
        assert "可以接收新操作" not in result.stdout
    assert (root / "console-service-instance.json").read_bytes() == before


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("console-archived-log-purge-intent", "ArchivedLogPurgeIntent"),
        ("console-archived-log-purge-receipt", "ArchivedLogPurgeReceipt"),
    ],
)
def test_archived_log_purge_schema_parity(name: str, model: str) -> None:
    from ai_software_engineer.web_console import fault_log_retention as retention

    schema = getattr(retention, model).model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://ai-software-engineer.local/schemas/{name}.schema.json"
    assert (
        json.loads((Path(__file__).parents[2] / "schemas" / f"{name}.schema.json").read_text())
        == schema
    )
