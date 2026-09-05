"""Production Product, Designer, and Planner adapters over structured model output."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal, Self, cast

from pydantic import Field, StringConstraints, model_validator

from ai_software_engineer.agents.structured import (
    StructuredModelClient,
    StructuredModelError,
)
from ai_software_engineer.design import (
    DesignerAgentAdapter,
    DesignerAgentFailure,
    DesignerAgentRequest,
    DesignerAgentResult,
    DesignerAgentRunStatus,
)
from ai_software_engineer.design.models import DesignerAgentErrorCode
from ai_software_engineer.domain import (
    AcceptanceCriterion,
    AcceptanceDesignMapping,
    AgentRole,
    BrainTier,
    DesignComponent,
    DesignRisk,
    DesignStep,
    ExecutionPlan,
    PlanPhaseDemand,
    ProductRequirement,
    ProductSpec,
    ProductSpecStatus,
    RequirementDesignMapping,
    RequirementPriority,
    RiskTier,
    TechnicalDesign,
)
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.planning import (
    PlannerAgentAdapter,
    PlannerAgentFailure,
    PlannerAgentRequest,
    PlannerAgentResult,
    PlannerAgentRunStatus,
)
from ai_software_engineer.planning.models import PlannerAgentErrorCode
from ai_software_engineer.product import (
    ProductAgentAdapter,
    ProductAgentErrorCode,
    ProductAgentFailure,
    ProductAgentRequest,
    ProductAgentResult,
    ProductAgentRunStatus,
    ProductClarification,
)

SafeIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$"),
]
DeliveryCapability = Literal[
    "implementation",
    "testing",
    "review",
    "security",
    "contract-validation",
    "python",
    "java",
    "cpp",
    "go",
    "typescript",
]


class AcceptanceDraft(DomainModel):
    description: NonEmptyStr
    verification: NonEmptyStr
    test_ids: tuple[NonEmptyStr, ...] = ()


class RequirementDraft(DomainModel):
    statement: NonEmptyStr
    priority: RequirementPriority = RequirementPriority.MUST
    rationale: NonEmptyStr
    acceptance: Annotated[tuple[AcceptanceDraft, ...], Field(min_length=1)]


class ProductDraft(DomainModel):
    action: Literal["clarify", "ready"]
    summary: NonEmptyStr
    questions: tuple[NonEmptyStr, ...] = ()
    goals: tuple[NonEmptyStr, ...] = ()
    non_goals: tuple[NonEmptyStr, ...] = ()
    assumptions: tuple[NonEmptyStr, ...] = ()
    requirements: tuple[RequirementDraft, ...] = ()

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if self.action == "clarify":
            if not self.questions or self.goals or self.requirements:
                raise ValueError("clarify output requires only summary and questions")
        elif self.questions or not self.goals or not self.requirements:
            raise ValueError("ready output requires goals and requirements without questions")
        return self


class ComponentDraft(DomainModel):
    key: SafeIdentifier
    name: NonEmptyStr
    responsibility: NonEmptyStr
    affected_paths: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class RequirementMappingDraft(DomainModel):
    requirement_id: NonEmptyStr
    component_keys: Annotated[tuple[SafeIdentifier, ...], Field(min_length=1)]
    approach: NonEmptyStr


class AcceptanceMappingDraft(DomainModel):
    acceptance_criterion_id: NonEmptyStr
    verification_strategy: NonEmptyStr
    test_levels: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class DesignStepDraft(DomainModel):
    key: SafeIdentifier
    description: NonEmptyStr
    component_keys: Annotated[tuple[SafeIdentifier, ...], Field(min_length=1)]
    verification: NonEmptyStr


class DesignRiskDraft(DomainModel):
    key: SafeIdentifier
    description: NonEmptyStr
    tier: RiskTier
    mitigation: NonEmptyStr


class TechnicalDesignDraft(DomainModel):
    summary: NonEmptyStr
    components: Annotated[tuple[ComponentDraft, ...], Field(min_length=1)]
    requirement_mappings: Annotated[tuple[RequirementMappingDraft, ...], Field(min_length=1)]
    acceptance_mappings: Annotated[tuple[AcceptanceMappingDraft, ...], Field(min_length=1)]
    implementation_steps: Annotated[tuple[DesignStepDraft, ...], Field(min_length=1)]
    risks: tuple[DesignRiskDraft, ...] = ()


class PhaseDraft(DomainModel):
    role: Literal["coder", "qa", "reviewer"]
    objective: NonEmptyStr
    required_capabilities: Annotated[tuple[DeliveryCapability, ...], Field(min_length=1)]
    risk: RiskTier
    minimum_brain_tier: BrainTier
    checkpoints: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class ExecutionPlanDraft(DomainModel):
    phases: Annotated[tuple[PhaseDraft, ...], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def validate_serial_roles(self) -> Self:
        if tuple(phase.role for phase in self.phases) != ("coder", "qa", "reviewer"):
            raise ValueError("plan phases must be coder, qa, reviewer")
        return self


class StructuredProductAgentAdapter(ProductAgentAdapter):
    def __init__(self, client: StructuredModelClient) -> None:
        self._client = client

    def run(self, request: ProductAgentRequest) -> ProductAgentResult:
        try:
            completion = self._client.complete(
                instructions=(
                    "Act as Product Agent. Decide whether material user decisions are missing. "
                    "If so return clarify; otherwise produce measurable requirements and "
                    "acceptance criteria. Do not design the implementation."
                ),
                input_payload=cast(dict[str, object], request.context.to_wire()),
                output_schema=ProductDraft.model_json_schema(),
                timeout_seconds=request.timeout_seconds,
            )
            draft = ProductDraft.model_validate(completion.payload)
            if draft.action == "clarify":
                return ProductAgentResult(
                    run_id=request.run_id,
                    project_id=request.project_id,
                    request_id=request.request_id,
                    context_id=request.context.context_id,
                    status=ProductAgentRunStatus.SUCCEEDED,
                    clarification=ProductClarification(
                        summary=draft.summary,
                        questions=draft.questions,
                    ),
                    duration_ms=completion.duration_ms,
                )
            spec = _product_spec(request, draft)
            return ProductAgentResult(
                run_id=request.run_id,
                project_id=request.project_id,
                request_id=request.request_id,
                context_id=request.context.context_id,
                status=ProductAgentRunStatus.SUCCEEDED,
                product_spec=spec,
                duration_ms=completion.duration_ms,
            )
        except StructuredModelError as error:
            return _product_failure(request, error)
        except ValueError:
            return ProductAgentResult(
                run_id=request.run_id,
                project_id=request.project_id,
                request_id=request.request_id,
                context_id=request.context.context_id,
                status=ProductAgentRunStatus.FAILED,
                error=ProductAgentFailure(
                    code=ProductAgentErrorCode.INVALID_OUTPUT,
                    message="Product model output failed its typed contract",
                    transient=False,
                ),
            )


class StructuredDesignerAgentAdapter(DesignerAgentAdapter):
    def __init__(self, client: StructuredModelClient) -> None:
        self._client = client

    def run(self, request: DesignerAgentRequest) -> DesignerAgentResult:
        try:
            completion = self._client.complete(
                instructions=(
                    "Act as Solution Designer. Use the approved ProductSpec and discovered project "
                    "facts to produce a minimal implementable design. Cover every exact "
                    "requirement and acceptance ID and use repository-relative affected path globs."
                ),
                input_payload=cast(dict[str, object], request.context.to_wire()),
                output_schema=TechnicalDesignDraft.model_json_schema(),
                timeout_seconds=request.timeout_seconds,
            )
            draft = TechnicalDesignDraft.model_validate(completion.payload)
            design = _technical_design(request, draft)
            return DesignerAgentResult(
                run_id=request.run_id,
                project_id=request.project_id,
                request_id=request.request_id,
                context_id=request.context.context_id,
                status=DesignerAgentRunStatus.SUCCEEDED,
                technical_design=design,
                duration_ms=completion.duration_ms,
            )
        except StructuredModelError as error:
            return _designer_failure(request, error)
        except ValueError:
            return DesignerAgentResult(
                run_id=request.run_id,
                project_id=request.project_id,
                request_id=request.request_id,
                context_id=request.context.context_id,
                status=DesignerAgentRunStatus.FAILED,
                error=DesignerAgentFailure(
                    code=DesignerAgentErrorCode.INVALID_OUTPUT,
                    message="Designer model output failed its typed contract",
                    transient=False,
                ),
            )


class StructuredPlannerAgentAdapter(PlannerAgentAdapter):
    def __init__(self, client: StructuredModelClient) -> None:
        self._client = client

    def run(self, request: PlannerAgentRequest) -> PlannerAgentResult:
        try:
            completion = self._client.complete(
                instructions=(
                    "Act as Planner Agent. Produce exactly the serial coder, qa, reviewer demands. "
                    "Assign no concrete Agent or provider. Each phase needs explicit capabilities, "
                    "risk, minimum brain tier, and verifiable checkpoints."
                ),
                input_payload=cast(dict[str, object], request.context.to_wire()),
                output_schema=ExecutionPlanDraft.model_json_schema(),
                timeout_seconds=request.timeout_seconds,
            )
            draft = ExecutionPlanDraft.model_validate(completion.payload)
            plan = _execution_plan(request, draft)
            return PlannerAgentResult(
                run_id=request.run_id,
                project_id=request.project_id,
                request_id=request.request_id,
                context_id=request.context.context_id,
                status=PlannerAgentRunStatus.SUCCEEDED,
                execution_plan=plan,
                duration_ms=completion.duration_ms,
            )
        except StructuredModelError as error:
            return _planner_failure(request, error)
        except ValueError:
            return PlannerAgentResult(
                run_id=request.run_id,
                project_id=request.project_id,
                request_id=request.request_id,
                context_id=request.context.context_id,
                status=PlannerAgentRunStatus.FAILED,
                error=PlannerAgentFailure(
                    code=PlannerAgentErrorCode.INVALID_OUTPUT,
                    message="Planner model output failed its typed contract",
                    transient=False,
                ),
            )


def _product_spec(request: ProductAgentRequest, draft: ProductDraft) -> ProductSpec:
    requirements: list[ProductRequirement] = []
    criteria: list[AcceptanceCriterion] = []
    for requirement_index, requirement in enumerate(draft.requirements, start=1):
        criterion_ids: list[str] = []
        for criterion_index, criterion in enumerate(requirement.acceptance, start=1):
            criterion_id = f"ac_{requirement_index:03d}_{criterion_index:03d}"
            criterion_ids.append(criterion_id)
            criteria.append(
                AcceptanceCriterion(
                    id=criterion_id,
                    description=criterion.description,
                    required=True,
                    verification=criterion.verification,
                    test_ids=criterion.test_ids,
                )
            )
        requirements.append(
            ProductRequirement(
                id=f"req_{requirement_index:03d}",
                statement=requirement.statement,
                priority=requirement.priority,
                rationale=requirement.rationale,
                acceptance_criterion_ids=tuple(criterion_ids),
            )
        )
    identity = _identity(request.run_id)
    return ProductSpec.create(
        spec_id=f"product_spec_{identity}",
        request_id=request.request_id,
        project_id=request.project_id,
        version=request.context.expected_product_spec_version,
        status=ProductSpecStatus.READY_FOR_REVIEW,
        summary=draft.summary,
        goals=draft.goals,
        non_goals=draft.non_goals,
        requirements=tuple(requirements),
        acceptance_criteria=tuple(criteria),
        assumptions=draft.assumptions,
        supersedes=request.context.expected_supersedes,
        created_at=request.context.built_at,
    )


def _technical_design(
    request: DesignerAgentRequest,
    draft: TechnicalDesignDraft,
) -> TechnicalDesign:
    components = tuple(
        DesignComponent(
            id=f"component_{item.key}",
            name=item.name,
            responsibility=item.responsibility,
            affected_paths=item.affected_paths,
        )
        for item in draft.components
    )
    return TechnicalDesign.create(
        request.context.product_spec,
        request.context.product_approval,
        design_id=f"technical_design_{_identity(request.run_id)}",
        version=1,
        summary=draft.summary,
        components=components,
        requirement_mappings=tuple(
            RequirementDesignMapping(
                requirement_id=item.requirement_id,
                component_ids=tuple(f"component_{key}" for key in item.component_keys),
                approach=item.approach,
            )
            for item in draft.requirement_mappings
        ),
        acceptance_mappings=tuple(
            AcceptanceDesignMapping(
                acceptance_criterion_id=item.acceptance_criterion_id,
                verification_strategy=item.verification_strategy,
                test_levels=item.test_levels,
            )
            for item in draft.acceptance_mappings
        ),
        implementation_steps=tuple(
            DesignStep(
                id=f"design_step_{item.key}",
                description=item.description,
                component_ids=tuple(f"component_{key}" for key in item.component_keys),
                verification=item.verification,
            )
            for item in draft.implementation_steps
        ),
        risks=tuple(
            DesignRisk(
                id=f"design_risk_{item.key}",
                description=item.description,
                tier=item.tier,
                mitigation=item.mitigation,
            )
            for item in draft.risks
        ),
        created_at=request.context.built_at,
    )


def _execution_plan(request: PlannerAgentRequest, draft: ExecutionPlanDraft) -> ExecutionPlan:
    phases = tuple(
        PlanPhaseDemand(
            id=f"phase_{item.role}_{index:03d}",
            role=AgentRole(item.role),
            objective=item.objective,
            required_capabilities=item.required_capabilities,
            risk=item.risk,
            minimum_brain_tier=item.minimum_brain_tier,
            checkpoints=item.checkpoints,
        )
        for index, item in enumerate(draft.phases, start=1)
    )
    return ExecutionPlan.create(
        request.context.product_spec,
        request.context.technical_design,
        plan_id=f"execution_plan_{_identity(request.run_id)}",
        version=request.context.expected_execution_plan_version,
        phases=phases,
        created_at=request.context.built_at,
    )


def _product_failure(
    request: ProductAgentRequest,
    error: StructuredModelError,
) -> ProductAgentResult:
    timed_out = error.code.value == "TIMEOUT"
    return ProductAgentResult(
        run_id=request.run_id,
        project_id=request.project_id,
        request_id=request.request_id,
        context_id=request.context.context_id,
        status=ProductAgentRunStatus.TIMED_OUT if timed_out else ProductAgentRunStatus.FAILED,
        error=ProductAgentFailure(
            code=(
                ProductAgentErrorCode.TIMEOUT if timed_out else ProductAgentErrorCode.PROVIDER_ERROR
            ),
            message=error.safe_message,
            transient=error.transient,
        ),
    )


def _designer_failure(
    request: DesignerAgentRequest,
    error: StructuredModelError,
) -> DesignerAgentResult:
    timed_out = error.code.value == "TIMEOUT"
    return DesignerAgentResult(
        run_id=request.run_id,
        project_id=request.project_id,
        request_id=request.request_id,
        context_id=request.context.context_id,
        status=DesignerAgentRunStatus.TIMED_OUT if timed_out else DesignerAgentRunStatus.FAILED,
        error=DesignerAgentFailure(
            code=(
                DesignerAgentErrorCode.TIMEOUT
                if timed_out
                else DesignerAgentErrorCode.PROVIDER_ERROR
            ),
            message=error.safe_message,
            transient=error.transient,
        ),
    )


def _planner_failure(
    request: PlannerAgentRequest,
    error: StructuredModelError,
) -> PlannerAgentResult:
    timed_out = error.code.value == "TIMEOUT"
    return PlannerAgentResult(
        run_id=request.run_id,
        project_id=request.project_id,
        request_id=request.request_id,
        context_id=request.context.context_id,
        status=PlannerAgentRunStatus.TIMED_OUT if timed_out else PlannerAgentRunStatus.FAILED,
        error=PlannerAgentFailure(
            code=(
                PlannerAgentErrorCode.TIMEOUT if timed_out else PlannerAgentErrorCode.PROVIDER_ERROR
            ),
            message=error.safe_message,
            transient=error.transient,
        ),
    )


def _identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


__all__ = [
    "ExecutionPlanDraft",
    "ProductDraft",
    "StructuredDesignerAgentAdapter",
    "StructuredPlannerAgentAdapter",
    "StructuredProductAgentAdapter",
    "TechnicalDesignDraft",
]
