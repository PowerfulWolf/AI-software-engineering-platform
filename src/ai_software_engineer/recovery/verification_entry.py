"""Production composition for approved QA/Reviewer continuation of one candidate."""

from __future__ import annotations

import json
from collections.abc import Mapping, Set
from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.agents import StoredContextResolver
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.company_workspace import _read_regular, _reject_symlinks
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentDefinition, AgentRole, WorkItem, WorkItemStatus
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.orchestration import FileRunContextBuilder
from ai_software_engineer.planning import FileExecutionPlanStore
from ai_software_engineer.planning.preview import derive_phase_demands
from ai_software_engineer.product import FileProductRecordStore
from ai_software_engineer.project_manager.delivery_checkpoint import (
    FileProjectDeliveryCheckpointStore,
    checkpoint_sha256_is_ancestor,
)
from ai_software_engineer.project_manager.dispatch import (
    DispatchPhaseCommit,
    DispatchWorkforceSnapshot,
    VerificationReservation,
)
from ai_software_engineer.project_manager.mysql_dispatch_authority import MySqlDispatchAuthority
from ai_software_engineer.project_manager.production_backend import (
    ProductionProjectDeliveryBackend,
    _agent_definitions,
    _delivery_role_permissions,
    _task_commands,
)
from ai_software_engineer.project_manager.production_delivery import (
    ConfiguredDeliveryRouteAdapterFactory,
    DeliveryRouteAdapterFactory,
    DispatchDeliveryAgentAdapter,
)
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryRejected,
    RecoveryScope,
    digest,
)
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification import (
    CandidateVerificationRunner,
)
from ai_software_engineer.recovery.verification_admission import (
    CandidateVerificationAdmission,
    ExplicitVerificationHuman,
    VerificationFacts,
)
from ai_software_engineer.recovery.verification_native import (
    NativeCandidateSource,
    NativeCandidateSourceReader,
)
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationCompletion,
    CandidateVerificationInputs,
    CandidateVerificationPlan,
)
from ai_software_engineer.runtime_workspace import load_project_profile
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.scheduling.models import (
    AssignmentDecisionStatus,
    ModelRoutingDecisionStatus,
)
from ai_software_engineer.store import MySqlTaskRepository


def verification_store_root(source: NativeCandidateSource) -> Path:
    return (
        Path(source.stages.preparation.project_workspace_root)
        / "state"
        / f"candidate-verification-{source.scope.delivery_id}"
    )


def open_candidate_verification_plan(
    config: ProductionConfig,
    environment: Mapping[str, str],
    path: Path,
) -> tuple[FileRecoveryStore, CandidateVerificationPlan]:
    """Open one exact verification plan without initializing the Team Host or database schema."""
    _reject_symlinks(path)
    envelope = json.loads(_read_regular(path, 8_000_000))
    plan = CandidateVerificationPlan.model_validate(envelope["record"])
    source = NativeCandidateSourceReader(config, environment).inspect(plan.scope)
    expected = verification_store_root(source) / f"verification-plan-{plan.plan_sha256}.json"
    if path != expected or plan.scope.company_id != config.company_id:
        raise RecoveryRejected("verification plan is outside its scoped store")
    store = FileRecoveryStore(path.parent, scope=plan.scope)
    return store, store.get_verification_plan(plan.plan_sha256)


def _policy_sha(definitions: Mapping[AgentRole, AgentDefinition], config: ProductionConfig) -> str:
    return digest(
        {
            "definitions": {
                role.value: value.to_wire()
                for role, value in sorted(definitions.items(), key=lambda x: x[0].value)
            },
            "enabled_routes": [route.to_wire() for route in config.enabled_routes()],
        }
    )


def _stage_sha(source: NativeCandidateSource) -> str:
    return digest(
        {
            "preparation": source.stages.preparation.to_wire(),
            "product": source.stages.product.to_wire(),
            "approval": source.stages.approval.to_wire(),
            "design": source.stages.design.to_wire(),
            "plan": source.stages.plan.to_wire(),
        }
    )


