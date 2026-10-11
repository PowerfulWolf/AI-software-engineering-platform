"""Trusted Host-owned process observations for safe service draining.

Only real runners register the Popen objects they have just spawned. This port
does not select or signal arbitrary process IDs, and is absent from Agent tools.
Finished operation threads alone cannot clear uncertain process observations.
"""

from __future__ import annotations

import os
import selectors
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

from ai_software_engineer.owned_sessions import (
    OwnedSessionController,
    OwnedSessionStopProof,
    OwnedSessionUnknown,
)

OwnedProcessKind = Literal["native", "structured", "tool"]
OwnedProcessState = Literal["running", "finalizing", "uncertain"]
_MAX_FINALIZATION_PROCESSES = 4096


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

_record_finalization: ContextVar[OwnedRecordFinalization | None] = ContextVar(
    "owned_process_record_finalization",
    default=None,
)


class OwnedRecordFinalization:
    """Trusted application save boundary; absent from every Agent tool registry."""

    def __init__(self, parent: OwnedRecordFinalization | None) -> None:
        self._parent = parent
        self._lock = threading.Lock()
        self._observations: dict[int, OwnedProcessObservation] = {}
        self._saved = False
        self._closed = False
        self._invalid = False

    def confirm_saved(self) -> None:
        """Only call after the exact typed store put/seal has actually returned."""
        with self._lock:
            if self._closed or self._saved or self._invalid:
                self._invalid = True
                raise OwnedProcessesUncertain("执行记录保存确认不能重复或迟到")
            self._saved = True

    def _add(self, observation: OwnedProcessObservation) -> None:
        with self._lock:
            if id(observation) in self._observations:
                return
            if (
                self._closed
                or self._saved
                or self._invalid
                or len(self._observations) >= _MAX_FINALIZATION_PROCESSES
            ):
                self._invalid = True
                observation.uncertain()
                raise OwnedProcessesUncertain("执行记录收尾范围已关闭或超出有界数量")
            self._observations[id(observation)] = observation
        observation._finalizing()

    @contextmanager
    def activate(self) -> Iterator[None]:
        """Only trusted owned worker threads carry their parent's save boundary."""
        token = _record_finalization.set(self)
        try:
            yield
        finally:
            _record_finalization.reset(token)

    def _finish(self) -> None:
        with self._lock:
            observations = tuple(self._observations.values())
            self._observations.clear()
            self._closed = True
            saved = self._saved and not self._invalid
            parent, self._parent = self._parent, None
        if not saved:
            for observation in observations:
                observation.uncertain()
            return
        try:
            if parent is not None:
                for observation in observations:
                    parent._add(observation)
            else:
                for observation in observations:
                    observation._validate_stopped(output_drained=True)
                for observation in observations:
                    observation._complete_saved()
        except BaseException:
            for observation in observations:
                observation.uncertain()
            raise


@contextmanager
def owned_record_finalization() -> Iterator[OwnedRecordFinalization]:
    """Defer Host registry removal until the owning application confirms save."""
    scope = OwnedRecordFinalization(_record_finalization.get())
    with scope.activate():
        try:
            yield scope
        finally:
            scope._finish()


def current_owned_record_finalization() -> OwnedRecordFinalization | None:
    return _record_finalization.get()


