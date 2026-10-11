"""Real silent peers must not survive a successful owned native stop."""

import gc
import os
import signal
import subprocess
import sys
import time
import weakref
from contextlib import suppress
from pathlib import Path

import pytest

from ai_software_engineer.agents.codex_cli import SubprocessCodexCommandRunner
from ai_software_engineer.agents.structured_execution import run_structured_command
from ai_software_engineer.domain import AgentPermissions, NetworkAccess
from ai_software_engineer.execution import SubprocessCommandExecutor
from ai_software_engineer.manager.verification_process import bounded_verification_command
from ai_software_engineer.owned_processes import (
    HostOwnedProcessRegistry,
    OwnedProcessesUncertain,
    finish_owned_process,
    observe_owned_process,
    run_owned_subprocess,
)
from ai_software_engineer.owned_sessions import (
    OwnedProcessIdentity,
    OwnedSessionUnknown,
    _SessionInspector,
    require_recorded_session_empty,
)


def _source(pid_file: Path, *, resistant: bool = False, escaped: bool = False) -> str:
    child = (
        "import os,time,signal; "
        + ("os.setsid(); " if escaped else "os.setpgid(0,0); ")
        + ("signal.signal(signal.SIGTERM,signal.SIG_IGN); " if resistant else "")
        + "os.close(1); os.close(2); time.sleep(30)"
    )
    return (
        "import pathlib,subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); "
        "time.sleep(.1); print('leader done')"
    )


def _assert_absent(pid: int) -> None:
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def _cleanup(pid_file: Path) -> None:
    if pid_file.exists():
        with suppress(ProcessLookupError):
            os.kill(int(pid_file.read_text()), signal.SIGKILL)


