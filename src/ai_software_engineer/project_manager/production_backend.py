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
from ai_software_engineer.context import ContextSource, FileContextStore
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
    ArtifactKind,
    BrainTier,
    ModelPolicy,
    ModelRoute,
    NetworkAccess,
    OrganizationRole,
    ProductApprovalDecision,
    RiskModelFloor,
    RiskTier,
    TaskConstraints,
    TechnicalDesign,
    WorkItem,
    WorkItemStatus,
    derive_delivery_task,
)
from ai_software_engineer.orchestration import (
    DispatchTaskMaterializer,
    ExecutionPlanAgentAdapter,
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
    ReplyToProduct,
    StartProjectDelivery,
)
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryFailureCode,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.project_manager.dispatch import (
    CommitDispatchRequest,
    DispatchCommitRecord,
    DispatchError,
    DispatchRejected,
    DispatchWorkforceSnapshot,
    ProjectManagerDispatchService,
)
from ai_software_engineer.project_manager.mysql_dispatch_authority import (
    MySqlDispatchAuthority,
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
)
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.spec_compiler import SpecRule
from ai_software_engineer.store import MySqlTaskRepository

Clock = Callable[[], datetime]
ResultT = TypeVar("ResultT")
_ALL_CAPABILITIES = (
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
)
_ROLE_INPUTS: dict[AgentRole, tuple[ArtifactKind, ...]] = {
    AgentRole.ORCHESTRATOR: (),
    AgentRole.CODER: (
        ArtifactKind.PLAN,
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
_ROLE_OUTPUT = {
    AgentRole.ORCHESTRATOR: ArtifactKind.PLAN,
    AgentRole.CODER: ArtifactKind.IMPLEMENTATION_REPORT,
    AgentRole.QA: ArtifactKind.QA_REPORT,
    AgentRole.REVIEWER: ArtifactKind.REVIEW_REPORT,
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
    ) -> None:
        self._config = config
        self._environment = dict(environment)
        self._organization = organization
        self._registry = registry
        self._clock = clock or (lambda: datetime.now(UTC))
        self._baseline_store = FileProjectBaselineCompilationStore()
        self._preparer = ProjectManagerSkillService(
            organization=organization,
            registry=registry,
            platform_rules=platform_rules,
            rule_provider=_NoProjectRules(),
            preparation_store_factory=FileProjectPreparationStore,
            baseline_recorder=self._baseline_store,
            clock=self._clock,
        )
        self._structured_clients = structured_clients or ConfiguredStructuredClientFactory(
            config, self._environment
        )
        self._delivery_route_adapters = delivery_route_adapters
        self._dsn = config.require_mysql_dsn(self._environment)

    def prepare(self, project_root: str) -> PrepareProjectResult:
        return self._preparer.prepare_project(PrepareProjectRequest(project_root=project_root))

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
        return self._guard("Delivery", lambda: self._run_delivery(checkpoint))

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
                commit = authority.get_commit(checkpoint.dispatch_commit_id)
                if commit.dispatch_sha256 != checkpoint.dispatch_commit_sha256:
                    raise ValueError("Dispatch checkpoint drifted")

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
            max_attempts=1,
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
        policy = workforce_store.put_policy(policy)
        agents = cast(
            tuple[AgentProfile, AgentProfile, AgentProfile],
            tuple(workforce_store.put_agent(agent) for agent in agents),
        )
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
            max_attempts=1,
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
        dispatch = authority.get_commit(cast(str, checkpoint.dispatch_commit_id))
        repository = MySqlTaskRepository(self._dsn)
        try:
            DispatchTaskMaterializer(repository).materialize(dispatch)
        finally:
            repository.close()
        definitions = _agent_definitions(dispatch, _task_commands(facts.profile))
        spec = facts.product.find_product_spec(cast(str, checkpoint.product_spec_id))
        design = facts.design.get_run(_designer_run_id(checkpoint.delivery_id)).technical_design
        if spec is None or design is None:
            raise ValueError("delivery plan inputs are missing")
        plan_adapter = ExecutionPlanAgentAdapter(
            task=dispatch.task,
            product_spec=spec,
            technical_design=design,
            execution_plan=facts.planning.get_execution_plan(dispatch.execution_plan_id),
            agent_id=definitions[AgentRole.ORCHESTRATOR].id,
            agent_version=definitions[AgentRole.ORCHESTRATOR].version,
            created_at=dispatch.committed_at,
        )
        paths = _runtime_paths(facts.workspace)
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
            route_adapters=self._delivery_route_adapters,
        )
        primary = self._config.enabled_routes()[0]
        runtime_config = RuntimeConfig(
            endpoint="https://runtime.invalid/v1/responses",
            model=primary.model,
            api_key_required=False,
            paths=paths,
            persistence=RuntimePersistence(
                backend="mysql",
                mysql_dsn_env=self._config.database.dsn_env,
            ),
            context_sources=(
                ContextSource(
                    source_id="project.profile",
                    uri=f"profile://{facts.profile.project_id}/{facts.profile.profile_sha256}",
                    content=json.dumps(facts.profile.to_wire(), ensure_ascii=False, sort_keys=True),
                    priority=20,
                    required=True,
                ),
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
        profile = ProjectProfile.model_validate_json(
            (workspace.directory("profile") / "project-profile.json").read_text(encoding="utf-8")
        )
        profile.validate_integrity()
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
            human_decision_verifier=_CliHumanDecisionVerifier(),
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
    ) -> tuple[tuple[AgentProfile, AgentProfile, AgentProfile], ModelPolicy]:
        primary = self._config.enabled_routes()[0]
        policy = ModelPolicy(
            id="model_policy_delivery_default",
            version="v0.1",
            default_tier=BrainTier.CRITICAL,
            routes=(
                ModelRoute(
                    provider=primary.provider,
                    model=primary.model,
                    tier=BrainTier.CRITICAL,
                    capabilities=_ALL_CAPABILITIES,
                ),
            ),
            risk_floors=tuple(
                RiskModelFloor(risk=risk, minimum_tier=BrainTier.CRITICAL) for risk in RiskTier
            ),
        )
        profiles = tuple(
            AgentProfile(
                id=f"agent_team_{role.value}",
                version="v0.1",
                display_name=f"Team {role.value.title()}",
                capabilities=_ALL_CAPABILITIES,
                eligible_roles=(OrganizationRole(role.value),),
                max_parallel_assignments=8,
                default_model_policy_id=policy.id,
            )
            for role in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)
        )
        return cast(tuple[AgentProfile, AgentProfile, AgentProfile], profiles), policy

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
        max_attempts=1,
        notes="Production v0.1 uses one serial Coder → QA → Reviewer attempt.",
    )


def _task_commands(profile: ProjectProfile) -> tuple[str, ...]:
    commands = {
        "git status",
        "git diff",
        "git add",
        "git commit",
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


def _agent_definitions(
    dispatch: DispatchCommitRecord,
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
            permissions=AgentPermissions(
                read_paths=("**",),
                write_paths=allowed_paths if phase.role is AgentRole.CODER else (),
                commands=commands,
                network=NetworkAccess.MODEL_ENDPOINT_ONLY,
            ),
            input_artifacts=_ROLE_INPUTS[phase.role],
            output_artifacts=(_ROLE_OUTPUT[phase.role],),
            max_retries=0,
            timeout_seconds=600,
            token_budget=20_000,
        )
    return definitions


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