class HostOwnedProcessRegistry:
    """A live set: only complete original-session and pipe proof can clear it."""

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
        observation: OwnedProcessObservation | None = None,
    ) -> OwnedProcessObservation:
        with self._condition:
            identity = self._next_identity
            self._next_identity += 1
            self._processes[identity] = OwnedProcessSnapshot(
                operation_id, process.pid, kind, "running"
            )
        if observation is None:
            return OwnedProcessObservation(self, identity, process)
        observation._bind(self, identity, process)
        return observation

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

    def _finalizing(self, identity: int) -> None:
        with self._condition:
            previous = self._processes.get(identity)
            if previous is not None and previous.state != "uncertain":
                self._processes[identity] = OwnedProcessSnapshot(
                    previous.operation_id,
                    previous.process_id,
                    previous.kind,
                    "finalizing",
                    "执行已停止, 等待实际记录保存完成",
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
        registry: HostOwnedProcessRegistry | None,
        identity: int | None,
        process: subprocess.Popen[str] | subprocess.Popen[bytes],
    ) -> None:
        self._registry = registry
        self._identity = identity
        self._process = process
        self._controller: OwnedSessionController | None = None
        self._capture_failed = False
        try:
            self._controller = OwnedSessionController(process)
        except (OSError, ValueError, OwnedSessionUnknown):
            # A raw exception would retain its traceback and interrupted caller
            # scope for the entire lifetime of this registry capability.
            self._capture_failed = True
            self.uncertain()

    def uncertain(self) -> None:
        if self._registry is not None and self._identity is not None:
            self._registry._uncertain(self._identity)

    def _bind(
        self,
        registry: HostOwnedProcessRegistry,
        identity: int,
        process: subprocess.Popen[str] | subprocess.Popen[bytes],
    ) -> None:
        if self._process is not process or self._registry is not None:
            registry._uncertain(identity)
            raise OwnedProcessesUncertain("执行会话不能绑定到其他启动或重复注册")
        self._registry, self._identity = registry, identity
        if self._capture_failed:
            self.uncertain()

    def stop_session(self, *, timeout_seconds: float = 1.0) -> OwnedSessionStopProof:
        """Only the actual captured spawn can stop its freshly verified SID peers."""
        try:
            if self._controller is None:
                # Capture failure still permits cleaning the actual owned leader;
                # this supplies no session proof and never clears uncertainty.
                self._process.kill()
                self._process.wait(timeout=timeout_seconds)
                raise OwnedSessionUnknown("spawn ownership could not be completely captured")
            return self._controller.stop(timeout_seconds=timeout_seconds)
        except (OSError, ValueError, subprocess.SubprocessError, OwnedSessionUnknown) as error:
            self.uncertain()
            raise OwnedProcessesUncertain("执行会话的完整停止状态无法确认") from error

    def observe_session(self) -> None:
        """Trusted finite owner polling; never exposed as an Agent operation."""
        try:
            if self._controller is None:
                raise OwnedSessionUnknown("spawn ownership capture failed")
            self._controller.observe_session()
        except (OSError, ValueError, OwnedSessionUnknown) as error:
            self.uncertain()
            raise OwnedProcessesUncertain("执行会话的当前归属状态无法确认") from error

    def stopped(self, *, output_drained: bool) -> None:
        """Independently recheck exact owned SID; the runner proves actual EOF."""
        self._validate_stopped(output_drained=output_drained)
        scope = _record_finalization.get()
        if scope is not None:
            scope._add(self)
        else:
            self._complete_saved()

    def _finalizing(self) -> None:
        if self._registry is not None and self._identity is not None:
            self._registry._finalizing(self._identity)

    def _validate_stopped(self, *, output_drained: bool) -> None:
        try:
            if not output_drained or self._process.poll() is None:
                raise OwnedProcessesUncertain("执行进程和输出收尾尚未确认停止")
            if self._controller is None:
                raise OwnedProcessesUncertain("执行会话归属尚未确认")
            self._controller.require_empty()
        except (OSError, OwnedSessionUnknown, OwnedProcessesUncertain) as error:
            self.uncertain()
            raise OwnedProcessesUncertain("执行进程停止状态无法确认") from error

    def _complete_saved(self) -> None:
        self._validate_stopped(output_drained=True)
        if self._registry is not None and self._identity is not None:
            self._registry._stopped(self._identity)


def observe_owned_process(
    process: subprocess.Popen[str] | subprocess.Popen[bytes],
    *,
    kind: OwnedProcessKind,
    observation: OwnedProcessObservation | None = None,
) -> OwnedProcessObservation:
    """Called immediately after trusted runners spawn an isolated process session."""
    context = _operation_context.get()
    if context is None:
        if observation is not None:
            if observation._process is not process:
                raise OwnedProcessesUncertain("执行会话与真实启动不一致")
            return observation
        return capture_owned_process(process)
    return context.registry._register(
        process,
        operation_id=context.operation_id,
        kind=kind,
        observation=observation,
    )


def capture_owned_process(
    process: subprocess.Popen[str] | subprocess.Popen[bytes],
) -> OwnedProcessObservation:
    """Capture actual spawn before resource close or fallible Host registration."""
    return OwnedProcessObservation(None, None, process)


def current_owned_operation() -> OwnedOperationContext | None:
    """Trusted thread owners explicitly carry this capability to their own workers."""
    return _operation_context.get()


def finish_owned_process(
    process: subprocess.Popen[str] | subprocess.Popen[bytes],
    observation: OwnedProcessObservation | None,
    *,
    output_drained: bool,
    timeout_seconds: float = 1.0,
    complete_observation: bool = True,
) -> None:
    """Stop the captured actual session and drain its pipes within finite bounds.

    Used by trusted verification runners, never exposed as an Agent command.
    Closing a local descriptor is not evidence that an escaped peer has stopped.
    """
    try:
        if observation is None:
            # Missing ownership cannot be reconstructed after leader reap.
            with suppress(OSError):
                process.kill()
            process.wait(timeout=timeout_seconds)
            raise OwnedProcessesUncertain("执行会话缺少启动时的完整归属记录")
        observation.stop_session(timeout_seconds=timeout_seconds)
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
        if complete_observation:
            observation.stopped(output_drained=True)
    except (OSError, subprocess.SubprocessError, OwnedProcessesUncertain) as error:
        if observation is not None:
            observation.uncertain()
        raise OwnedProcessesUncertain("执行会话和输出收尾停止状态无法确认") from error


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
