"""Exact approved Product facts for Designer tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_software_engineer.design import RunDesignerCommand
from ai_software_engineer.domain import (
    AcceptanceCriterion,
    AcceptanceDesignMapping,
    DesignComponent,
    DesignRisk,
    DesignStep,
    ProductApprovalDecision,
    ProductRequirement,
    ProductSpec,
    ProductSpecApproval,
    ProductSpecStatus,
    ProjectRequest,
    ProjectRequestStatus,
    RequirementDesignMapping,
    RequirementPriority,
    RiskTier,
    TechnicalDesign,
)
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.product.store import FileProductRecordStore
from ai_software_engineer.project_manager.stages import (
    ProjectStage,
    ProjectStageAdvancer,
    StageAdvanceAuthorization,
    StageAdvanceRequest,
)
from tests.product.factories import prepared_product_facts

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


class BoundStageAdvancer:
    """Bind deterministic time around the raw T028 domain guard."""

    def __init__(self) -> None:
        self.calls = 0

    def advance_stage(self, request: StageAdvanceRequest) -> StageAdvanceAuthorization:
        self.calls += 1
        return ProjectStageAdvancer().advance_stage(request, authorized_at=NOW + timedelta(hours=1))


def approved_facts(
    tmp_path: Path,
) -> tuple[
    RunDesignerCommand,
    FileProductRecordStore,
    BoundStageAdvancer,
]:
    preparation, profile, baseline = prepared_product_facts(
        tmp_path, project_id="project_design_001"
    )
    request = ProjectRequest.create(
        request_id="request_design_001",
        project_id=preparation.project_id,
        preparation_sha256=preparation.preparation_sha256,
        title="Design auditable delivery",
        original_request="Produce an exact technical design from approved intent.",
        status=ProjectRequestStatus.DESIGNING,
        created_at=NOW,
    )
    revision = ProjectRequestRevision.create(
        request,
        revision=1,
        supersedes_sha256=None,
        recorded_at=NOW,
    )
    criterion = AcceptanceCriterion(
        id="ac_design_01",
        description="Every approved requirement has a testable design mapping.",
        required=True,
        verification="Run Designer contract tests.",
        test_ids=("test_designer_service",),
    )
    spec = ProductSpec.create(
        spec_id="product_spec_design_001",
        request_id=request.id,
        project_id=request.project_id,
        version=1,
        status=ProductSpecStatus.READY_FOR_REVIEW,
        summary="Turn approved product intent into an implementation-ready design.",
        goals=("Preserve exact requirement and acceptance lineage.",),
        requirements=(
            ProductRequirement(
                id="req_design_01",
                statement="The Designer must map approved intent to technical components.",
                priority=RequirementPriority.MUST,
                rationale="Delivery cannot rely on implicit Agent assumptions.",
                acceptance_criterion_ids=(criterion.id,),
            ),
        ),
        acceptance_criteria=(criterion,),
        created_at=NOW + timedelta(minutes=1),
    )
    approval = ProductSpecApproval.create(
        spec,
        decision=ProductApprovalDecision.APPROVED,
        operator_id="user_owner_001",
        rationale="The product scope is approved exactly.",
        decided_at=NOW + timedelta(minutes=2),
    )
    solution_authorization = ProjectStageAdvancer().advance_stage(
        StageAdvanceRequest(
            target=ProjectStage.SOLUTION_DESIGN,
            preparation=preparation,
            project_request=request,
            product_spec=spec,
            product_approval=approval,
        ),
        authorized_at=NOW + timedelta(minutes=3),
    )
    store = FileProductRecordStore(tmp_path / "product-records")
    store.put_request_revision(revision)
    store.put_product_spec(spec)
    store.put_approval(approval)
    command = RunDesignerCommand(
        run_id="run_designer_001",
        preparation=preparation,
        project_profile=profile,
        project_baseline=baseline,
        request_revision=revision,
        product_spec=spec,
        product_approval=approval,
        solution_design_authorization=solution_authorization,
        submitted_at=NOW + timedelta(minutes=4),
    )
    return command, store, BoundStageAdvancer()


def design_for(
    command: RunDesignerCommand,
    *,
    summary: str = "Add explicit Designer context, service, and immutable records.",
) -> TechnicalDesign:
    return TechnicalDesign.create(
        command.product_spec,
        command.product_approval,
        design_id="technical_design_design_001",
        version=1,
        summary=summary,
        components=(
            DesignComponent(
                id="component_design_contract",
                name="Designer contract",
                responsibility="Validate and persist the exact design handoff.",
                affected_paths=("src/ai_software_engineer/design",),
            ),
        ),
        requirement_mappings=(
            RequirementDesignMapping(
                requirement_id="req_design_01",
                component_ids=("component_design_contract",),
                approach="Compile approved project and product facts into typed context.",
            ),
        ),
        acceptance_mappings=(
            AcceptanceDesignMapping(
                acceptance_criterion_id="ac_design_01",
                verification_strategy="Run deterministic service and replay tests.",
                test_levels=("contract", "unit"),
            ),
        ),
        implementation_steps=(
            DesignStep(
                id="design_step_handoff_01",
                description="Persist design and advance the request to planning.",
                component_ids=("component_design_contract",),
                verification="Read back design, request revision, and commit checkpoint.",
            ),
        ),
        risks=(
            DesignRisk(
                id="design_risk_partial_01",
                description="A crash can occur between append-only effects.",
                tier=RiskTier.HIGH,
                mitigation="Use a receipt journal and publish a final commit checkpoint.",
            ),
        ),
        created_at=command.submitted_at,
    )
