"""Offline cross-language acceptance test for the unified Project Manager entry."""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_software_engineer.design import DesignerServiceResult
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
    ProjectRequest,
    ProjectRequestStatus,
    RequirementDesignMapping,
    RequirementPriority,
    RiskTier,
    TaskStatus,
    TechnicalDesign,
    derive_delivery_task,
)
from ai_software_engineer.orchestration import (
    BlockedResult,
    RetryClassification,
    RetryDeliveryResult,
    RetryResult,
)
from ai_software_engineer.planning import PlanningStageResult
from ai_software_engineer.product import (
    ProductDiscoveryCheckpoint,
    ProductDiscoveryOutcome,
    ProductDiscoveryResult,
    ProductDiscoveryStatus,
    ProjectRequestRevision,
)
from ai_software_engineer.project_manager import (
    FileProjectBaselineCompilationStore,
    FileProjectDeliveryCheckpointStore,
    FileProjectPreparationStore,
    PrepareProjectRequest,
    PrepareProjectResult,
    ProjectManagerSkillService,
)
from ai_software_engineer.project_manager.delivery import (
    ApproveProductSpec,
    DeliveryBackendFailure,
    DeliveryCheckpointStale,
    ProjectDeliveryCheckpointCatalog,
    ReplyToProduct,
    ResumeProjectDelivery,
    StartProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryStage,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.project_manager.dispatch import DispatchCommitRecord
from ai_software_engineer.project_manager.stages import (
    ProjectStage,
    ProjectStageAdvancer,
    StageAdvanceRequest,
)
from ai_software_engineer.project_profile import ProjectProfile
from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry
from ai_software_engineer.runtime_workspace import OrganizationWorkspace
from ai_software_engineer.spec_compiler import SpecRule, SpecRuleLayer

NOW = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


class _NoProjectRules:
    def rules_for(self, profile: ProjectProfile) -> Sequence[SpecRule]:
        del profile
        return ()


class _OfflineBackend:
    """Use the real preparation service and deterministic stage facts after it."""

    def __init__(self, platform: Path) -> None:
        organization = OrganizationWorkspace.initialize(
            platform / "organization",
            organization_id="organization_unified_e2e",
            created_at=NOW,
        )
        hard_rule = SpecRule(
            id="rule_unified_no_self_approval",
            field="safety.self_approval",
            value=False,
            layer=SpecRuleLayer.PLATFORM_HARD,
            priority=10,
            source_uri="platform://hard-safety/v1",
            source_sha256="a" * 64,
            rationale="No Agent may approve its own work.",
        )
        self._preparer = ProjectManagerSkillService(
            organization=organization,
            registry=ProjectWorkspaceRegistry(platform / "projects"),
            platform_rules=(hard_rule,),
            rule_provider=_NoProjectRules(),
            preparation_store_factory=FileProjectPreparationStore,
            baseline_recorder=FileProjectBaselineCompilationStore(),
            clock=lambda: NOW,
        )
        self.prepared: PrepareProjectResult | None = None
        self.product: ProductDiscoveryResult | None = None
        self.approval: ProductSpecApproval | None = None
        self.design: TechnicalDesign | None = None
        self.plan: ExecutionPlan | None = None
        self.ready_revision: ProjectRequestRevision | None = None
        self.dispatch: DispatchCommitRecord | None = None
        self.reconciliations = 0

    def prepare(self, project_root: str) -> PrepareProjectResult:
        self.prepared = self._preparer.prepare_project(
            PrepareProjectRequest(project_root=project_root)
        )
        return self.prepared

    def start_product(
        self,
        delivery_id: str,
        preparation: PrepareProjectResult,
        command: StartProjectDelivery,
    ) -> ProductDiscoveryResult:
        assert preparation.preparation is not None
        request = ProjectRequest.create(
            request_id=f"request_{delivery_id.removeprefix('delivery_')}",
            project_id=preparation.project_id,
            preparation_sha256=preparation.preparation.preparation_sha256,
            title=command.title,
            original_request=command.requirement,
            status=ProjectRequestStatus.PRODUCT_DISCOVERY,
            created_at=command.submitted_at,
        )
        revision = ProjectRequestRevision.create(
            request,
            revision=1,
            supersedes_sha256=None,
            recorded_at=command.submitted_at,
        )
        criterion = AcceptanceCriterion(
            id="ac_unified_delivery",
            description="The requested feature is independently delivered.",
            required=True,
            verification="Run the project test command.",
            test_ids=("test_unified_delivery",),
        )
        spec = ProductSpec.create(
            spec_id=f"product_spec_{delivery_id.removeprefix('delivery_')}",
            request_id=request.id,
            project_id=request.project_id,
            version=1,
            status=ProductSpecStatus.READY_FOR_REVIEW,
            summary=command.requirement,
            goals=("Deliver the approved requirement.",),
            requirements=(
                ProductRequirement(
                    id="req_unified_delivery",
                    statement=command.requirement,
                    priority=RequirementPriority.MUST,
                    rationale="This is the user's requested outcome.",
                    acceptance_criterion_ids=(criterion.id,),
                ),
            ),
            acceptance_criteria=(criterion,),
            created_at=command.submitted_at,
        )
        checkpoint = ProductDiscoveryCheckpoint.create(
            request_id=request.id,
            project_id=request.project_id,
            revision=1,
            previous_checkpoint_sha256=None,
            request_revision=1,
            request_sha256=request.request_sha256,
            dialogue_count=0,
            dialogue_head_sha256=None,
            current_product_spec_id=spec.id,
            current_product_spec_sha256=spec.product_spec_sha256,
            current_product_spec_version=spec.version,
            status=ProductDiscoveryStatus.WAITING_PRODUCT_APPROVAL,
            updated_at=command.submitted_at,
        )
        self.product = ProductDiscoveryResult(
            operation_id=f"run_{delivery_id.removeprefix('delivery_')}",
            outcome=ProductDiscoveryOutcome.READY_FOR_APPROVAL,
            request_revision=revision,
            checkpoint=checkpoint,
            product_spec=spec,
        )
        return self.product

    def reply_product(
        self, checkpoint: ProjectDeliveryCheckpoint, command: ReplyToProduct
    ) -> ProductDiscoveryResult:
        del checkpoint, command
        assert self.product is not None
        return self.product

    def approve_product(
        self, checkpoint: ProjectDeliveryCheckpoint, command: ApproveProductSpec
    ) -> ProductDiscoveryResult:
        del checkpoint
        assert self.product is not None and self.product.product_spec is not None
        approval = ProductSpecApproval.create(
            self.product.product_spec,
            decision=ProductApprovalDecision.APPROVED,
            operator_id="user_e2e",
            rationale=command.approval_reference,
            decided_at=command.submitted_at,
        )
        prior = self.product.request_revision
        request = ProjectRequest.create(
            request_id=prior.request.id,
            project_id=prior.request.project_id,
            preparation_sha256=prior.request.preparation_sha256,
            title=prior.request.title,
            original_request=prior.request.original_request,
            status=ProjectRequestStatus.DESIGNING,
            created_at=prior.request.created_at,
            updated_at=command.submitted_at,
        )
        revision = ProjectRequestRevision.create(
            request,
            revision=2,
            supersedes_sha256=prior.request_revision_sha256,
            recorded_at=command.submitted_at,
        )
        product_checkpoint = ProductDiscoveryCheckpoint.create(
            request_id=request.id,
            project_id=request.project_id,
            revision=2,
            previous_checkpoint_sha256=self.product.checkpoint.checkpoint_sha256,
            request_revision=revision.revision,
            request_sha256=request.request_sha256,
            dialogue_count=0,
            dialogue_head_sha256=None,
            current_product_spec_id=self.product.product_spec.id,
            current_product_spec_sha256=self.product.product_spec.product_spec_sha256,
            current_product_spec_version=1,
            current_approval_id=approval.id,
            current_approval_sha256=approval.approval_sha256,
            status=ProductDiscoveryStatus.APPROVED,
            updated_at=command.submitted_at,
        )
        assert self.prepared is not None and self.prepared.preparation is not None
        authorization = ProjectStageAdvancer().advance_stage(
            StageAdvanceRequest(
                target=ProjectStage.SOLUTION_DESIGN,
                preparation=self.prepared.preparation,
                project_request=request,
                product_spec=self.product.product_spec,
                product_approval=approval,
            ),
            authorized_at=command.submitted_at,
        )
        self.approval = approval
        self.product = ProductDiscoveryResult(
            operation_id=f"approve_{request.id}",
            outcome=ProductDiscoveryOutcome.APPROVED,
            replayed=False,
            request_revision=revision,
            checkpoint=product_checkpoint,
            product_spec=self.product.product_spec,
            approval=approval,
            authorization=authorization,
        )
        return self.product

    def run_designer(self, checkpoint: ProjectDeliveryCheckpoint) -> DesignerServiceResult:
        assert self.product is not None
        assert self.product.product_spec is not None and self.approval is not None
        spec = self.product.product_spec
        design = TechnicalDesign.create(
            spec,
            self.approval,
            design_id=f"technical_design_{checkpoint.delivery_id.removeprefix('delivery_')}",
            version=1,
            summary="Implement the approved change with isolated verification.",
            components=(
                DesignComponent(
                    id="component_unified_delivery",
                    name="Target project change",
                    responsibility="Implement the approved feature.",
                    affected_paths=("src/**", "tests/**"),
                ),
            ),
            requirement_mappings=(
                RequirementDesignMapping(
                    requirement_id="req_unified_delivery",
                    component_ids=("component_unified_delivery",),
                    approach="Use the target project's discovered conventions.",
                ),
            ),
            acceptance_mappings=(
                AcceptanceDesignMapping(
                    acceptance_criterion_id="ac_unified_delivery",
                    verification_strategy="Run the discovered project tests.",
                    test_levels=("unit",),
                ),
            ),
            implementation_steps=(
                DesignStep(
                    id="design_step_unified_delivery",
                    description="Implement and test the approved feature.",
                    component_ids=("component_unified_delivery",),
                    verification="Run the project's test command.",
                ),
            ),
            created_at=checkpoint.checkpointed_at,
        )
        self.design = design
        record = SimpleNamespace(technical_design=design)
        return DesignerServiceResult.model_construct(
            run_record=record,
            replayed=False,
            checkpoint=SimpleNamespace(),
        )

    def run_planner(self, checkpoint: ProjectDeliveryCheckpoint) -> PlanningStageResult:
        assert self.product is not None and self.product.product_spec is not None
        assert self.design is not None
        plan = ExecutionPlan.create(
            self.product.product_spec,
            self.design,
            plan_id=f"execution_plan_{checkpoint.delivery_id.removeprefix('delivery_')}",
            version=1,
            phases=tuple(
                PlanPhaseDemand(
                    id=f"phase_{role.value}_unified",
                    role=role,
                    objective=f"Complete {role.value} independently.",
                    required_capabilities=("project-delivery",),
                    risk=RiskTier.NORMAL,
                    minimum_brain_tier=BrainTier.STANDARD,
                    checkpoints=(f"{role.value} artifact is verified",),
                )
                for role in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)
            ),
            created_at=checkpoint.checkpointed_at,
        )
        prior = self.product.request_revision
        request = ProjectRequest.create(
            request_id=prior.request.id,
            project_id=prior.request.project_id,
            preparation_sha256=prior.request.preparation_sha256,
            title=prior.request.title,
            original_request=prior.request.original_request,
            status=ProjectRequestStatus.READY_FOR_DELIVERY,
            created_at=prior.request.created_at,
            updated_at=checkpoint.checkpointed_at,
        )
        ready = ProjectRequestRevision.create(
            request,
            revision=prior.revision + 1,
            supersedes_sha256=prior.request_revision_sha256,
            recorded_at=checkpoint.checkpointed_at,
        )
        self.plan = plan
        self.ready_revision = ready
        return PlanningStageResult.model_construct(
            execution_plan=plan,
            ready_request_revision=ready,
            run_record=SimpleNamespace(),
            checkpoint=SimpleNamespace(),
            replayed=False,
        )

    def commit_dispatch(self, checkpoint: ProjectDeliveryCheckpoint) -> DispatchCommitRecord:
        assert self.prepared is not None and self.prepared.preparation is not None
        assert self.product is not None and self.product.product_spec is not None
        assert self.approval is not None and self.design is not None and self.plan is not None
        assert self.ready_revision is not None
        task = derive_delivery_task(
            self.prepared.preparation,
            self.ready_revision.request,
            self.product.product_spec,
            self.approval,
            self.design,
            self.plan,
            task_id=f"task_{checkpoint.delivery_id.removeprefix('delivery_')}",
            repository=self.prepared.preparation.project_root,
            base_ref="a" * 40,
            max_attempts=1,
            created_at=checkpoint.checkpointed_at,
        )
        self.dispatch = DispatchCommitRecord.model_construct(
            id="dispatch_commit_" + "d" * 64,
            planning_preview_id="planning_preview_" + "e" * 64,
            planning_preview_sha256="f" * 64,
            dispatch_sha256="1" * 64,
            task_id=task.id,
            task=task,
        )
        return self.dispatch

    def run_delivery(self, checkpoint: ProjectDeliveryCheckpoint) -> RetryResult:
        del checkpoint
        assert self.dispatch is not None
        task = self.dispatch.task.model_copy(
            update={
                "status": TaskStatus.DONE,
                "attempts": 1,
                "updated_at": NOW + timedelta(hours=1),
            }
        )
        return RetryDeliveryResult(
            task=task,
            candidate_revision="b" * 40,
            artifact_ids=("art_plan_e2e", "art_impl_e2e", "art_qa_e2e", "art_review_e2e"),
            context_manifest_ids=tuple(
                f"ctx_{character * 64}" for character in ("1", "2", "3", "4")
            ),
            run_ids=("run_plan_e2e", "run_coder_e2e", "run_qa_e2e", "run_review_e2e"),
            event_ids=tuple(f"evt_unified_{index}" for index in range(5)),
        )

    def reconcile(self, checkpoint: ProjectDeliveryCheckpoint) -> None:
        checkpoint.validate_integrity()
        self.reconciliations += 1