def test_native_silent_separate_group_is_stopped(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    child = "import os,time; os.setpgid(0,0); os.close(1); os.close(2); time.sleep(30)"
    source = (
        "import pathlib,subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); "
        "time.sleep(.1); print('leader done')"
    )
    registry = HostOwnedProcessRegistry()
    try:
        with registry.operation_scope("test_silent_session_peer"):
            result = SubprocessCodexCommandRunner().run(
                (sys.executable, "-c", source),
                cwd=tmp_path,
                environment={},
                stdin="",
                timeout_seconds=2,
            )
        assert result.process_stop is not None
        proof = result.process_stop.session_proof
        assert proof is not None and proof.proof_scope == "owned_session_empty"
        proof.validate_integrity()
        child_pid = int(pid_file.read_text())
        assert any(
            p.process_id == p.group_id == child_pid
            and p.session_id == result.process_stop.process_id
            for p in proof.observed_processes
        )
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("same-SID different-PGID silent child survived native stop")
        registry.require_stopped()
    finally:
        if pid_file.exists():
            with suppress(ProcessLookupError):
                os.kill(int(pid_file.read_text()), signal.SIGKILL)


@pytest.mark.parametrize(
    "runner", ["native", "structured", "tool", "verification", "owned", "devnull"]
)
@pytest.mark.parametrize("resistant", [False, True])
def test_registered_consumers_stop_all_owned_groups(
    tmp_path: Path,
    runner: str,
    resistant: bool,
) -> None:
    pid_file = tmp_path / "child.pid"
    argv = (sys.executable, "-c", _source(pid_file, resistant=resistant))
    registry = HostOwnedProcessRegistry()
    started = time.monotonic()
    try:
        with registry.operation_scope("operation_silent_peer_" + runner):
            if runner == "native":
                result = SubprocessCodexCommandRunner().run(
                    argv,
                    cwd=tmp_path,
                    environment={},
                    stdin="",
                    timeout_seconds=2,
                )
                assert result.process_stop is not None
                assert result.process_stop.session_proof is not None
            elif runner == "structured":
                run_structured_command(
                    argv,
                    cwd=tmp_path,
                    env={},
                    input="",
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
            elif runner == "tool":
                permissions = AgentPermissions(
                    read_paths=("**",),
                    write_paths=("**",),
                    commands=(sys.executable,),
                    network=NetworkAccess.NONE,
                )
                SubprocessCommandExecutor(tmp_path, permissions).run(argv, timeout_seconds=2)
            elif runner == "verification":
                bounded_verification_command(argv, cwd=tmp_path, environment={}, timeout=2)
            elif runner == "owned":
                run_owned_subprocess(argv, cwd=tmp_path, env={}, timeout=2)
            else:
                process = subprocess.Popen(
                    argv,
                    cwd=tmp_path,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                observation = observe_owned_process(process, kind="tool")
                process.wait(timeout=2)
                finish_owned_process(process, observation, output_drained=True)
        _assert_absent(int(pid_file.read_text()))
        registry.require_stopped()
        assert time.monotonic() - started < 4
    finally:
        _cleanup(pid_file)


def test_silent_setsid_escape_is_explicitly_outside_proof_scope(tmp_path: Path) -> None:
    pid_file = tmp_path / "escaped.pid"
    registry = HostOwnedProcessRegistry()
    try:
        with registry.operation_scope("operation_scope_limit"):
            result = SubprocessCodexCommandRunner().run(
                (sys.executable, "-c", _source(pid_file, escaped=True)),
                cwd=tmp_path,
                environment={},
                stdin="",
                timeout_seconds=2,
            )
        assert result.process_stop is not None and result.process_stop.session_proof is not None
        proof = result.process_stop.session_proof
        escaped_pid = int(pid_file.read_text())
        assert os.getsid(escaped_pid) != proof.leader.session_id
        assert proof.proof_scope == "owned_session_empty"
        assert not any(p.process_id == escaped_pid for p in proof.observed_processes)
        os.kill(escaped_pid, 0)  # This bounded scope never asserted all descendants stopped.
        registry.require_stopped()
    finally:
        _cleanup(pid_file)


class _FaultInspector:
    def __init__(self, wrapped: _SessionInspector, fault: str) -> None:
        self.wrapped, self.fault = wrapped, fault

    def boot_identity(self) -> str:
        value = self.wrapped.boot_identity()
        return value + "-changed" if self.fault == "boot" else value

    def identity(self, pid: int) -> OwnedProcessIdentity | None:
        value = self.wrapped.identity(pid)
        if value is not None and self.fault == "birth":
            return value.model_copy(update={"birth_identity": value.birth_identity + "-changed"})
        return value

    def members(self, sid: int) -> tuple[OwnedProcessIdentity, ...]:
        if self.fault == "denied":
            raise PermissionError("fixture denied full enumeration")
        if self.fault == "bound":
            raise OwnedSessionUnknown("fixture complete enumeration exceeded bound")
        return self.wrapped.members(sid)


@pytest.mark.parametrize("fault", ["denied", "bound", "birth", "boot"])
def test_inspection_failure_never_signals_or_clears_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    registry = HostOwnedProcessRegistry()
    process = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(30)"),
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        with registry.operation_scope("operation_unknown_" + fault):
            observation = observe_owned_process(process, kind="tool")
        controller = observation._controller
        assert controller is not None
        controller._inspector = _FaultInspector(controller._inspector, fault)
        signalled: list[int] = []

        def forbidden(pid: int, sent: int) -> None:
            signalled.append(pid)

        with monkeypatch.context() as patch:
            patch.setattr(os, "kill", forbidden)
            with pytest.raises(OwnedProcessesUncertain):
                observation.stop_session(timeout_seconds=0.05)
        assert signalled == []
        assert process.poll() is None
        assert registry.shutdown_failed and not registry.await_stopped(0)
        with pytest.raises(OwnedProcessesUncertain):
            registry.require_stopped()
    finally:
        process.kill()
        process.wait(timeout=1)


def test_new_session_stop_save_failure_keeps_uncertainty(tmp_path: Path) -> None:
    registry = HostOwnedProcessRegistry()

    def reject(_: object) -> None:
        raise OSError("fixture refuses durable stop publication")

    with registry.operation_scope("operation_stop_save"), pytest.raises(OSError):
        SubprocessCodexCommandRunner().run_observed(
            (sys.executable, "-c", "print('complete')"),
            cwd=tmp_path,
            environment={},
            stdin="",
            timeout_seconds=2,
            observer=reject,
        )
    assert registry.shutdown_failed
    with pytest.raises(OwnedProcessesUncertain):
        registry.require_stopped()


def _wait_file(path: Path) -> None:
    deadline = time.monotonic() + 2
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert path.exists()


def test_observed_peer_escape_retains_uncertainty_and_stored_proof_recheck_rejects(
    tmp_path: Path,
) -> None:
    ready, go, escaped, exit_leader = (tmp_path / p for p in ("ready", "go", "escaped", "exit"))
    pid_file = tmp_path / "child.pid"
    child_source = (
        "import os,pathlib,time; os.setpgid(0,0); "
        f"pathlib.Path({str(ready)!r}).touch(); "
        f"go=pathlib.Path({str(go)!r})\n"
        "while not go.exists():time.sleep(.005)\n"
        "os.setsid(); os.close(1); os.close(2); "
        f"pathlib.Path({str(escaped)!r}).touch(); time.sleep(30)"
    )
    # A process-group leader cannot call setsid; this peer initially shares the
    # original group and becomes a session leader only after the observed barrier.
    child_source = child_source.replace("os.setpgid(0,0); ", "")
    leader_source = (
        "import pathlib,subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable,'-c',{child_source!r}]); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); "
        f"end=pathlib.Path({str(exit_leader)!r})\n"
        "while not end.exists():time.sleep(.005)"
    )
    registry = HostOwnedProcessRegistry()
    process = subprocess.Popen(
        (sys.executable, "-c", leader_source),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        with registry.operation_scope("operation_observed_escape"):
            observation = observe_owned_process(process, kind="native")
        _wait_file(ready)
        observation.observe_session()
        controller = observation._controller
        assert controller is not None
        child_pid = int(pid_file.read_text())
        assert any(p.process_id == child_pid for p in controller._observed.values())
        go.touch()
        _wait_file(escaped)
        exit_leader.touch()
        process.communicate(timeout=2)
        assert os.getsid(child_pid) != process.pid
        with pytest.raises(OwnedProcessesUncertain):
            observation.stop_session(timeout_seconds=0.05)
        with pytest.raises(OwnedProcessesUncertain):
            observation.stopped(output_drained=True)
        assert registry.shutdown_failed and not registry.await_stopped(0)
        # Simulate an incorrectly supplied stored proof of original-SID absence:
        # reading it must still inspect every recorded exact process birth.
        proof = controller._proof()
        with pytest.raises(OwnedSessionUnknown, match="birth remains alive"):
            require_recorded_session_empty(proof)
        os.kill(child_pid, 0)
    finally:
        _cleanup(pid_file)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=1)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def test_capture_failure_does_not_retain_exception_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ScopePayload:
        pass

    references: list[weakref.ReferenceType[ScopePayload]] = []

    def failed(_: object) -> None:
        payload = ScopePayload()
        references.append(weakref.ref(payload))
        raise OwnedSessionUnknown("private failed inspection scope")

    registry = HostOwnedProcessRegistry()
    process = subprocess.Popen(
        (sys.executable, "-c", "import time;time.sleep(30)"),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        monkeypatch.setattr("ai_software_engineer.owned_processes.OwnedSessionController", failed)
        with registry.operation_scope("operation_capture_failure"):
            observation = observe_owned_process(process, kind="native")
        gc.collect()
        assert len(references) == 1 and references[0]() is None
        assert observation._capture_failed and registry.shutdown_failed
        with pytest.raises(OwnedProcessesUncertain):
            observation.stop_session(timeout_seconds=0.1)
        assert not registry.await_stopped(0)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=1)


def test_already_reaped_spawn_never_reconstructs_a_stronger_stop(tmp_path: Path) -> None:
    process = subprocess.Popen(
        (sys.executable, "-c", "pass"),
        cwd=tmp_path,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    process.wait(timeout=1)
    registry = HostOwnedProcessRegistry()
    with registry.operation_scope("operation_short_lived"):
        observation = observe_owned_process(process, kind="native")
    assert observation._capture_failed and registry.shutdown_failed
    with pytest.raises(OwnedProcessesUncertain):
        observation.stop_session()
    with pytest.raises(OwnedProcessesUncertain):
        observation.stopped(output_drained=True)
    assert not registry.await_stopped(0)
