"""Real isolated fault retirement authorizes only persistent inspection mode."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.web_console import fault_retirement as module
from ai_software_engineer.web_console.fault_retirement import (
    FaultRetirementError,
    execute_fault_retirement,
    inspection_required,
    prepare_fault_retirement,
    require_inspection_retirement,
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
    root.mkdir(mode=0o700)
    entry = tmp_path / "checkout" / ".venv" / "bin" / "ase-console"
    entry.parent.mkdir(parents=True)
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


def test_actual_host_and_supervisor_retirement_only_admits_inspection(tmp_path: Path) -> None:
    with _host(tmp_path, supervisor=True) as (env, child):
        root = Path(env["ASE_SERVICE_STATE_DIR"])
        original = {p.name: p.read_bytes() for p in root.glob("console-service-*.json")}
        log = (root / "ase-console.log").read_bytes()
        plan = prepare_fault_retirement(env)
        assert plan.scope.execution_completeness == "UNKNOWN"
        assert not inspection_required(env)
        receipt = _execute(env, plan.record_sha256)
        assert child.wait(timeout=5) == -signal.SIGKILL
        assert receipt.signal_sent == "CONFIRMED"
        assert receipt.signal_sent_at is not None
        assert receipt.historical_state == "REFUSED"
        assert receipt.historical_execution_outcome == "UNKNOWN"
        assert receipt.execution_scope_completeness == "UNKNOWN"
        assert receipt.log_sha256 == hashlib.sha256(log).hexdigest()
        assert original == {p.name: p.read_bytes() for p in root.glob("console-service-*.json")}
        assert inspection_required(env)
        require_inspection_retirement(env, plan.instance, plan.request, plan.result)
        assert _cli(env, "dead", str(child.pid)).returncode == 0
        assert _cli(env, "initial").returncode == 0
        assert (
            _cli({**env, "ASE_CONSOLE_MODE": "normal"}, "launch-mode").stdout.strip()
            == "inspection"
        )
        assert _execute(env, plan.record_sha256) == receipt
        # Successor lifecycle may change but the old archive and mode persist.
        ServiceLifecycleStore(root).publish_instance(
            ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC))
        )
        assert inspection_required(env)


@pytest.mark.parametrize(
    "fault", ("confirm", "digest", "original_drift", "config_drift", "unfrozen")
)
def test_bad_prerequisite_never_signals_target(tmp_path: Path, fault: str) -> None:
    with _host(tmp_path) as (env, child):
        plan = prepare_fault_retirement(env)
        if fault == "original_drift":
            path = Path(env["ASE_SERVICE_STATE_DIR"]) / "ase-console.pid"
            path.write_bytes(path.read_bytes() + b" ")
        elif fault == "config_drift":
            path = Path(env["ASE_CONFIG"])
            path.write_text(path.read_text() + " ")
        elif fault == "unfrozen":
            os.kill(child.pid, signal.SIGCONT)
        with pytest.raises((FaultRetirementError, OSError, ValueError)):
            execute_fault_retirement(
                env,
                plan_sha256="f" * 64 if fault == "digest" else plan.record_sha256,
                confirm_fault_retirement=fault != "confirm",
            )
        assert child.poll() is None
        assert (Path(env["ASE_SERVICE_STATE_DIR"]) / "ase-console.log").exists()
        assert not inspection_required(env)


@pytest.mark.parametrize("stage", ("rename", "chmod", "signal_ack", "hash", "receipt", "marker"))
def test_every_interrupted_stage_retries_same_plan_without_resignaling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    with _host(tmp_path) as (env, child):
        plan = prepare_fault_retirement(env)
        calls: list[int] = []
        real_kill = os.kill

        def kill(pid: int, sig: int) -> None:
            calls.append(pid)
            real_kill(pid, sig)

        monkeypatch.setattr(os, "kill", kill)
        failed = False
        if stage in {"rename", "chmod"}:
            real = getattr(os, stage)

            def file_operation(*args: object, **kwargs: object) -> None:
                nonlocal failed
                real(*args, **kwargs)
                if not failed:
                    failed = True
                    raise OSError("injected after successful file mutation")

            monkeypatch.setattr(os, stage, file_operation)
        elif stage == "hash":
            real_hash = module._hash_log

            def hash_log(archive: Path, size: int) -> str:
                nonlocal failed
                if not failed:
                    failed = True
                    raise OSError("injected after actual kill")
                return real_hash(archive, size)

            monkeypatch.setattr(module, "_hash_log", hash_log)
        else:
            real_save = module._save
            names = {
                "signal_ack": "signal-sent.json",
                "receipt": "receipt.json",
                "marker": module.MARKER_NAME,
            }

            def save(root: Path, name: str, record: module._Record) -> None:
                nonlocal failed
                if name == names[stage] and not failed:
                    failed = True
                    raise OSError("injected before record publication")
                real_save(root, name, record)

            monkeypatch.setattr(module, "_save", save)
        with pytest.raises(OSError):
            _execute(env, plan.record_sha256)
        assert failed
        if stage not in {"rename", "chmod"}:
            assert child.wait(timeout=5) == -signal.SIGKILL
        receipt = _execute(env, plan.record_sha256)
        assert inspection_required(env)
        assert calls == [child.pid]
        assert receipt.signal_sent == ("UNKNOWN" if stage == "signal_ack" else "CONFIRMED")


@pytest.mark.parametrize("fault", ("same_size_log", "marker", "archive_symlink", "receipt"))
def test_complete_archive_drift_or_forged_marker_refuses(tmp_path: Path, fault: str) -> None:
    with _host(tmp_path) as (env, _):
        plan = prepare_fault_retirement(env)
        _execute(env, plan.record_sha256)
        root = Path(env["ASE_SERVICE_STATE_DIR"])
        archive = root / "console-fault-retirements" / plan.record_sha256
        if fault == "same_size_log":
            path = archive / "ase-console.log"
            path.write_bytes(b"x" * path.stat().st_size)
        elif fault == "marker":
            (root / module.MARKER_NAME).write_text('{"successor_mode":"normal"}')
        elif fault == "archive_symlink":
            path = archive / "ase-console.pid"
            path.unlink()
            path.symlink_to(root / "ase-console.pid")
        else:
            (archive / "receipt.json").write_text("{}")
        with pytest.raises(FaultRetirementError):
            inspection_required(env)
        assert _cli(env, "initial").returncode == 1


def test_prepare_rejects_old_instance_with_recycled_current_birth(tmp_path: Path) -> None:
    with _host(tmp_path) as (env, child):
        store = ServiceLifecycleStore(Path(env["ASE_SERVICE_STATE_DIR"]))
        old = ServiceInstance.new(pid=child.pid, at=datetime.now(UTC) - timedelta(days=1))
        request = ServiceShutdownRequest.new(old, at=old.started_at)
        store.publish_instance(old.with_state(ServiceState.REFUSED, at=old.started_at))
        store.write_request(request)
        store.write_result(
            ServiceShutdownResult.for_request(
                request, state=ServiceState.REFUSED, at=old.started_at
            )
        )
        with pytest.raises(FaultRetirementError):
            prepare_fault_retirement(env)
        assert child.poll() is None


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


def test_live_unknown_log_writer_blocks_finalize_until_it_closes(tmp_path: Path) -> None:
    with _host(tmp_path) as (env, child):
        plan = prepare_fault_retirement(env)
        root = Path(env["ASE_SERVICE_STATE_DIR"])
        with (root / "ase-console.log").open("ab"):
            with pytest.raises(FaultRetirementError, match="旧日志仍有写入者"):
                _execute(env, plan.record_sha256)
            assert child.wait(timeout=5) == -signal.SIGKILL
            assert not inspection_required(env)
        receipt = _execute(env, plan.record_sha256)
        assert receipt.historical_execution_outcome == "UNKNOWN"
        assert inspection_required(env)


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
    assert schema == model.model_json_schema()