def _verification_inputs_are_current(
    approved: CandidateVerificationInputs,
    current: CandidateVerificationInputs,
    admitted_run_ids: Set[str],
) -> bool:
    """Accept only append-only run facts durably admitted by this exact plan."""
    approved_runs, current_runs = set(approved.prior_run_ids), set(current.prior_run_ids)
    return (
        current.model_copy(update={"prior_run_ids": approved.prior_run_ids}) == approved
        and approved_runs <= current_runs
        and current_runs - approved_runs <= set(admitted_run_ids)
    )


def _verification_allocation(
    source: NativeCandidateSource,
    snapshot: DispatchWorkforceSnapshot,
    *,
    execution_task_id: str,
    plan_sha256: str,
    now: datetime,
) -> VerificationReservation:
    scheduler = PortfolioScheduler()
    router = ModelRouter(
        route_context_capacities={
            (route.provider, route.model): 2_000_000
            for policy in snapshot.model_policies
            for route in policy.routes
        }
    )
    demands = derive_phase_demands(source.runtime.task, source.stages.plan)
    phases = []
    leases, assignments = tuple(snapshot.active_leases), tuple(snapshot.assignments)
    profiles = {agent.id: agent for agent in snapshot.agents}
    policies = {policy.id: policy for policy in snapshot.model_policies}
    for phase, demand in zip(source.stages.plan.phases[1:], demands[1:], strict=True):
        item = WorkItem(
            task_id=execution_task_id,
            project_id=source.scope.project_id,
            status=WorkItemStatus.READY,
            priority=500,
            risk=phase.risk,
            required_capabilities=phase.required_capabilities,
            created_at=now,
            updated_at=now,
        )
        decision = scheduler.match(
            item,
            phase.role,
            snapshot.agents,
            leases,
            assignments,
            now=now,
            attempt=1,
            work_items=(item,),
        )
        if decision.status is not AssignmentDecisionStatus.ASSIGNED:
            raise RecoveryRejected(f"no available {phase.role.value} Agent")
        assert decision.agent_id and decision.assignment and decision.lease
        profile = profiles[decision.agent_id]
        routing = router.route(
            demand.model_copy(update={"task_id": execution_task_id}),
            profile,
            policies[profile.default_model_policy_id],
            now=now,
        )
        if routing.status is not ModelRoutingDecisionStatus.SELECTED or routing.selection is None:
            raise RecoveryRejected(f"no approved {phase.role.value} model")
        phases.append(
            DispatchPhaseCommit(
                phase_id=phase.id,
                role=phase.role,
                agent_id=profile.id,
                assignment=decision.assignment,
                lease=decision.lease,
                model_selection=routing.selection,
            )
        )
        assignments = (*assignments, decision.assignment)
        leases = (*leases, decision.lease)
    return VerificationReservation(
        plan_sha256=plan_sha256,
        project_id=source.scope.project_id,
        source_task_id=source.inputs.task_id,
        task_id=execution_task_id,
        workforce_snapshot_sha256=snapshot.snapshot_sha256,
        phases=tuple(phases),
        committed_at=now,
    )


def _definitions(
    source: NativeCandidateSource, reservation: VerificationReservation
) -> dict[AgentRole, AgentDefinition]:
    profile = load_project_profile(
        Path(source.stages.preparation.project_workspace_root),
        source.stages.preparation.project_profile_sha256,
    )
    commands = _task_commands(profile)
    result = _agent_definitions(source.runtime.dispatch, commands)
    allowed = (
        source.runtime.task.constraints.allowed_paths if source.runtime.task.constraints else ()
    )
    for phase in reservation.phases:
        previous = result[phase.role]
        result[phase.role] = previous.model_copy(
            update={
                "id": phase.agent_id,
                "provider": phase.model_selection.provider,
                "model": phase.model_selection.model,
                "permissions": _delivery_role_permissions(phase.role, allowed, commands),
            }
        )
    return result


