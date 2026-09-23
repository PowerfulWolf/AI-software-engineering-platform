"""Typed, operation-scoped call observations; never provider payloads or authority."""

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, field_validator

from ai_software_engineer.agents.diagnostics import safe_diagnostic
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.model import (
    CodexConnectionMode,
    DomainModel,
    ProviderRouteKind,
    ReasoningEffort,
)

CallPhase = Literal["stage_reply", "knowledge_intent", "knowledge_assessment"]
RequestId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]


class ModelCallDiagnostic(DomainModel):
    invocation_id: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]
    route_index: int = Field(ge=1, le=16)
    started_at: AwareDatetime
    role: TeamRole | None = None
    phase: CallPhase
    provider: Annotated[str, Field(min_length=1, max_length=200)]
    model: Annotated[str, Field(min_length=1, max_length=200)]
    route_kind: ProviderRouteKind | None = None
    connection_mode: CodexConnectionMode | None = None
    reasoning_effort: ReasoningEffort
    duration_ms: int = Field(ge=0)
    outcome: Literal["SUCCEEDED", "FAILED"]
    http_status: int | None = Field(default=None, ge=100, le=599)
    request_id: RequestId | None = None
    correlation_id: RequestId | None = None
    error_code: AgentErrorCode | None = None
    error_summary: Annotated[str, Field(max_length=500)] | None = None

    @field_validator("provider", "model", mode="before")
    @classmethod
    def clean_text(cls, value: object) -> object:
        return safe_diagnostic(value, limit=200) if isinstance(value, str) else value

    @field_validator("error_summary", mode="before")
    @classmethod
    def clean_error(cls, value: object) -> object:
        return safe_diagnostic(value) if isinstance(value, str) else value


CallSink = Callable[[ModelCallDiagnostic], None]
_sink: ContextVar[CallSink | None] = ContextVar("model_call_sink", default=None)
_phase: ContextVar[CallPhase] = ContextVar("model_call_phase", default="stage_reply")


@contextmanager
def capture_model_calls(sink: CallSink) -> Iterator[None]:
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


@contextmanager
def model_call_phase(phase: CallPhase) -> Iterator[None]:
    token = _phase.set(phase)
    try:
        yield
    finally:
        _phase.reset(token)


def current_call_phase() -> CallPhase:
    return _phase.get()


def record_model_call(call: ModelCallDiagnostic) -> None:
    if sink := _sink.get():
        sink(call)


def safe_request_id(value: str | None, *, secret: str = "") -> str | None:
    """Ignore arbitrary header content, credential echoes and secret-like IDs."""
    if not value or (secret and secret in value):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
        return None
    return value if safe_diagnostic(value) == value else None
