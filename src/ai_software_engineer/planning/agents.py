"""Provider-neutral Planner Agent adapter contract and deterministic fake."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, StrictBool, StrictInt, model_validator

from ai_software_engineer.domain.agent import TimeoutSeconds
from ai_software_engineer.domain.identity import ContextId, ProjectId, RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import (
    ExecutionPlan,
    ProjectRequestId,
    StageContractError,
    validate_execution_plan,
)
from ai_software_engineer.planning.context import (
    PLANNER_AGENT_PERMISSIONS,
    PlannerAgentPermissions,
    PlannerContextManifest,
)
from ai_software_engineer.planning.models import PlannerAgentErrorCode

DurationMs = Annotated[StrictInt, Field(ge=0)]


class PlannerAgentError(RuntimeError):
    """Base error for Planner Agent adapter invocation."""


class PlannerAgentRequestConflict(PlannerAgentError):
    """Raised when one run ID is replayed with different input."""


class PlannerAgentConfigurationError(PlannerAgentError):
    """Raised when a fake Planner scenario is missing or invalid."""


class PlannerAgentRunStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class FakePlannerBehavior(StrEnum):
    READY = "ready"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_ERROR = "provider_error"


class PlannerAgentFailure(DomainModel):
    code: PlannerAgentErrorCode
    message: NonEmptyStr
    transient: StrictBool


class PlannerAgentRequest(DomainModel):
    """Exact Planner context and least-authority envelope sent to an adapter."""

    kind: Literal["planner_agent_request"] = "planner_agent_request"
    schema_version: Literal["v0.1"] = "v0.1"
    run_id: RunId
    project_id: ProjectId
    request_id: ProjectRequestId
    context: PlannerContextManifest
    permissions: PlannerAgentPermissions = PLANNER_AGENT_PERMISSIONS
    output_schema: Literal["schemas/execution-plan.schema.json"] = (
        "schemas/execution-plan.schema.json"
    )
    timeout_seconds: TimeoutSeconds = 600

    @model_validator(mode="after")
    def validate_context_identity(self) -> Self:
        self.context.validate_integrity()
        if self.project_id != self.context.project_id or self.request_id != self.context.request_id:
            raise ValueError("PlannerAgentRequest identity does not match context")
        if self.permissions != self.context.permissions:
            raise ValueError("PlannerAgentRequest permissions do not match context policy")
        return self


class PlannerAgentResult(DomainModel):
    """Typed terminal Planner output; failure never carries an ExecutionPlan."""

    kind: Literal["planner_agent_result"] = "planner_agent_result"
    schema_version: Literal["v0.1"] = "v0.1"
    run_id: RunId
    project_id: ProjectId
    request_id: ProjectRequestId
    context_id: ContextId
    status: PlannerAgentRunStatus
    execution_plan: ExecutionPlan | None = None
    error: PlannerAgentFailure | None = None
    duration_ms: DurationMs = 0

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        if self.status is PlannerAgentRunStatus.SUCCEEDED:
            if self.execution_plan is None or self.error is not None:
                raise ValueError("successful PlannerAgentResult requires only ExecutionPlan")
        elif self.execution_plan is not None or self.error is None:
            raise ValueError("failed PlannerAgentResult requires only a typed error")
        if self.status is PlannerAgentRunStatus.TIMED_OUT and (
            self.error is None or self.error.code is not PlannerAgentErrorCode.TIMEOUT
        ):
            raise ValueError("TIMED_OUT PlannerAgentResult requires TIMEOUT error")
        if (
            self.status is PlannerAgentRunStatus.FAILED
            and self.error is not None
            and self.error.code is PlannerAgentErrorCode.TIMEOUT
        ):
            raise ValueError("TIMEOUT error must use TIMED_OUT status")
        return self


class PlannerAgentAdapter(Protocol):
    """Provider-neutral Planner execution boundary."""

    def run(self, request: PlannerAgentRequest) -> PlannerAgentResult: ...


class FakePlannerScenario(DomainModel):
    """One deterministic offline Planner outcome."""

    behavior: FakePlannerBehavior
    execution_plan: ExecutionPlan | None = None
    message: NonEmptyStr = "simulated fake Planner Agent outcome"
    duration_ms: DurationMs = 0

    @model_validator(mode="after")
    def validate_output_shape(self) -> Self:
        if self.behavior is FakePlannerBehavior.READY:
            if self.execution_plan is None:
                raise ValueError("READY Planner scenario requires ExecutionPlan")
        elif self.execution_plan is not None:
            raise ValueError("failure Planner scenario cannot carry ExecutionPlan")
        return self


class FakePlannerAgentAdapter:
    """Execute Planner contract scenarios without model, stores, Git, or shell."""

    def __init__(
        self,
        *,
        scenarios: Mapping[str, FakePlannerScenario] | None = None,
        default: FakePlannerScenario | None = None,
    ) -> None:
        self._scenarios = dict(scenarios or {})
        self._default = default
        self._requests: dict[str, PlannerAgentRequest] = {}
        self._results: dict[str, PlannerAgentResult] = {}

    def run(self, request: PlannerAgentRequest) -> PlannerAgentResult:
        prior = self._requests.get(request.run_id)
        if prior is not None:
            if prior != request:
                raise PlannerAgentRequestConflict(
                    f"run ID already used with a different request: {request.run_id}"
                )
            return self._results[request.run_id]
        scenario = self._scenarios.get(request.run_id, self._default)
        if scenario is None:
            raise PlannerAgentConfigurationError(
                f"no fake Planner scenario configured for run: {request.run_id}"
            )
        result = self._execute(request, scenario)
        self._requests[request.run_id] = request
        self._results[request.run_id] = result
        return result

    @staticmethod
    def _execute(
        request: PlannerAgentRequest,
        scenario: FakePlannerScenario,
    ) -> PlannerAgentResult:
        if scenario.behavior is FakePlannerBehavior.TIMEOUT:
            return _failure_result(
                request,
                status=PlannerAgentRunStatus.TIMED_OUT,
                code=PlannerAgentErrorCode.TIMEOUT,
                message=scenario.message,
                transient=True,
                duration_ms=scenario.duration_ms,
            )
        if scenario.behavior is FakePlannerBehavior.INVALID_OUTPUT:
            return _failure_result(
                request,
                status=PlannerAgentRunStatus.FAILED,
                code=PlannerAgentErrorCode.INVALID_OUTPUT,
                message=scenario.message,
                transient=False,
                duration_ms=scenario.duration_ms,
            )
        if scenario.behavior is FakePlannerBehavior.PROVIDER_ERROR:
            return _failure_result(
                request,
                status=PlannerAgentRunStatus.FAILED,
                code=PlannerAgentErrorCode.PROVIDER_ERROR,
                message=scenario.message,
                transient=True,
                duration_ms=scenario.duration_ms,
            )
        assert scenario.execution_plan is not None
        try:
            _validate_plan_output(request, scenario.execution_plan)
        except (ValueError, StageContractError) as error:
            return _failure_result(
                request,
                status=PlannerAgentRunStatus.FAILED,
                code=PlannerAgentErrorCode.INVALID_OUTPUT,
                message=str(error),
                transient=False,
                duration_ms=scenario.duration_ms,
            )
        return PlannerAgentResult(
            run_id=request.run_id,
            project_id=request.project_id,
            request_id=request.request_id,
            context_id=request.context.context_id,
            status=PlannerAgentRunStatus.SUCCEEDED,
            execution_plan=scenario.execution_plan,
            duration_ms=scenario.duration_ms,
        )


def validate_planner_result(
    request: PlannerAgentRequest,
    result: PlannerAgentResult,
) -> ExecutionPlan:
    """Guard adapter identity and return the exact successful abstract plan."""
    if (
        result.run_id != request.run_id
        or result.project_id != request.project_id
        or result.request_id != request.request_id
        or result.context_id != request.context.context_id
    ):
        raise ValueError("PlannerAgentResult identity does not match request")
    if result.status is not PlannerAgentRunStatus.SUCCEEDED or result.execution_plan is None:
        message = "Planner Agent did not produce an ExecutionPlan"
        if result.error is not None:
            message = f"{message}: {result.error.code.value}"
        raise PlannerAgentError(message)
    _validate_plan_output(request, result.execution_plan)
    return result.execution_plan


def _validate_plan_output(request: PlannerAgentRequest, plan: ExecutionPlan) -> None:
    context = request.context
    validate_execution_plan(context.product_spec, context.technical_design, plan)
    if (
        plan.project_id != request.project_id
        or plan.request_id != request.request_id
        or plan.version != context.expected_execution_plan_version
    ):
        raise ValueError("ExecutionPlan identity or version does not match Planner context")


def _failure_result(
    request: PlannerAgentRequest,
    *,
    status: PlannerAgentRunStatus,
    code: PlannerAgentErrorCode,
    message: str,
    transient: bool,
    duration_ms: int,
) -> PlannerAgentResult:
    return PlannerAgentResult(
        run_id=request.run_id,
        project_id=request.project_id,
        request_id=request.request_id,
        context_id=request.context.context_id,
        status=status,
        error=PlannerAgentFailure(code=code, message=message, transient=transient),
        duration_ms=duration_ms,
    )


__all__ = [
    "FakePlannerAgentAdapter",
    "FakePlannerBehavior",
    "FakePlannerScenario",
    "PlannerAgentAdapter",
    "PlannerAgentConfigurationError",
    "PlannerAgentError",
    "PlannerAgentErrorCode",
    "PlannerAgentFailure",
    "PlannerAgentRequest",
    "PlannerAgentRequestConflict",
    "PlannerAgentResult",
    "PlannerAgentRunStatus",
    "validate_planner_result",
]
