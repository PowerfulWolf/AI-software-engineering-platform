"""Human-operated production recovery entry; no terminal history is rewritten."""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ai_software_engineer.company_workspace import _read_regular, _reject_symlinks
from ai_software_engineer.config import ModelProviderKind, ProductionConfig
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.domain import AgentRole, Task, TaskStatus
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.orchestration import RetryResult
from ai_software_engineer.planning import FileExecutionPlanStore
from ai_software_engineer.product import FileProductRecordStore
from ai_software_engineer.project_manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.project_manager.mysql_dispatch_authority import (
    MySqlDispatchAuthority,
    _decode_allocation,
)
from ai_software_engineer.project_manager.production_backend import (
    ProductionProjectDeliveryBackend,
    _agent_definitions,
    _task_commands,
)
from ai_software_engineer.project_manager.production_delivery import (
    ConfiguredDeliveryRouteAdapterFactory,
    DeliveryRouteAdapterFactory,
)
from ai_software_engineer.recovery.allocation import RecoveryAllocator
from ai_software_engineer.recovery.context import recovery_context_sources
from ai_software_engineer.recovery.current import NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.models import (
    CapturedChanges,
    RecoveryApprovalCommand,
    RecoveryInputMode,
    RecoveryPlan,
    RecoveryRejected,
    RecoveryScope,
    VerifiedRecoveryDecision,
)
from ai_software_engineer.recovery.native import NativeRecoverySourceReader
from ai_software_engineer.recovery.sealing import RecoveryTaskSealingService
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.recovery.service import RecoveryAuthorizationService
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.task import AuthorizedRecoveryTaskBuilder
from ai_software_engineer.role_workspace import DispatchRoleWorktreeCoordinator, RoleWorktreeSession
from ai_software_engineer.runtime_workspace import FileOrganizationWorkforceStore
from ai_software_engineer.store import MySqlTaskRepository, TaskNotFound
from ai_software_engineer.store.mysql_repository import _decode_task, open_mysql_connection


def open_recovery_plan(
    config: ProductionConfig, path: Path
) -> tuple[FileRecoveryStore, RecoveryPlan]:
    """Read-only exact company/store resolution, usable without constructing Team Host."""
    _reject_symlinks(path)
    envelope = json.loads(_read_regular(path, 8_000_000))
    plan = RecoveryPlan.model_validate(envelope["record"])
    expected = (
        Path(config.platform_root)
        / "companies"
        / config.company_id
        / "projects"
        / plan.source.scope.project_id
        / "state"
        / f"recovery-{plan.source.scope.delivery_id}"
        / f"plan-{plan.plan_sha256}.json"
    )
    if path != expected or plan.source.scope.company_id != config.company_id:
        raise RecoveryRejected("plan is outside the selected company recovery store")
    store = FileRecoveryStore(path.parent, scope=plan.source.scope)
    return store, store.get_plan(plan.plan_sha256)


def read_recovery_task(
    config: ProductionConfig,
    environment: Mapping[str, str],
    store: FileRecoveryStore,
    plan: RecoveryPlan,
) -> Task | None:
    """Read an already materialized recovery Task; no repository constructor or DDL."""
    connection = open_mysql_connection(config.require_mysql_dsn(environment))
    try:
        with connection.cursor() as cursor:
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            cursor.execute(
                "SELECT * FROM dispatch_commits WHERE id = %s",
                (f"dispatch_commit_{plan.plan_sha256}",),
            )
            row = cast(Mapping[str, object] | None, cursor.fetchone())
            if row is None:
                return None
            dispatch = _decode_allocation(row)
            sealed = store.get_task_record(plan.plan_sha256)
            if (
                not isinstance(dispatch, RecoveryDispatchRecord)
                or dispatch.task != sealed.task
                or dispatch.recovery_task_record_sha256 != sealed.record_sha256
            ):
                raise RecoveryRejected("recovery dispatch differs from sealed Task")
            cursor.execute("SELECT * FROM tasks WHERE id = %s", (plan.new_task_id,))
            row = cast(Mapping[str, object] | None, cursor.fetchone())
            if row is None:
                return None
            task = _decode_task(plan.new_task_id, str(row["payload_json"]))
            normalized = task.model_copy(
                update={
                    "status": TaskStatus.NEW,
                    "attempts": 0,
                    "updated_at": dispatch.task.updated_at,
                }
            )
            if normalized != dispatch.task or task.status.value != row["status"]:
                raise RecoveryRejected("Task snapshot differs from recovery allocation")
            return task
    finally:
        connection.rollback()
        connection.close()


