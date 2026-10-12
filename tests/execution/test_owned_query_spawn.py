"""Actual trusted queries capture their birth before a short or setuid target executes."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path

import pytest

from ai_software_engineer import owned_spawn
from ai_software_engineer.manager import legacy_local_execution as survey_module
from ai_software_engineer.manager.legacy_local_execution import TrustedLegacyLocalExecutionObserver
from ai_software_engineer.manager.verification_process import bounded_verification_command
from ai_software_engineer.owned_processes import (
    HostOwnedProcessRegistry,
    OwnedProcessesUncertain,
    OwnedProcessObservation,
    finish_owned_process,
)
from ai_software_engineer.owned_spawn import spawn_owned_query


@pytest.mark.skipif(sys.platform != "darwin", reason="actual Darwin setuid ps contract")
def test_real_setuid_ps_query_preserves_verified_owned_stop() -> None:
    registry = HostOwnedProcessRegistry()
    for attempt in range(3):
        with registry.operation_scope(f"operation_actual_ps_{attempt}"):
            output = bounded_verification_command(
                ("/bin/ps", "-p", str(os.getpid()), "-o", "pid="),
                environment={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
                timeout=2,
            )
        assert output.strip() == str(os.getpid()).encode()
        assert not registry.snapshot()
    registry.require_stopped()


@pytest.mark.skipif(sys.platform != "darwin", reason="actual local ps query contract")
def test_actual_survey_query_uses_original_ps_body_and_stop_gate() -> None:
    registry = HostOwnedProcessRegistry()
    token = survey_module._DEADLINE.set(time.monotonic() + 5)
    try:
        with registry.operation_scope("operation_survey_ps"):
            output = TrustedLegacyLocalExecutionObserver()._query(
                ("/bin/ps", "-p", str(os.getpid()), "-o", "pid=")
            )
        assert output.strip() == str(os.getpid()).encode()
        registry.require_stopped()
    finally:
        survey_module._DEADLINE.reset(token)


def test_short_targets_always_capture_before_exit_and_release_registry() -> None:
    registry = HostOwnedProcessRegistry()
    for attempt in range(12):
        with registry.operation_scope(f"operation_fast_{attempt}"):
            output = bounded_verification_command(
                (sys.executable, "-I", "-S", "-c", "print('short')"),
                environment={},
                timeout=2,
            )
        assert output == b"short\n"
        assert not registry.snapshot()
    registry.require_stopped()


def test_target_argv_environment_input_cwd_and_fds_remain_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASE_HOST_ONLY_FIXTURE", "never inherited")
    source = (
        "import os,sys; "
        "assert sys.argv[1:]==['two words','$(literal)','`literal`']; "
        "assert os.environ['ASE_ALLOWED_FIXTURE']=='preserved'; "
        "assert 'ASE_HOST_ONLY_FIXTURE' not in os.environ; "
        "assert os.getcwd()==os.environ['ASE_EXPECTED_CWD']; "
        "assert sys.stdin.buffer.read()==b'original input'; "
        "open_fds=[]\n"
        "for fd in range(3,128):\n"
        "    try: os.fstat(fd)\n"
        "    except OSError: continue\n"
        "    open_fds.append(fd)\n"
        "assert not open_fds\n"
        "sys.stdout.buffer.write(b'\\x00exact-output')\n"
        "sys.stderr.write('exact-error')\n"
    )
    with tempfile.TemporaryFile() as errors:
        spawned = spawn_owned_query(
            (sys.executable, "-I", "-S", "-c", source, "two words", "$(literal)", "`literal`"),
            cwd=tmp_path,
            environment={"ASE_ALLOWED_FIXTURE": "preserved", "ASE_EXPECTED_CWD": str(tmp_path)},
            stdin=subprocess.PIPE,
            stderr=errors,
        )
        output, _ = spawned.process.communicate(b"original input", timeout=2)
        finish_owned_process(spawned.process, spawned.observation, output_drained=True)
        assert spawned.process.returncode == 0
        assert output == b"\x00exact-output"
        errors.seek(0)
        assert errors.read() == b"exact-error"


@pytest.mark.parametrize("environment", [{}, {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}])
def test_bootstrap_cannot_add_interpreter_environment_to_the_target(
    environment: dict[str, str],
) -> None:
    output = bounded_verification_command(("/usr/bin/env",), environment=environment, timeout=2)
    observed = dict(line.split("=", 1) for line in output.decode().splitlines())
    assert observed == environment


@pytest.mark.parametrize("failure", ["initial_capture", "second_observation"])
def test_denied_capture_never_executes_target_and_retains_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    target_marker = tmp_path / "target-ran"
    registry = HostOwnedProcessRegistry()
    if failure == "initial_capture":

        def denied(process: subprocess.Popen[bytes]) -> OwnedProcessObservation:
            raise PermissionError("raw secret permission error")

        monkeypatch.setattr("ai_software_engineer.owned_processes.OwnedSessionController", denied)
    else:

        def denied_observation(observation: OwnedProcessObservation) -> None:
            assert not target_marker.exists()
            raise OwnedProcessesUncertain("raw secret second observation")

        monkeypatch.setattr(OwnedProcessObservation, "observe_session", denied_observation)
    with (
        registry.operation_scope("operation_denied_capture"),
        pytest.raises(OwnedProcessesUncertain) as caught,
    ):
        spawn_owned_query(
            (
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(target_marker)!r}).touch()",
            ),
            environment={},
        )
    assert not target_marker.exists()
    assert "raw secret" not in str(caught.value)
    (unknown,) = registry.snapshot()
    assert unknown.state == "uncertain"
    with pytest.raises(ProcessLookupError):
        os.kill(unknown.process_id, 0)
    with pytest.raises(OwnedProcessesUncertain):
        registry.require_stopped()


@pytest.mark.parametrize(
    "release",
    [
        b"",
        b"x",
        b"1",
        b"1\x00\x00\x00\x03{}",
        b"1\x00\x20\x00\x01",
        b"1\x00\x00\x00\x02[]",
        b"1\x00\x00\x00\x02xx",
        b'1\x00\x00\x00\x07{"x":1}',
    ],
)
def test_bootstrap_eof_or_invalid_ack_never_executes_target(tmp_path: Path, release: bytes) -> None:
    marker = tmp_path / "must-not-execute"
    read_fd, write_fd = os.pipe()
    process = subprocess.Popen(
        (
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            owned_spawn._BOOTSTRAP,
            owned_spawn._BOOTSTRAP_VERSION,
            str(read_fd),
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).touch()",
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        pass_fds=(read_fd,),
        start_new_session=True,
    )
    os.close(read_fd)
    try:
        if release:
            os.write(write_fd, release)
    finally:
        os.close(write_fd)
    assert process.wait(timeout=2) == 125
    assert not marker.exists()


def test_denied_target_exec_is_failure_after_actual_bootstrap_stop(tmp_path: Path) -> None:
    executable = tmp_path / "denied"
    executable.write_text("should never execute\n")
    executable.chmod(0o600)
    registry = HostOwnedProcessRegistry()
    with registry.operation_scope("operation_exec_denied"), pytest.raises(ValueError):
        bounded_verification_command((str(executable),), environment={}, timeout=2)
    registry.require_stopped()


def test_ack_write_failure_cleans_actual_bootstrap_and_does_not_run_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "target-must-not-run"
    registry = HostOwnedProcessRegistry()

    def denied_write(descriptor: int, payload: bytes) -> int:
        raise BrokenPipeError("raw secret pipe failure")

    monkeypatch.setattr("ai_software_engineer.owned_spawn.os.write", denied_write)
    with (
        registry.operation_scope("operation_ack_failed"),
        pytest.raises(OwnedProcessesUncertain) as caught,
    ):
        spawn_owned_query(
            (sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"),
            environment={},
        )
    assert not marker.exists()
    assert "raw secret" not in str(caught.value)
    (unknown,) = registry.snapshot()
    assert unknown.state == "uncertain"
    with pytest.raises(ProcessLookupError):
        os.kill(unknown.process_id, 0)


def test_failed_capture_closes_parent_control_and_output_fds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied_observation(observation: OwnedProcessObservation) -> None:
        raise OwnedProcessesUncertain("fixture observation unavailable")

    monkeypatch.setattr(OwnedProcessObservation, "observe_session", denied_observation)
    before = len(os.listdir("/dev/fd"))
    for _ in range(5):
        with pytest.raises(OwnedProcessesUncertain):
            spawn_owned_query((sys.executable, "-c", "pass"), environment={})
    assert len(os.listdir("/dev/fd")) == before


def test_escaped_output_pipe_keeps_timeout_uncertain(tmp_path: Path) -> None:
    child_file = tmp_path / "escaped-child"
    source = (
        "import os,pathlib,subprocess,sys; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(15)'],"
        "start_new_session=True); "
        f"pathlib.Path({str(child_file)!r}).write_text(str(child.pid))"
    )
    registry = HostOwnedProcessRegistry()
    try:
        with (
            registry.operation_scope("operation_escaped_pipe"),
            pytest.raises(OwnedProcessesUncertain),
        ):
            bounded_verification_command((sys.executable, "-c", source), environment={}, timeout=1)
        assert registry.snapshot()[0].state == "uncertain"
        with pytest.raises(OwnedProcessesUncertain):
            registry.require_stopped()
    finally:
        if child_file.exists():
            with suppress(ProcessLookupError):
                os.kill(int(child_file.read_text()), signal.SIGKILL)


@pytest.mark.skipif(not Path("/dev/fd").is_dir(), reason="actual descriptor inventory")
def test_repeated_query_launches_do_not_leak_parent_control_or_output_fds() -> None:
    before = len(os.listdir("/dev/fd"))
    for _ in range(10):
        bounded_verification_command(
            (sys.executable, "-I", "-S", "-c", "pass"), environment={}, timeout=2
        )
    assert len(os.listdir("/dev/fd")) == before


def test_actual_exec_retains_captured_popen_pid_and_isolated_session() -> None:
    registry = HostOwnedProcessRegistry()
    with registry.operation_scope("operation_exact_exec_identity"):
        spawned = spawn_owned_query(
            (sys.executable, "-I", "-S", "-c", "import os;print(os.getpid(),os.getsid(0))"),
            environment={},
        )
        output, errors = spawned.process.communicate(timeout=2)
        finish_owned_process(spawned.process, spawned.observation, output_drained=True)
    assert tuple(map(int, output.split())) == (spawned.process.pid, spawned.process.pid)
    assert errors == b"" and spawned.process.returncode == 0
    registry.require_stopped()


def test_ack_not_writable_is_finite_and_target_stays_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "target-must-stay-blocked"
    registry = HostOwnedProcessRegistry()
    monkeypatch.setattr(
        "ai_software_engineer.owned_spawn.select.select", lambda *args: ([], [], [])
    )
    started = time.monotonic()
    with registry.operation_scope("operation_ack_timeout"), pytest.raises(OwnedProcessesUncertain):
        spawn_owned_query(
            (sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"),
            environment={},
        )
    assert time.monotonic() - started < 2
    assert not marker.exists()
    (unknown,) = registry.snapshot()
    assert unknown.state == "uncertain"
    with pytest.raises(ProcessLookupError):
        os.kill(unknown.process_id, 0)


def test_failed_bootstrap_launch_closes_control_fds_and_creates_no_owned_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied_launch(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        raise OSError("fixture denied bootstrap launch")

    monkeypatch.setattr("ai_software_engineer.owned_spawn.subprocess.Popen", denied_launch)
    registry = HostOwnedProcessRegistry()
    before = len(os.listdir("/dev/fd"))
    with registry.operation_scope("operation_bootstrap_denied"), pytest.raises(OSError):
        spawn_owned_query((sys.executable, "-c", "pass"), environment={})
    assert len(os.listdir("/dev/fd")) == before
    registry.require_stopped()
