"""Owned execution must outlive an operation thread's successful return."""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO, cast

import pytest

from ai_software_engineer.agents.codex_cli import (
    CodexExecutionUnconfirmed,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.agents.structured_execution import run_structured_command
from ai_software_engineer.domain import AgentPermissions, NetworkAccess
from ai_software_engineer.execution import CommandExecutionUncertain, SubprocessCommandExecutor
from ai_software_engineer.manager.python_mysql_proxy import MysqlUnixProxy
from ai_software_engineer.manager.python_mysql_resources import IsolatedMysqlResource
from ai_software_engineer.manager.verification_process import bounded_verification_command
from ai_software_engineer.owned_processes import (
    HostOwnedProcessRegistry,
    OwnedProcessesUncertain,
    observe_owned_process,
    run_owned_subprocess,
)


def test_unguarded_structured_command_owns_an_isolated_session(tmp_path: Path) -> None:
    """The previous subprocess.run bridge owned no stoppable process group."""
    result = run_structured_command(
        (sys.executable, "-c", "import os; print(os.getpid()); print(os.getpgrp())"),
        cwd=tmp_path,
        env={},
        input="",
        capture_output=True,
        text=True,
        timeout=1,
        check=False,
    )
    process_id, group_id = map(int, result.stdout.splitlines())
    assert group_id == process_id


def test_operation_return_does_not_clear_an_unverified_owned_process(tmp_path: Path) -> None:
    registry = HostOwnedProcessRegistry()
    with registry.operation_scope("operation_test"):
        process = subprocess.Popen(
            (sys.executable, "-c", "print('done')"),
            cwd=tmp_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        observation = observe_owned_process(process, kind="native")
    assert observation is not None
    with pytest.raises(OwnedProcessesUncertain):
        registry.require_stopped()
    assert not registry.await_stopped(0)
    process.communicate(timeout=1)
    with pytest.raises(OwnedProcessesUncertain):
        observation.stopped(output_drained=False)
    assert registry.snapshot()[0].state == "uncertain"
    assert registry.shutdown_failed
    observation.stopped(output_drained=True)
    assert registry.await_stopped(0)
    registry.require_stopped()
    assert not registry.shutdown_failed


def test_structured_execution_is_tracked_without_a_queue_guard(tmp_path: Path) -> None:
    registry = HostOwnedProcessRegistry()
    started_file = tmp_path / "started"
    errors: list[BaseException] = []

    def execute() -> None:
        try:
            with registry.operation_scope("operation_structured"):
                run_structured_command(
                    (
                        sys.executable,
                        "-c",
                        f"import pathlib,time; pathlib.Path({str(started_file)!r}).touch(); "
                        "time.sleep(0.3)",
                    ),
                    cwd=tmp_path,
                    env={},
                    input="",
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=execute)
    thread.start()
    deadline = time.monotonic() + 1
    while not started_file.exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert started_file.exists()
    snapshot = registry.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].operation_id == "operation_structured"
    assert snapshot[0].kind == "structured"
    assert not registry.await_stopped(0.01)
    thread.join(timeout=3)
    assert not thread.is_alive() and not errors
    registry.require_stopped()


def _escaped_source(pid_file: Path, *, wait: bool) -> str:
    return (
        "import pathlib,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'], "
        "start_new_session=True); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); "
        + ("time.sleep(20)" if wait else "")
    )


def _stop_fixture_child(pid_file: Path) -> None:
    if pid_file.exists():
        with suppress(ProcessLookupError):
            os.kill(int(pid_file.read_text()), signal.SIGKILL)


def test_native_escaped_pipe_is_bounded_and_blocks_service_ready(tmp_path: Path) -> None:
    registry = HostOwnedProcessRegistry()
    pid_file = tmp_path / "escaped.pid"
    observed: list[CodexInvocationResult] = []
    started = time.monotonic()
    try:
        with registry.operation_scope("operation_native"), pytest.raises(CodexExecutionUnconfirmed):
            SubprocessCodexCommandRunner().run_observed(
                (sys.executable, "-c", _escaped_source(pid_file, wait=True)),
                cwd=tmp_path,
                environment={},
                stdin="",
                timeout_seconds=0.2,
                observer=observed.append,
            )
        assert time.monotonic() - started < 4
        assert not observed, "uncertain output drain must not publish a false native stop"
        assert registry.snapshot()[0].state == "uncertain"
        with pytest.raises(OwnedProcessesUncertain):
            registry.require_stopped()
    finally:
        _stop_fixture_child(pid_file)


def test_tool_escaped_pipe_retains_uncertain_observation(tmp_path: Path) -> None:
    registry = HostOwnedProcessRegistry()
    pid_file = tmp_path / "escaped.pid"
    permissions = AgentPermissions(
        read_paths=("**",),
        write_paths=("**",),
        commands=(sys.executable,),
        network=NetworkAccess.NONE,
    )
    try:
        with registry.operation_scope("operation_tool"), pytest.raises(CommandExecutionUncertain):
            SubprocessCommandExecutor(tmp_path, permissions).run(
                (sys.executable, "-c", _escaped_source(pid_file, wait=False)),
                timeout_seconds=2,
            )
        assert registry.snapshot()[0].state == "uncertain"
        assert not registry.await_stopped(0)
    finally:
        _stop_fixture_child(pid_file)


def test_registry_cannot_register_a_process_by_user_selected_pid() -> None:
    registry = HostOwnedProcessRegistry()
    with (
        registry.operation_scope("operation_no_prompt_authority"),
        pytest.raises(AttributeError),
    ):
        observe_owned_process(123, kind="native")  # type: ignore[arg-type]
    registry.require_stopped()


def test_native_stop_save_failure_refuses_service_ready(tmp_path: Path) -> None:
    registry = HostOwnedProcessRegistry()

    def reject_stop(_: CodexInvocationResult) -> None:
        raise OSError("isolated stop record write failed")

    with registry.operation_scope("operation_native_stop_save"), pytest.raises(OSError):
        SubprocessCodexCommandRunner().run_observed(
            (sys.executable, "-c", "print('complete')"),
            cwd=tmp_path,
            environment={},
            stdin="",
            timeout_seconds=1,
            observer=reject_stop,
        )
    assert registry.snapshot()[0].state == "uncertain"
    with pytest.raises(OwnedProcessesUncertain):
        registry.require_stopped()


def test_owned_verification_success_completes_real_process_proof(tmp_path: Path) -> None:
    registry = HostOwnedProcessRegistry()
    with registry.operation_scope("operation_verification"):
        assert (
            bounded_verification_command(
                (sys.executable, "-c", "print('verified')"), cwd=tmp_path, environment={}
            )
            == b"verified\n"
        )
        result = run_owned_subprocess(
            (sys.executable, "-c", "import sys; print(sys.stdin.read())"),
            cwd=tmp_path,
            env={},
            input="private fixture input",
            timeout=1,
        )
        assert result.stdout == "private fixture input\n"
    registry.require_stopped()


def test_owned_verification_escaped_pipe_refuses_ready(tmp_path: Path) -> None:
    registry = HostOwnedProcessRegistry()
    pid_file = tmp_path / "escaped.pid"
    try:
        with (
            registry.operation_scope("operation_verification"),
            pytest.raises(OwnedProcessesUncertain),
        ):
            bounded_verification_command(
                (sys.executable, "-c", _escaped_source(pid_file, wait=False)),
                cwd=tmp_path,
                environment={},
                timeout=1,
            )
        assert registry.snapshot()[0].state == "uncertain"
    finally:
        _stop_fixture_child(pid_file)


def test_mysql_proxy_threads_keep_the_original_operation_scope() -> None:
    registry = HostOwnedProcessRegistry()
    resource = cast(
        IsolatedMysqlResource,
        SimpleNamespace(
            container_id="isolated_proxy_fixture",
            docker_prefix=(
                sys.executable,
                "-c",
                "import os,time; os.write(1,b'fixture greeting'); time.sleep(20)",
            ),
        ),
    )
    # UNIX socket names have an OS byte limit; fixture owns this exact directory.
    with tempfile.TemporaryDirectory(prefix="ase-proxy-", dir="/tmp") as directory:
        endpoint = Path(directory) / "mysql.sock"
        with registry.operation_scope("operation_proxy"):
            proxy = MysqlUnixProxy(resource, endpoint)
        try:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(2)
                client.connect(str(endpoint))
                assert client.recv(64) == b"fixture greeting"
                assert registry.snapshot()[0].operation_id == "operation_proxy"
                assert not registry.await_stopped(0)
        finally:
            proxy.close()
    registry.require_stopped()


def test_closed_output_reader_is_not_eof_or_service_stop_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.execution import _OutputCollector

    def failed_reader(collector: _OutputCollector, stream: BinaryIO) -> None:
        collector._error = OSError("isolated read failure")
        stream.close()

    monkeypatch.setattr(_OutputCollector, "drain", failed_reader)
    registry = HostOwnedProcessRegistry()
    permissions = AgentPermissions(
        read_paths=("**",),
        write_paths=("**",),
        commands=(sys.executable,),
        network=NetworkAccess.NONE,
    )
    with (
        registry.operation_scope("operation_broken_reader"),
        pytest.raises(CommandExecutionUncertain),
    ):
        SubprocessCommandExecutor(tmp_path, permissions).run((sys.executable, "-c", "pass"))
    assert registry.shutdown_failed
    assert registry.snapshot()[0].state == "uncertain"
    with pytest.raises(OwnedProcessesUncertain):
        registry.require_stopped()
