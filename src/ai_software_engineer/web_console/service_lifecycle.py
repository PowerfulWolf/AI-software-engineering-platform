"""Private, instance-bound handshake and coordination for controlled local shutdown."""

from __future__ import annotations

import os
import secrets
import stat
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal, Protocol

from pydantic import Field, StringConstraints, ValidationError, field_validator, model_validator

from ai_software_engineer.domain.model import DomainModel

from .shutdown import ServiceWriteGate, ShutdownResult, ShutdownState

ServiceInstanceId = Annotated[str, StringConstraints(pattern=r"^console_instance_[a-f0-9]{32}$")]
ServiceShutdownRequestId = Annotated[
    str, StringConstraints(pattern=r"^console_shutdown_[a-f0-9]{32}$")
]
ServicePid = Annotated[int, Field(gt=1, strict=True)]


class ServiceLifecycleError(RuntimeError):
    """Private lifecycle facts cannot be safely read or published."""


class ServiceState(StrEnum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"
    READY = "READY"
    REFUSED = "REFUSED"


class ServiceShutdownAction(StrEnum):
    SHUTDOWN = "SHUTDOWN"
    RESUME = "RESUME"


_SUMMARIES = {
    ServiceState.STARTING: "服务正在启动, 尚未接收操作。",
    ServiceState.RUNNING: "服务正在运行, 可以接收新操作。",
    ServiceState.DRAINING: "服务正在安全收尾, 已暂停新操作。",
    ServiceState.READY: "当前操作与写入已保存, 执行器和索引已结束, 可以安全退出服务。",
    ServiceState.REFUSED: (
        "尚未确认安全收尾, 已暂停新操作。请查看服务状态; 若只是等待超时, 可重试等待或解除安全停止。"
    ),
}


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("service lifecycle timestamps must be timezone-aware")
    return value.astimezone(UTC)


class ServiceInstance(DomainModel):
    schema_version: Literal["v1"] = "v1"
    instance_id: ServiceInstanceId
    pid: ServicePid
    state: ServiceState = ServiceState.RUNNING
    started_at: datetime
    updated_at: datetime
    safe_summary: str

    _timestamps = field_validator("started_at", "updated_at")(_aware)

    @model_validator(mode="after")
    def valid_state(self) -> ServiceInstance:
        if self.updated_at < self.started_at or self.safe_summary != _SUMMARIES[self.state]:
            raise ValueError("invalid service instance state")
        return self

    @classmethod
    def new(cls, *, pid: int, at: datetime) -> ServiceInstance:
        return cls(
            instance_id="console_instance_" + secrets.token_hex(16),
            pid=pid,
            started_at=at,
            updated_at=at,
            safe_summary=_SUMMARIES[ServiceState.RUNNING],
        )

    def with_state(self, state: ServiceState, *, at: datetime) -> ServiceInstance:
        return ServiceInstance(
            **self.model_dump(exclude={"state", "updated_at", "safe_summary"}),
            state=state,
            updated_at=at,
            safe_summary=_SUMMARIES[state],
        )


class ServiceShutdownRequest(DomainModel):
    schema_version: Literal["v1"] = "v1"
    request_id: ServiceShutdownRequestId
    instance_id: ServiceInstanceId
    pid: ServicePid
    action: ServiceShutdownAction = ServiceShutdownAction.SHUTDOWN
    state: Literal["REQUESTED"] = "REQUESTED"
    requested_at: datetime
    timeout_seconds: Annotated[float, Field(ge=0.01, le=3600, allow_inf_nan=False)] = 300.0

    _timestamp = field_validator("requested_at")(_aware)

    @classmethod
    def new(
        cls,
        instance: ServiceInstance,
        *,
        at: datetime,
        timeout_seconds: float = 300.0,
        action: ServiceShutdownAction = ServiceShutdownAction.SHUTDOWN,
    ) -> ServiceShutdownRequest:
        return cls(
            request_id="console_shutdown_" + secrets.token_hex(16),
            instance_id=instance.instance_id,
            pid=instance.pid,
            requested_at=at,
            timeout_seconds=timeout_seconds,
            action=action,
        )

    def matches(self, instance: ServiceInstance) -> bool:
        return (
            self.instance_id == instance.instance_id
            and self.pid == instance.pid
            and self.requested_at >= instance.started_at
        )


class ServiceShutdownResult(DomainModel):
    schema_version: Literal["v1"] = "v1"
    request_id: ServiceShutdownRequestId
    instance_id: ServiceInstanceId
    pid: ServicePid
    state: ServiceState
    recorded_at: datetime
    safe_summary: str

    _timestamp = field_validator("recorded_at")(_aware)

    @model_validator(mode="after")
    def fixed_summary(self) -> ServiceShutdownResult:
        if self.safe_summary != _SUMMARIES[self.state]:
            raise ValueError("service shutdown summary must use safe fixed text")
        return self

    @classmethod
    def for_request(
        cls, request: ServiceShutdownRequest, *, state: ServiceState, at: datetime
    ) -> ServiceShutdownResult:
        return cls(
            request_id=request.request_id,
            instance_id=request.instance_id,
            pid=request.pid,
            state=state,
            recorded_at=at,
            safe_summary=_SUMMARIES[state],
        )

    def matches(self, request: ServiceShutdownRequest) -> bool:
        return (
            self.request_id == request.request_id
            and self.instance_id == request.instance_id
            and self.pid == request.pid
        )


class ServiceLifecycleStore:
    """Only fixed private filenames; reads never follow symlinks or unbounded payloads."""

    FILENAMES = (
        "console-service-instance.json",
        "console-service-shutdown.request.json",
        "console-service-shutdown.result.json",
    )
    MAX_BYTES = 8192

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().absolute()
        if self.root == Path("/"):
            raise ServiceLifecycleError("服务生命周期目录不可用。")
        self._lock = Lock()

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> ServiceLifecycleStore:
        configured = environment.get("ASE_SERVICE_STATE_DIR")
        if configured is not None:
            root = Path(configured)
        else:
            state_home = environment.get("XDG_STATE_HOME")
            if state_home is None:
                home = environment.get("HOME")
                if home is None:
                    raise ServiceLifecycleError("服务生命周期目录不可用。")
                state_home = str(Path(home) / ".local" / "state")
            root = Path(state_home) / "ai-software-engineer"
        if not root.is_absolute():
            raise ServiceLifecycleError("服务生命周期目录不可用。")
        return cls(root)

    def publish_instance(self, value: ServiceInstance) -> None:
        self._write(self.FILENAMES[0], value)

    def read_instance(self) -> ServiceInstance | None:
        return self._read(self.FILENAMES[0], ServiceInstance)

    def write_request(self, value: ServiceShutdownRequest) -> None:
        self._write(self.FILENAMES[1], value)

    def read_request(self) -> ServiceShutdownRequest | None:
        return self._read(self.FILENAMES[1], ServiceShutdownRequest)

    def write_result(self, value: ServiceShutdownResult) -> None:
        self._write(self.FILENAMES[2], value)

    def read_result(self) -> ServiceShutdownResult | None:
        return self._read(self.FILENAMES[2], ServiceShutdownResult)

    def _require_root(self, *, create: bool = False) -> None:
        if create:
            self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        metadata = self.root.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o022
        ):
            raise ServiceLifecycleError("服务生命周期目录不可用。")

    def _read[ModelT: DomainModel](self, name: str, model: type[ModelT]) -> ModelT | None:
        with self._lock:
            descriptor = -1
            try:
                self._require_root()
                try:
                    descriptor = os.open(self.root / name, os.O_RDONLY | os.O_NOFOLLOW)
                except FileNotFoundError:
                    return None
                metadata = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.getuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o600
                    or metadata.st_nlink != 1
                    or metadata.st_size > self.MAX_BYTES
                ):
                    raise ServiceLifecycleError("服务生命周期记录不可用。")
                with os.fdopen(descriptor, "rb") as stream:
                    descriptor = -1
                    payload = stream.read(self.MAX_BYTES + 1)
                if len(payload) > self.MAX_BYTES:
                    raise ServiceLifecycleError("服务生命周期记录不可用。")
                return model.model_validate_json(payload)
            except (OSError, ValidationError) as error:
                raise ServiceLifecycleError("服务生命周期记录不可用。") from error
            finally:
                if descriptor >= 0:
                    os.close(descriptor)

    def _write(self, name: str, value: DomainModel) -> None:
        with self._lock:
            temporary: Path | None = None
            try:
                self._require_root(create=True)
                target = self.root / name
                if target.is_symlink() or (target.exists() and not target.is_file()):
                    raise ServiceLifecycleError("服务生命周期记录不可用。")
                payload = value.model_dump_json().encode("utf-8")
                if len(payload) > self.MAX_BYTES:
                    raise ServiceLifecycleError("服务生命周期记录不可用。")
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=".console-service-", dir=self.root
                )
                temporary = Path(temporary_name)
                with os.fdopen(descriptor, "wb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
                temporary = None
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except OSError as error:
                raise ServiceLifecycleError("服务生命周期记录不可用。") from error
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)