class _InterruptedProductBackend(_OfflineBackend):
    def __init__(self, platform: Path) -> None:
        super().__init__(platform)
        self.interrupted = False
        self.resumed_start: StartProjectDelivery | None = None

    def start_product(
        self,
        delivery_id: str,
        preparation: PrepareProjectResult,
        command: StartProjectDelivery,
    ) -> ProductDiscoveryResult:
        if not self.interrupted:
            self.interrupted = True
            raise RuntimeError("simulated process interruption")
        self.resumed_start = command
        return super().start_product(delivery_id, preparation, command)


class _BlockedDeliveryBackend(_OfflineBackend):
    def run_delivery(self, checkpoint: ProjectDeliveryCheckpoint) -> BlockedResult:
        del checkpoint
        assert self.dispatch is not None
        task = self.dispatch.task.model_copy(
            update={
                "status": TaskStatus.BLOCKED,
                "attempts": 1,
                "updated_at": NOW + timedelta(hours=1),
            }
        )
        return BlockedResult(
            task=task,
            classification=RetryClassification.BUDGET_EXHAUSTED,
            reason="delivery retry budget exhausted",
            attempt=1,
            artifact_ids=("art_failure_evidence",),
            event_ids=("evt_delivery_blocked",),
        )


class _InvalidPlannerBackend(_OfflineBackend):
    def run_planner(self, checkpoint: ProjectDeliveryCheckpoint) -> PlanningStageResult:
        del checkpoint
        raise DeliveryBackendFailure(
            DeliveryFailureCode.INVALID_AGENT_OUTPUT,
            "Planner output failed its typed contract",
        )


