"""Fail-closed, policy-bound subprocess execution for role worktrees."""

import math
import os
import re
import signal
import subprocess
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from pydantic import Field, StrictBool, StrictInt

from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.git import WorkspacePolicy

_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_DEFAULT_ENVIRONMENT_ALLOWLIST = ("PATH", "LANG", "LC_ALL")
_FIXED_ENVIRONMENT = {"LANG": "C", "LC_ALL": "C"}


class CommandExecutionError(RuntimeError):
    """Raised when an allowlisted command cannot be started."""


class CommandTimedOut(CommandExecutionError):
    """Raised after the command process group is terminated at its timeout."""

    def __init__(self, arguments: tuple[str, ...], duration_ms: int) -> None:
        super().__init__("command timed out")
        self.arguments = arguments
        self.duration_ms = duration_ms


@dataclass(frozen=True, slots=True)
class CommandExecutorSettings:
    """Validated reusable limits for one or more role-bound executors."""

    environment_allowlist: tuple[str, ...] = _DEFAULT_ENVIRONMENT_ALLOWLIST
    default_timeout_seconds: float = 600.0
    max_output_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "environment_allowlist",
            _validate_environment_allowlist(self.environment_allowlist),
        )
        object.__setattr__(
            self,
            "default_timeout_seconds",
            _validate_timeout(self.default_timeout_seconds),
        )
        if type(self.max_output_bytes) is not int or self.max_output_bytes < 1:
            raise ValueError("max_output_bytes must be a positive integer")


class CommandResult(DomainModel):
    """Bounded, serializable evidence returned by one command invocation."""

    argv: tuple[NonEmptyStr, ...] = Field(min_length=1)
    cwd: NonEmptyStr
    returncode: StrictInt
    stdout: str
    stderr: str
    duration_ms: StrictInt = Field(ge=0)
    stdout_truncated: StrictBool = False
    stderr_truncated: StrictBool = False


class CommandExecutor(Protocol):
    """Port used by QA/Coder services to run already-tokenized commands."""

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult: ...


class SubprocessCommandExecutor:
    """Execute one command in a fixed worktree with policy and environment guards."""

    def __init__(
        self,
        workspace_root: str | Path,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
        environment: Mapping[str, str] | None = None,
        environment_allowlist: tuple[str, ...] = _DEFAULT_ENVIRONMENT_ALLOWLIST,
        default_timeout_seconds: float = 600.0,
        max_output_bytes: int = 1_000_000,
    ) -> None:
        settings = CommandExecutorSettings(
            environment_allowlist=environment_allowlist,
            default_timeout_seconds=default_timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        self._workspace_root = Path(workspace_root).resolve()
        self._policy = WorkspacePolicy(
            self._workspace_root,
            permissions,
            denied_paths=denied_paths,
        )
        self._environment = dict(environment if environment is not None else os.environ)
        self._environment_allowlist = settings.environment_allowlist
        self._default_timeout_seconds = settings.default_timeout_seconds
        self._max_output_bytes = settings.max_output_bytes

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        """Authorize and execute argv without invoking a shell or inheriting secrets."""
        authorized = self._policy.authorize_command(arguments)
        timeout = (
            self._default_timeout_seconds
            if timeout_seconds is None
            else _validate_timeout(timeout_seconds)
        )
        started = time.monotonic()
        process: subprocess.Popen[bytes] | None = None
        collectors: tuple[_OutputCollector, _OutputCollector] | None = None
        drain_threads: tuple[threading.Thread, threading.Thread] | None = None
        try:
            process = subprocess.Popen(
                authorized,
                cwd=self._workspace_root,
                env=self._build_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=True,
            )
            if process.stdout is None or process.stderr is None:
                raise CommandExecutionError("command output pipes were not created")
            collectors = (
                _OutputCollector(self._max_output_bytes),
                _OutputCollector(self._max_output_bytes),
            )
            drain_threads = (
                threading.Thread(
                    target=collectors[0].drain,
                    args=(process.stdout,),
                    daemon=True,
                ),
                threading.Thread(
                    target=collectors[1].drain,
                    args=(process.stderr,),
                    daemon=True,
                ),
            )
            for thread in drain_threads:
                thread.start()
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            duration_ms = _duration_ms(started)
            if process is not None:
                _terminate_process_group(process)
            if drain_threads is not None:
                _join_drain_threads(drain_threads)
            raise CommandTimedOut(authorized, duration_ms) from error
        except OSError as error:
            raise CommandExecutionError("command could not start") from error

        if collectors is None or drain_threads is None:
            raise CommandExecutionError("command output capture was not initialized")
        _join_drain_threads(drain_threads)
        stdout_text, stdout_truncated = collectors[0].result()
        stderr_text, stderr_truncated = collectors[1].result()
        return CommandResult(
            argv=authorized,
            cwd=str(self._workspace_root),
            returncode=process.returncode,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_ms=_duration_ms(started),
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

    def _build_environment(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for name in self._environment_allowlist:
            if name in _FIXED_ENVIRONMENT:
                result[name] = _FIXED_ENVIRONMENT[name]
            elif name == "PATH":
                result[name] = self._environment.get(name, os.defpath)
            elif name in self._environment:
                result[name] = self._environment[name]
        result.setdefault("PATH", os.defpath)
        result.update(_FIXED_ENVIRONMENT)
        return result


def _validate_environment_allowlist(names: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(names)) != len(names):
        raise ValueError("environment_allowlist entries must be unique")
    for name in names:
        if not isinstance(name, str) or _ENV_NAME.fullmatch(name) is None:
            raise ValueError(f"invalid environment variable name: {name!r}")
    return names


def _validate_timeout(timeout_seconds: float) -> float:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be finite and positive")
    return float(timeout_seconds)


class _OutputCollector:
    """Drain a pipe completely while retaining at most the configured byte budget."""

    def __init__(self, max_output_bytes: int) -> None:
        self._max_output_bytes = max_output_bytes
        self._buffer = bytearray()
        self._truncated = False
        self._error: OSError | None = None

    def drain(self, stream: BinaryIO) -> None:
        try:
            while chunk := stream.read(64 * 1024):
                remaining = self._max_output_bytes - len(self._buffer)
                if remaining > 0:
                    self._buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self._truncated = True
        except OSError as error:
            self._error = error
        finally:
            stream.close()

    def result(self) -> tuple[str, bool]:
        if self._error is not None:
            raise CommandExecutionError("command output could not be read") from self._error
        return self._buffer.decode("utf-8", errors="replace"), self._truncated


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _join_drain_threads(threads: tuple[threading.Thread, threading.Thread]) -> None:
    for thread in threads:
        thread.join(timeout=1.0)
        if thread.is_alive():
            raise CommandExecutionError("command output pipe did not close")


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate the child process group, escalating to SIGKILL if needed."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        with suppress(ProcessLookupError):
            process.terminate()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            with suppress(ProcessLookupError):
                process.kill()
        process.wait()


__all__ = [
    "CommandExecutionError",
    "CommandExecutor",
    "CommandExecutorSettings",
    "CommandResult",
    "CommandTimedOut",
    "SubprocessCommandExecutor",
]
