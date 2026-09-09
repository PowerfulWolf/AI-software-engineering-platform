"""Concrete Project Manager backend for the organization-owned production team."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, TypeVar, cast

from ai_software_engineer.agents import (
    CodexCliStructuredModelClient,
    FallbackStructuredModelClient,
    ResponsesStructuredModelClient,
    StoredContextResolver,
    StructuredModelClient,
    StructuredModelRoute,
)
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import (
    ModelProviderKind,
    ProductionConfig,
    ProductionConfigError,
)
from ai_software_engineer.context import ContextBudget, ContextSource, FileContextStore
from ai_software_engineer.context.profile import project_profile_context
from ai_software_engineer.design import (
    DesignerService,
    DesignerServiceResult,
    FileDesignRecordStore,
    RunDesignerCommand,
)
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentPermissions,
    AgentProfile,
    AgentRole,
    Artifact,
    ArtifactKind,
    ExecutionPlan,
    ImplementationReportArtifact,
    ModelPolicy,
    NetworkAccess,
    PlanArtifact,
    ProductApprovalDecision,
    ProductSpec,
    QaReportArtifact,
    QaReportStatus,
    ReviewReportArtifact,
    ReviewVerdict,
    RiskTier,
    TaskConstraints,
    TaskStatus,
    TechnicalDesign,
    WorkItem,
    WorkItemStatus,
    derive_delivery_task,
)
from ai_software_engineer.orchestration import (
    BlockedResult,
    DispatchTaskMaterializer,
    ExecutionPlanAgentAdapter,
    RetryClassification,
    RetryDeliveryResult,
    RetryResult,
)
from ai_software_engineer.planning import (
    FileExecutionPlanStore,
    PlannerContextBuilder,
    PlannerStageService,
    PlanningPreviewService,
    PlanningStageResult,
    ProduceExecutionPlanCommand,
)
from ai_software_engineer.product import (
    FileProductRecordStore,
    HumanProductDecisionCommand,
    HumanProductDecisionVerifier,
    ProductDiscoveryResult,
    ProductDiscoveryService,
    RecordHumanMessageCommand,
    RunProductAgentCommand,
    StartProductDiscoveryCommand,
    VerifiedHumanProductDecision,
)
from ai_software_engineer.project_manager.baseline import (
    FileProjectBaselineCompilationStore,
    ProjectSpecBaseline,
)
from ai_software_engineer.project_manager.delivery import (
    ApproveProductSpec,
    DeliveryBackendFailure,
    DeliveryFailureSnapshot,
    ReplyToProduct,
    StartProjectDelivery,
)
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryFailureCode,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
    checkpoint_sha256_is_ancestor,
)
from ai_software_engineer.project_manager.dispatch import (
    CommitDispatchRequest,
    ContinuationDispatchRecord,
    DeliveryAllocation,
    DispatchCommitRecord,
    DispatchError,
    DispatchRejected,
    DispatchWorkforceSnapshot,
    ProjectManagerDispatchService,
)
from ai_software_engineer.project_manager.mysql_dispatch_authority import (
    MySqlDispatchAuthority,
)
from ai_software_engineer.project_manager.organization_team import (
    DELIVERY_CAPABILITIES,
    production_organization_team,
)
from ai_software_engineer.project_manager.preparation import (
    PrepareProjectRequest,
    PrepareProjectResult,
    PrepareProjectStatus,
    ProjectManagerSkillService,
    ProjectRuleProvider,
)
from ai_software_engineer.project_manager.production_agents import (
    StructuredDesignerAgentAdapter,
    StructuredPlannerAgentAdapter,
    StructuredProductAgentAdapter,
)
from ai_software_engineer.project_manager.production_delivery import (
    DeliveryRouteAdapterFactory,
    DispatchDeliveryAgentAdapter,
)
from ai_software_engineer.project_manager.stages import (
    ProjectStage,
    ProjectStageAdvancer,
    StageAdvanceAuthorization,
    StageAdvanceRequest,
)
from ai_software_engineer.project_manager.store import FileProjectPreparationStore
from ai_software_engineer.project_profile import BuildSystem, ProjectProfile
from ai_software_engineer.project_workspace import ProjectWorkspace, ProjectWorkspaceRegistry
from ai_software_engineer.runtime import (
    RuntimeConfig,
    RuntimePaths,
    RuntimePersistence,
    RuntimeSession,
)
from ai_software_engineer.runtime_workspace import (
    FileOrganizationWorkforceStore,
    OrganizationWorkspace,
    load_project_profile,
)
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.spec_compiler import SpecRule
from ai_software_engineer.store import MySqlTaskRepository

Clock = Callable[[], datetime]
ResultT = TypeVar("ResultT")
PRODUCTION_DELIVERY_CONTEXT_BUDGET = ContextBudget(
    max_input_tokens=32_000, reserved_output_tokens=4_000
)
PRODUCTION_DELIVERY_MAX_ATTEMPTS = 3
_ALL_CAPABILITIES = DELIVERY_CAPABILITIES
_ROLE_INPUTS: dict[AgentRole, tuple[ArtifactKind, ...]] = {
    AgentRole.ORCHESTRATOR: (),
    AgentRole.CODER: (
        ArtifactKind.PLAN,
        ArtifactKind.CODER_PROGRESS,
        ArtifactKind.QA_REPORT,
        ArtifactKind.REVIEW_REPORT,
    ),
    AgentRole.QA: (ArtifactKind.PLAN, ArtifactKind.IMPLEMENTATION_REPORT),
    AgentRole.REVIEWER: (
        ArtifactKind.PLAN,
        ArtifactKind.IMPLEMENTATION_REPORT,
        ArtifactKind.QA_REPORT,
    ),
}
_ROLE_OUTPUTS = {
    AgentRole.ORCHESTRATOR: (ArtifactKind.PLAN,),
    AgentRole.CODER: (ArtifactKind.CODER_PROGRESS, ArtifactKind.IMPLEMENTATION_REPORT),
    AgentRole.QA: (ArtifactKind.QA_REPORT,),
    AgentRole.REVIEWER: (ArtifactKind.REVIEW_REPORT,),
}


class StructuredClientFactory(Protocol):
    def for_project(self, project_root: Path) -> StructuredModelClient: ...


class ConfiguredStructuredClientFactory:
    """Build the configured upstream route chain without persisting credentials."""

    def __init__(
        self,
        config: ProductionConfig,
        environment: Mapping[str, str],
    ) -> None:
        self._config = config
        self._environment = dict(environment)

    def for_project(self, project_root: Path) -> StructuredModelClient:
        if not self._config.live_model_execution:
            raise ProductionConfigError(
                "live_model_execution is disabled in the production configuration"
            )
        routes: list[StructuredModelRoute] = []
        for route in self._config.enabled_routes():
            if route.kind is ModelProviderKind.CODEX_CLI:
                client: StructuredModelClient = CodexCliStructuredModelClient(
                    project_root=project_root,
                    model=route.model,
                    executable=self._config.codex_executable,
                    reasoning_effort=route.reasoning_effort,
                    environment=self._environment,
                )
            else:
                assert route.api_key_env is not None and route.endpoint is not None
                api_key = self._environment.get(route.api_key_env)
                if not api_key:
                    raise ProductionConfigError(
                        "enabled Responses route is missing API key environment variable: "
                        f"{route.api_key_env}"
                    )
                client = ResponsesStructuredModelClient(
                    endpoint=route.endpoint,
                    api_key=api_key,
                    model=route.model,
                )
            routes.append(
                StructuredModelRoute(
                    provider=route.provider,
                    model=route.model,
                    client=client,
                )
            )
        return FallbackStructuredModelClient(tuple(routes))


class _NoProjectRules(ProjectRuleProvider):
    def rules_for(self, profile: ProjectProfile) -> Sequence[SpecRule]:
        del profile
        return ()


class _CliHumanDecisionVerifier:
    """Treat the explicit ``ase project approve`` command as the trusted boundary."""

    def verify(self, command: HumanProductDecisionCommand) -> VerifiedHumanProductDecision:
        return VerifiedHumanProductDecision(
            approval_reference=command.approval_reference,
            request_id=command.request_id,
            product_spec_id=command.product_spec_id,
            product_spec_sha256=command.product_spec_sha256,
            decision=ProductApprovalDecision.APPROVED,
            operator_id="cli-user",
            rationale=command.approval_reference,
            decided_at=command.submitted_at,
        )


@dataclass(frozen=True, slots=True)
class _ProjectFacts:
    preparation: PrepareProjectResult
    workspace: ProjectWorkspace
    profile: ProjectProfile
    baseline: ProjectSpecBaseline
    product: FileProductRecordStore
    design: FileDesignRecordStore
    planning: FileExecutionPlanStore


class ProductionProjectDeliveryBackend:
    """Compose native stage services behind the unified Project Manager facade."""

    def __init__(
        self,
        *,
        config: ProductionConfig,
        environment: Mapping[str, str],
        organization: OrganizationWorkspace,
        registry: ProjectWorkspaceRegistry,
        platform_rules: Sequence[SpecRule],
        structured_clients: StructuredClientFactory | None = None,
        delivery_route_adapters: DeliveryRouteAdapterFactory | None = None,
        clock: Clock | None = None,
        preparation_guard: Callable[[], None] | None = None,
        delivery_context_sources: tuple[ContextSource, ...] = (),
        human_decision_verifier: HumanProductDecisionVerifier | None = None,
    ) -> None:
        self._config = config
        self._environment = dict(environment)
        self._organization = organization
        self._registry = registry
        self._clock = clock or (lambda: datetime.now(UTC))
        self._preparation_guard = preparation_guard
        self._delivery_context_sources = delivery_context_sources
        self._human_decision_verifier = human_decision_verifier or _CliHumanDecisionVerifier()
        self._baseline_store = FileProjectBaselineCompilationStore()
        self._preparer = ProjectManagerSkillService(
            organization=organization,
            registry=registry,
            platform_rules=platform_rules,
            rule_provider=_NoProjectRules(),
            preparation_store_factory=FileProjectPreparationStore,
            baseline_recorder=self._baseline_store,
            clock=self._clock,
            versioned_preparations=True,
        )
        self._structured_clients = structured_clients or ConfiguredStructuredClientFactory(
            config, self._environment
        )
        self._delivery_route_adapters = delivery_route_adapters
        self._dsn = config.require_mysql_dsn(self._environment)

    def prepare(self, project_root: str) -> PrepareProjectResult:
        if self._preparation_guard is not None:
            self._preparation_guard()
        return self._preparer.prepare_project(PrepareProjectRequest(project_root=project_root))

    def prepared_context(self, preparation: PrepareProjectResult) -> tuple[ContextSource, ...]:
        """Export verified, readable preparation facts for a joint Product conversation."""
        facts = self._facts(preparation)
        return (
            project_profile_context(facts.profile),
            ContextSource(
                source_id="project.baseline",
                uri=f"baseline://{facts.profile.project_id}",
                content=json.dumps(facts.baseline.to_wire(), sort_keys=True),
                required=True,
            ),
        )

    def start_product(
        self,
        delivery_id: str,
        preparation: PrepareProjectResult,
        command: StartProjectDelivery,
    ) -> ProductDiscoveryResult:
        def execute() -> ProductDiscoveryResult:
            facts = self._facts(preparation)
            service = self._product_service(facts)
            suffix = _suffix(delivery_id)
            started = service.start(
                StartProductDiscoveryCommand(
                    operation_id=f"start_{suffix}",
                    request_id=f"request_{suffix}",
                    title=command.title,
                    initial_requirement=command.requirement,
                    submitted_at=command.submitted_at,
                )
            )
            return service.run_product(
                RunProductAgentCommand(
                    run_id=f"run_product_{suffix}",
                    request_id=started.checkpoint.request_id,
                    expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
                    submitted_at=command.submitted_at,
                )
            )

        return self._guard("Product", execute)

    def reply_product(
        self,
        checkpoint: ProjectDeliveryCheckpoint,
        command: ReplyToProduct,
    ) -> ProductDiscoveryResult:
        def execute() -> ProductDiscoveryResult:
            facts = self._facts_for_checkpoint(checkpoint)
            service = self._product_service(facts)
            assert checkpoint.request_id is not None
            sequence = checkpoint.sequence
            recorded = service.record_human_message(
                RecordHumanMessageCommand(
                    operation_id=f"reply_{_suffix(checkpoint.delivery_id)}_{sequence}",
                    request_id=checkpoint.request_id,
                    expected_checkpoint_sha256=cast(str, checkpoint.product_checkpoint_sha256),
                    content=command.message,
                    submitted_at=command.submitted_at,
                )
            )
            return service.run_product(
                RunProductAgentCommand(
                    run_id=f"run_product_reply_{_suffix(checkpoint.delivery_id)}_{sequence}",
                    request_id=checkpoint.request_id,
                    expected_checkpoint_sha256=recorded.checkpoint.checkpoint_sha256,
                    submitted_at=command.submitted_at,
                )
            )

        return self._guard("Product reply", execute)

    def approve_product(
        self,
        checkpoint: ProjectDeliveryCheckpoint,
        command: ApproveProductSpec,
    ) -> ProductDiscoveryResult:
        def execute() -> ProductDiscoveryResult:
            facts = self._facts_for_checkpoint(checkpoint)
            assert checkpoint.request_id is not None
            assert checkpoint.product_spec_id is not None
            assert checkpoint.product_spec_sha256 is not None
            return self._product_service(facts).decide_as_human(
                HumanProductDecisionCommand(
                    operation_id=_approval_operation_id(checkpoint.delivery_id),
                    request_id=checkpoint.request_id,
                    expected_checkpoint_sha256=cast(str, checkpoint.product_checkpoint_sha256),
                    product_spec_id=checkpoint.product_spec_id,
                    product_spec_sha256=checkpoint.product_spec_sha256,
                    approval_reference=command.approval_reference,
                    submitted_at=command.submitted_at,
                )
            )

        return self._guard("Product approval", execute)

    def run_designer(
        self,
        checkpoint: ProjectDeliveryCheckpoint,
    ) -> DesignerServiceResult:
        def execute() -> DesignerServiceResult:
            facts = self._facts_for_checkpoint(checkpoint)
            request_id = cast(str, checkpoint.request_id)
            revision = facts.product.current_request_revision(request_id)
            spec = facts.product.find_product_spec(cast(str, checkpoint.product_spec_id))
            approval = facts.product.find_approval(cast(str, checkpoint.approval_id))
            if spec is None or approval is None:
                raise ValueError("approved Product facts are missing")
            authorization = self._product_authorization(facts, checkpoint.delivery_id)
            service = DesignerService(
                design_store=facts.design,
                product_store=facts.product,
                adapter=StructuredDesignerAgentAdapter(
                    self._structured_clients.for_project(facts.workspace.project_root)
                ),
                stage_advancer=self._preparer,
            )
            preparation = facts.preparation.preparation
            assert preparation is not None
            return service.run(
                RunDesignerCommand(
                    run_id=_designer_run_id(checkpoint.delivery_id),
                    preparation=preparation,
                    project_profile=facts.profile,
                    project_baseline=facts.baseline,
                    request_revision=revision,
                    product_spec=spec,
                    product_approval=approval,
                    solution_design_authorization=authorization,
                    submitted_at=checkpoint.checkpointed_at,
                )
            )

        return self._guard("Designer", execute)

    def run_planner(self, checkpoint: ProjectDeliveryCheckpoint) -> PlanningStageResult:
        def execute() -> PlanningStageResult:
            facts = self._facts_for_checkpoint(checkpoint)
            design_run = facts.design.get_run(_designer_run_id(checkpoint.delivery_id))
            design_checkpoint = facts.design.get_checkpoint(
                _designer_run_id(checkpoint.delivery_id)
            )
            design = design_run.technical_design
            revision = design_run.next_request_revision
            authorization = design_run.planning_authorization
            spec = facts.product.find_product_spec(cast(str, checkpoint.product_spec_id))
            approval = facts.product.find_approval(cast(str, checkpoint.approval_id))
            if design is None or revision is None or authorization is None:
                raise ValueError("Planner design handoff is incomplete")
            if spec is None or approval is None:
                raise ValueError("Planner Product handoff is incomplete")
            service = PlannerStageService(
                context_builder=PlannerContextBuilder(),
                adapter=StructuredPlannerAgentAdapter(
                    self._structured_clients.for_project(facts.workspace.project_root)
                ),
                execution_plans=facts.planning,
                request_revisions=facts.product,
                design_records=facts.design,
            )
            return service.produce(
                ProduceExecutionPlanCommand(
                    run_id=_planner_run_id(checkpoint.delivery_id),
                    current_request_revision=revision,
                    product_spec=spec,
                    product_approval=approval,
                    technical_design=design,
                    design_checkpoint=design_checkpoint,
                    planning_authorization=authorization,
                    expected_execution_plan_version=1,
                    transitioned_at=checkpoint.checkpointed_at,
                )
            )

        return self._guard("Planner", execute)

    def commit_dispatch(self, checkpoint: ProjectDeliveryCheckpoint) -> DispatchCommitRecord:
        return self._guard("Dispatch", lambda: self._commit_dispatch(checkpoint))

    def run_delivery(self, checkpoint: ProjectDeliveryCheckpoint) -> RetryResult:
        try:
            return self._guard("Delivery", lambda: self._run_delivery(checkpoint))
        except DeliveryBackendFailure as error:
            if checkpoint.task_id is None:
                raise
            repository = MySqlTaskRepository(self._dsn)
            try:
                task = repository.get(checkpoint.task_id)
                events = repository.list_events(task.id)
                revision = repository.current_revision(task.id)
                if (
                    revision != len(events)
                    or repository.get(task.id) != task
                    or repository.current_revision(task.id) != revision
                    or (events and events[-1].to_status is not task.status)
                ):
                    raise ValueError("failure snapshot event revision mismatch")
                candidate = next(
                    (
                        event.source_revision
                        for event in reversed(events)
                        if event.reason == "candidate_ready"
                    ),
                    None,
                )
                snapshot = DeliveryFailureSnapshot(
                    task=task,
                    task_revision=revision,
                    candidate_revision=candidate,
                )
            finally:
                repository.close()
            raise DeliveryBackendFailure(
                error.code,
                error.safe_summary,
                snapshot=snapshot,
            ) from error

    def reconcile(self, checkpoint: ProjectDeliveryCheckpoint) -> None:
        def execute() -> None:
            facts = self._facts_for_checkpoint(checkpoint)
            if checkpoint.product_checkpoint_sha256 is not None:
                current = facts.product.current_checkpoint(cast(str, checkpoint.request_id))
                if current.checkpoint_sha256 != checkpoint.product_checkpoint_sha256:
                    raise ValueError("Product checkpoint drifted")
            if checkpoint.technical_design_id is not None:
                run = facts.design.get_run(_designer_run_id(checkpoint.delivery_id))
                if (
                    run.technical_design is None
                    or run.technical_design.technical_design_sha256
                    != checkpoint.technical_design_sha256
                ):
                    raise ValueError("Designer checkpoint drifted")
            if checkpoint.execution_plan_id is not None:
                plan = facts.planning.get_execution_plan(checkpoint.execution_plan_id)
                if plan.execution_plan_sha256 != checkpoint.execution_plan_sha256:
                    raise ValueError("Planner checkpoint drifted")
            if checkpoint.dispatch_commit_id is not None:
                authority = MySqlDispatchAuthority(
                    self._dsn,
                    request_revisions=facts.product,
                    planner_records=facts.planning,
                )
                commit = authority.get_allocation(checkpoint.dispatch_commit_id)
                if commit.dispatch_sha256 != checkpoint.dispatch_commit_sha256:
                    raise ValueError("Dispatch checkpoint drifted")
            if checkpoint.verification_plan_sha256 is not None:
                from ai_software_engineer.recovery.models import RecoveryScope
                from ai_software_engineer.recovery.store import FileRecoveryStore

                scope = RecoveryScope(
                    company_id=self._config.company_id,
                    project_id=checkpoint.project_id,
                    project_root=checkpoint.project_root,
                    delivery_id=checkpoint.delivery_id,
                )
                store = FileRecoveryStore(
                    facts.workspace.root
                    / "state"
                    / f"candidate-verification-{checkpoint.delivery_id}",
                    scope=scope,
                )
                verification_plan = store.get_verification_plan(checkpoint.verification_plan_sha256)
                completion = store.get_verification_completion(verification_plan.plan_sha256)
                journal = FileProjectDeliveryCheckpointStore(
                    facts.workspace.root / "state/project-deliveries",
                    read_only=True,
                )
                history = journal.list(checkpoint.delivery_id)
                if len(history) < 2 or history[-1] != checkpoint:
                    raise ValueError("accepted candidate verification history drifted")
                source = history[-2]
                if (
                    not completion.verified
                    or completion.completion_sha256 != checkpoint.verification_completion_sha256
                    or not checkpoint_sha256_is_ancestor(
                        history[:-1], verification_plan.native_checkpoint_sha256
                    )
                    or checkpoint.previous_checkpoint_sha256 != source.checkpoint_sha256
                    or verification_plan.inputs.task_id != checkpoint.task_id
                    or verification_plan.inputs.candidate_revision != checkpoint.candidate_revision
                ):
                    raise ValueError("accepted candidate verification drifted")

        self._guard("Reconciliation", execute)

    def _commit_dispatch(self, checkpoint: ProjectDeliveryCheckpoint) -> DispatchCommitRecord:
        facts = self._facts_for_checkpoint(checkpoint)
        preparation = facts.preparation.preparation
        assert preparation is not None
        planner_run = facts.planning.get_run(_planner_run_id(checkpoint.delivery_id))
        planner_checkpoint = facts.planning.get_checkpoint(_planner_run_id(checkpoint.delivery_id))
        plan = planner_run.execution_plan
        ready_revision = planner_run.ready_request_revision
        design_run = facts.design.get_run(_designer_run_id(checkpoint.delivery_id))
        design = design_run.technical_design
        spec = facts.product.find_product_spec(cast(str, checkpoint.product_spec_id))
        approval = facts.product.find_approval(cast(str, checkpoint.approval_id))
        if plan is None or ready_revision is None or design is None:
            raise ValueError("Dispatch design/planning handoff is incomplete")
        if spec is None or approval is None:
            raise ValueError("Dispatch Product handoff is incomplete")
        task_id = f"task_{_suffix(checkpoint.delivery_id)}"
        base_ref = _clean_git_head(facts.workspace.project_root)
        constraints = _task_constraints(facts.profile, design)
        task = derive_delivery_task(
            preparation,
            ready_revision.request,
            spec,
            approval,
            design,
            plan,
            task_id=task_id,
            repository=str(facts.workspace.project_root),
            base_ref=base_ref,
            max_attempts=PRODUCTION_DELIVERY_MAX_ATTEMPTS,
            created_at=checkpoint.checkpointed_at,
            constraints=constraints,
            owner="project-manager",
            labels=("ai-delivery", "serial-v0.1"),
        )
        risk = _maximum_risk(phase.risk for phase in plan.phases)
        work_item = WorkItem(
            task_id=task.id,
            project_id=preparation.project_id,
            status=WorkItemStatus.READY,
            priority=500,
            risk=risk,
            required_capabilities=tuple(
                sorted(
                    {
                        capability
                        for phase in plan.phases
                        for capability in phase.required_capabilities
                    }
                )
            ),
            created_at=checkpoint.checkpointed_at,
            updated_at=checkpoint.checkpointed_at,
        )
        agents, policy = self._workforce()
        workforce_store = FileOrganizationWorkforceStore(self._organization)
        policy = workforce_store.put_policy(policy, versioned=True)
        agents = tuple(workforce_store.put_agent(agent) for agent in agents)
        snapshot = DispatchWorkforceSnapshot.create(
            project_id=preparation.project_id,
            task_id=task.id,
            work_item=work_item,
            agents=agents,
            model_policies=(policy,),
        )
        authority = MySqlDispatchAuthority(
            self._dsn,
            request_revisions=facts.product,
            planner_records=facts.planning,
        )
        authority.seed_snapshot(snapshot)
        current_snapshot = authority.current_snapshot(
            project_id=preparation.project_id,
            task_id=task.id,
        )
        router = ModelRouter(
            route_context_capacities={
                (policy.routes[0].provider, policy.routes[0].model): 2_000_000
            }
        )
        scheduler = PortfolioScheduler()
        preview = PlanningPreviewService(
            scheduler=scheduler,
            model_router=router,
        ).preview(
            task=task,
            work_item=current_snapshot.work_item,
            execution_plan=plan,
            agents=current_snapshot.agents,
            active_leases=current_snapshot.active_leases,
            assignments=current_snapshot.assignments,
            policies=current_snapshot.model_policies,
            previewed_at=checkpoint.checkpointed_at,
        )
        stage_authorization = ProjectStageAdvancer().advance_stage(
            StageAdvanceRequest(
                target=ProjectStage.DELIVERY_DISPATCH,
                preparation=preparation,
                project_request=ready_revision.request,
                product_spec=spec,
                product_approval=approval,
                technical_design=design,
                execution_plan=plan,
            ),
            authorized_at=checkpoint.checkpointed_at,
        )
        request = CommitDispatchRequest(
            preparation=preparation,
            project_request=ready_revision.request,
            product_spec=spec,
            product_approval=approval,
            technical_design=design,
            execution_plan=plan,
            ready_request_revision=ready_revision,
            planner_run_record=planner_run,
            planner_checkpoint=planner_checkpoint,
            stage_authorization=stage_authorization,
            planning_preview=preview,
            task_id=task.id,
            repository=str(facts.workspace.project_root),
            base_ref=base_ref,
            max_attempts=PRODUCTION_DELIVERY_MAX_ATTEMPTS,
            task_created_at=checkpoint.checkpointed_at,
            committed_at=checkpoint.checkpointed_at + timedelta(seconds=1),
            constraints=constraints,
            owner="project-manager",
            labels=("ai-delivery", "serial-v0.1"),
        )
        return ProjectManagerDispatchService(
            scheduler=scheduler,
            model_router=router,
            authority=authority,
            request_revisions=facts.product,
            planner_records=facts.planning,
        ).commit_dispatch(request)

    def _run_delivery(self, checkpoint: ProjectDeliveryCheckpoint) -> RetryResult:
        facts = self._facts_for_checkpoint(checkpoint)
        authority = MySqlDispatchAuthority(
            self._dsn,
            request_revisions=facts.product,
            planner_records=facts.planning,
        )
        dispatch = authority.get_allocation(cast(str, checkpoint.dispatch_commit_id))
        spec = facts.product.find_product_spec(cast(str, checkpoint.product_spec_id))
        design = facts.design.get_run(_designer_run_id(checkpoint.delivery_id)).technical_design
        if spec is None or design is None:
            raise ValueError("delivery plan inputs are missing")
        extra_context = (
            _continuation_context(self._config, facts, dispatch)
            if isinstance(dispatch, ContinuationDispatchRecord)
            else ()
        )
        result = self.run_prepared_allocation(
            dispatch,
            facts.preparation,
            spec,
            design,
            facts.planning.get_execution_plan(dispatch.execution_plan_id),
            extra_context=extra_context,
        )
        return result

    def run_prepared_allocation(
        self,
        dispatch: DeliveryAllocation,
        preparation: PrepareProjectResult,
        spec: ProductSpec,
        design: TechnicalDesign,
        plan: ExecutionPlan,
        *,
        route_adapters: DeliveryRouteAdapterFactory | None = None,
        extra_context: tuple[ContextSource, ...] = (),
    ) -> RetryResult:
        """Trusted composition after native or recovery allocation authorization."""
        facts = self._facts(preparation)
        if dispatch.project_id != facts.workspace.project_id:
            raise ValueError("allocation and preparation project mismatch")
        paths = _runtime_paths(facts.workspace)
        repository = MySqlTaskRepository(self._dsn)
        try:
            DispatchTaskMaterializer(repository).materialize(dispatch)
            terminal = _terminal_delivery_result(
                repository,
                FileArtifactStore(paths.artifacts),
                dispatch.task_id,
            )
        finally:
            repository.close()
        if terminal is not None:
            return terminal
        definitions = _agent_definitions(dispatch, _task_commands(facts.profile))
        plan_adapter = ExecutionPlanAgentAdapter(
            task=dispatch.task,
            product_spec=spec,
            technical_design=design,
            execution_plan=plan,
            agent_id=definitions[AgentRole.ORCHESTRATOR].id,
            agent_version=definitions[AgentRole.ORCHESTRATOR].version,
            created_at=dispatch.committed_at,
        )
        resolver = StoredContextResolver(
            FileContextStore(paths.contexts),
            FileArtifactStore(paths.artifacts),
        )
        adapter = DispatchDeliveryAgentAdapter(
            dispatch=dispatch,
            definitions=definitions,
            plan_adapter=plan_adapter,
            config=self._config,
            project_root=facts.workspace.project_root,
            project_workspace_root=facts.workspace.root,
            context_resolver=resolver,
            environment=self._environment,
            route_adapters=route_adapters or self._delivery_route_adapters,
        )
        primary = self._config.enabled_routes()[0]
        runtime_config = RuntimeConfig(
            endpoint="https://runtime.invalid/v1/responses",
            model=primary.model,
            api_key_required=False,
            context_max_input_tokens=PRODUCTION_DELIVERY_CONTEXT_BUDGET.max_input_tokens,
            token_budget=_delivery_token_budget(),
            paths=paths,
            persistence=RuntimePersistence(
                backend="mysql",
                mysql_dsn_env=self._config.database.dsn_env,
            ),
            context_sources=(
                *self._delivery_context_sources,
                *extra_context,
                project_profile_context(facts.profile),
                ContextSource(
                    source_id="project.baseline",
                    uri=f"baseline://{facts.baseline.project_id}/{facts.baseline.baseline_sha256}",
                    content=json.dumps(
                        facts.baseline.to_wire(), ensure_ascii=False, sort_keys=True
                    ),
                    priority=10,
                    required=True,
                ),
            ),
            max_retries=0,
        )
        try:
            with RuntimeSession(
                runtime_config,
                environment=self._environment,
                agent_adapter=adapter,
                agent_definitions=definitions,
                project_root=facts.workspace.project_root,
            ) as runtime:
                return runtime.run_task(dispatch.task_id).result
        finally:
            adapter.close_clean_worktrees()

    def _facts(self, preparation: PrepareProjectResult) -> _ProjectFacts:
        if preparation.status is not PrepareProjectStatus.PREPARED:
            raise ValueError("project is not prepared")
        prepared = preparation.preparation
        assert prepared is not None
        workspace = self._registry.register(
            prepared.project_root,
            project_id=prepared.project_id,
        )
        profile = load_project_profile(workspace.root, prepared.project_profile_sha256)
        if profile.project_id != prepared.project_id:
            raise ValueError("prepared profile belongs to another project")
        compilation = self._baseline_store.get(workspace, preparation.baseline_compilation_sha256)
        baseline = compilation.compiled_spec
        if baseline is None:
            raise ValueError("prepared baseline is missing")
        state = workspace.directory("state")
        return _ProjectFacts(
            preparation=preparation,
            workspace=workspace,
            profile=profile,
            baseline=baseline,
            product=FileProductRecordStore(state / "product"),
            design=FileDesignRecordStore(state / "design"),
            planning=FileExecutionPlanStore(state / "planning"),
        )

    def _facts_for_checkpoint(self, checkpoint: ProjectDeliveryCheckpoint) -> _ProjectFacts:
        preparation = self.prepare(checkpoint.project_root)
        if (
            preparation.preparation is None
            or preparation.project_id != checkpoint.project_id
            or preparation.preparation.preparation_sha256 != checkpoint.preparation_sha256
        ):
            raise ValueError("delivery preparation checkpoint drifted")
        return self._facts(preparation)

    def _product_service(self, facts: _ProjectFacts) -> ProductDiscoveryService:
        preparation = facts.preparation.preparation
        assert preparation is not None
        return ProductDiscoveryService(
            preparation=preparation,
            project_profile=facts.profile,
            project_baseline=facts.baseline,
            store=facts.product,
            adapter=StructuredProductAgentAdapter(
                self._structured_clients.for_project(facts.workspace.project_root)
            ),
            stage_advancer=self._preparer,
            human_decision_verifier=self._human_decision_verifier,
        )

    @staticmethod
    def _product_authorization(
        facts: _ProjectFacts,
        delivery_id: str,
    ) -> StageAdvanceAuthorization:
        operation = facts.product.find_operation(_approval_operation_id(delivery_id))
        if operation is None:
            raise ValueError("Product approval operation is missing")
        payload = operation.result_payload.get("authorization")
        if not isinstance(payload, dict):
            raise ValueError("Product approval authorization is missing")
        authorization = StageAdvanceAuthorization.model_validate(payload)
        authorization.validate_integrity()
        return authorization

    def _workforce(
        self,
    ) -> tuple[tuple[AgentProfile, ...], ModelPolicy]:
        return production_organization_team(self._config)

    @staticmethod
    def _guard(label: str, operation: Callable[[], ResultT]) -> ResultT:
        try:
            return operation()
        except DeliveryBackendFailure:
            raise
        except ProductionConfigError as error:
            raise DeliveryBackendFailure(
                DeliveryFailureCode.PERMISSION_DENIED,
                f"{label} is not configured for live execution",
            ) from error
        except DispatchRejected as error:
            raise DeliveryBackendFailure(
                DeliveryFailureCode.RESOURCE_UNAVAILABLE,
                f"{label} has no eligible organization resource",
            ) from error
        except DispatchError as error:
            raise DeliveryBackendFailure(
                DeliveryFailureCode.CHECKPOINT_DRIFT,
                f"{label} rejected stale or inconsistent facts: {error}",
            ) from error
        except Exception as error:
            raise DeliveryBackendFailure(
                DeliveryFailureCode.INVARIANT_VIOLATION,
                f"{label} stopped safely ({type(error).__name__})",
            ) from error


def _terminal_delivery_result(
    repository: MySqlTaskRepository,
    artifacts: FileArtifactStore,
    task_id: str,
) -> RetryResult | None:
    """Rebuild a sealed runtime result after Task completion beat checkpointing.

    The Task event stream remains authoritative.  This seam performs no model call and
    lets the Delivery journal adopt a result that was already durably completed by an
    earlier process.
    """
    task = repository.get(task_id)
    if task.status not in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}:
        return None
    events = repository.list_events(task.id)
    revision = repository.current_revision(task.id)
    if (
        not events
        or revision != len(events)
        or events[-1].to_status is not task.status
        or repository.get(task.id) != task
    ):
        raise ValueError("terminal Task event stream is inconsistent")
    event_ids = tuple(event.event_id for event in events)
    candidate = next(
        (
            event.source_revision
            for event in reversed(events)
            if event.reason in {"candidate_ready", "candidate_recovered"}
            and event.source_revision != task.base_ref
        ),
        None,
    )
    if task.status is not TaskStatus.DONE:
        classification, reason = _terminal_failure_reason(events[-1].reason)
        artifact_ids = tuple(
            dict.fromkeys(artifact_id for event in events for artifact_id in event.artifact_ids)
        )
        return BlockedResult(
            task=task,
            classification=classification,
            reason=reason,
            attempt=max(task.attempts, 1),
            artifact_ids=artifact_ids,
            event_ids=event_ids,
            candidate_revision=candidate,
        )
    if events[-1].reason != "review_approved" or len(events[-1].artifact_ids) != 4:
        raise ValueError("DONE Task has no complete review_approved artifact set")
    result_artifacts: tuple[Artifact, ...] = tuple(
        artifacts.get(artifact_id) for artifact_id in events[-1].artifact_ids
    )
    plan, implementation, qa, review = result_artifacts
    if (
        not isinstance(plan, PlanArtifact)
        or not isinstance(implementation, ImplementationReportArtifact)
        or not isinstance(qa, QaReportArtifact)
        or not isinstance(review, ReviewReportArtifact)
        or any(artifact.task_id != task.id for artifact in result_artifacts)
        or candidate is None
        or plan.source_revision != task.base_ref
        or implementation.content.commit_sha != candidate
        or implementation.source_revision != candidate
        or plan.artifact_id not in implementation.parent_artifact_ids
        or qa.content.status is not QaReportStatus.PASS
        or qa.source_revision != candidate
        or qa.parent_artifact_ids != (implementation.artifact_id,)
        or review.content.verdict is not ReviewVerdict.APPROVE
        or review.source_revision != candidate
        or review.parent_artifact_ids != (qa.artifact_id,)
    ):
        raise ValueError("DONE Task artifact lineage is incomplete")
    return RetryDeliveryResult(
        task=task,
        candidate_revision=candidate,
        artifact_ids=events[-1].artifact_ids,
        context_manifest_ids=tuple(item.context_manifest_id for item in result_artifacts),
        run_ids=tuple(item.producer.run_id for item in result_artifacts),
        event_ids=event_ids,
    )


def _terminal_failure_reason(reason: str) -> tuple[RetryClassification, str]:
    prefix, separator, detail = reason.partition(": ")
    try:
        classification = RetryClassification(prefix)
    except ValueError:
        classification = RetryClassification.PLATFORM_BUG
    safe_reason = detail if separator and detail else reason
    return classification, safe_reason or "Terminal Task requires human inspection"


def _suffix(delivery_id: str) -> str:
    return delivery_id.removeprefix("delivery_")


def _approval_operation_id(delivery_id: str) -> str:
    return f"approve_{_suffix(delivery_id)}"


def _designer_run_id(delivery_id: str) -> str:
    return f"run_designer_{_suffix(delivery_id)}"


def _planner_run_id(delivery_id: str) -> str:
    return f"run_planner_{_suffix(delivery_id)}"


def _maximum_risk(risks: Iterable[RiskTier]) -> RiskTier:
    values = tuple(risks)
    ranks = {
        RiskTier.LOW: 0,
        RiskTier.NORMAL: 1,
        RiskTier.HIGH: 2,
        RiskTier.CRITICAL: 3,
    }
    return max(values, key=ranks.__getitem__)


def _task_constraints(profile: ProjectProfile, design: TechnicalDesign) -> TaskConstraints:
    affected = tuple(
        sorted({path for component in design.components for path in component.affected_paths})
    )
    denied = tuple(
        sorted(
            {
                source.relative_path
                for source in profile.native_rules
                if source.relative_path.endswith(("AGENTS.md", "CONTRIBUTING.md"))
            }
        )
    )
    return TaskConstraints(
        allowed_paths=affected,
        denied_paths=denied,
        allowed_commands=_task_commands(profile),
        max_attempts=PRODUCTION_DELIVERY_MAX_ATTEMPTS,
        notes=(
            "Production v0.1 is serial; bounded Coder runs may checkpoint and continue before QA."
        ),
    )


def _task_commands(profile: ProjectProfile) -> tuple[str, ...]:
    commands = {
        "git status",
        "git diff",
        "git rev-parse",
        "git ls-files",
        "git show",
    }
    build_commands = {
        BuildSystem.PYTHON: ("python", "python3", "pytest", "uv", "ruff", "mypy"),
        BuildSystem.MAVEN: ("mvn", "./mvnw", "java"),
        BuildSystem.GRADLE: ("gradle", "./gradlew", "java"),
        BuildSystem.GO: ("go",),
        BuildSystem.NPM: ("npm", "npx", "node"),
        BuildSystem.PNPM: ("pnpm", "node"),
        BuildSystem.YARN: ("yarn", "node"),
        BuildSystem.BUN: ("bun",),
        BuildSystem.CMAKE: ("cmake", "ctest"),
        BuildSystem.MESON: ("meson", "ninja"),
        BuildSystem.MAKE: ("make",),
        BuildSystem.BAZEL: ("bazel",),
    }
    for fact in profile.build_systems:
        commands.update(build_commands.get(fact.system, ()))
    return tuple(sorted(commands))


def _delivery_role_permissions(
    role: AgentRole,
    allowed_paths: tuple[str, ...],
    commands: tuple[str, ...],
) -> AgentPermissions:
    """Compile the current machine-enforced policy for one delivery role."""
    return AgentPermissions(
        read_paths=("**",),
        write_paths=allowed_paths if role is AgentRole.CODER else (),
        commands=commands,
        network=NetworkAccess.MODEL_ENDPOINT_ONLY,
    )


def _clean_git_head(project_root: Path) -> str:
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_TERMINAL_PROMPT": "0",
    }

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            raise ValueError("target project is not a readable Git repository")
        return completed.stdout.strip()

    if Path(git("rev-parse", "--show-toplevel")).resolve() != project_root.resolve():
        raise ValueError("target project must be the Git repository root")
    if git("status", "--porcelain"):
        raise ValueError("target project must be clean before dispatch")
    revision = git("rev-parse", "HEAD")
    if len(revision) < 40:
        raise ValueError("target project has no durable Git commit")
    return revision


def _continuation_context(
    config: ProductionConfig,
    facts: _ProjectFacts,
    dispatch: ContinuationDispatchRecord,
) -> tuple[ContextSource, ...]:
    """Rebuild durable remediation input after a process restart."""
    from ai_software_engineer.recovery.models import RecoveryScope, digest
    from ai_software_engineer.recovery.remediation import remediation_context
    from ai_software_engineer.recovery.store import FileRecoveryStore

    scope = RecoveryScope(
        company_id=config.company_id,
        project_id=dispatch.project_id,
        project_root=str(facts.workspace.project_root),
        delivery_id=dispatch.source_delivery_id,
    )
    store = FileRecoveryStore(
        facts.workspace.root / "state" / f"candidate-verification-{dispatch.source_delivery_id}",
        scope=scope,
    )
    plan = store.get_verification_plan(dispatch.continuation_plan_sha256)
    completion = store.get_verification_completion(plan.plan_sha256)
    if (
        completion.verified
        or completion.completion_sha256 != dispatch.continuation_sha256
        or plan.inputs.task_id != dispatch.source_task_id
        or plan.inputs.candidate_revision != dispatch.source_revision
    ):
        raise ValueError("continuation verifier lineage drifted")
    sources = remediation_context(
        project_root=scope.project_root,
        source_delivery_id=scope.delivery_id,
        source_base_revision=dispatch.source_base_revision,
        candidate_revision=dispatch.source_revision,
        plan=plan,
        completion=completion,
    )
    if digest([item.to_wire() for item in sources]) != dispatch.continuation_context_sha256:
        raise ValueError("continuation context drifted")
    return sources


def _agent_definitions(
    dispatch: DeliveryAllocation,
    commands: tuple[str, ...],
) -> dict[AgentRole, AgentDefinition]:
    constraints = dispatch.task.constraints
    allowed_paths = constraints.allowed_paths if constraints is not None else ()
    definitions: dict[AgentRole, AgentDefinition] = {
        AgentRole.ORCHESTRATOR: AgentDefinition(
            id="agent_team_orchestrator",
            role=AgentRole.ORCHESTRATOR,
            version="v0.1",
            model="approved-execution-plan",
            provider="deterministic",
            permissions=AgentPermissions(
                read_paths=("**",),
                write_paths=(),
                commands=(),
                network=NetworkAccess.NONE,
                can_change_state=True,
            ),
            input_artifacts=(),
            output_artifacts=(ArtifactKind.PLAN,),
            max_retries=0,
            timeout_seconds=60,
        )
    }
    for phase in dispatch.phases:
        definitions[phase.role] = AgentDefinition(
            id=phase.agent_id,
            role=phase.role,
            version="v0.1",
            model=phase.model_selection.model,
            provider=phase.model_selection.provider,
            permissions=_delivery_role_permissions(phase.role, allowed_paths, commands),
            input_artifacts=_ROLE_INPUTS[phase.role],
            output_artifacts=_ROLE_OUTPUTS[phase.role],
            max_retries=0,
            timeout_seconds=_delivery_timeout_seconds(phase.role),
            token_budget=_delivery_token_budget(),
        )
    return definitions


def _delivery_timeout_seconds(role: AgentRole) -> int:
    try:
        return {
            AgentRole.CODER: 1_800,
            AgentRole.QA: 1_200,
            AgentRole.REVIEWER: 1_200,
        }[role]
    except KeyError as exc:
        raise ValueError(f"unsupported production delivery role: {role.value}") from exc


def _delivery_token_budget() -> int:
    budget = PRODUCTION_DELIVERY_CONTEXT_BUDGET
    return budget.max_input_tokens + budget.reserved_output_tokens


def _runtime_paths(workspace: ProjectWorkspace) -> RuntimePaths:
    return RuntimePaths(
        database=str(workspace.directory("state") / "unused.sqlite3"),
        artifacts=str(workspace.directory("artifacts")),
        contexts=str(workspace.directory("contexts")),
        evaluation_events=str(workspace.directory("evaluations")),
        handoffs=str(workspace.directory("handoffs")),
        evidence=str(workspace.directory("evidence")),
        runs=str(workspace.directory("runs")),
    )


__all__ = [
    "ConfiguredStructuredClientFactory",
    "ProductionProjectDeliveryBackend",
    "StructuredClientFactory",
]