def _copy_fixture(tmp_path: Path, language: str) -> Path:
    source = Path(__file__).parents[2] / "fixtures" / "target-projects" / language
    target = tmp_path / "target"
    shutil.copytree(source, target)
    return target


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize("language", ("python", "java", "cpp"))
def test_directory_and_requirement_reach_done_without_polluting_target(
    tmp_path: Path, language: str
) -> None:
    project = _copy_fixture(tmp_path, language)
    before = _files(project)
    platform = tmp_path / "platform"
    backend = _OfflineBackend(platform)
    service = UnifiedProjectEntryService(
        backend=backend,
        catalog=ProjectDeliveryCheckpointCatalog(platform / "projects"),
    )
    started = service.start(
        StartProjectDelivery(
            project_root=str(project.resolve()),
            requirement="Add a deterministic greeting.",
            submitted_at=NOW,
        )
    )

    assert started.checkpoint.stage.value == "WAITING_PRODUCT_APPROVAL"
    completed = service.approve(
        ApproveProductSpec(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            approval_reference="e2e-user-confirmation",
            submitted_at=NOW + timedelta(minutes=1),
        )
    )

    assert completed.checkpoint.stage.value == "DONE"
    assert completed.checkpoint.task_status is TaskStatus.DONE
    assert completed.checkpoint.sequence == 8
    assert _files(project) == before
    reopened = UnifiedProjectEntryService(
        backend=backend,
        catalog=ProjectDeliveryCheckpointCatalog(platform / "projects"),
    ).status(completed.checkpoint.delivery_id)
    assert reopened.checkpoint == completed.checkpoint
    assert backend.reconciliations >= 1


