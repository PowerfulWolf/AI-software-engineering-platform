"""Trusted structured-call facts, without execution authority or provider payloads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Annotated, Literal, Protocol, Self
from uuid import uuid4

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from ai_software_engineer.agents.diagnostics import safe_diagnostic
from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.model_diagnostics import CallPhase
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.model import (
    CodexConnectionMode,
    DomainModel,
    ProviderRouteKind,
    ReasoningEffort,
)
from ai_software_engineer.domain.project_delivery import StageSha256

ObservationId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]
RouteText = Annotated[str, StringConstraints(min_length=1, max_length=200)]


def observation_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def structured_request_digest(
    *,
    instructions: str,
    input_payload: Mapping[str, object],
    output_schema: Mapping[str, object],
    timeout_seconds: int,
    image_sha256s: tuple[str, ...] = (),
) -> str:
    """Bind the exact structured request; image digests come from verified source bytes."""
    return observation_digest(
        {
            "instructions": instructions,
            "input_payload": input_payload,
            "output_schema": output_schema,
            "timeout_seconds": timeout_seconds,
            "input_images": image_sha256s,
        }
    )


class StructuredObservationRejected(RuntimeError):
    """A trusted observation could not be published; never a provider retry signal."""


class StructuredCallIdentity(DomainModel):
    invocation_id: ObservationId
    route_index: int = Field(ge=1, le=16)
    provider: RouteText
    model: RouteText
    reasoning_effort: ReasoningEffort
    route_kind: ProviderRouteKind | None = None
    connection_mode: CodexConnectionMode | None = None
    role: TeamRole | None = None
    phase: CallPhase
    request_sha256: StageSha256

    @field_validator("provider", "model")
    @classmethod
    def safe_route(cls, value: str) -> str:
        if safe_diagnostic(value, limit=200) != value:
            raise ValueError("structured observation route contains unsafe text")
        return value


class StructuredExecutionAdmission(DomainModel):
    kind: Literal["structured_execution_admission"] = "structured_execution_admission"
    schema_version: Literal["v0.1"] = "v0.1"
    observation_id: ObservationId
    call: StructuredCallIdentity
    execution_kind: Literal["native", "http"]
    transport_request_sha256: StageSha256
    timeout_seconds: float = Field(gt=0)
    admitted_at: AwareDatetime
    admission_sha256: StageSha256

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "admission_sha256": "0" * 64})
        return value.model_copy(update={"admission_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return observation_digest(self.model_dump(mode="json", exclude={"admission_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.admission_sha256 != self.recompute_sha256():
            raise ValueError("structured admission digest mismatch")


class StructuredNativeStopReceipt(DomainModel):
    kind: Literal["structured_native_stop"] = "structured_native_stop"
    schema_version: Literal["v0.1"] = "v0.1"
    admission: StructuredExecutionAdmission
    process_stop: NativeProcessStop
    stdout_sha256: StageSha256
    stderr_sha256: StageSha256
    receipt_sha256: StageSha256

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        self.admission.validate_integrity()
        self.process_stop.validate_integrity()
        if (
            self.admission.execution_kind != "native"
            or self.process_stop.stopped_at < self.admission.admitted_at
        ):
            raise ValueError("native stop does not bind the structured admission")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "receipt_sha256": "0" * 64})
        return value.model_copy(update={"receipt_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return observation_digest(self.model_dump(mode="json", exclude={"receipt_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.receipt_sha256 != self.recompute_sha256():
            raise ValueError("structured native receipt digest mismatch")


class StructuredNativeNotStartedReceipt(DomainModel):
    """The owned runner failed before creating a process; this is not a stop."""

    kind: Literal["structured_native_not_started"] = "structured_native_not_started"
    schema_version: Literal["v0.1"] = "v0.1"
    admission: StructuredExecutionAdmission
    failure_kind: Literal["input_preparation_failed", "process_spawn_failed"]
    failed_at: AwareDatetime
    receipt_sha256: StageSha256

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        self.admission.validate_integrity()
        if self.admission.execution_kind != "native" or self.failed_at < self.admission.admitted_at:
            raise ValueError("native not-started fact does not bind the structured admission")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "receipt_sha256": "0" * 64})
        return value.model_copy(update={"receipt_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return observation_digest(self.model_dump(mode="json", exclude={"receipt_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.receipt_sha256 != self.recompute_sha256():
            raise ValueError("structured native not-started receipt digest mismatch")


class StructuredHttpRoundTripReceipt(DomainModel):
    """The local synchronous transport returned; remote work may still be running."""

    kind: Literal["structured_http_round_trip"] = "structured_http_round_trip"
    schema_version: Literal["v0.1"] = "v0.1"
    admission: StructuredExecutionAdmission
    outcome: Literal["returned", "transport_error"]
    completed_at: AwareDatetime
    http_status: int | None = Field(default=None, ge=100, le=599)
    response_body_sha256: StageSha256 | None = None
    error_kind: Literal["timeout", "os_error"] | None = None
    receipt_sha256: StageSha256

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        self.admission.validate_integrity()
        if (
            self.admission.execution_kind != "http"
            or self.completed_at < self.admission.admitted_at
            or (
                self.outcome == "returned"
                and (
                    self.http_status is None
                    or self.response_body_sha256 is None
                    or self.error_kind is not None
                )
            )
            or (
                self.outcome == "transport_error"
                and (
                    self.error_kind is None
                    or self.http_status is not None
                    or self.response_body_sha256 is not None
                )
            )
        ):
            raise ValueError("HTTP observation does not bind the structured admission")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "receipt_sha256": "0" * 64})
        return value.model_copy(update={"receipt_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return observation_digest(
            self.model_dump(mode="json", exclude_none=True, exclude={"receipt_sha256"})
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.receipt_sha256 != self.recompute_sha256():
            raise ValueError("structured HTTP receipt digest mismatch")


StructuredObservationRecord = Annotated[
    StructuredExecutionAdmission
    | StructuredNativeStopReceipt
    | StructuredNativeNotStartedReceipt
    | StructuredHttpRoundTripReceipt,
    Field(discriminator="kind"),
]


class StructuredExecutionObserver(Protocol):
    def admit(self, admission: StructuredExecutionAdmission) -> None: ...

    def native_stopped(self, receipt: StructuredNativeStopReceipt) -> None: ...

    def native_not_started(self, receipt: StructuredNativeNotStartedReceipt) -> None: ...

    def http_completed(self, receipt: StructuredHttpRoundTripReceipt) -> None: ...


_observer: ContextVar[StructuredExecutionObserver | None] = ContextVar(
    "structured_execution_observer", default=None
)
_identity: ContextVar[StructuredCallIdentity | None] = ContextVar(
    "structured_call_identity", default=None
)


@contextmanager
def bind_structured_execution_observer(observer: StructuredExecutionObserver) -> Iterator[None]:
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


@contextmanager
def structured_call_identity(identity: StructuredCallIdentity) -> Iterator[None]:
    token = _identity.set(identity)
    try:
        yield
    finally:
        _identity.reset(token)


def current_structured_execution_observer() -> StructuredExecutionObserver | None:
    return _observer.get()


def admit_structured_execution(
    *,
    execution_kind: Literal["native", "http"],
    transport_request_sha256: str,
    timeout_seconds: float,
) -> StructuredExecutionAdmission | None:
    observer = _observer.get()
    if observer is None:
        return None
    identity = _identity.get()
    if identity is None:
        raise StructuredObservationRejected("结构化执行缺少可信调用身份; 未启动模型")
    try:
        admission = StructuredExecutionAdmission.create(
            observation_id=uuid4().hex,
            call=identity,
            execution_kind=execution_kind,
            transport_request_sha256=transport_request_sha256,
            timeout_seconds=timeout_seconds,
            admitted_at=datetime.now(UTC),
        )
        observer.admit(admission)
        return admission
    except Exception as error:
        raise StructuredObservationRejected("结构化执行准入记录保存失败; 未启动模型") from error


def record_structured_native_stop(receipt: StructuredNativeStopReceipt) -> None:
    observer = _observer.get()
    if observer is None:
        raise StructuredObservationRejected("结构化执行停止记录缺少可信观察者")
    try:
        receipt.validate_integrity()
        observer.native_stopped(receipt)
    except Exception as error:
        raise StructuredObservationRejected(
            "结构化执行实际停止记录保存失败; 暂停后续执行"
        ) from error


def record_structured_native_not_started(receipt: StructuredNativeNotStartedReceipt) -> None:
    observer = _observer.get()
    if observer is None:
        raise StructuredObservationRejected("结构化执行未启动记录缺少可信观察者")
    try:
        receipt.validate_integrity()
        observer.native_not_started(receipt)
    except Exception as error:
        raise StructuredObservationRejected("结构化执行未启动记录保存失败; 暂停后续执行") from error


def record_structured_http_completion(receipt: StructuredHttpRoundTripReceipt) -> None:
    observer = _observer.get()
    if observer is None:
        raise StructuredObservationRejected("结构化请求回执缺少可信观察者")
    try:
        receipt.validate_integrity()
        observer.http_completed(receipt)
    except Exception as error:
        raise StructuredObservationRejected("结构化请求回执保存失败; 暂停后续执行") from error
