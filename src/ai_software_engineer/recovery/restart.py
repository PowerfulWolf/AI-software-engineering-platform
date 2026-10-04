"""Audited fresh execution after an initial context failure, never Coder adoption."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ai_software_engineer.agents import FileModelRouteAttemptStore
from ai_software_engineer.agents.fallback import model_route_root
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.domain import Task, TaskStatus
from ai_software_engineer.domain.branch import successor_branch
from ai_software_engineer.manager import production_backend
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.dispatch import (
    ContinuationDispatchRecord,
    DispatchPhaseCommit,
    DispatchWorkforceSnapshot,
    _record_digest,
)
from ai_software_engineer.manager.mysql_dispatch_authority import MySqlDispatchAuthority
from ai_software_engineer.manager.preparation import PrepareProjectResult
from ai_software_engineer.planning import PlanningPreviewService
from ai_software_engineer.recovery.context import approved_parent_context
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryAuthorization,
    RecoveryRejected,
    RecoveryScope,
    VerifiedRecoveryDecision,
    digest,
)
from ai_software_engineer.recovery.native import NativeApprovedStages, _parent, read_approved_stages
from ai_software_engineer.recovery.remediation import _snapshot
from ai_software_engineer.recovery.restart_records import PreExecutionRestartPlan
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification_snapshot import (
    CandidateRuntimeSnapshot,
    read_pre_execution_snapshot,
)
from ai_software_engineer.runtime_workspace import FileTeamWorkforceStore
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.team_workspace import TeamWorkspace, _reject_symlinks


@dataclass(frozen=True)
class RestartProposal:
    plan: PreExecutionRestartPlan
    runtime: CandidateRuntimeSnapshot
    stages: NativeApprovedStages
    preparation: PrepareProjectResult
    root: Path

    def store(self) -> FileRecoveryStore:
        return FileRecoveryStore.initialize(
            self.root / "state" / f"pre-execution-{self.plan.scope.delivery_id}",
            scope=self.plan.scope,
        )


class PreExecutionRestartService:
    def __init__(
        self,
        config: ProductionConfig,
        environment: Mapping[str, str],
        backend: production_backend.ProductionProjectDeliveryBackend,
    ) -> None:
        self.config, self.environment, self.backend = config, dict(environment), backend

    def propose(self, checkpoint: ProjectDeliveryCheckpoint) -> RestartProposal | None:
        preparation_rebind = (
            checkpoint.stage is DeliveryStage.DELIVERING
            and checkpoint.task_status is TaskStatus.NEW
            and checkpoint.task_revision == 0
            and checkpoint.candidate_revision is None
            and checkpoint.failed_stage is None
            and checkpoint.failure_code is None
        )
        if not preparation_rebind and (
            checkpoint.failure_code is not DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED
            or checkpoint.task_revision != 2
        ):
            return None
        team = TeamWorkspace.initialize(
            self.config.platform_root,
            team_id=self.config.team_id,
            name=self.config.team_name,
            read_only=True,
        )
        _, repository = team.project_registry().locate_repository(checkpoint.repository_id)
        root = repository.root
        scope = RecoveryScope(
            team_id=self.config.team_id,
            repository_id=checkpoint.repository_id,
            repository_root=checkpoint.repository_root,
            delivery_id=checkpoint.delivery_id,
        )
        if str(repository.repository_root) != scope.repository_root:
            raise RecoveryRejected("restart repository identity mismatch")
        history = FileProjectDeliveryCheckpointStore(
            root / "state/project-deliveries",
            read_only=True,
        ).list(scope.delivery_id)
        if not history or history[-1] != checkpoint:
            raise RecoveryRejected("restart source checkpoint changed")
        runtime = read_pre_execution_snapshot(
            self.config,
            self.environment,
            history,
            allow_unstarted=preparation_rebind,
        )
        if runtime is None:
            return None
        _require_no_execution(self.config, root, runtime)
        stages = read_approved_stages(
            self.config,
            root,
            scope,
            checkpoint,
            runtime.task,
            runtime.planner_dispatch,
            current_dispatch=runtime.dispatch if preparation_rebind else None,
        )
        parent_id, parent_sha = _parent(team, checkpoint, stages.approval)
        sources = approved_parent_context(self.config, scope, parent_id, parent_sha)
        preparation = self.backend.prepare(scope.repository_root)
        prepared = preparation.preparation
        if prepared is None:
            raise RecoveryRejected("restart requires conflict-free current preparation")
        if preparation_rebind and prepared.preparation_sha256 == checkpoint.preparation_sha256:
            return None
        base = self.backend.delivery_base_revision(Path(scope.repository_root))
        # This repair changes execution/context policy only, not source or scope. A rebase
        # needs a different explicit plan contract; it must not sneak into a bug recovery.
        if not preparation_rebind and (
            base != runtime.task.base_ref
            or prepared.preparation_sha256 != checkpoint.preparation_sha256
        ):
            raise RecoveryRejected(
                "restart source/preparation changed; explicit replanning required"
            )
        plan = PreExecutionRestartPlan(
            scope=scope,
            restart_kind="preparation_rebind" if preparation_rebind else None,
            source_task_id=runtime.task.id,
            source_task_sha256=digest(runtime.task.to_wire()),
            source_events_sha256=digest([event.to_wire() for event in runtime.events]),
            source_checkpoint_sha256=checkpoint.checkpoint_sha256,
            source_dispatch_id=runtime.dispatch.id,
            source_dispatch_sha256=runtime.dispatch.dispatch_sha256,
            approved_stages_sha256=digest(
                [
                    stages.preparation.to_wire(),
                    stages.product.to_wire(),
                    stages.approval.to_wire(),
                    stages.design.to_wire(),
                    stages.plan.to_wire(),
                    stages.request.to_wire(),
                ]
            ),
            parent_delivery_id=parent_id,
            parent_checkpoint_sha256=parent_sha,
            target_preparation_sha256=prepared.preparation_sha256,
            target_base_revision=base,
            target_branch_name=successor_branch(runtime.task.branch_name, "recovery"),
            config_sha256=digest(self.config.to_wire()),
            context_budget=production_backend.PRODUCTION_DELIVERY_CONTEXT_BUDGET,
            context_sources=sources,
            created_at=checkpoint.checkpointed_at,
            plan_sha256="0" * 64,
        )
        plan = plan.model_copy(update={"plan_sha256": plan.recompute_sha256()})
        return RestartProposal(plan, runtime, stages, preparation, root)

    def approve_and_dispatch(
        self,
        proposal: RestartProposal,
        command: ResumeProjectDelivery,
    ) -> ContinuationDispatchRecord:
        plan, store = proposal.plan, proposal.store()
        if command.approved_plan_sha256 != plan.plan_sha256 or command.approval_reference is None:
            raise RecoveryRejected("restart requires exact explicit human approval")
        with store.execution_lock():
            self._require_current(proposal)
            store.put_restart_plan(plan)
            try:
                authorization = store.get_restart_authorization(plan.plan_sha256)
            except RecoveryRecordMissing:
                authorization = store.put_restart_authorization(
                    RecoveryAuthorization.create(
                        RecoveryApprovalCommand(
                            operation_id=f"restart_{plan.plan_sha256}",
                            plan_sha256=plan.plan_sha256,
                            approval_reference=command.approval_reference,
                            submitted_at=command.submitted_at,
                        ),
                        VerifiedRecoveryDecision(
                            plan_sha256=plan.plan_sha256,
                            approved=True,
                            approval_reference=command.approval_reference,
                            operator_id="console-operator",
                            rationale="Approved fresh execution before first Coder, same scope",
                            decided_at=command.submitted_at,
                        ),
                    )
                )
            if not authorization.decision.approved:
                raise RecoveryRejected("restart plan was not approved")
            return self._dispatch(proposal, authorization)

    def _require_current(self, proposal: RestartProposal) -> None:
        current = FileProjectDeliveryCheckpointStore(
            proposal.root / "state/project-deliveries",
            read_only=True,
        ).current(proposal.plan.scope.delivery_id)
        if current is None or self.propose(current) != proposal:
            raise RecoveryRejected("restart facts changed; propose and approve a new plan")

    def _dispatch(
        self,
        proposal: RestartProposal,
        authorization: RecoveryAuthorization,
    ) -> ContinuationDispatchRecord:
        plan, original = proposal.plan, proposal.runtime.dispatch.task
        now = authorization.decision.decided_at
        task_id = f"task_continue_{plan.plan_sha256[:32]}"
        source_id = proposal.runtime.dispatch.id
        context_sha = digest([s.to_wire() for s in restart_context(plan)])
        task = Task.model_validate(
            {
                **original.to_wire(),
                "id": task_id,
                "branch_name": plan.target_branch_name,
                "base_ref": (
                    plan.target_base_revision
                    if plan.restart_kind == "preparation_rebind"
                    else original.base_ref
                ),
                "created_at": now,
                "updated_at": now,
                "metadata": {
                    **original.metadata,
                    "continuation_kind": "pre_execution_restart",
                    "continuation_sha256": plan.plan_sha256,
                    "continuation_plan_sha256": plan.plan_sha256,
                    "continuation_context_sha256": context_sha,
                    "continuation_target_preparation_sha256": plan.target_preparation_sha256,
                    "continuation_of_delivery_id": plan.scope.delivery_id,
                    "continuation_of_task_id": original.id,
                    "continuation_source_base_revision": original.base_ref,
                    "continuation_source_revision": original.base_ref,
                    "continuation_source_dispatch_id": source_id,
                    "restart_source_checkpoint_sha256": plan.source_checkpoint_sha256,
                },
            }
        )
        agents, policy = self.backend._workforce()
        workforce = FileTeamWorkforceStore(self.backend._organization)
        saved_agents = tuple(workforce.put_agent(agent) for agent in agents)
        saved_policy = workforce.put_policy(policy, versioned=True)
        facts = self.backend._facts(proposal.preparation)
        authority = MySqlDispatchAuthority(
            self.config.require_mysql_dsn(self.environment),
            request_revisions=facts.product,
            planner_records=facts.planning,
        )
        authority.seed_snapshot(
            _snapshot(
                task,
                proposal.stages.plan,
                plan.scope.repository_id,
                saved_agents,
                (saved_policy,),
            )
        )

        def validate(existing: ContinuationDispatchRecord | None) -> None:
            self._require_current(proposal)
            if existing is not None:
                require_restart_dispatch(plan, existing)
                if existing.task != task:
                    raise RecoveryRejected("restart dispatch differs from approved Task")

        def build(snapshot: DispatchWorkforceSnapshot) -> ContinuationDispatchRecord:
            preview = PlanningPreviewService(
                scheduler=PortfolioScheduler(),
                model_router=ModelRouter(
                    route_context_capacities={
                        (r.provider, r.model): 2_000_000
                        for p in snapshot.model_policies
                        for r in p.routes
                    }
                ),
            ).preview(
                task=task,
                work_item=snapshot.work_item,
                execution_plan=proposal.stages.plan,
                agents=snapshot.agents,
                active_leases=snapshot.active_leases,
                assignments=snapshot.assignments,
                policies=snapshot.model_policies,
                previewed_at=now,
            )
            phases: list[DispatchPhaseCommit] = []
            for phase in preview.phases:
                assignment, route = phase.assignment_decision, phase.model_routing_decision
                if (
                    assignment.agent_id is None
                    or assignment.assignment is None
                    or assignment.lease is None
                    or route is None
                    or route.selection is None
                ):
                    raise RecoveryRejected(f"no current {phase.role.value} allocation for restart")
                phases.append(
                    DispatchPhaseCommit(
                        phase_id=phase.phase_id,
                        role=phase.role,
                        agent_id=assignment.agent_id,
                        assignment=assignment.assignment,
                        lease=assignment.lease,
                        model_selection=route.selection,
                    )
                )
            value = ContinuationDispatchRecord(
                id=f"dispatch_commit_{plan.plan_sha256}",
                task_id=task.id,
                repository_id=plan.scope.repository_id,
                project_request_id=proposal.runtime.dispatch.project_request_id,
                execution_plan_id=proposal.stages.plan.id,
                execution_plan_sha256=proposal.stages.plan.execution_plan_sha256,
                execution_plan_phase_ids=proposal.runtime.dispatch.execution_plan_phase_ids,
                continuation_kind="pre_execution_restart",
                continuation_sha256=plan.plan_sha256,
                continuation_plan_sha256=plan.plan_sha256,
                continuation_context_sha256=context_sha,
                target_preparation_sha256=plan.target_preparation_sha256,
                source_delivery_id=plan.scope.delivery_id,
                source_task_id=plan.source_task_id,
                source_base_revision=original.base_ref,
                source_revision=original.base_ref,
                source_dispatch_id=source_id,
                workforce_snapshot_sha256=snapshot.snapshot_sha256,
                task=task,
                phases=tuple(phases),
                committed_at=now,
                dispatch_sha256="0" * 64,
            )
            return value.model_copy(update={"dispatch_sha256": _record_digest(value)})

        return authority.commit_continuation(
            repository_id=plan.scope.repository_id,
            task_id=task.id,
            continuation_sha256=plan.plan_sha256,
            validate_current=validate,
            build=build,
        )


def require_restart_dispatch(
    plan: PreExecutionRestartPlan, dispatch: ContinuationDispatchRecord
) -> None:
    plan.validate_integrity()
    dispatch.validate_integrity()
    if (
        dispatch.continuation_kind != "pre_execution_restart"
        or dispatch.continuation_plan_sha256 != plan.plan_sha256
        or dispatch.source_task_id != plan.source_task_id
        or dispatch.source_dispatch_id != plan.source_dispatch_id
        or dispatch.source_base_revision != plan.target_base_revision
        or dispatch.source_delivery_id != plan.scope.delivery_id
        or dispatch.repository_id != plan.scope.repository_id
        or dispatch.task.repository != plan.scope.repository_root
        or dispatch.task.base_ref != plan.target_base_revision
        or dispatch.task.branch_name != plan.target_branch_name
        or dispatch.target_preparation_sha256 != plan.target_preparation_sha256
        or dispatch.task.metadata.get("restart_source_checkpoint_sha256")
        != plan.source_checkpoint_sha256
        or digest([s.to_wire() for s in restart_context(plan)])
        != dispatch.continuation_context_sha256
    ):
        raise RecoveryRejected("restart allocation does not match approved plan")


def restart_context(plan: PreExecutionRestartPlan) -> tuple[ContextSource, ...]:
    if plan.restart_kind == "preparation_rebind":
        content = (
            f"Original Task {plan.source_task_id} was dispatched but never started. "
            "Its preparation facts changed before the first role claimed work. "
            "This approved successor is bound to the current preparation and base; "
            "it is a fresh execution of the same approved requirement, not retained code. "
            "Independent Coder, QA and Reviewer gates remain mandatory."
        )
    else:
        content = (
            f"Original Task {plan.source_task_id} stopped before the first Coder. "
            "This is an approved fresh execution of the same requirements, not retained code. "
            "No implementation or passing verdict exists; all original acceptance gates apply."
        )
    return (
        *plan.context_sources,
        ContextSource(
            source_id="restart.authorization",
            uri=f"pre-execution-restart://{plan.plan_sha256}",
            content=content,
            required=True,
            priority=2,
        ),
    )


def _require_no_execution(
    config: ProductionConfig,
    root: Path,
    runtime: CandidateRuntimeSnapshot,
) -> None:
    for directory in (root / "artifacts", root / "contexts", model_route_root(root)):
        _reject_symlinks(directory)
    if FileArtifactStore(root / "artifacts", read_only=True).list_for_task(runtime.task.id):
        raise RecoveryRejected("pre-execution source already has artifacts")
    contexts = FileContextStore(root / "contexts", read_only=True)
    for path in (root / "contexts").glob("*.json"):
        _reject_symlinks(path)
        if contexts.get(path.stem).task_id == runtime.task.id:
            raise RecoveryRejected("pre-execution source already has a role context")
    routes_root = model_route_root(root)
    if routes_root.exists():
        routes = FileModelRouteAttemptStore(routes_root, read_only=True)
        for directory in routes_root.iterdir():
            _reject_symlinks(directory)
            if any(r.task_id == runtime.task.id for r in routes.list_for_run(directory.name)):
                raise RecoveryRejected("pre-execution source already has a model invocation")
    worktree = (
        Path(config.platform_root) / "worktrees" / runtime.dispatch.repository_id / runtime.task.id
    )
    if worktree.exists() or worktree.is_symlink():
        raise RecoveryRejected("pre-execution source has a retained workspace; inspect it first")