class ConsoleShutdownPort(Protocol):
    def begin_shutdown(self) -> ShutdownResult: ...
    def await_shutdown(self, timeout: float) -> ShutdownResult: ...
    def cancel_shutdown(
        self, *, before_resume: Callable[[], None] | None = None
    ) -> ShutdownResult: ...


class IndexShutdownPort(Protocol):
    @property
    def shutdown_failed(self) -> bool: ...
    def begin_shutdown(self) -> None: ...
    def close(self, *, timeout: float = 5.0) -> bool: ...
    def cancel_shutdown(self) -> None: ...


class OwnedProcessShutdownPort(Protocol):
    @property
    def shutdown_failed(self) -> bool: ...

    def operation_scope(self, operation_id: str) -> AbstractContextManager[None]: ...
    def await_stopped(self, timeout_seconds: float) -> bool: ...


class ConsoleShutdownCoordinator:
    """Quiesce all admission first; completion is conjunctive, never a thread join guess."""

    def __init__(
        self,
        *,
        console: ConsoleShutdownPort,
        write_gate: ServiceWriteGate,
        knowledge_worker: IndexShutdownPort | None = None,
        owned_processes: OwnedProcessShutdownPort | None = None,
    ) -> None:
        self.write_gate = write_gate
        self._console = console
        self._knowledge_worker = knowledge_worker
        self._owned_processes = owned_processes
        self._sticky_failure = False
        self._state = ShutdownState.RUNNING
        self._lock = Lock()

    def begin_shutdown(self) -> ShutdownResult:
        with self._lock:
            self.write_gate.begin_shutdown()
            self._console.begin_shutdown()
            if self._knowledge_worker is not None:
                self._knowledge_worker.begin_shutdown()
            self._state = ShutdownState.REFUSED if self._sticky_failure else ShutdownState.DRAINING
            return _shutdown_result(self._state)

    def await_shutdown(self, timeout: float) -> ShutdownResult:
        deadline = time.monotonic() + max(0, timeout)

        def remaining() -> float:
            return max(0, deadline - time.monotonic())

        try:
            gate = self.write_gate.await_shutdown(remaining())
            if gate.state is not ShutdownState.READY:
                return self._refused()
            operation = self._console.await_shutdown(remaining())
            if operation.state is not ShutdownState.READY:
                return self._refused()
            if self._knowledge_worker is not None and not self._knowledge_worker.close(
                timeout=remaining()
            ):
                if self._knowledge_worker.shutdown_failed:
                    self.record_failure()
                return self._refused()
            if self._owned_processes is not None and not self._owned_processes.await_stopped(
                remaining()
            ):
                if self._owned_processes.shutdown_failed:
                    self.record_failure()
                return self._refused()
        except Exception:
            # Store/worker diagnostics belong to their durable history. No payload escapes
            # this trusted stop boundary, and uncertain finishing never permits replacement.
            with self._lock:
                self._sticky_failure = True
            return self._refused()
        with self._lock:
            if self._sticky_failure:
                return _shutdown_result(ShutdownState.REFUSED)
            self._state = ShutdownState.READY
        return _shutdown_result(ShutdownState.READY)

    def record_failure(self) -> None:
        with self._lock:
            self._sticky_failure = True
            self._state = ShutdownState.REFUSED

    def shutdown_status(self) -> ShutdownResult:
        with self._lock:
            return _shutdown_result(self._state)

    def _refused(self) -> ShutdownResult:
        with self._lock:
            self._state = ShutdownState.REFUSED
        return _shutdown_result(ShutdownState.REFUSED)

    def cancel_shutdown(self, *, before_resume: Callable[[], None] | None = None) -> ShutdownResult:
        with self._lock:
            if self._sticky_failure or self._state is not ShutdownState.REFUSED:
                return _shutdown_result(ShutdownState.REFUSED)
            if self._knowledge_worker is not None and self._knowledge_worker.shutdown_failed:
                self._sticky_failure = True
                return _shutdown_result(ShutdownState.REFUSED)
            if self._owned_processes is not None and self._owned_processes.shutdown_failed:
                self._sticky_failure = True
                return _shutdown_result(ShutdownState.REFUSED)

            def resume_components() -> None:
                if self._knowledge_worker is not None:
                    self._knowledge_worker.cancel_shutdown()
                if before_resume is not None:
                    before_resume()

            # Hold Console admission closed through both durable RESUME and
            # index restart. Thread-start failure must not dispatch a new Operation.
            result = self._console.cancel_shutdown(before_resume=resume_components)
            if result.state is not ShutdownState.RUNNING:
                if self._knowledge_worker is not None:
                    self._knowledge_worker.begin_shutdown()
                self._sticky_failure = True
                return result
            self.write_gate.cancel_shutdown()
            self._state = ShutdownState.RUNNING
        return _shutdown_result(ShutdownState.RUNNING)


def _shutdown_result(state: ShutdownState) -> ShutdownResult:
    return ShutdownResult(state=state, safe_summary=_SUMMARIES[ServiceState(state.value)])
