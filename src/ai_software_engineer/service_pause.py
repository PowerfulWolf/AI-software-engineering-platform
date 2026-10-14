"""Host-owned, operation-scoped pause; never an Agent tool or a write fence."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import Literal, Self
from uuid import uuid4

from pydantic import AwareDatetime, model_validator

from ai_software_engineer.agents.execution import (
    NativeProcessStop,
    PausedInvocationProof,
    SynchronousToolLoopStop,
)
from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.knowledge.models import digest


class ServicePauseRequested(RuntimeError):
    """Current durable boundary may finish; no new execution is authorized."""

    safe_summary = "服务重启已暂停执行。原阶段、审批和工作现场保留, 重启后可核验并继续。"

    def __init__(self, *, evidence_ids: tuple[str, ...] = ()) -> None:
        super().__init__(self.safe_summary)
        self.evidence_ids = evidence_ids


class PausedProcessReceipt(DomainModel):
    kind: Literal["service_pause_stop"] = "service_pause_stop"
    schema_version: Literal["v1"] = "v1"
    operation_id: NonEmptyStr
    request_id: NonEmptyStr
    instance_id: NonEmptyStr | None = None
    requested_at: AwareDatetime
    process_stop: NativeProcessStop
    receipt_sha256: StageSha256

    @model_validator(mode="after")
    def require_pause_stop(self) -> Self:
        self.process_stop.validate_integrity()
        if (
            self.process_stop.kind != "service_pause"
            or self.process_stop.session_proof is None
            or self.process_stop.stopped_at < self.requested_at
        ):
            raise ValueError("service pause needs the exact actual owned-session stop")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.receipt_sha256 != digest(self.model_dump(mode="json", exclude={"receipt_sha256"})):
            raise ValueError("service pause stop digest mismatch")


@dataclass(frozen=True, slots=True)
class PauseRequest:
    request_id: str
    instance_id: str | None
    requested_at: datetime
    deadline: float


@dataclass(frozen=True, slots=True)
class ServicePauseScope:
    control: ServicePauseControl
    operation_id: str

    @contextmanager
    def activate(self) -> Iterator[None]:
        with self.control.operation_scope(self.operation_id):
            yield


_request: ContextVar[AgentRequest | None] = ContextVar("service_pause_request", default=None)


_scope: ContextVar[ServicePauseScope | None] = ContextVar("service_pause_scope", default=None)


class ServicePauseControl:
    """Only actual runners stop themselves, after a fixed completion window."""

    def __init__(
        self,
        *,
        grace_seconds: float = 30,
        persist_stop: Callable[[PausedProcessReceipt], None] | None = None,
    ) -> None:
        if not math.isfinite(grace_seconds) or not 0 <= grace_seconds <= 300:
            raise ValueError("service pause grace must be finite and between zero and 300 seconds")
        self._grace = grace_seconds
        self._persist_stop = persist_stop
        self._lock = Lock()
        self._request_id: str | None = None
        self._instance_id: str | None = None
        self._requested_at: datetime | None = None
        self._deadline: float | None = None
        self._stops: dict[str, PausedInvocationProof] = {}

    @property
    def request_id(self) -> str | None:
        with self._lock:
            return self._request_id

    def request(self, *, request_id: str | None = None, instance_id: str | None = None) -> None:
        with self._lock:
            if self._deadline is not None:
                return
            self._request_id = request_id or "service_pause_" + uuid4().hex
            self._instance_id = instance_id
            self._requested_at = datetime.now(UTC)
            self._deadline = monotonic() + self._grace

    def cancel(self) -> None:
        with self._lock:
            self._deadline = None
            self._request_id = None
            self._instance_id = None
            self._requested_at = None

    def requested(self) -> bool:
        with self._lock:
            return self._deadline is not None

    def due(self) -> bool:
        return self.due_request() is not None

    def due_request(self) -> PauseRequest | None:
        """Freeze the stopping epoch; a later RESUME cannot erase its evidence."""
        with self._lock:
            if self._deadline is None or monotonic() < self._deadline:
                return None
            assert self._request_id is not None and self._requested_at is not None
            return PauseRequest(
                self._request_id, self._instance_id, self._requested_at, self._deadline
            )

    @contextmanager
    def admission(self) -> Iterator[None]:
        """Linearize a short spawn/claim with shutdown, never a whole invocation."""
        with self._lock:
            if self._deadline is not None:
                raise ServicePauseRequested()
            yield

    @contextmanager
    def operation_scope(self, operation_id: str) -> Iterator[None]:
        if not operation_id or len(operation_id) > 256:
            raise ValueError("pause scope needs a bounded exact Operation identity")
        token = _scope.set(ServicePauseScope(self, operation_id))
        try:
            yield
        finally:
            _scope.reset(token)

    def record_stop(
        self, scope: ServicePauseScope, stop: NativeProcessStop, request: PauseRequest
    ) -> None:
        if scope.control is not self:
            raise ValueError("service pause stop has no matching requested pause")
        receipt = PausedProcessReceipt(
            operation_id=scope.operation_id,
            request_id=request.request_id,
            instance_id=request.instance_id,
            requested_at=request.requested_at,
            process_stop=stop,
            receipt_sha256="0" * 64,
        )
        receipt = receipt.model_copy(
            update={
                "receipt_sha256": digest(
                    receipt.model_dump(mode="json", exclude={"receipt_sha256"})
                )
            }
        )
        receipt.validate_integrity()
        if self._persist_stop is not None:
            self._persist_stop(receipt)
        self.record_invocation_stop(stop)

    def record_invocation_stop(
        self, stop: NativeProcessStop | SynchronousToolLoopStop | None
    ) -> None:
        request = _request.get()
        if request is None:
            return
        proof = PausedInvocationProof.create(
            request=request, process_stop=stop, admission_closed=stop is None
        )
        with self._lock:
            self._stops[digest(request.to_wire())] = proof

    def invocation_stop(self, request: AgentRequest) -> PausedInvocationProof | None:
        with self._lock:
            return self._stops.get(digest(request.to_wire()))


def current_service_pause() -> ServicePauseScope | None:
    return _scope.get()


def service_pause_requested() -> bool:
    scope = current_service_pause()
    return scope is not None and scope.control.requested()


def check_service_pause() -> None:
    if service_pause_requested():
        raise ServicePauseRequested()


@contextmanager
def pause_admission() -> Iterator[None]:
    scope = current_service_pause()
    if scope is None:
        yield
    else:
        with scope.control.admission():
            yield


@contextmanager
def pause_invocation(request: AgentRequest) -> Iterator[None]:
    token = _request.set(request)
    try:
        yield
    finally:
        _request.reset(token)


def record_invocation_pause(stop: NativeProcessStop | SynchronousToolLoopStop | None) -> None:
    scope = current_service_pause()
    if scope is not None:
        scope.control.record_invocation_stop(stop)