def test_resume_replays_durable_intake_after_product_start_interruption(
    tmp_path: Path,
) -> None:
    project = _copy_fixture(tmp_path, "python")
    platform = tmp_path / "platform"
    backend = _InterruptedProductBackend(platform)
    service = UnifiedProjectEntryService(
        backend=backend,
        catalog=ProjectDeliveryCheckpointCatalog(platform / "projects"),
    )
    started_at = NOW - timedelta(minutes=5)

    with pytest.raises(RuntimeError, match="simulated process interruption"):
        service.start(
            StartProjectDelivery(
                project_root=str(project.resolve()),
                requirement="Add a durable greeting.",
                title="Durable greeting",
                submitted_at=started_at,
            )
        )

    checkpoint = next(
        path.parent.name
        for path in (platform / "projects").glob(
            "*/state/project-deliveries/delivery_*/0000000002.json"
        )
    )
    resumed = service.resume(ResumeProjectDelivery(delivery_id=checkpoint, submitted_at=NOW))

    assert resumed.checkpoint.stage is DeliveryStage.WAITING_PRODUCT_APPROVAL
    assert backend.resumed_start is not None
    assert backend.resumed_start.submitted_at == started_at
    assert backend.resumed_start.title == "Durable greeting"


def test_repeated_start_recovers_intake_published_before_first_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _copy_fixture(tmp_path, "python")
    platform = tmp_path / "platform"
    backend = _OfflineBackend(platform)
    service = UnifiedProjectEntryService(
        backend=backend,
        catalog=ProjectDeliveryCheckpointCatalog(platform / "projects"),
    )
    original_put = FileProjectDeliveryCheckpointStore.put

    def interrupt_first_checkpoint(
        _store: FileProjectDeliveryCheckpointStore,
        _checkpoint: ProjectDeliveryCheckpoint,
    ) -> ProjectDeliveryCheckpoint:
        raise RuntimeError("simulated checkpoint interruption")

    monkeypatch.setattr(FileProjectDeliveryCheckpointStore, "put", interrupt_first_checkpoint)
    started_at = NOW - timedelta(minutes=10)
    command = StartProjectDelivery(
        project_root=str(project.resolve()),
        requirement="Add a recoverable greeting.",
        title="Recoverable greeting",
        submitted_at=started_at,
    )
    with pytest.raises(RuntimeError, match="simulated checkpoint interruption"):
        service.start(command)

    monkeypatch.setattr(FileProjectDeliveryCheckpointStore, "put", original_put)
    recovered = service.start(command.model_copy(update={"submitted_at": NOW}))

    assert recovered.checkpoint.stage is DeliveryStage.WAITING_PRODUCT_APPROVAL
    assert recovered.product is not None
    assert recovered.product.request_revision.request.created_at == started_at