class NativeVerificationFacts(VerificationFacts):
    def __init__(
        self,
        config: ProductionConfig,
        environment: Mapping[str, str],
        *,
        store: FileRecoveryStore | None = None,
    ) -> None:
        self.config, self.environment, self.store = config, dict(environment), store

    def _admitted_run_ids(self, plan: CandidateVerificationPlan) -> set[str]:
        if self.store is None:
            return set()
        result: set[str] = set()
        for role in (AgentRole.QA, AgentRole.REVIEWER):
            try:
                invocation = self.store.get_verification_invocation(plan.plan_sha256, role)
            except RecoveryRecordMissing:
                continue
            result.add(invocation.request.run_id)
        return result

    def validate(self, plan: CandidateVerificationPlan) -> None:
        source = NativeCandidateSourceReader(self.config, self.environment).inspect(plan.scope)
        checkpoint_history = FileProjectDeliveryCheckpointStore(
            Path(source.stages.preparation.project_workspace_root) / "state/project-deliveries",
            read_only=True,
        ).list(source.scope.delivery_id)
        if (
            not _verification_inputs_are_current(
                plan.inputs, source.inputs, self._admitted_run_ids(plan)
            )
            or not checkpoint_history
            or checkpoint_history[-1] != source.checkpoint
            or not checkpoint_sha256_is_ancestor(checkpoint_history, plan.native_checkpoint_sha256)
            or source.runtime.dispatch.dispatch_sha256 != plan.dispatch_sha256
            or _stage_sha(source) != plan.approved_stage_chain_sha256
            or source.parent_delivery_id != plan.parent_delivery_id
            or source.parent_checkpoint_sha256 != plan.parent_checkpoint_sha256
        ):
            raise RecoveryRejected("verification source changed after proposal")
        manager = GitWorktreeManager(
            source.scope.project_root,
            Path(self.config.platform_root) / "worktrees" / source.scope.project_id,
        )
        manager._validate_repository()
        if (
            manager._run_git(
                ("rev-parse", f"{source.inputs.candidate_revision}^{{commit}}"),
                cwd=Path(source.scope.project_root),
            )
            != source.inputs.candidate_revision
        ):
            raise RecoveryRejected("approved candidate commit is unavailable")
        current = {d.role: d for d in plan.definitions}
        if _policy_sha(current, self.config) != plan.current_policy_sha256:
            raise RecoveryRejected("approved verifier policy digest changed")