class ExplicitRecoveryHuman:
    """Local operator port, instantiated only after exact plan confirmation."""

    def __init__(self, confirmed_plan: str | None) -> None:
        self.confirmed_plan = confirmed_plan

    def verify(self, command: RecoveryApprovalCommand) -> VerifiedRecoveryDecision:
        if command.plan_sha256 != self.confirmed_plan:
            raise RecoveryRejected("explicit human confirmation of this exact plan is required")
        return VerifiedRecoveryDecision(
            plan_sha256=command.plan_sha256,
            approval_reference=command.approval_reference,
            approved=True,
            operator_id="local-operator",
            rationale="Explicitly approved original solution reuse, target base and captured edits",
            decided_at=command.submitted_at,
        )


class NativeRecoveryEntry:
    def __init__(
        self,
        config: ProductionConfig,
        environment: Mapping[str, str],
        backend: ProductionProjectDeliveryBackend,
    ) -> None:
        self.config, self.environment, self.backend = config, dict(environment), backend

    def propose(
        self,
        *,
        project_root: str,
        delivery_id: str,
        failed_run_id: str,
        failed_context_id: str,
        input_mode: RecoveryInputMode | None = None,
    ) -> tuple[RecoveryPlan, Path]:
        prepared = self.backend.prepare(project_root).preparation
        if prepared is None:
            raise RecoveryRejected("project preparation needs human resolution")
        scope = RecoveryScope(
            company_id=self.config.company_id,
            project_id=prepared.project_id,
            project_root=prepared.project_root,
            delivery_id=delivery_id,
        )
        original = NativeRecoverySourceReader(self.config, self.environment).inspect(
            scope,
            failed_run_id=failed_run_id,
            failed_context_id=failed_context_id,
        )
        manager = self._manager(scope)
        old = manager.recover(
            WorktreeSpec(
                task_id=original.task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=original.source.base_revision,
            )
        )
        capture = manager.capture_changes(
            old, original.permissions, denied_paths=original.denied_paths
        )
        plan = RecoveryPlan.create(
            input_mode=input_mode,
            source=original.source,
            capture=CapturedChanges.from_capture(capture),
            target_base_revision=manager._run_git(("rev-parse", "HEAD"), cwd=Path(project_root)),
            target_preparation_sha256=prepared.preparation_sha256,
            permissions=original.permissions,
            denied_paths=original.denied_paths,
            created_at=datetime.now(UTC),
        )
        store = FileRecoveryStore.initialize(
            Path(prepared.project_workspace_root) / "state" / f"recovery-{delivery_id}",
            scope=scope,
        )
        self._services(store, plan, None)[0].propose(plan)
        return plan, Path(
            prepared.project_workspace_root
        ) / "state" / f"recovery-{delivery_id}" / f"plan-{plan.plan_sha256}.json"

    def open_plan(self, path: Path) -> tuple[FileRecoveryStore, RecoveryPlan]:
        return open_recovery_plan(self.config, path)

    def approve(self, path: Path, *, confirmed_plan: str, reference: str) -> None:
        store, plan = self.open_plan(path)
        command = RecoveryApprovalCommand(
            operation_id=f"op_recovery_{plan.plan_sha256[:32]}",
            plan_sha256=plan.plan_sha256,
            approval_reference=reference,
            submitted_at=datetime.now(UTC),
        )
        prior = store.find_authorization(plan.plan_sha256)
        if prior is not None:
            if prior.command.approval_reference != reference or confirmed_plan != plan.plan_sha256:
                raise RecoveryRejected("approval replay differs from original confirmation")
            command = prior.command
        service, _, sealing = self._services(store, plan, confirmed_plan)
        service.authorize(command)
        sealing.seal(plan.plan_sha256)

    def _manager(self, scope: RecoveryScope) -> GitWorktreeManager:
        return GitWorktreeManager(
            scope.project_root, Path(self.config.platform_root) / "worktrees" / scope.project_id
        )

    def _services(
        self, store: FileRecoveryStore, plan: RecoveryPlan, confirmed: str | None
    ) -> tuple[
        RecoveryAuthorizationService, AuthorizedRecoveryTaskBuilder, RecoveryTaskSealingService
    ]:
        facts = NativeRecoveryFactsVerifier(self.config, self.environment)
        service = RecoveryAuthorizationService(
            store,
            facts=facts,
            captures=self._manager(plan.source.scope),
            human=ExplicitRecoveryHuman(confirmed),
        )
        builder = AuthorizedRecoveryTaskBuilder(service, facts)
        return service, builder, RecoveryTaskSealingService(store, builder)

    def execute(
        self,
        path: Path,
        *,
        route_factory: Callable[[RecoverySeedService], DeliveryRouteAdapterFactory] | None = None,
    ) -> RetryResult:
        """One fresh serial attempt. Uncertain prior provider invocation requires inspection."""
        if not self.config.live_model_execution:
            raise RecoveryRejected("live model execution is disabled")
        routes = self.config.enabled_routes()
        if len(routes) != 1 or routes[0].kind is not ModelProviderKind.CODEX_CLI:
            raise RecoveryRejected("seed recovery currently requires one explicit Codex route")
        store, plan = self.open_plan(path)
        with store.execution_lock():
            return self._execute(store, plan, route_factory)

    def _execute(
        self,
        store: FileRecoveryStore,
        plan: RecoveryPlan,
        route_factory: Callable[[RecoverySeedService], DeliveryRouteAdapterFactory] | None,
    ) -> RetryResult:
        _, builder, sealing = self._services(store, plan, None)
        sealed = sealing.require_current(plan.plan_sha256)
        try:
            store.get_invocation(plan.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            raise RecoveryRejected(
                "recovery Coder already admitted; inspect Task/artifacts, do not rerun"
            )
        dsn = self.config.require_mysql_dsn(self.environment)
        repository = MySqlTaskRepository(dsn)
        try:
            try:
                task = repository.get(sealed.task.id)
            except TaskNotFound:
                pass
            else:
                if task.status not in (
                    TaskStatus.NEW,
                    TaskStatus.PLANNING,
                    TaskStatus.IMPLEMENTING,
                ) or task.attempts not in (0, 1):
                    raise RecoveryRejected(
                        "recovery Task already advanced; inspect its durable history"
                    )
        finally:
            repository.close()
        draft = builder.build(plan.plan_sha256)
        preparation = self.backend.prepare(draft.facts.target.project_root)
        if preparation.preparation != draft.facts.target:
            raise RecoveryRejected("prepared target changed before execution")
        sidecar = Path(draft.facts.target.project_workspace_root)
        authority = MySqlDispatchAuthority(
            dsn,
            request_revisions=FileProductRecordStore(sidecar / "state/product"),
            planner_records=FileExecutionPlanStore(sidecar / "state/planning"),
        )
        agents, policy = self.backend._workforce()
        workforce = FileOrganizationWorkforceStore(self.backend._organization)
        saved_agents = tuple(workforce.put_agent(a) for a in agents)
        policy = workforce.put_policy(policy, versioned=True)
        dispatch = RecoveryAllocator(
            sealing=sealing,
            builder=builder,
            authority=authority,
            agents=saved_agents,
            policies=(policy,),
        ).allocate(plan.plan_sha256)
        definitions = _agent_definitions(dispatch, _task_commands(draft.facts.profile))
        if definitions[AgentRole.CODER].permissions != plan.permissions:
            raise RecoveryRejected("new Coder permissions differ from approved recovery")
        manager = self._manager(plan.source.scope)
        coordinator = DispatchRoleWorktreeCoordinator(
            RoleWorktreeSession(manager, environment=self.environment)
        )
        target_path = (
            Path(self.config.platform_root)
            / "worktrees"
            / dispatch.project_id
            / dispatch.task_id
            / "coder-attempt-01"
        )
        binding = coordinator.open_coder(dispatch, definitions, recover=target_path.exists())
        contexts = FileContextStore(sidecar / "contexts")
        seed = RecoverySeedService(
            store=store,
            sealing=sealing,
            manager=manager,
            dispatch=dispatch,
            permissions=definitions[AgentRole.CODER].permissions,
            contexts=contexts,
        )
        seed.seed(binding.worktree)
        old_context = contexts.get(plan.source.failed_context_id)
        extra = tuple(
            ContextSource(
                source_id="joint.approved_context",
                uri=s.uri,
                content=s.content,
                priority=s.priority,
                required=True,
            )
            for s in old_context.sections
            if s.name == "source:joint.approved_context"
        )
        if plan.source.parent_delivery_id is not None and not extra:
            raise RecoveryRejected("recovery lost approved joint context")
        # Test factories must explicitly honor the same admission port; real Codex receives it here.
        factory = (
            route_factory(seed)
            if route_factory is not None
            else ConfiguredDeliveryRouteAdapterFactory(initial_workspace_admission=seed)
        )
        return self.backend.run_prepared_allocation(
            dispatch,
            preparation,
            draft.facts.original.product,
            draft.facts.original.design,
            draft.facts.original.plan,
            route_adapters=factory,
            extra_context=(*extra, *recovery_context_sources(plan)),
        )
