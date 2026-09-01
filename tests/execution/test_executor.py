"""T015 tests for the policy-bound subprocess executor."""

import os
import sys
import time
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentPermissions, NetworkAccess
from ai_software_engineer.execution import (
    CommandExecutionError,
    CommandTimedOut,
    SubprocessCommandExecutor,
)
from ai_software_engineer.git import CommandPolicyViolation, PathPolicyViolation


def _permissions() -> AgentPermissions:
    return AgentPermissions(
        read_paths=("src/**", "tests/**"),
        write_paths=("src/**", "tests/**"),
        commands=(sys.executable,),
        network=NetworkAccess.NONE,
    )


def _executor(
    tmp_path: Path,
    *,
    environment: dict[str, str] | None = None,
    environment_allowlist: tuple[str, ...] = ("PATH", "LANG", "LC_ALL"),
    default_timeout_seconds: float = 600.0,
    max_output_bytes: int = 1_000_000,
) -> SubprocessCommandExecutor:
    return SubprocessCommandExecutor(
        tmp_path,
        _permissions(),
        environment=environment,
        environment_allowlist=environment_allowlist,
        default_timeout_seconds=default_timeout_seconds,
        max_output_bytes=max_output_bytes,
    )


def test_successful_command_returns_bounded_typed_evidence(tmp_path: Path) -> None:
    result = _executor(tmp_path).run(
        (sys.executable, "-c", "import os; print(os.getcwd()); print('ready')")
    )

    assert result.returncode == 0
    assert result.cwd == str(tmp_path.resolve())
    assert result.stdout.splitlines() == [str(tmp_path.resolve()), "ready"]
    assert result.stderr == ""
    assert result.stdout_truncated is False
    assert result.argv[0] == sys.executable


def test_nonzero_exit_is_returned_without_a_fake_pass(tmp_path: Path) -> None:
    result = _executor(tmp_path).run((sys.executable, "-c", "import sys; sys.exit(7)"))

    assert result.returncode == 7
    assert result.stdout == ""


def test_output_is_truncated_at_the_configured_limit(tmp_path: Path) -> None:
    result = _executor(tmp_path, max_output_bytes=16).run(
        (sys.executable, "-c", "print('x' * 100)")
    )

    assert len(result.stdout.encode("utf-8")) <= 16
    assert result.stdout_truncated is True


def test_default_environment_does_not_leak_unallowlisted_secrets(tmp_path: Path) -> None:
    result = _executor(
        tmp_path,
        environment={"PATH": os.defpath, "ASE_SECRET": "do-not-leak"},
    ).run((sys.executable, "-c", "import os; print(os.getenv('ASE_SECRET'))"))

    assert result.stdout.strip() == "None"


def test_explicit_environment_allowlist_is_the_only_opt_in(tmp_path: Path) -> None:
    result = _executor(
        tmp_path,
        environment={"PATH": os.defpath, "ASE_SAFE": "allowed"},
        environment_allowlist=("PATH", "ASE_SAFE"),
    ).run((sys.executable, "-c", "import os; print(os.getenv('ASE_SAFE'))"))

    assert result.stdout.strip() == "allowed"


def test_policy_rejects_unauthorized_and_shell_like_argv(tmp_path: Path) -> None:
    executor = _executor(tmp_path)

    with pytest.raises(CommandPolicyViolation):
        executor.run(("echo", "not-allowlisted"))
    with pytest.raises(CommandPolicyViolation):
        executor.run((sys.executable, "-c", "print('x')", ";", "echo", "bad"))


def test_timeout_terminates_the_process_group_without_output_evidence(tmp_path: Path) -> None:
    with pytest.raises(CommandTimedOut) as error:
        _executor(tmp_path).run(
            (sys.executable, "-c", "import time; time.sleep(10)"),
            timeout_seconds=0.05,
        )

    assert error.value.arguments[0] == sys.executable
    assert error.value.duration_ms >= 0
    assert str(error.value) == "command timed out"


def test_timeout_kills_descendant_processes_too(tmp_path: Path) -> None:
    marker = tmp_path / "descendant-survived"
    child_code = f"import pathlib, time; time.sleep(0.2); pathlib.Path({str(marker)!r}).touch()"
    parent_code = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(10)"
    )

    with pytest.raises(CommandTimedOut):
        _executor(tmp_path).run((sys.executable, "-c", parent_code), timeout_seconds=0.05)

    time.sleep(0.3)
    assert not marker.exists()


def test_invalid_timeout_and_environment_configuration_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_output_bytes"):
        _executor(tmp_path, max_output_bytes=0)
    with pytest.raises(ValueError, match="environment variable name"):
        _executor(tmp_path, environment_allowlist=("not_safe",))
    with pytest.raises(ValueError, match="timeout_seconds"):
        _executor(tmp_path, default_timeout_seconds=0)
    with pytest.raises(ValueError, match="timeout_seconds"):
        _executor(tmp_path).run((sys.executable,), timeout_seconds=float("inf"))


def test_missing_workspace_is_rejected_before_subprocess_start(tmp_path: Path) -> None:
    with pytest.raises(PathPolicyViolation):
        SubprocessCommandExecutor(tmp_path / "missing", _permissions())


def test_missing_executable_is_an_execution_error(tmp_path: Path) -> None:
    permissions = _permissions().model_copy(update={"commands": ("definitely-not-an-executable",)})

    with pytest.raises(CommandExecutionError, match="could not start"):
        SubprocessCommandExecutor(tmp_path, permissions).run(("definitely-not-an-executable",))
