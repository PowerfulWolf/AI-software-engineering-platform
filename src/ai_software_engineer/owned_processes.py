"""Trusted Host-owned process observations for safe service draining.

Only real runners register the Popen objects they have just spawned. This port
does not select or signal arbitrary process IDs, and is absent from Agent tools.
Finished operation threads alone cannot clear uncertain process observations.
"""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

OwnedProcessKind = Literal["native", "structured", "tool"]
OwnedProcessState = Literal["running", "uncertain"]


class OwnedProcessesUncertain(RuntimeError):
    """The trusted Host still owns a process without a verified complete stop."""


@dataclass(frozen=True, slots=True)
class OwnedProcessSnapshot:
    operation_id: str
    process_id: int
    kind: OwnedProcessKind
    state: OwnedProcessState
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class OwnedOperationContext:
    registry: HostOwnedProcessRegistry
    operation_id: str

    def activate(self) -> AbstractContextManager[None]:
        return self.registry.operation_scope(self.operation_id)


_operation_context: ContextVar[OwnedOperationContext | None] = ContextVar(
    "host_owned_process_operation", default=None
)


class HostOwnedProcessRegistry:
    """A bounded live set: observations disappear only after group and pipe proof."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._processes: dict[int, OwnedProcessSnapshot] = {}
        self._next_identity = 0

    @contextmanager
    def operation_scope(self, operation_id: str) -> Iterator[None]:
        if not operation_id or len(operation_id) > 256:
            raise ValueError("owned execution requires an exact operation identity")
        token = _operation_context.set(OwnedOperationContext(self, operation_id))
        try:
            yield
        finally:
            _operation_context.reset(token)

    def snapshot(self) -> tuple[OwnedProcessSnapshot, ...]:
        with self._condition:
            return tuple(self._processes.values())

    @property
    def shutdown_failed(self) -> bool:
        return any(value.state == "uncertain" for value in self.snapshot())

    def require_stopped(self) -> None:
        if self.snapshot():
            raise OwnedProcessesUncertain("当前服务仍有执行进程或输出收尾尚未确认停止")

    def await_stopped(self, timeout_seconds: float) -> bool:
        if timeout_seconds < 0 or not timeout_seconds < float("inf"):
            raise ValueError("owned process drain requires a finite nonnegative timeout")
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while self._processes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def _register(
        self,
        process: subprocess.Popen[str] | subprocess.Popen[bytes],
        *,
        operation_id: str,
        kind: OwnedProcessKind,
    ) -> OwnedProcessObservation:
        with self._condition:
            identity = self._next_identity
            self._next_identity += 1
            self._processes[identity] = OwnedProcessSnapshot(
                operation_id, process.pid, kind, "running"
            )
        return OwnedProcessObservation(self, identity, process)

    def _uncertain(self, identity: int) -> None:
        with self._condition:
            previous = self._processes.get(identity)
            if previous is not None:
                self._processes[identity] = OwnedProcessSnapshot(
                    previous.operation_id,
                    previous.process_id,
                    previous.kind,
                    "uncertain",
                    "执行停止、输出收尾或停止记录保存尚未完成核验",
                )
                self._condition.notify_all()

    def _stopped(self, identity: int) -> None:
        with self._condition:
            self._processes.pop(identity, None)
            self._condition.notify_all()


class OwnedProcessObservation:
    """Capability for one actual spawn; no supplied PID or kill operation."""

    def __init__(
        self,
        registry: HostOwnedProcessRegistry,
        identity: int,
        process: subprocess.Popen[str] | subprocess.Popen[bytes],
    ) -> None:
        self._registry = registry
        self._identity = identity
        self._process = process

    def uncertain(self) -> None:
        self._registry._uncertain(self._identity)

    def stopped(self, *, output_drained: bool) -> None:
        """Recheck owned leader/group; output proof belongs to the real pipe runner."""
        try:
            if not output_drained or self._process.poll() is None:
                raise OwnedProcessesUncertain("执行进程和输出收尾尚未确认停止")
            try:
                os.killpg(self._process.pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise OwnedProcessesUncertain("执行进程组尚未确认停止")
        except (OSError, OwnedProcessesUncertain) as error:
            self.uncertain()
            raise OwnedProcessesUncertain("执行进程停止状态无法确认") from error
        self._registry._stopped(self._identity)


def observe_owned_process(
    process: subprocess.Popen[str] | subprocess.Popen[bytes], *, kind: OwnedProcessKind
) -> OwnedProcessObservation | None:
    """Called immediately after trusted runners spawn an isolated process session."""
    context = _operation_context.get()
    if context is None:
        return None
    return context.registry._register(process, operation_id=context.operation_id, kind=kind)


def current_owned_operation() -> OwnedOperationContext | None:
    """Trusted thread owners explicitly carry this capability to their own workers."""
    return _operation_context.get()


def finish_owned_process(
    process: subprocess.Popen[str] | subprocess.Popen[bytes],
    observation: OwnedProcessObservation | None,
    *,
    output_drained: bool,
    timeout_seconds: float = 1.0,
) -> None:
    """Stop one actual owned group and drain its pipes, within an explicit bound.

    Used by trusted verification runners, never exposed as an Agent command.
    Closing a local descriptor is not evidence that an escaped peer has stopped.
    """
    try:
        # Reap an already-exited leader first. macOS can return EPERM rather
        # than ESRCH for the transient group containing its unreaped zombie.
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            pass
        except PermissionError:
            # This is not stop proof: the following wait plus group absence is
            # still mandatory. A live inaccessible process times out/refuses.
            process.wait(timeout=timeout_seconds)
        else:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=timeout_seconds)
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break
            except PermissionError:
                # Do not treat inaccessible/zombie groups as absent. Recheck
                # within the bound; only actual ESRCH is stop evidence.
                pass
            if time.monotonic() >= deadline:
                raise OwnedProcessesUncertain("执行进程组尚未确认停止")
            time.sleep(0.01)
        if not output_drained:
            with selectors.DefaultSelector() as selector:
                for stream in (process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        selector.register(stream, selectors.EVENT_READ)
                deadline = time.monotonic() + timeout_seconds
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise OwnedProcessesUncertain("执行输出管道尚未确认停止")
                    for key, _ in selector.select(min(0.1, remaining)):
                        if not os.read(key.fd, 65_536):
                            selector.unregister(key.fileobj)
        if observation is not None:
            observation.stopped(output_drained=True)
    except (OSError, subprocess.SubprocessError, OwnedProcessesUncertain) as error:
        if observation is not None:
            observation.uncertain()
        raise OwnedProcessesUncertain("执行进程组和输出收尾停止状态无法确认") from error


def run_owned_subprocess(
    argv: tuple[str, ...] | list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: int,
    input: str | None = None,
    capture_output: bool = True,
    text: bool = True,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Trusted native UI build/driver seam with an isolated and tracked session."""
    if not capture_output or not text:
        raise ValueError("owned verification commands require captured text output")
    with tempfile.TemporaryFile(mode="w+b") as stdin:
        stdin.write((input or "").encode("utf-8"))
        stdin.seek(0)
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=dict(env),
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
        observation = observe_owned_process(process, kind="tool")
    drained = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        drained = True
        if check and process.returncode:
            raise subprocess.CalledProcessError(process.returncode, argv, stdout, stderr)
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    finally:
        try:
            finish_owned_process(process, observation, output_drained=drained)
        finally:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