def test_stale_approval_has_zero_effects(tmp_path: Path) -> None:
    project = _copy_fixture(tmp_path, "python")
    platform = tmp_path / "platform"
    backend = _OfflineBackend(platform)
    catalog = ProjectDeliveryCheckpointCatalog(platform / "projects")
    service = UnifiedProjectEntryService(backend=backend, catalog=catalog)
    started = service.start(
        StartProjectDelivery(
            project_root=str(project.resolve()),
            requirement="Add a fenced greeting.",
            submitted_at=NOW,
        )
    )
    store = catalog.for_delivery(started.checkpoint.delivery_id)
    before = store.list(started.checkpoint.delivery_id)

    with pytest.raises(DeliveryCheckpointStale):
        service.approve(
            ApproveProductSpec(
                delivery_id=started.checkpoint.delivery_id,
                expected_checkpoint_sha256="0" * 64,
                approval_reference="stale-user-confirmation",
                submitted_at=NOW + timedelta(minutes=1),
            )
        )

    assert store.list(started.checkpoint.delivery_id) == before
    assert backend.approval is None


def test_delivery_budget_exhaustion_returns_stable_blocked_checkpoint(
    tmp_path: Path,
) -> None:
    project = _copy_fixture(tmp_path, "cpp")
    platform = tmp_path / "platform"
    backend = _BlockedDeliveryBackend(platform)
    service = UnifiedProjectEntryService(
        backend=backend,
        catalog=ProjectDeliveryCheckpointCatalog(platform / "projects"),
    )
    started = service.start(
        StartProjectDelivery(
            project_root=str(project.resolve()),
            requirement="Add a bounded greeting.",
            submitted_at=NOW,
        )
    )

    blocked = service.approve(
        ApproveProductSpec(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            approval_reference="e2e-blocked-confirmation",
            submitted_at=NOW + timedelta(minutes=1),
        )
    )

    assert blocked.checkpoint.stage is DeliveryStage.BLOCKED
    assert blocked.checkpoint.task_status is TaskStatus.BLOCKED
    assert blocked.checkpoint.failure_code is DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED
    assert isinstance(blocked.delivery, BlockedResult)
    assert blocked.delivery.reason == "delivery retry budget exhausted"
    reopened = service.status(blocked.checkpoint.delivery_id)
    assert reopened.checkpoint == blocked.checkpoint


def test_classified_invalid_output_becomes_a_safe_checkpoint(tmp_path: Path) -> None:
    project = _copy_fixture(tmp_path, "java")
    platform = tmp_path / "platform"
    backend = _InvalidPlannerBackend(platform)
    service = UnifiedProjectEntryService(
        backend=backend,
        catalog=ProjectDeliveryCheckpointCatalog(platform / "projects"),
    )
    started = service.start(
        StartProjectDelivery(
            project_root=str(project.resolve()),
            requirement="Add a validated greeting.",
            submitted_at=NOW,
        )
    )

    blocked = service.approve(
        ApproveProductSpec(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            approval_reference="e2e-invalid-output-confirmation",
            submitted_at=NOW + timedelta(minutes=1),
        )
    )

    assert blocked.checkpoint.stage is DeliveryStage.BLOCKED
    assert blocked.checkpoint.failure_code is DeliveryFailureCode.INVALID_AGENT_OUTPUT
    assert blocked.checkpoint.failure_summary == "Planner output failed its typed contract"
