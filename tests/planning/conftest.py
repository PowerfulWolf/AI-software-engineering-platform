"""Shared, exact upstream-stage fixtures for Planner tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_software_engineer.design import (
    DesignCommitCheckpoint,
    DesignRunOutcome,
    DesignRunRecord,
    FileDesignRecordStore,
)
from ai_software_engineer.domain import (
    AcceptanceCriterion,
    AcceptanceDesignMapping,
    AgentRole,
    BrainTier,
    DesignComponent,
    DesignStep,
    ExecutionPlan,
    PlanPhaseDemand,
    ProductApprovalDecision,
    ProductRequirement,
    ProductSpec,
    ProductSpecApproval,
    ProductSpecStatus,
    ProjectPreparation,
    ProjectRequest,
    ProjectRequestStatus,
    RequirementDesignMapping,
    RequirementPriority,
    RiskTier,
    Task,
    TechnicalDesign,
    derive_delivery_task,
)
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.project_manager.stages import (
    ProjectStage,
    ProjectStageAdvancer,
    StageAdvanceRequest,
)

NOW = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)


def preparation(tmp_path: Path) -> ProjectPreparation:
    project = tmp_path / "target"
    project.mkdir(exist_ok=True)
    return ProjectPreparation.create(
        organization_id="organization_planning_001",
        project_id="project_planning_001",
        project_root=str(project),
        project_workspace_root=str(tmp_path / "sidecar"),
        organization_root=str(tmp_path / "organization"),
        project_profile_sha256="a" * 64,
        runtime_binding_sha256="b" * 64,
        baseline_spec_sha256="c" * 64,
        prepared_at=NOW,
    )


def planning_request(prepared: ProjectPreparation) -> ProjectRequest:
    return ProjectRequest.create(
        request_id="request_planning_001",
        project_id=prepared.project_id,
        preparation_sha256=prepared.preparation_sha256,
        title="Add planner preview",
        original_request="Plan delivery using current team capacity.",
        status=ProjectRequestStatus.PLANNING,
        created_at=NOW,
        updated_at=NOW + timedelta(minutes=3),
    )


def request_revision(request: ProjectRequest) -> ProjectRequestRevision:
    previous = designing_request_revision(request)
    return ProjectRequestRevision.create(
        request,
        revision=2,
        supersedes_sha256=previous.request_revision_sha256,
        recorded_at=request.updated_at,
    )


def designing_request_revision(request: ProjectRequest) -> ProjectRequestRevision:
    designing = ProjectRequest.create(
        request_id=request.id,
        project_id=request.project_id,
        preparation_sha256=request.preparation_sha256,
        title=request.title,
        original_request=request.original_request,
        status=ProjectRequestStatus.DESIGNING,
        created_at=request.created_at,
        updated_at=NOW,
    )
    return ProjectRequestRevision.create(
        designing,
        revision=1,
        supersedes_sha256=None,
        recorded_at=NOW,
    )


def product_spec(request: ProjectRequest) -> ProductSpec:
    criterion = AcceptanceCriterion(
        id="ac_planner_01",
        description="Planner returns replayable feasibility evidence.",
        required=True,
        verification="Run Planner preview tests.",
        test_ids=("test_planning_preview",),
    )
    return ProductSpec.create(
        spec_id="product_spec_planning_001",
        request_id=request.id,
        project_id=request.project_id,
        version=1,
        status=ProductSpecStatus.READY_FOR_REVIEW,
        summary="Preview delivery feasibility without reserving resources.",
        goals=("Preserve read-only planning and current-facts evidence.",),
        requirements=(
            ProductRequirement(
                id="req_planner_01",
                statement="Planner must not persist concrete allocation.",
                priority=RequirementPriority.MUST,
                rationale="Project Manager remains the allocation authority.",
                acceptance_criterion_ids=(criterion.id,),
            ),
        ),
        acceptance_criteria=(criterion,),
        created_at=NOW + timedelta(minutes=1),
    )


def approval(spec: ProductSpec) -> ProductSpecApproval:
    return ProductSpecApproval.create(
        spec,
        decision=ProductApprovalDecision.APPROVED,
        operator_id="user_owner_001",
        rationale="The planning boundary is correct.",
        decided_at=NOW + timedelta(minutes=2),
    )


def technical_design(spec: ProductSpec, approved: ProductSpecApproval) -> TechnicalDesign:
    return TechnicalDesign.create(
        spec,
        approved,
        design_id="technical_design_planning_001",
        version=1,
        summary="Use pure scheduling engines and immutable preview evidence.",
        components=(
            DesignComponent(
                id="component_planning_preview",
                name="Planning preview",
                responsibility="Preview scheduler and model routes without stores.",
                affected_paths=("src/ai_software_engineer/planning",),
            ),
        ),
        requirement_mappings=(
            RequirementDesignMapping(
                requirement_id="req_planner_01",
                component_ids=("component_planning_preview",),
                approach="Inject pure Scheduler and ModelRouter engines.",
            ),
        ),
        acceptance_mappings=(
            AcceptanceDesignMapping(
                acceptance_criterion_id="ac_planner_01",
                verification_strategy="Assert deterministic preview and zero write port.",
                test_levels=("unit", "contract"),
            ),
        ),
        implementation_steps=(
            DesignStep(
                id="design_step_planner_01",
                description="Build an abstract plan and preview every delivery phase.",
                component_ids=("component_planning_preview",),
                verification="Run tests/planning.",
            ),
        ),
        created_at=NOW + timedelta(minutes=3),
    )


def committed_design_handoff(
    tmp_path: Path,
    current: ProjectRequestRevision,
    spec: ProductSpec,
    approved: ProductSpecApproval,
    design: TechnicalDesign,
) -> tuple[FileDesignRecordStore, DesignCommitCheckpoint]:
    prepared = preparation(tmp_path)
    authorization = ProjectStageAdvancer().advance_stage(
        StageAdvanceRequest(
            target=ProjectStage.PLANNING,
            preparation=prepared,
            project_request=current.request,
            product_spec=spec,
            product_approval=approved,
            technical_design=design,
        ),
        authorized_at=NOW + timedelta(minutes=3),
    )
    assert current.supersedes_sha256 is not None
    record = DesignRunRecord.create(
        run_id="run_designer_planning_001",
        project_id=current.request.project_id,
        request_id=current.request.id,
        context_id="ctx_" + "a" * 64,
        input_sha256="b" * 64,
        input_request_revision_sha256=current.supersedes_sha256,
        outcome=DesignRunOutcome.READY_FOR_PLANNING,
        technical_design=design,
        next_request_revision=current,
        planning_authorization=authorization,
        recorded_at=NOW + timedelta(minutes=3),
    )
    checkpoint = DesignCommitCheckpoint.create(record, committed_at=record.recorded_at)
    store = FileDesignRecordStore(tmp_path / "design-records")
    store.put_run(record)
    store.put_design(design)
    store.put_checkpoint(checkpoint)
    return store, checkpoint


def execution_plan(spec: ProductSpec, design: TechnicalDesign) -> ExecutionPlan:
    return ExecutionPlan.create(
        spec,
        design,
        plan_id="execution_plan_planning_001",
        version=1,
        phases=tuple(
            PlanPhaseDemand(
                id=f"phase_{role.value}_01",
                role=role,
                objective=f"Complete the {role.value} checkpoint.",
                required_capabilities=("python",),
                risk=RiskTier.NORMAL,
                minimum_brain_tier=BrainTier.STANDARD,
                checkpoints=(f"{role.value} artifact is verified",),
                critical_path=True,
            )
            for role in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)
        ),
        created_at=NOW + timedelta(minutes=4),
    )


def ready_request(request: ProjectRequest) -> ProjectRequest:
    return ProjectRequest.create(
        request_id=request.id,
        project_id=request.project_id,
        preparation_sha256=request.preparation_sha256,
        title=request.title,
        original_request=request.original_request,
        status=ProjectRequestStatus.READY_FOR_DELIVERY,
        created_at=request.created_at,
        updated_at=NOW + timedelta(minutes=5),
    )


def delivery_task(
    prepared: ProjectPreparation,
    request: ProjectRequest,
    spec: ProductSpec,
    approved: ProductSpecApproval,
    design: TechnicalDesign,
    plan: ExecutionPlan,
) -> Task:
    return derive_delivery_task(
        prepared,
        ready_request(request),
        spec,
        approved,
        design,
        plan,
        task_id="task_planning_001",
        repository=prepared.project_root,
        base_ref="main",
        max_attempts=3,
        created_at=NOW + timedelta(minutes=5),
    )
