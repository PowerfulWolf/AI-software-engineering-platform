"""Typed Product Agent adapter seam and deterministic offline fake."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, StrictBool, StrictInt, model_validator

from ai_software_engineer.domain import ProductSpec, ProductSpecStatus
from ai_software_engineer.domain.agent import TimeoutSeconds
from ai_software_engineer.domain.identity import ContextId, ProjectId, RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.project_delivery import ProjectRequestId
from ai_software_engineer.product.context import (
    PRODUCT_AGENT_PERMISSIONS,
    ProductAgentPermissions,
    ProductContextManifest,
)

DurationMs = Annotated[StrictInt, Field(ge=0)]


class ProductAgentError(RuntimeError):
    """Base error for Product Agent adapter configuration/invocation."""


class ProductAgentRequestConflict(ProductAgentError):
    """Raised when a run ID is replayed with different input."""


class ProductAgentConfigurationError(ProductAgentError):
    """Raised when a fake scenario is missing or internally inconsistent."""


class ProductAgentRunStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class ProductAgentErrorCode(StrEnum):
    TIMEOUT = "TIMEOUT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class FakeProductBehavior(StrEnum):
    CLARIFY = "clarify"
    READY = "ready"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_ERROR = "provider_error"


class ProductClarification(DomainModel):
    """Structured Product Agent request for missing user decisions."""

    kind: Literal["product_clarification"] = "product_clarification"
    schema_version: Literal["v0.1"] = "v0.1"
    summary: NonEmptyStr
    questions: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_questions(self) -> Self:
        ensure_unique(self.questions, "Product clarification questions")
        return self


class ProductAgentFailure(DomainModel):
    code: ProductAgentErrorCode
    message: NonEmptyStr
    transient: StrictBool


class ProductAgentRequest(DomainModel):
    """Exact Product context and capability envelope sent to an adapter."""

    kind: Literal["product_agent_request"] = "product_agent_request"
    schema_version: Literal["v0.1"] = "v0.1"
    run_id: RunId
    project_id: ProjectId
    request_id: ProjectRequestId
    context: ProductContextManifest
    permissions: ProductAgentPermissions = PRODUCT_AGENT_PERMISSIONS
    output_schema: Literal["schemas/product-spec.schema.json"] = "schemas/product-spec.schema.json"
    timeout_seconds: TimeoutSeconds = 600

    @model_validator(mode="after")
    def validate_context_identity(self) -> Self:
        self.context.validate_integrity()
        if self.project_id != self.context.project_id or self.request_id != self.context.request_id:
            raise ValueError("ProductAgentRequest identity does not match context")
        if self.permissions != self.context.permissions:
            raise ValueError("ProductAgentRequest permissions do not match context policy")
        return self


class ProductAgentResult(DomainModel):
    """Typed terminal Product run output; only clarification or spec can succeed."""

    kind: Literal["product_agent_result"] = "product_agent_result"
    schema_version: Literal["v0.1"] = "v0.1"
    run_id: RunId
    project_id: ProjectId
    request_id: ProjectRequestId
    context_id: ContextId
    status: ProductAgentRunStatus
    clarification: ProductClarification | None = None
    product_spec: ProductSpec | None = None
    error: ProductAgentFailure | None = None
    duration_ms: DurationMs = 0

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        output_count = int(self.clarification is not None) + int(self.product_spec is not None)
        if self.status is ProductAgentRunStatus.SUCCEEDED:
            if output_count != 1 or self.error is not None:
                raise ValueError("successful ProductAgentResult requires exactly one output")
        elif output_count != 0 or self.error is None:
            raise ValueError("failed ProductAgentResult requires only a typed error")
        if self.status is ProductAgentRunStatus.TIMED_OUT and (
            self.error is None or self.error.code is not ProductAgentErrorCode.TIMEOUT
        ):
            raise ValueError("TIMED_OUT ProductAgentResult requires TIMEOUT error")
        if (
            self.status is ProductAgentRunStatus.FAILED
            and self.error is not None
            and self.error.code is ProductAgentErrorCode.TIMEOUT
        ):
            raise ValueError("TIMEOUT error must use TIMED_OUT status")
        return self


class ProductAgentAdapter(Protocol):
    """Provider-neutral Product Agent execution boundary."""

    def run(self, request: ProductAgentRequest) -> ProductAgentResult: ...


class FakeProductScenario(DomainModel):
    """One deterministic offline Product Agent outcome."""

    behavior: FakeProductBehavior
    clarification: ProductClarification | None = None
    product_spec: ProductSpec | None = None
    message: NonEmptyStr = "simulated fake Product Agent outcome"
    duration_ms: DurationMs = 0

    @model_validator(mode="after")
    def validate_output_shape(self) -> Self:
        if self.behavior is FakeProductBehavior.CLARIFY:
            if self.clarification is None or self.product_spec is not None:
                raise ValueError("CLARIFY scenario requires only clarification")
        elif self.behavior is FakeProductBehavior.READY:
            if self.product_spec is None or self.clarification is not None:
                raise ValueError("READY scenario requires only ProductSpec")
        elif self.clarification is not None or self.product_spec is not None:
            raise ValueError("failure Product scenario cannot carry output")
        return self


class FakeProductAgentAdapter:
    """Run Product Agent contract scenarios without model, Git, or filesystem access."""

    def __init__(
        self,
        *,
        scenarios: Mapping[str, FakeProductScenario] | None = None,
        default: FakeProductScenario | None = None,
    ) -> None:
        self._scenarios = dict(scenarios or {})
        self._default = default
        self._requests: dict[str, ProductAgentRequest] = {}
        self._results: dict[str, ProductAgentResult] = {}

    def run(self, request: ProductAgentRequest) -> ProductAgentResult:
        """Return a cached exact replay or execute one configured fake scenario."""
        prior_request = self._requests.get(request.run_id)
        if prior_request is not None:
            if prior_request != request:
                raise ProductAgentRequestConflict(
                    f"run ID already used with a different request: {request.run_id}"
                )
            return self._results[request.run_id]
        scenario = self._scenarios.get(request.run_id, self._default)
        if scenario is None:
            raise ProductAgentConfigurationError(
                f"no fake Product scenario configured for run: {request.run_id}"
            )
        result = self._execute(request, scenario)
        self._requests[request.run_id] = request
        self._results[request.run_id] = result
        return result

    def _execute(
        self,
        request: ProductAgentRequest,
        scenario: FakeProductScenario,
    ) -> ProductAgentResult:
        if scenario.behavior is FakeProductBehavior.TIMEOUT:
            return _failure_result(
                request,
                status=ProductAgentRunStatus.TIMED_OUT,
                code=ProductAgentErrorCode.TIMEOUT,
                message=scenario.message,
                transient=True,
                duration_ms=scenario.duration_ms,
            )
        if scenario.behavior is FakeProductBehavior.INVALID_OUTPUT:
            return _failure_result(
                request,
                status=ProductAgentRunStatus.FAILED,
                code=ProductAgentErrorCode.INVALID_OUTPUT,
                message=scenario.message,
                transient=False,
                duration_ms=scenario.duration_ms,
            )
        if scenario.behavior is FakeProductBehavior.PROVIDER_ERROR:
            return _failure_result(
                request,
                status=ProductAgentRunStatus.FAILED,
                code=ProductAgentErrorCode.PROVIDER_ERROR,
                message=scenario.message,
                transient=True,
                duration_ms=scenario.duration_ms,
            )
        if scenario.behavior is FakeProductBehavior.CLARIFY:
            if scenario.clarification is None:
                raise ProductAgentConfigurationError("CLARIFY scenario has no clarification")
            return ProductAgentResult(
                run_id=request.run_id,
                project_id=request.project_id,
                request_id=request.request_id,
                context_id=request.context.context_id,
                status=ProductAgentRunStatus.SUCCEEDED,
                clarification=scenario.clarification,
                duration_ms=scenario.duration_ms,
            )
        if scenario.product_spec is None:
            raise ProductAgentConfigurationError("READY scenario has no ProductSpec")
        mismatch = _product_spec_mismatch(request, scenario.product_spec)
        if mismatch is not None:
            return _failure_result(
                request,
                status=ProductAgentRunStatus.FAILED,
                code=ProductAgentErrorCode.INVALID_OUTPUT,
                message=mismatch,
                transient=False,
                duration_ms=scenario.duration_ms,
            )
        return ProductAgentResult(
            run_id=request.run_id,
            project_id=request.project_id,
            request_id=request.request_id,
            context_id=request.context.context_id,
            status=ProductAgentRunStatus.SUCCEEDED,
            product_spec=scenario.product_spec,
            duration_ms=scenario.duration_ms,
        )


def _product_spec_mismatch(request: ProductAgentRequest, product_spec: ProductSpec) -> str | None:
    try:
        product_spec.validate_integrity()
    except RuntimeError:
        return "fake ProductSpec integrity does not match content"
    context = request.context
    if (
        product_spec.project_id != request.project_id
        or product_spec.request_id != request.request_id
    ):
        return "fake ProductSpec project/request does not match ProductAgentRequest"
    if product_spec.status is not ProductSpecStatus.READY_FOR_REVIEW:
        return "fake ProductSpec must be READY_FOR_REVIEW"
    if product_spec.version != context.expected_product_spec_version:
        return "fake ProductSpec version does not match Product context"
    if product_spec.supersedes != context.expected_supersedes:
        return "fake ProductSpec supersedes does not match Product context"
    return None


def _failure_result(
    request: ProductAgentRequest,
    *,
    status: ProductAgentRunStatus,
    code: ProductAgentErrorCode,
    message: str,
    transient: bool,
    duration_ms: int,
) -> ProductAgentResult:
    return ProductAgentResult(
        run_id=request.run_id,
        project_id=request.project_id,
        request_id=request.request_id,
        context_id=request.context.context_id,
        status=status,
        error=ProductAgentFailure(code=code, message=message, transient=transient),
        duration_ms=duration_ms,
    )


__all__ = [
    "FakeProductAgentAdapter",
    "FakeProductBehavior",
    "FakeProductScenario",
    "ProductAgentAdapter",
    "ProductAgentConfigurationError",
    "ProductAgentError",
    "ProductAgentErrorCode",
    "ProductAgentFailure",
    "ProductAgentRequest",
    "ProductAgentRequestConflict",
    "ProductAgentResult",
    "ProductAgentRunStatus",
    "ProductClarification",
]
