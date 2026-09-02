"""Provider-neutral Designer adapter and deterministic offline fake."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, StrictBool, StrictInt, model_validator

from ai_software_engineer.design.context import (
    DESIGNER_AGENT_PERMISSIONS,
    DesignContextManifest,
    DesignerAgentPermissions,
)
from ai_software_engineer.design.models import DesignerAgentErrorCode
from ai_software_engineer.domain import TechnicalDesign
from ai_software_engineer.domain.agent import TimeoutSeconds
from ai_software_engineer.domain.identity import ContextId, ProjectId, RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import ProjectRequestId

DurationMs = Annotated[StrictInt, Field(ge=0)]


class DesignerAgentError(RuntimeError):
    """Base error for Designer adapter invocation/configuration."""


class DesignerAgentRequestConflict(DesignerAgentError):
    """Raised when a run ID is replayed with different exact input."""


class DesignerAgentConfigurationError(DesignerAgentError):
    """Raised when a fake scenario is absent or inconsistent."""


class DesignerAgentRunStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class FakeDesignerBehavior(StrEnum):
    READY = "ready"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_ERROR = "provider_error"


class DesignerAgentFailure(DomainModel):
    code: DesignerAgentErrorCode
    message: NonEmptyStr
    transient: StrictBool


class DesignerAgentRequest(DomainModel):
    """Exact context and machine policy sent to a Designer provider."""

    kind: Literal["designer_agent_request"] = "designer_agent_request"
    schema_version: Literal["v0.1"] = "v0.1"
    run_id: RunId
    project_id: ProjectId
    request_id: ProjectRequestId
    context: DesignContextManifest
    permissions: DesignerAgentPermissions = DESIGNER_AGENT_PERMISSIONS
    output_schema: Literal["schemas/technical-design.schema.json"] = (
        "schemas/technical-design.schema.json"
    )
    timeout_seconds: TimeoutSeconds = 600

    @model_validator(mode="after")
    def validate_context_identity(self) -> Self:
        self.context.validate_integrity()
        if self.project_id != self.context.project_id or self.request_id != self.context.request_id:
            raise ValueError("DesignerAgentRequest identity does not match context")
        if self.permissions != self.context.permissions:
            raise ValueError("DesignerAgentRequest permissions do not match context")
        return self


class DesignerAgentResult(DomainModel):
    """Typed terminal output; only success may carry TechnicalDesign."""

    kind: Literal["designer_agent_result"] = "designer_agent_result"
    schema_version: Literal["v0.1"] = "v0.1"
    run_id: RunId
    project_id: ProjectId
    request_id: ProjectRequestId
    context_id: ContextId
    status: DesignerAgentRunStatus
    technical_design: TechnicalDesign | None = None
    error: DesignerAgentFailure | None = None
    duration_ms: DurationMs = 0

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        if self.status is DesignerAgentRunStatus.SUCCEEDED:
            if self.technical_design is None or self.error is not None:
                raise ValueError("successful DesignerAgentResult requires only TechnicalDesign")
        elif self.technical_design is not None or self.error is None:
            raise ValueError("failed DesignerAgentResult requires only typed error")
        if self.status is DesignerAgentRunStatus.TIMED_OUT and (
            self.error is None or self.error.code is not DesignerAgentErrorCode.TIMEOUT
        ):
            raise ValueError("TIMED_OUT DesignerAgentResult requires TIMEOUT error")
        if (
            self.status is DesignerAgentRunStatus.FAILED
            and self.error is not None
            and self.error.code is DesignerAgentErrorCode.TIMEOUT
        ):
            raise ValueError("TIMEOUT error must use TIMED_OUT status")
        return self


class DesignerAgentAdapter(Protocol):
    """Provider-neutral Designer execution boundary."""

    def run(self, request: DesignerAgentRequest) -> DesignerAgentResult: ...


class FakeDesignerScenario(DomainModel):
    """One deterministic Designer outcome for offline contract tests."""

    behavior: FakeDesignerBehavior
    technical_design: TechnicalDesign | None = None
    message: NonEmptyStr = "simulated fake Designer outcome"
    duration_ms: DurationMs = 0

    @model_validator(mode="after")
    def validate_output(self) -> Self:
        if (self.behavior is FakeDesignerBehavior.READY) != (self.technical_design is not None):
            raise ValueError("READY fake behavior requires exactly one TechnicalDesign")
        return self


class FakeDesignerAgentAdapter:
    """Execute Designer scenarios without model, Git, filesystem, or shell access."""

    def __init__(
        self,
        *,
        scenarios: Mapping[str, FakeDesignerScenario] | None = None,
        default: FakeDesignerScenario | None = None,
    ) -> None:
        self._scenarios = dict(scenarios or {})
        self._default = default
        self._requests: dict[str, DesignerAgentRequest] = {}
        self._results: dict[str, DesignerAgentResult] = {}

    def run(self, request: DesignerAgentRequest) -> DesignerAgentResult:
        prior = self._requests.get(request.run_id)
        if prior is not None:
            if prior != request:
                raise DesignerAgentRequestConflict(
                    f"run ID already used with different Designer input: {request.run_id}"
                )
            return self._results[request.run_id]
        scenario = self._scenarios.get(request.run_id, self._default)
        if scenario is None:
            raise DesignerAgentConfigurationError(
                f"no fake Designer scenario configured for run: {request.run_id}"
            )
        result = self._execute(request, scenario)
        self._requests[request.run_id] = request
        self._results[request.run_id] = result
        return result

    def _execute(
        self, request: DesignerAgentRequest, scenario: FakeDesignerScenario
    ) -> DesignerAgentResult:
        if scenario.behavior is FakeDesignerBehavior.READY:
            return DesignerAgentResult(
                run_id=request.run_id,
                project_id=request.project_id,
                request_id=request.request_id,
                context_id=request.context.context_id,
                status=DesignerAgentRunStatus.SUCCEEDED,
                technical_design=scenario.technical_design,
                duration_ms=scenario.duration_ms,
            )
        if scenario.behavior is FakeDesignerBehavior.TIMEOUT:
            return _failure(
                request,
                status=DesignerAgentRunStatus.TIMED_OUT,
                code=DesignerAgentErrorCode.TIMEOUT,
                message=scenario.message,
                transient=True,
                duration_ms=scenario.duration_ms,
            )
        return _failure(
            request,
            status=DesignerAgentRunStatus.FAILED,
            code=(
                DesignerAgentErrorCode.INVALID_OUTPUT
                if scenario.behavior is FakeDesignerBehavior.INVALID_OUTPUT
                else DesignerAgentErrorCode.PROVIDER_ERROR
            ),
            message=scenario.message,
            transient=scenario.behavior is FakeDesignerBehavior.PROVIDER_ERROR,
            duration_ms=scenario.duration_ms,
        )


def _failure(
    request: DesignerAgentRequest,
    *,
    status: DesignerAgentRunStatus,
    code: DesignerAgentErrorCode,
    message: str,
    transient: bool,
    duration_ms: int,
) -> DesignerAgentResult:
    return DesignerAgentResult(
        run_id=request.run_id,
        project_id=request.project_id,
        request_id=request.request_id,
        context_id=request.context.context_id,
        status=status,
        error=DesignerAgentFailure(code=code, message=message, transient=transient),
        duration_ms=duration_ms,
    )


__all__ = [
    "DesignerAgentAdapter",
    "DesignerAgentConfigurationError",
    "DesignerAgentError",
    "DesignerAgentErrorCode",
    "DesignerAgentFailure",
    "DesignerAgentRequest",
    "DesignerAgentRequestConflict",
    "DesignerAgentResult",
    "DesignerAgentRunStatus",
    "FakeDesignerAgentAdapter",
    "FakeDesignerBehavior",
    "FakeDesignerScenario",
]