class CandidateVerificationEntry:
    def __init__(
        self,
        config: ProductionConfig,
        environment: Mapping[str, str],
        backend: ProductionProjectDeliveryBackend,
    ) -> None:
        self.config, self.environment, self.backend = config, dict(environment), backend
        self._route_factory = backend._delivery_route_adapters

    def _authority(self, source: NativeCandidateSource) -> MySqlDispatchAuthority:
        sidecar = Path(source.stages.preparation.project_workspace_root)
        return MySqlDispatchAuthority(
            self.config.require_mysql_dsn(self.environment),
            request_revisions=FileProductRecordStore(sidecar / "state/product"),
            planner_records=FileExecutionPlanStore(sidecar / "state/planning"),
        )

    def propose_project(
        self, *, project_root: str, delivery_id: str
    ) -> tuple[CandidateVerificationPlan, Path]:
        """Resolve the registered project and propose verification without invoking a model."""
        prepared = self.backend.prepare(project_root).preparation
        if prepared is None:
            raise RecoveryRejected("project preparation needs human resolution")
        return self.propose(
            RecoveryScope(
                company_id=self.config.company_id,
                project_id=prepared.project_id,
                project_root=prepared.project_root,
                delivery_id=delivery_id,
            )
        )

    def latest_project(
        self, *, project_root: str, delivery_id: str
    ) -> tuple[FileRecoveryStore, CandidateVerificationPlan, Path] | None:
        """Return the newest sealed plan for the current terminal candidate, if any."""
        prepared = self.backend.prepare(project_root).preparation
        if prepared is None:
            raise RecoveryRejected("project preparation needs human resolution")
        scope = RecoveryScope(
            company_id=self.config.company_id,
            project_id=prepared.project_id,
            project_root=prepared.project_root,
            delivery_id=delivery_id,
        )
        source = NativeCandidateSourceReader(self.config, self.environment).inspect(scope)
        root = verification_store_root(source)
        if not root.exists():
            return None
        store = FileRecoveryStore(root, scope=scope)
        plans: list[tuple[CandidateVerificationPlan, Path]] = []
        for path in sorted(root.glob("verification-plan-*.json")):
            _reject_symlinks(path)
            prefix, suffix = "verification-plan-", ".json"
            plan_sha256 = path.name.removeprefix(prefix).removesuffix(suffix)
            if path.name != f"{prefix}{plan_sha256}{suffix}":
                raise RecoveryRejected("candidate verification plan path is malformed")
            plan = store.get_verification_plan(plan_sha256)
            if plan.scope != scope:
                raise RecoveryRejected("candidate verification plan scope drifted")
            try:
                NativeVerificationFacts(self.config, self.environment, store=store).validate(plan)
            except RecoveryRejected:
                continue
            plans.append((plan, path))
        if not plans:
            return None
        plan, path = max(plans, key=lambda item: (item[0].created_at, item[0].plan_sha256))
        return store, plan, path

    def propose(self, scope: RecoveryScope) -> tuple[CandidateVerificationPlan, Path]:
        source = NativeCandidateSourceReader(self.config, self.environment).inspect(scope)
        now = datetime.now(UTC)
        execution_id = (
            f"task_verify_{digest({'task': source.inputs.task_id, 'time': now.isoformat()})[:32]}"
        )
        snapshot = self._authority(source).current_snapshot(
            project_id=scope.project_id, task_id=source.inputs.task_id
        )
        preview = _verification_allocation(
            source, snapshot, execution_task_id=execution_id, plan_sha256="0" * 64, now=now
        )
        definitions = _definitions(source, preview)
        plan = CandidateVerificationPlan.create(
            scope=scope,
            inputs=source.inputs,
            execution_task_id=execution_id,
            native_checkpoint_sha256=source.checkpoint.checkpoint_sha256,
            dispatch_sha256=source.runtime.dispatch.dispatch_sha256,
            approved_stage_chain_sha256=_stage_sha(source),
            current_policy_sha256=_policy_sha(definitions, self.config),
            parent_delivery_id=source.parent_delivery_id,
            parent_checkpoint_sha256=source.parent_checkpoint_sha256,
            definitions=tuple(definitions[role] for role in AgentRole),
            created_at=now,
        )
        store = FileRecoveryStore.initialize(verification_store_root(source), scope=scope)
        CandidateVerificationAdmission(
            store=store,
            plan_sha256=plan.plan_sha256,
            facts=NativeVerificationFacts(self.config, self.environment, store=store),
            artifacts=FileArtifactStore(
                Path(source.stages.preparation.project_workspace_root) / "artifacts"
            ),
            clock=lambda: datetime.now(UTC),
        ).propose(plan)
        path = verification_store_root(source) / f"verification-plan-{plan.plan_sha256}.json"
        return plan, path

    def open(self, path: Path) -> tuple[FileRecoveryStore, CandidateVerificationPlan]:
        return open_candidate_verification_plan(self.config, self.environment, path)

    def approve(self, path: Path, *, confirmed_plan: str, reference: str) -> None:
        store, plan = self.open(path)
        admission = self._admission(store, plan)
        command = RecoveryApprovalCommand(
            operation_id=f"op_verify_{plan.plan_sha256[:32]}",
            plan_sha256=plan.plan_sha256,
            approval_reference=reference,
            submitted_at=datetime.now(UTC),
        )
        try:
            previous = store.get_verification_authorization(plan.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            if (
                previous.command.approval_reference != reference
                or confirmed_plan != plan.plan_sha256
            ):
                raise RecoveryRejected("approval replay differs from original confirmation")
            command = previous.command
        admission.approve(
            command,
            human=ExplicitVerificationHuman(confirmed_plan),
        )

    def execute(
        self, path: Path, *, route_factory: DeliveryRouteAdapterFactory | None = None
    ) -> CandidateVerificationCompletion:
        if not self.config.live_model_execution:
            raise RecoveryRejected("live model execution is disabled")
        store, plan = self.open(path)
        try:
            completion = store.get_verification_completion(plan.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            NativeVerificationFacts(self.config, self.environment, store=store).validate(plan)
            return completion
        for role in (AgentRole.QA, AgentRole.REVIEWER):
            try:
                invocation = store.get_verification_invocation(plan.plan_sha256, role)
            except RecoveryRecordMissing:
                continue
            raise RecoveryRejected(
                f"{role.value} run {invocation.request.run_id} was already admitted without "
                "a sealed completion; this approved plan cannot be replayed. Run "
                "verify-propose for the same project and delivery, then approve the new plan; "
                "Coder will not run"
            )
        source = NativeCandidateSourceReader(self.config, self.environment).inspect(plan.scope)
        admission = self._admission(store, plan)
        authority = self._authority(source)
        definitions = {d.role: d for d in plan.definitions}

        def build(snapshot: DispatchWorkforceSnapshot) -> VerificationReservation:
            value = _verification_allocation(
                source,
                snapshot,
                execution_task_id=plan.execution_task_id,
                plan_sha256=plan.plan_sha256,
                now=datetime.now(UTC),
            )
            if _definitions(source, value) != definitions:
                raise RecoveryRejected("current Agent/model allocation differs from approved plan")
            return value

        reservation = authority.reserve_verification(
            project_id=plan.scope.project_id,
            source_task_id=plan.inputs.task_id,
            plan_sha256=plan.plan_sha256,
            validate_current=lambda _: NativeVerificationFacts(
                self.config, self.environment, store=store
            ).validate(plan),
            build=build,
        )
        sidecar = Path(source.stages.preparation.project_workspace_root)
        artifacts, contexts = (
            FileArtifactStore(sidecar / "artifacts"),
            FileContextStore(sidecar / "contexts"),
        )
        adapter = DispatchDeliveryAgentAdapter(
            dispatch=reservation,
            definitions=definitions,
            plan_adapter=None,
            config=self.config,
            project_root=plan.scope.project_root,
            project_workspace_root=sidecar,
            context_resolver=StoredContextResolver(contexts, artifacts),
            environment=self.environment,
            route_adapters=(
                route_factory or self._route_factory or ConfiguredDeliveryRouteAdapterFactory()
            ),
        )
        repository = MySqlTaskRepository(self.config.require_mysql_dsn(self.environment))
        try:
            runner = CandidateVerificationRunner(
                repository=repository,
                artifact_store=artifacts,
                context_builder=FileRunContextBuilder(
                    plan.scope.project_root, context_store=contexts
                ),
                agent_adapter=adapter,
                agent_definitions=definitions,
                admission=admission,
            )
            completion = admission.complete(runner.verify_candidate(plan.inputs))
            authority.complete_verification(
                plan_sha256=plan.plan_sha256,
                completion_sha256=completion.completion_sha256,
                validate_completion=lambda record, sha: self._validate_completion(
                    record, reservation, completion, sha
                ),
            )
            return completion
        finally:
            repository.close()
            adapter.close_clean_worktrees()

    def _admission(
        self, store: FileRecoveryStore, plan: CandidateVerificationPlan
    ) -> CandidateVerificationAdmission:
        source = NativeCandidateSourceReader(self.config, self.environment).inspect(plan.scope)
        return CandidateVerificationAdmission(
            store=store,
            plan_sha256=plan.plan_sha256,
            facts=NativeVerificationFacts(self.config, self.environment, store=store),
            artifacts=FileArtifactStore(
                Path(source.stages.preparation.project_workspace_root) / "artifacts"
            ),
            clock=lambda: datetime.now(UTC),
        )

    @staticmethod
    def _validate_completion(
        record: VerificationReservation,
        expected: VerificationReservation,
        completion: CandidateVerificationCompletion,
        digest_value: str,
    ) -> None:
        if record != expected or digest_value != completion.completion_sha256:
            raise RecoveryRejected("completion does not match its verification reservation")
