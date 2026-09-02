"""Upstream product, design, and planning contracts for one project delivery.

These immutable documents are the explicit hand-off boundary between the Product,
Solution Designer, Planner, and delivery roles.  They deliberately precede the
existing Delivery ``Task`` and never rely on shared Agent conversation memory.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.enums import (
    AgentRole,
    BrainTier,
    ProductApprovalDecision,
    ProductSpecStatus,
    ProjectRequestStatus,
    RequirementPriority,
    RiskTier,
    TaskStatus,
)
from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import DomainModel, JsonValue, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import (
    AcceptanceCriterion,
    AcceptanceCriterionId,
    AttemptLimit,
    Task,
    TaskConstraints,
    TaskId,
)

StageSha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
ProjectRequestId = Annotated[str, StringConstraints(pattern=r"^request_[a-z0-9][a-z0-9_-]{2,63}$")]
ProductSpecId = Annotated[
    str, StringConstraints(pattern=r"^product_spec_[a-z0-9][a-z0-9_-]{2,63}$")
]
ProductApprovalId = Annotated[str, StringConstraints(pattern=r"^product_approval_[a-f0-9]{64}$")]
TechnicalDesignId = Annotated[
    str, StringConstraints(pattern=r"^technical_design_[a-z0-9][a-z0-9_-]{2,63}$")
]
ExecutionPlanId = Annotated[
    str, StringConstraints(pattern=r"^execution_plan_[a-z0-9][a-z0-9_-]{2,63}$")
]
RequirementId = Annotated[str, StringConstraints(pattern=r"^req_[a-z0-9][a-z0-9_-]{1,63}$")]
DecisionId = Annotated[str, StringConstraints(pattern=r"^decision_[a-z0-9][a-z0-9_-]{1,63}$")]
DesignComponentId = Annotated[
    str, StringConstraints(pattern=r"^component_[a-z0-9][a-z0-9_-]{1,63}$")
]
DesignStepId = Annotated[str, StringConstraints(pattern=r"^design_step_[a-z0-9][a-z0-9_-]{1,63}$")]
DesignRiskId = Annotated[str, StringConstraints(pattern=r"^design_risk_[a-z0-9][a-z0-9_-]{1,63}$")]
PlanPhaseId = Annotated[str, StringConstraints(pattern=r"^phase_[a-z0-9][a-z0-9_-]{1,63}$")]
OrganizationId = Annotated[
    str, StringConstraints(pattern=r"^organization_[a-z0-9][a-z0-9_-]{2,63}$")
]
StageVersion = Annotated[StrictInt, Field(ge=1)]


class StageContractError(RuntimeError):
    """Base error for a cross-stage delivery contract violation."""


class StageIntegrityError(StageContractError):
    """Raised when an immutable stage document no longer matches its digest."""


class StageContractMismatch(StageContractError):
    """Raised when adjacent stage documents refer to different work."""


class ProductApprovalRequired(StageContractError):
    """Raised when design or delivery is attempted without exact user approval."""


class ProjectPreparation(DomainModel):
    """Proof that project facts and the project-level rule baseline are ready."""

    kind: Literal["project_preparation"] = "project_preparation"
    schema_version: Literal["v0.1"] = "v0.1"
    organization_id: OrganizationId
    project_id: ProjectId
    project_root: NonEmptyStr
    project_workspace_root: NonEmptyStr
    organization_root: NonEmptyStr
    project_profile_sha256: StageSha256
    runtime_binding_sha256: StageSha256
    baseline_spec_sha256: StageSha256
    baseline_source_uris: tuple[NonEmptyStr, ...] = ()
    status: Literal["PREPARED"] = "PREPARED"
    prepared_at: AwareDatetime
    preparation_sha256: StageSha256

    @model_validator(mode="after")
    def validate_preparation(self) -> Self:
        roots = tuple(
            Path(value)
            for value in (self.project_root, self.project_workspace_root, self.organization_root)
        )
        if any(not root.is_absolute() for root in roots):
            raise ValueError("ProjectPreparation roots must be absolute")
        if any(
            _paths_overlap(left, right)
            for index, left in enumerate(roots)
            for right in roots[index + 1 :]
        ):
            raise ValueError("ProjectPreparation roots must not overlap")
        ensure_unique(self.baseline_source_uris, "baseline_source_uris")
        return self

    @classmethod
    def create(
        cls,
        *,
        organization_id: OrganizationId,
        project_id: ProjectId,
        project_root: str,
        project_workspace_root: str,
        organization_root: str,
        project_profile_sha256: StageSha256,
        runtime_binding_sha256: StageSha256,
        baseline_spec_sha256: StageSha256,
        baseline_source_uris: tuple[str, ...] = (),
        prepared_at: datetime,
    ) -> ProjectPreparation:
        provisional = cls(
            organization_id=organization_id,
            project_id=project_id,
            project_root=project_root,
            project_workspace_root=project_workspace_root,
            organization_root=organization_root,
            project_profile_sha256=project_profile_sha256,
            runtime_binding_sha256=runtime_binding_sha256,
            baseline_spec_sha256=baseline_spec_sha256,
            baseline_source_uris=baseline_source_uris,
            prepared_at=prepared_at,
            preparation_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={"preparation_sha256": _stage_digest(provisional, "preparation_sha256")}
        )

    def validate_integrity(self) -> None:
        _require_digest(self, "preparation_sha256", self.preparation_sha256)


class ProjectRequest(DomainModel):
    """Durable product request before it becomes a Delivery Task."""

    kind: Literal["project_request"] = "project_request"
    schema_version: Literal["v0.1"] = "v0.1"
    id: ProjectRequestId
    project_id: ProjectId
    preparation_sha256: StageSha256
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    original_request: NonEmptyStr
    status: ProjectRequestStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
    request_sha256: StageSha256

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("ProjectRequest updated_at cannot precede created_at")
        return self

    @classmethod
    def create(
        cls,
        *,
        request_id: ProjectRequestId,
        project_id: ProjectId,
        preparation_sha256: StageSha256,
        title: str,
        original_request: str,
        status: ProjectRequestStatus,
        created_at: datetime,
        updated_at: datetime | None = None,
    ) -> ProjectRequest:
        provisional = cls(
            id=request_id,
            project_id=project_id,
            preparation_sha256=preparation_sha256,
            title=title,
            original_request=original_request,
            status=status,
            created_at=created_at,
            updated_at=updated_at or created_at,
            request_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={"request_sha256": _stage_digest(provisional, "request_sha256")}
        )

    def validate_integrity(self) -> None:
        _require_digest(self, "request_sha256", self.request_sha256)


class ProductRequirement(DomainModel):
    """One product requirement with explicit acceptance coverage."""

    id: RequirementId
    statement: NonEmptyStr
    priority: RequirementPriority
    rationale: NonEmptyStr
    acceptance_criterion_ids: Annotated[tuple[AcceptanceCriterionId, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_acceptance_ids(self) -> Self:
        ensure_unique(self.acceptance_criterion_ids, "requirement acceptance IDs")
        return self


class ProductDecision(DomainModel):
    """One traceable user decision captured during product discovery."""

    id: DecisionId
    question: NonEmptyStr
    decision: NonEmptyStr
    rationale: NonEmptyStr
    decided_by: NonEmptyStr
    decided_at: AwareDatetime


class ProductSpec(DomainModel):
    """Versioned product truth produced by Product Agent and reviewed by a human."""

    kind: Literal["product_spec"] = "product_spec"
    schema_version: Literal["v0.1"] = "v0.1"
    id: ProductSpecId
    request_id: ProjectRequestId
    project_id: ProjectId
    version: StageVersion
    status: ProductSpecStatus
    summary: NonEmptyStr
    goals: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    non_goals: tuple[NonEmptyStr, ...] = ()
    requirements: Annotated[tuple[ProductRequirement, ...], Field(min_length=1)]
    acceptance_criteria: Annotated[tuple[AcceptanceCriterion, ...], Field(min_length=1)]
    assumptions: tuple[NonEmptyStr, ...] = ()
    open_questions: tuple[NonEmptyStr, ...] = ()
    decisions: tuple[ProductDecision, ...] = ()
    supersedes: ProductSpecId | None = None
    created_at: AwareDatetime
    product_spec_sha256: StageSha256

    @model_validator(mode="after")
    def validate_product_spec(self) -> Self:
        ensure_unique(self.goals, "ProductSpec goals")
        ensure_unique(self.non_goals, "ProductSpec non_goals")
        ensure_unique((item.id for item in self.requirements), "ProductSpec requirement IDs")
        ensure_unique(
            (item.id for item in self.acceptance_criteria),
            "ProductSpec acceptance criterion IDs",
        )
        ensure_unique(self.assumptions, "ProductSpec assumptions")
        ensure_unique(self.open_questions, "ProductSpec open_questions")
        ensure_unique((item.id for item in self.decisions), "ProductSpec decision IDs")
        known = {item.id for item in self.acceptance_criteria}
        referenced = {
            criterion_id
            for requirement in self.requirements
            for criterion_id in requirement.acceptance_criterion_ids
        }
        unknown = sorted(referenced - known)
        if unknown:
            raise ValueError("ProductSpec requirements reference unknown acceptance IDs")
        unowned = sorted(known - referenced)
        if unowned:
            raise ValueError("every ProductSpec acceptance criterion must cover a requirement")
        if self.supersedes == self.id:
            raise ValueError("ProductSpec cannot supersede itself")
        return self

    @classmethod
    def create(
        cls,
        *,
        spec_id: ProductSpecId,
        request_id: ProjectRequestId,
        project_id: ProjectId,
        version: int,
        status: ProductSpecStatus,
        summary: str,
        goals: tuple[str, ...],
        requirements: tuple[ProductRequirement, ...],
        acceptance_criteria: tuple[AcceptanceCriterion, ...],
        created_at: datetime,
        non_goals: tuple[str, ...] = (),
        assumptions: tuple[str, ...] = (),
        open_questions: tuple[str, ...] = (),
        decisions: tuple[ProductDecision, ...] = (),
        supersedes: ProductSpecId | None = None,
    ) -> ProductSpec:
        provisional = cls(
            id=spec_id,
            request_id=request_id,
            project_id=project_id,
            version=version,
            status=status,
            summary=summary,
            goals=goals,
            non_goals=non_goals,
            requirements=requirements,
            acceptance_criteria=acceptance_criteria,
            assumptions=assumptions,
            open_questions=open_questions,
            decisions=decisions,
            supersedes=supersedes,
            created_at=created_at,
            product_spec_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={
                "product_spec_sha256": _stage_digest(
                    provisional,
                    "product_spec_sha256",
                    "created_at",
                )
            }
        )

    def validate_integrity(self) -> None:
        _require_digest(
            self,
            "product_spec_sha256",
            self.product_spec_sha256,
            "created_at",
        )


class ProductSpecApproval(DomainModel):
    """Human decision over one exact ProductSpec version and digest."""

    kind: Literal["product_spec_approval"] = "product_spec_approval"
    schema_version: Literal["v0.1"] = "v0.1"
    id: ProductApprovalId
    request_id: ProjectRequestId
    project_id: ProjectId
    product_spec_id: ProductSpecId
    product_spec_sha256: StageSha256
    decision: ProductApprovalDecision
    operator_id: NonEmptyStr
    rationale: NonEmptyStr
    decided_at: AwareDatetime
    approval_sha256: StageSha256

    @classmethod
    def create(
        cls,
        product_spec: ProductSpec,
        *,
        decision: ProductApprovalDecision,
        operator_id: str,
        rationale: str,
        decided_at: datetime,
    ) -> ProductSpecApproval:
        product_spec.validate_integrity()
        identity = _canonical_json(
            {
                "request_id": product_spec.request_id,
                "project_id": product_spec.project_id,
                "product_spec_id": product_spec.id,
                "product_spec_sha256": product_spec.product_spec_sha256,
                "decision": decision.value,
                "operator_id": operator_id,
                "rationale": rationale,
                "decided_at": decided_at.isoformat(),
            }
        )
        provisional = cls(
            id=f"product_approval_{hashlib.sha256(identity.encode()).hexdigest()}",
            request_id=product_spec.request_id,
            project_id=product_spec.project_id,
            product_spec_id=product_spec.id,
            product_spec_sha256=product_spec.product_spec_sha256,
            decision=decision,
            operator_id=operator_id,
            rationale=rationale,
            decided_at=decided_at,
            approval_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={"approval_sha256": _stage_digest(provisional, "approval_sha256")}
        )

    def validate_integrity(self) -> None:
        _require_digest(self, "approval_sha256", self.approval_sha256)


class DesignComponent(DomainModel):
    id: DesignComponentId
    name: NonEmptyStr
    responsibility: NonEmptyStr
    affected_paths: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        ensure_unique(self.affected_paths, "DesignComponent affected_paths")
        return self


class RequirementDesignMapping(DomainModel):
    requirement_id: RequirementId
    component_ids: Annotated[tuple[DesignComponentId, ...], Field(min_length=1)]
    approach: NonEmptyStr

    @model_validator(mode="after")
    def validate_components(self) -> Self:
        ensure_unique(self.component_ids, "RequirementDesignMapping component_ids")
        return self


class AcceptanceDesignMapping(DomainModel):
    acceptance_criterion_id: AcceptanceCriterionId
    verification_strategy: NonEmptyStr
    test_levels: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_test_levels(self) -> Self:
        ensure_unique(self.test_levels, "AcceptanceDesignMapping test_levels")
        return self


class DesignStep(DomainModel):
    id: DesignStepId
    description: NonEmptyStr
    component_ids: Annotated[tuple[DesignComponentId, ...], Field(min_length=1)]
    verification: NonEmptyStr

    @model_validator(mode="after")
    def validate_components(self) -> Self:
        ensure_unique(self.component_ids, "DesignStep component_ids")
        return self


class DesignRisk(DomainModel):
    id: DesignRiskId
    description: NonEmptyStr
    tier: RiskTier
    mitigation: NonEmptyStr


class TechnicalDesign(DomainModel):
    """Technical solution for one exact, human-approved ProductSpec."""

    kind: Literal["technical_design"] = "technical_design"
    schema_version: Literal["v0.1"] = "v0.1"
    id: TechnicalDesignId
    request_id: ProjectRequestId
    project_id: ProjectId
    product_spec_id: ProductSpecId
    product_spec_sha256: StageSha256
    product_approval_id: ProductApprovalId
    version: StageVersion
    status: Literal["READY_FOR_PLANNING"] = "READY_FOR_PLANNING"
    summary: NonEmptyStr
    components: Annotated[tuple[DesignComponent, ...], Field(min_length=1)]
    requirement_mappings: Annotated[tuple[RequirementDesignMapping, ...], Field(min_length=1)]
    acceptance_mappings: Annotated[tuple[AcceptanceDesignMapping, ...], Field(min_length=1)]
    implementation_steps: Annotated[tuple[DesignStep, ...], Field(min_length=1)]
    risks: tuple[DesignRisk, ...] = ()
    created_at: AwareDatetime
    technical_design_sha256: StageSha256

    @model_validator(mode="after")
    def validate_design(self) -> Self:
        ordered_component_ids = tuple(component.id for component in self.components)
        ensure_unique(ordered_component_ids, "TechnicalDesign component IDs")
        component_ids = set(ordered_component_ids)
        ensure_unique(
            (mapping.requirement_id for mapping in self.requirement_mappings),
            "TechnicalDesign requirement mappings",
        )
        ensure_unique(
            (mapping.acceptance_criterion_id for mapping in self.acceptance_mappings),
            "TechnicalDesign acceptance mappings",
        )
        ensure_unique((step.id for step in self.implementation_steps), "TechnicalDesign step IDs")
        ensure_unique((risk.id for risk in self.risks), "TechnicalDesign risk IDs")
        referenced_components = {
            component_id
            for mapping in self.requirement_mappings
            for component_id in mapping.component_ids
        } | {
            component_id
            for step in self.implementation_steps
            for component_id in step.component_ids
        }
        if referenced_components - component_ids:
            raise ValueError("TechnicalDesign references unknown components")
        return self

    @classmethod
    def create(
        cls,
        product_spec: ProductSpec,
        approval: ProductSpecApproval,
        *,
        design_id: TechnicalDesignId,
        version: int,
        summary: str,
        components: tuple[DesignComponent, ...],
        requirement_mappings: tuple[RequirementDesignMapping, ...],
        acceptance_mappings: tuple[AcceptanceDesignMapping, ...],
        implementation_steps: tuple[DesignStep, ...],
        created_at: datetime,
        risks: tuple[DesignRisk, ...] = (),
    ) -> TechnicalDesign:
        require_product_approval(product_spec, approval)
        provisional = cls(
            id=design_id,
            request_id=product_spec.request_id,
            project_id=product_spec.project_id,
            product_spec_id=product_spec.id,
            product_spec_sha256=product_spec.product_spec_sha256,
            product_approval_id=approval.id,
            version=version,
            summary=summary,
            components=components,
            requirement_mappings=requirement_mappings,
            acceptance_mappings=acceptance_mappings,
            implementation_steps=implementation_steps,
            risks=risks,
            created_at=created_at,
            technical_design_sha256="0" * 64,
        )
        design = provisional.model_copy(
            update={
                "technical_design_sha256": _stage_digest(
                    provisional,
                    "technical_design_sha256",
                    "created_at",
                )
            }
        )
        validate_technical_design(product_spec, approval, design)
        return design

    def validate_integrity(self) -> None:
        _require_digest(
            self,
            "technical_design_sha256",
            self.technical_design_sha256,
            "created_at",
        )


class PlanPhaseDemand(DomainModel):
    """Abstract workforce demand; never a concrete assignment or model selection."""

    id: PlanPhaseId
    role: AgentRole
    objective: NonEmptyStr
    required_capabilities: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    risk: RiskTier
    minimum_brain_tier: BrainTier
    checkpoints: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    critical_path: StrictBool = True

    @model_validator(mode="after")
    def validate_phase(self) -> Self:
        ensure_unique(self.required_capabilities, "PlanPhaseDemand required_capabilities")
        ensure_unique(self.checkpoints, "PlanPhaseDemand checkpoints")
        return self


class ExecutionPlan(DomainModel):
    """Planner-owned serial plan containing demand but no concrete allocation."""

    kind: Literal["execution_plan"] = "execution_plan"
    schema_version: Literal["v0.1"] = "v0.1"
    id: ExecutionPlanId
    request_id: ProjectRequestId
    project_id: ProjectId
    product_spec_id: ProductSpecId
    product_spec_sha256: StageSha256
    technical_design_id: TechnicalDesignId
    technical_design_sha256: StageSha256
    version: StageVersion
    status: Literal["READY_FOR_DISPATCH"] = "READY_FOR_DISPATCH"
    phases: Annotated[tuple[PlanPhaseDemand, ...], Field(min_length=3, max_length=3)]
    feasibility_evidence_uris: tuple[NonEmptyStr, ...] = ()
    created_at: AwareDatetime
    execution_plan_sha256: StageSha256

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        ensure_unique((phase.id for phase in self.phases), "ExecutionPlan phase IDs")
        ensure_unique(self.feasibility_evidence_uris, "ExecutionPlan feasibility evidence")
        expected = (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)
        if tuple(phase.role for phase in self.phases) != expected:
            raise ValueError("v0.1 ExecutionPlan phases must be coder, qa, reviewer in order")
        return self

    @classmethod
    def create(
        cls,
        product_spec: ProductSpec,
        technical_design: TechnicalDesign,
        *,
        plan_id: ExecutionPlanId,
        version: int,
        phases: tuple[PlanPhaseDemand, ...],
        created_at: datetime,
        feasibility_evidence_uris: tuple[str, ...] = (),
    ) -> ExecutionPlan:
        technical_design.validate_integrity()
        provisional = cls(
            id=plan_id,
            request_id=product_spec.request_id,
            project_id=product_spec.project_id,
            product_spec_id=product_spec.id,
            product_spec_sha256=product_spec.product_spec_sha256,
            technical_design_id=technical_design.id,
            technical_design_sha256=technical_design.technical_design_sha256,
            version=version,
            phases=phases,
            feasibility_evidence_uris=feasibility_evidence_uris,
            created_at=created_at,
            execution_plan_sha256="0" * 64,
        )
        plan = provisional.model_copy(
            update={
                "execution_plan_sha256": _stage_digest(
                    provisional,
                    "execution_plan_sha256",
                    "created_at",
                )
            }
        )
        validate_execution_plan(product_spec, technical_design, plan)
        return plan

    def validate_integrity(self) -> None:
        _require_digest(
            self,
            "execution_plan_sha256",
            self.execution_plan_sha256,
            "created_at",
        )


def require_product_approval(
    product_spec: ProductSpec,
    approval: ProductSpecApproval,
) -> None:
    """Require one explicit human approval of the exact ProductSpec digest."""
    product_spec.validate_integrity()
    approval.validate_integrity()
    if approval.decision is not ProductApprovalDecision.APPROVED:
        raise ProductApprovalRequired("ProductSpec approval requested changes")
    expected = (
        product_spec.request_id,
        product_spec.project_id,
        product_spec.id,
        product_spec.product_spec_sha256,
    )
    observed = (
        approval.request_id,
        approval.project_id,
        approval.product_spec_id,
        approval.product_spec_sha256,
    )
    if observed != expected:
        raise StageContractMismatch("ProductSpecApproval does not match the exact ProductSpec")
    if product_spec.status is not ProductSpecStatus.READY_FOR_REVIEW:
        raise ProductApprovalRequired("only READY_FOR_REVIEW ProductSpec can be approved")


def validate_technical_design(
    product_spec: ProductSpec,
    approval: ProductSpecApproval,
    technical_design: TechnicalDesign,
) -> None:
    """Validate approval lineage and exact requirement/acceptance coverage."""
    require_product_approval(product_spec, approval)
    technical_design.validate_integrity()
    expected = (
        product_spec.request_id,
        product_spec.project_id,
        product_spec.id,
        product_spec.product_spec_sha256,
        approval.id,
    )
    observed = (
        technical_design.request_id,
        technical_design.project_id,
        technical_design.product_spec_id,
        technical_design.product_spec_sha256,
        technical_design.product_approval_id,
    )
    if observed != expected:
        raise StageContractMismatch("TechnicalDesign lineage does not match ProductSpec approval")
    requirement_ids = {requirement.id for requirement in product_spec.requirements}
    design_requirement_ids = {
        mapping.requirement_id for mapping in technical_design.requirement_mappings
    }
    if design_requirement_ids != requirement_ids:
        raise StageContractMismatch("TechnicalDesign must cover exact ProductSpec requirements")
    acceptance_ids = {criterion.id for criterion in product_spec.acceptance_criteria}
    design_acceptance_ids = {
        mapping.acceptance_criterion_id for mapping in technical_design.acceptance_mappings
    }
    if design_acceptance_ids != acceptance_ids:
        raise StageContractMismatch(
            "TechnicalDesign must cover exact ProductSpec acceptance criteria"
        )


def validate_execution_plan(
    product_spec: ProductSpec,
    technical_design: TechnicalDesign,
    execution_plan: ExecutionPlan,
) -> None:
    """Validate exact design lineage before dispatch preview or commit."""
    product_spec.validate_integrity()
    technical_design.validate_integrity()
    execution_plan.validate_integrity()
    if (
        technical_design.request_id != product_spec.request_id
        or technical_design.project_id != product_spec.project_id
        or technical_design.product_spec_id != product_spec.id
        or technical_design.product_spec_sha256 != product_spec.product_spec_sha256
    ):
        raise StageContractMismatch("TechnicalDesign does not match ProductSpec")
    expected = (
        product_spec.request_id,
        product_spec.project_id,
        product_spec.id,
        product_spec.product_spec_sha256,
        technical_design.id,
        technical_design.technical_design_sha256,
    )
    observed = (
        execution_plan.request_id,
        execution_plan.project_id,
        execution_plan.product_spec_id,
        execution_plan.product_spec_sha256,
        execution_plan.technical_design_id,
        execution_plan.technical_design_sha256,
    )
    if observed != expected:
        raise StageContractMismatch("ExecutionPlan lineage does not match TechnicalDesign")


def validate_stage_chain(
    preparation: ProjectPreparation,
    request: ProjectRequest,
    product_spec: ProductSpec,
    approval: ProductSpecApproval,
    technical_design: TechnicalDesign,
    execution_plan: ExecutionPlan,
) -> None:
    """Fail closed unless the complete prepared-to-dispatch chain is coherent."""
    preparation.validate_integrity()
    request.validate_integrity()
    if request.status is not ProjectRequestStatus.READY_FOR_DELIVERY:
        raise StageContractMismatch("ProjectRequest is not ready for Delivery Task creation")
    if (
        request.project_id != preparation.project_id
        or request.preparation_sha256 != preparation.preparation_sha256
        or product_spec.request_id != request.id
        or product_spec.project_id != request.project_id
    ):
        raise StageContractMismatch("ProjectPreparation, Request, and ProductSpec do not match")
    validate_technical_design(product_spec, approval, technical_design)
    validate_execution_plan(product_spec, technical_design, execution_plan)


def derive_delivery_task(
    preparation: ProjectPreparation,
    request: ProjectRequest,
    product_spec: ProductSpec,
    approval: ProductSpecApproval,
    technical_design: TechnicalDesign,
    execution_plan: ExecutionPlan,
    *,
    task_id: TaskId,
    repository: str,
    base_ref: str,
    max_attempts: AttemptLimit,
    created_at: datetime,
    constraints: TaskConstraints | None = None,
    owner: str | None = None,
    labels: tuple[str, ...] = (),
) -> Task:
    """Create the existing Delivery Task only after every upstream gate passes."""
    validate_stage_chain(
        preparation,
        request,
        product_spec,
        approval,
        technical_design,
        execution_plan,
    )
    resolved_repository = Path(repository).expanduser().resolve(strict=False)
    if resolved_repository != Path(preparation.project_root):
        raise StageContractMismatch("Delivery Task repository does not match prepared project root")
    metadata: dict[str, JsonValue] = {
        "project_id": preparation.project_id,
        "project_request_id": request.id,
        "product_spec_id": product_spec.id,
        "product_spec_sha256": product_spec.product_spec_sha256,
        "product_approval_id": approval.id,
        "technical_design_id": technical_design.id,
        "technical_design_sha256": technical_design.technical_design_sha256,
        "execution_plan_id": execution_plan.id,
        "execution_plan_sha256": execution_plan.execution_plan_sha256,
    }
    return Task(
        id=task_id,
        title=request.title,
        description=product_spec.summary,
        repository=str(resolved_repository),
        base_ref=base_ref,
        acceptance_criteria=product_spec.acceptance_criteria,
        constraints=constraints,
        status=TaskStatus.NEW,
        max_attempts=max_attempts,
        owner=owner,
        labels=labels,
        created_at=created_at,
        updated_at=created_at,
        metadata=metadata,
    )


def _require_digest(
    model: DomainModel,
    digest_field: str,
    observed: str,
    *excluded_fields: str,
) -> None:
    expected = _stage_digest(model, digest_field, *excluded_fields)
    if observed != expected:
        raise StageIntegrityError(f"{model.__class__.__name__} digest does not match content")


def _stage_digest(model: DomainModel, digest_field: str, *excluded_fields: str) -> str:
    excluded = {digest_field, *excluded_fields}
    payload = model.model_dump(mode="json", exclude=excluded, exclude_none=True)
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


__all__ = [
    "AcceptanceDesignMapping",
    "DesignComponent",
    "DesignRisk",
    "DesignStep",
    "ExecutionPlan",
    "PlanPhaseDemand",
    "ProductApprovalRequired",
    "ProductDecision",
    "ProductRequirement",
    "ProductSpec",
    "ProductSpecApproval",
    "ProjectPreparation",
    "ProjectRequest",
    "RequirementDesignMapping",
    "StageContractError",
    "StageContractMismatch",
    "StageIntegrityError",
    "TechnicalDesign",
    "derive_delivery_task",
    "require_product_approval",
    "validate_execution_plan",
    "validate_stage_chain",
    "validate_technical_design",
]
