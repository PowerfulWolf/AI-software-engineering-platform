"""Human-operated production recovery entry; no terminal history is rewritten."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.agents.codex_cli import InitialWorkspaceAdmission
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import (
    ModelProviderKind,
    ProductionConfig,
    ProviderRouteConfig,
)
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.domain import (
    AgentRole,
    Task,
    TaskStatus,
    TeamRole,
)
from ai_software_engineer.domain.branch import BranchName, available_successor_branch
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal, OperatorDuty
from ai_software_engineer.domain.task import task_matches_dispatch
from ai_software_engineer.git import GitWorktreeManager, WorktreeNotFound, WorktreeSpec
from ai_software_engineer.git.policy import is_protected_rule_path
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGap,
    KnowledgeGapRaised,
)
from ai_software_engineer.manager.delivery_checkpoint import ProjectDeliveryCheckpoint
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.manager.mysql_dispatch_authority import (
    MySqlDispatchAuthority,
    _decode_allocation,
)
from ai_software_engineer.manager.production_backend import (
    ProductionProjectDeliveryBackend,
    _agent_definitions,
    _delivery_role_permissions,
    _task_commands,
)
from ai_software_engineer.manager.production_delivery import (
    ConfiguredDeliveryRouteAdapterFactory,
    DeliveryRouteAdapterFactory,
)
from ai_software_engineer.orchestration import RetryResult
from ai_software_engineer.planning import FileExecutionPlanStore
from ai_software_engineer.product import FileProductRecordStore
from ai_software_engineer.recovery.allocation import RecoveryAllocator
from ai_software_engineer.recovery.context import (
    approved_parent_context,
    preserved_native_verdict_context,
    preserved_prerequisite_context,
    preserved_verification_context,
    recovery_context_sources,
)
from ai_software_engineer.recovery.current import NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.models import (
    CapturedChanges,
    RecoveryApprovalCommand,
    RecoveryAuthorization,
    RecoveryInputMode,
    RecoveryPlan,
    RecoveryRejected,
    RecoveryScope,
    RecoveryScopeRequest,
    RecoveryScopeSupplement,
    SafeText,
    VerifiedRecoveryDecision,
    digest,
)
from ai_software_engineer.recovery.native import NativeRecoverySourceReader
from ai_software_engineer.recovery.scope import (
    expanded_recovery_permissions,
    inspect_recovery_scope_supplement,
)
from ai_software_engineer.recovery.sealing import RecoveryTaskSealingService
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.recovery.service import RecoveryAuthorizationService
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.task import AuthorizedRecoveryTaskBuilder
from ai_software_engineer.recovery.workspace_snapshot import read_terminal_workspace_snapshot
from ai_software_engineer.redaction import source_inspection_scope
from ai_software_engineer.role_workspace import DispatchRoleWorktreeCoordinator, RoleWorktreeSession
from ai_software_engineer.runtime_workspace import FileTeamWorkforceStore
from ai_software_engineer.store import MySqlTaskRepository, TaskNotFound
from ai_software_engineer.store.mysql_repository import _decode_task, open_mysql_connection
from ai_software_engineer.team_workspace import TeamWorkspace, _read_regular, _reject_symlinks

if TYPE_CHECKING:
    from ai_software_engineer.recovery.interruption import RecoveryInterruptionService


@dataclass(frozen=True)
class NativeRecoveryExecution:
    """One approved recovery allocation plus its serial delivery result."""

    plan: RecoveryPlan
    dispatch: RecoveryDispatchRecord
    delivery: RetryResult | KnowledgeGap


def _require_seed_recovery_route(config: ProductionConfig) -> ProviderRouteConfig:
    """Select one policy-ordered Codex route for the approved recovery execution."""
    routes = tuple(
        route
        for route in config.routes_for(TeamRole.CODER)
        if route.kind is ModelProviderKind.CODEX_CLI
    )
    if not routes:
        raise RecoveryRejected("seed recovery requires an explicit Coder Codex route")
    return routes[0]


def _append_exact_paths(current: tuple[str, ...], additions: tuple[str, ...]) -> tuple[str, ...]:
    return (*current, *(path for path in additions if path not in current))


def _repository_sidecar(config: ProductionConfig, repository_id: str) -> Path:
    team = TeamWorkspace.initialize(
        config.platform_root,
        team_id=config.team_id,
        name=config.team_name,
        read_only=True,
    )
    _, repository = team.project_registry().locate_repository(repository_id)
    return repository.root


def _approved_parent_context(
    config: ProductionConfig, plan: RecoveryPlan
) -> tuple[ContextSource, ...]:
    """Rebuild exact joint context from its durable approved parent checkpoint.

    A remediation Coder context may contain only the verification verdict and patch.
    Recovery therefore cannot assume the immediately failed context still embeds the
    original parent payload.  The parent IDs sealed into RecoverySource identify the
    authoritative joint checkpoint from which the canonical context is reconstructed.
    """
    return approved_parent_context(
        config,
        plan.source.scope,
        plan.source.parent_delivery_id,
        plan.source.parent_checkpoint_sha256,
    )


def open_recovery_plan(
    config: ProductionConfig, path: Path
) -> tuple[FileRecoveryStore, RecoveryPlan]:
    """Read-only exact team/store resolution, usable without constructing Team Host."""
    _reject_symlinks(path)
    envelope = json.loads(_read_regular(path, 8_000_000))
    plan = RecoveryPlan.model_validate(envelope["record"])
    expected = (
        _repository_sidecar(config, plan.source.scope.repository_id)
        / "state"
        / f"recovery-{plan.source.scope.delivery_id}"
        / f"plan-{plan.plan_sha256}.json"
    )
    if path != expected or plan.source.scope.team_id != config.team_id:
        raise RecoveryRejected("plan is outside the selected team recovery store")
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
            if not task_matches_dispatch(task, dispatch.task) or task.status.value != row["status"]:
                raise RecoveryRejected("Task snapshot differs from recovery allocation")
            return task
    finally:
        connection.rollback()
        connection.close()


class ExplicitRecoveryHuman:
    """Local operator port, instantiated only after exact plan confirmation."""

    def __init__(
        self, confirmed_plan: str | None, principal: LocalOperatorPrincipal | None = None
    ) -> None:
        self.confirmed_plan = confirmed_plan
        self.principal = principal

    def verify(self, command: RecoveryApprovalCommand) -> VerifiedRecoveryDecision:
        if self.principal is not None:
            self.principal.require_duty(OperatorDuty.ENGINEERING)
        if command.plan_sha256 != self.confirmed_plan:
            raise RecoveryRejected("explicit human confirmation of this exact plan is required")
        return VerifiedRecoveryDecision(
            plan_sha256=command.plan_sha256,
            approval_reference=command.approval_reference,
            approved=True,
            operator_id=self.principal.operator_id if self.principal else "local-operator",
            rationale="Explicitly approved original solution reuse, target base and captured edits",
            decided_at=command.submitted_at,
        )


class NativeRecoveryEntry:
    def __init__(
        self,
        config: ProductionConfig,
        environment: Mapping[str, str],
        backend: ProductionProjectDeliveryBackend,
        *,
        operator_principal: LocalOperatorPrincipal | None = None,
    ) -> None:
        self.config, self.environment, self.backend = config, dict(environment), backend
        self.operator_principal = operator_principal
        self._facts = NativeRecoveryFactsVerifier(config, self.environment)

    @source_inspection_scope()
    def propose(
        self,
        *,
        repository_root: str,
        delivery_id: str,
        failed_run_id: str,
        failed_context_id: str,
        input_mode: RecoveryInputMode | None = None,
        target_branch_name: BranchName | None = None,
        approved_scope_sha256: str | None = None,
        scope_approval_reference: str | None = None,
        coder_scope_request: RecoveryScopeRequest | None = None,
    ) -> tuple[RecoveryPlan, Path]:
        prepared_result = self.backend.prepare(repository_root)
        prepared = prepared_result.preparation
        if prepared is None:
            raise RecoveryRejected("project preparation needs human resolution")
        scope = RecoveryScope(
            team_id=self.config.team_id,
            repository_id=prepared.repository_id,
            repository_root=prepared.repository_root,
            delivery_id=delivery_id,
        )
        original = NativeRecoverySourceReader(self.config, self.environment).inspect(
            scope,
            failed_run_id=failed_run_id,
            failed_context_id=failed_context_id,
        )
        manager = self._manager(scope, {original.task.id: original.task.branch_name})
        source_spec = WorktreeSpec(
            task_id=original.task.id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=original.worktree_revision,
        )
        restored_clean_source = False
        try:
            old = manager.recover(source_spec)
        except WorktreeNotFound:
            old = manager.restore_clean_coder(source_spec)
            restored_clean_source = True
        if restored_clean_source:
            input_mode = "coder_reapply"
        supplement = inspect_recovery_scope_supplement(
            manager, old, original, request=coder_scope_request
        )
        if supplement is not None:
            if (
                approved_scope_sha256 != supplement.supplement_sha256
                or not scope_approval_reference
            ):
                raise RecoveryRejected(
                    "explicit approval of the exact recovery scope supplement is required"
                )
            try:
                scope_approval_reference = TypeAdapter(SafeText).validate_python(
                    scope_approval_reference
                )
            except ValidationError as error:
                raise RecoveryRejected("recovery scope approval reference is unsafe") from error
        elif approved_scope_sha256 is not None or scope_approval_reference is not None:
            raise RecoveryRejected("recovery scope approval does not match current changed paths")
        source_permissions = expanded_recovery_permissions(original.permissions, supplement)
        capture = manager.capture_legacy_changes(
            old,
            source_permissions,
            denied_paths=original.denied_paths,
            base_revision=original.source.effective_base_revision,
        )
        captured = CapturedChanges.from_capture(capture)
        workspace_snapshot = read_terminal_workspace_snapshot(
            self.config,
            self.environment,
            original,
            captured,
            approved_permissions=source_permissions,
            scope_supplement=supplement,
        )
        constraints = original.task.constraints
        allowed_paths = constraints.allowed_paths if constraints is not None else ()
        if supplement is not None:
            allowed_paths = _append_exact_paths(allowed_paths, supplement.paths)
        quarantined_paths = tuple(
            path for path in capture.changed_paths if is_protected_rule_path(path)
        )
        if quarantined_paths:
            input_mode = "coder_reapply"
        target_permissions = _delivery_role_permissions(
            AgentRole.CODER,
            allowed_paths,
            _task_commands(self.backend._facts(prepared_result).profile),
        )
        target_branch_name = target_branch_name or available_successor_branch(
            original.product.branch_name or original.task.branch_name,
            "recovery",
            is_occupied=manager.branch_exists,
        )
        if target_branch_name is not None:
            target_branch_name = TypeAdapter(BranchName).validate_python(target_branch_name)
            if manager.branch_exists(target_branch_name):
                raise RecoveryRejected(
                    "recovery target branch already exists; propose again with "
                    "--target-branch-name and a meaningful scope qualifier, "
                    "then approve the new plan"
                )
        plan = RecoveryPlan.create(
            input_mode=input_mode,
            source=original.source,
            capture=captured,
            workspace_snapshot=workspace_snapshot,
            target_base_revision=manager._run_git(("rev-parse", "HEAD"), cwd=Path(repository_root)),
            target_preparation_sha256=prepared.preparation_sha256,
            target_branch_name=target_branch_name,
            scope_supplement=supplement,
            scope_approval_reference=scope_approval_reference if supplement is not None else None,
            permissions=source_permissions,
            target_permissions=target_permissions,
            quarantined_paths=quarantined_paths or None,
            denied_paths=original.denied_paths,
            created_at=datetime.now(UTC),
        )
        store = FileRecoveryStore.initialize(
            Path(prepared.repository_workspace_root) / "state" / f"recovery-{delivery_id}",
            scope=scope,
        )
        self._services(store, plan, None)[0].propose(plan)
        return plan, Path(
            prepared.repository_workspace_root
        ) / "state" / f"recovery-{delivery_id}" / f"plan-{plan.plan_sha256}.json"

    def scope_supplement(
        self, checkpoint: ProjectDeliveryCheckpoint, *, request: RecoveryScopeRequest | None = None
    ) -> RecoveryScopeSupplement | None:
        """Discover exact omitted changed paths without reading their file contents."""
        scope = RecoveryScope(
            team_id=self.config.team_id,
            repository_id=checkpoint.repository_id,
            repository_root=checkpoint.repository_root,
            delivery_id=checkpoint.delivery_id,
        )
        original = NativeRecoverySourceReader(self.config, self.environment).discover_failed_coder(
            scope
        )
        manager = self._manager(scope, {original.task.id: original.task.branch_name})
        try:
            old = manager.recover(
                WorktreeSpec(
                    task_id=original.task.id,
                    role=AgentRole.CODER,
                    attempt=1,
                    source_revision=original.worktree_revision,
                )
            )
        except WorktreeNotFound:
            # A clean terminal provider failure is removed by normal workspace cleanup.
            # Proposal performs the bounded branch-identity repair; scope inspection has
            # no omitted changed paths when no worktree evidence remains.
            if request is not None:
                raise RecoveryRejected(
                    "requested scope requires a retained Coder worktree"
                ) from None
            return None
        return inspect_recovery_scope_supplement(manager, old, original, request=request)

    @source_inspection_scope()
    def propose_delivery(
        self,
        checkpoint: ProjectDeliveryCheckpoint,
        *,
        approved_scope_sha256: str | None = None,
        scope_approval_reference: str | None = None,
        coder_scope_request: RecoveryScopeRequest | None = None,
    ) -> tuple[RecoveryPlan, Path]:
        """Discover the failed Coder identity and publish one exact recovery plan."""
        scope = RecoveryScope(
            team_id=self.config.team_id,
            repository_id=checkpoint.repository_id,
            repository_root=checkpoint.repository_root,
            delivery_id=checkpoint.delivery_id,
        )
        source = NativeRecoverySourceReader(self.config, self.environment).discover_failed_coder(
            scope
        )
        return self.propose(
            repository_root=checkpoint.repository_root,
            delivery_id=checkpoint.delivery_id,
            failed_run_id=source.source.failed_run_id,
            failed_context_id=source.source.failed_context_id,
            approved_scope_sha256=approved_scope_sha256,
            scope_approval_reference=scope_approval_reference,
            coder_scope_request=coder_scope_request,
        )

    def latest_delivery(
        self, checkpoint: ProjectDeliveryCheckpoint
    ) -> tuple[FileRecoveryStore, RecoveryPlan, Path] | None:
        """Return the latest plan pinned to this exact terminal Delivery checkpoint."""
        root = (
            _repository_sidecar(self.config, checkpoint.repository_id)
            / "state"
            / f"recovery-{checkpoint.delivery_id}"
        )
        if not root.exists():
            return None
        _reject_symlinks(root)
        matches: list[tuple[RecoveryPlan, Path, FileRecoveryStore]] = []
        for path in sorted(root.glob("plan-*.json")):
            store, plan = self.open_plan(path)
            if plan.source.checkpoint_sha256 == checkpoint.checkpoint_sha256:
                matches.append((plan, path, store))
        if not matches:
            return None
        plan, path, store = max(
            matches,
            key=lambda item: (item[0].created_at, item[0].plan_sha256),
        )
        return store, plan, path

    def open_plan(self, path: Path) -> tuple[FileRecoveryStore, RecoveryPlan]:
        return open_recovery_plan(self.config, path)

    def require_current_plan(self, path: Path) -> RecoveryPlan:
        """Reject a plan whose retained work, policy, target, or scope approval drifted."""
        _, plan = self.open_plan(path)
        self._facts.validate(plan)
        return plan

    @source_inspection_scope()
    def approve(self, path: Path, *, confirmed_plan: str, reference: str) -> None:
        if self.operator_principal is not None:
            self.operator_principal.require_duty(OperatorDuty.ENGINEERING)
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

    def _manager(
        self, scope: RecoveryScope, branch_names: Mapping[str, BranchName | None] | None = None
    ) -> GitWorktreeManager:
        return GitWorktreeManager(
            scope.repository_root,
            Path(self.config.platform_root) / "worktrees" / scope.repository_id,
            branch_names=branch_names,
        )

    def _services(
        self, store: FileRecoveryStore, plan: RecoveryPlan, confirmed: str | None
    ) -> tuple[
        RecoveryAuthorizationService, AuthorizedRecoveryTaskBuilder, RecoveryTaskSealingService
    ]:
        facts = self._facts
        service = RecoveryAuthorizationService(
            store,
            facts=facts,
            # The service validates native facts (including this exact name) before capture.
            captures=self._manager(
                plan.source.scope, {plan.capture.task_id: plan.capture.branch_name}
            ),
            human=ExplicitRecoveryHuman(confirmed, self.operator_principal),
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
        recovery_route = _require_seed_recovery_route(self.config)
        store, plan = self.open_plan(path)
        with store.execution_lock():
            return self._execute(store, plan, route_factory, recovery_route)

    def resume_execution(self, path: Path) -> NativeRecoveryExecution:
        """Execute an unconsumed recovery or adopt its already-terminal Task."""
        recovery_route = _require_seed_recovery_route(self.config)
        store, plan = self.open_plan(path)
        try:
            store.get_invocation(plan.plan_sha256)
        except RecoveryRecordMissing:
            try:
                delivery: RetryResult | KnowledgeGap = self.execute(path)
            except KnowledgeGapRaised as error:
                delivery = self._knowledge_wait(store, plan)
                if delivery != error.gap:
                    raise RecoveryRejected(
                        "recovery knowledge wait differs from durable gap"
                    ) from error
        else:
            task = read_recovery_task(self.config, self.environment, store, plan)
            if task is not None and task.status in {
                TaskStatus.IMPLEMENTING,
                TaskStatus.QA,
                TaskStatus.REVIEW,
            }:
                return NativeRecoveryExecution(
                    plan,
                    self._dispatch_for(store, plan),
                    self._knowledge_wait(store, plan),
                )
            if task is None or task.status not in {
                TaskStatus.DONE,
                TaskStatus.BLOCKED,
                TaskStatus.FAILED,
            }:
                raise RecoveryRejected(
                    "recovery Coder invocation is uncertain; inspect its Task before a successor"
                )
            facts = self._facts.inspect(plan)
            preparation = self.backend.prepare(plan.source.scope.repository_root)
            if preparation.preparation != facts.target:
                raise RecoveryRejected("recovery target changed before terminal adoption")
            dispatch = self._dispatch_for(store, plan)
            delivery = self.backend.run_prepared_allocation(
                dispatch,
                preparation,
                facts.original.product,
                facts.original.design,
                facts.original.plan,
                route_scope=(recovery_route,),
            )
        return NativeRecoveryExecution(
            plan=plan,
            dispatch=self._dispatch_for(store, plan),
            delivery=delivery,
        )

    def execute_interruption(
        self,
        path: Path,
        *,
        confirmed_plan: str,
        reference: str,
        route_factory: Callable[[InitialWorkspaceAdmission], DeliveryRouteAdapterFactory]
        | None = None,
    ) -> NativeRecoveryExecution:
        from datetime import timedelta

        from ai_software_engineer.manager.queue_capacity import production_role_queue
        from ai_software_engineer.recovery.interruption import RecoveryInterruptionService

        if not self.config.live_model_execution:
            raise RecoveryRejected("live model execution is disabled")
        store, plan = self.open_plan(path)
        with store.execution_lock():
            interruption = RecoveryInterruptionService(self, store, plan)
            proposal = interruption.propose()
            if confirmed_plan != proposal.plan_sha256:
                raise RecoveryRejected("exact interruption plan approval is required")
            try:
                approval = store.get_interruption_authorization(plan.plan_sha256)
            except RecoveryRecordMissing:
                command = RecoveryApprovalCommand(
                    operation_id="interruption_" + proposal.plan_sha256[:32],
                    plan_sha256=proposal.plan_sha256,
                    approval_reference=reference,
                    submitted_at=datetime.now(UTC),
                )
                decision = (
                    ExplicitRecoveryHuman(confirmed_plan, self.operator_principal)
                    .verify(command)
                    .model_copy(
                        update={
                            "rationale": (
                                "One replacement Run; exact approved workspace and same Task"
                                if proposal.stopped_capture is not None
                                else "One replacement Run; unchanged seed and Task"
                            )
                        }
                    )
                )
                approval = store.put_interruption_authorization(
                    plan.plan_sha256, RecoveryAuthorization.create(command, decision)
                )
            if not approval.decision.approved:
                raise RecoveryRejected("interruption was not approved")
            interruption.propose()
            # Use the native reaper before expensive preparation, so the normal
            # Dispatcher can claim the next generation when preparation finishes.
            now = datetime.now(UTC)
            production_role_queue(self.config.require_mysql_dsn(self.environment)).reclaim_expired(
                now=now, retry_at=now + timedelta(seconds=1)
            )
            factory = (
                route_factory(interruption)
                if route_factory
                else ConfiguredDeliveryRouteAdapterFactory(initial_workspace_admission=interruption)
            )
            try:
                result: RetryResult | KnowledgeGap = self._execute(
                    store,
                    plan,
                    lambda seed: factory,
                    _require_seed_recovery_route(self.config),
                    interruption=interruption,
                )
            except KnowledgeGapRaised as error:
                result = self._knowledge_wait(store, plan)
                if result != error.gap:
                    raise RecoveryRejected(
                        "replacement knowledge wait differs from durable gap"
                    ) from error
            return NativeRecoveryExecution(plan, self._dispatch_for(store, plan), result)

    def pending_knowledge_wait(self, path: Path) -> NativeRecoveryExecution | None:
        """Adopt only a current queue wait belonging to the approved recovery allocation."""
        store, plan = self.open_plan(path)
        return self._pending_knowledge_wait(store, plan)

    def _pending_knowledge_wait(
        self,
        store: FileRecoveryStore,
        plan: RecoveryPlan,
    ) -> NativeRecoveryExecution | None:
        from ai_software_engineer.recovery.knowledge_wait import pending_recovery_knowledge_wait

        if read_recovery_task(self.config, self.environment, store, plan) is None:
            return None
        dispatch = self._dispatch_for(store, plan)
        team = TeamWorkspace.initialize(
            self.config.platform_root,
            team_id=self.config.team_id,
            name=self.config.team_name,
            read_only=True,
        )
        project, repository = team.project_registry().locate_repository(dispatch.repository_id)
        gap = pending_recovery_knowledge_wait(
            dsn=self.config.require_mysql_dsn(self.environment),
            sidecar=repository.root,
            project_id=project.manifest.project_id,
            plan=plan,
            dispatch=dispatch,
        )
        if gap is None:
            return None
        self._facts.validate(plan)
        authorization = store.get_authorization(plan.plan_sha256)
        if not authorization.decision.approved:
            raise RecoveryRejected("recovery knowledge wait requires exact approval")
        return NativeRecoveryExecution(plan, dispatch, gap)

    def _knowledge_wait(self, store: FileRecoveryStore, plan: RecoveryPlan) -> KnowledgeGap:
        execution = self._pending_knowledge_wait(store, plan)
        if execution is None or not isinstance(execution.delivery, KnowledgeGap):
            raise RecoveryRejected("recovery has no current durable knowledge wait")
        return execution.delivery

    def _dispatch_for(self, store: FileRecoveryStore, plan: RecoveryPlan) -> RecoveryDispatchRecord:
        connection = open_mysql_connection(self.config.require_mysql_dsn(self.environment))
        try:
            with connection.cursor() as cursor:
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                cursor.execute(
                    "SELECT * FROM dispatch_commits WHERE id=%s",
                    (f"dispatch_commit_{plan.plan_sha256}",),
                )
                row = cast(Mapping[str, object] | None, cursor.fetchone())
                if row is None:
                    raise RecoveryRejected("recovery allocation is missing")
                dispatch = _decode_allocation(row)
        finally:
            connection.rollback()
            connection.close()
        sealed = store.get_task_record(plan.plan_sha256)
        if (
            not isinstance(dispatch, RecoveryDispatchRecord)
            or dispatch.task != sealed.task
            or dispatch.recovery_task_record_sha256 != sealed.record_sha256
        ):
            raise RecoveryRejected("recovery allocation differs from the approved Task")
        return dispatch

    def _execute(
        self,
        store: FileRecoveryStore,
        plan: RecoveryPlan,
        route_factory: Callable[[RecoverySeedService], DeliveryRouteAdapterFactory] | None,
        recovery_route: ProviderRouteConfig,
        *,
        interruption: "RecoveryInterruptionService | None" = None,
    ) -> RetryResult:
        _, builder, sealing = self._services(store, plan, None)
        sealed = sealing.require_current(plan.plan_sha256)
        try:
            store.get_invocation(plan.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            if interruption is not None:
                interruption.propose()
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
        preparation = self.backend.prepare(draft.facts.target.repository_root)
        if preparation.preparation != draft.facts.target:
            raise RecoveryRejected("prepared target changed before execution")
        sidecar = Path(draft.facts.target.repository_workspace_root)
        authority = MySqlDispatchAuthority(
            dsn,
            request_revisions=FileProductRecordStore(sidecar / "state/product"),
            planner_records=FileExecutionPlanStore(sidecar / "state/planning"),
        )
        agents, policy = self.backend._workforce()
        selected_routes = tuple(
            route
            for route in policy.routes
            if route.provider == recovery_route.provider
            and route.model == recovery_route.model
            and route.reasoning_effort == recovery_route.reasoning_effort
            and route.route_kind == recovery_route.kind.value
            and route.connection_mode == self.config.effective_connection_mode(recovery_route)
        )
        if len(selected_routes) != 1:
            raise RecoveryRejected("selected recovery route is absent or ambiguous in policy")
        policy = policy.model_copy(update={"routes": selected_routes, "role_routes": ()})
        policy = policy.model_copy(
            update={
                "version": "v0.1-recovery-"
                + digest(policy.model_dump(mode="json", exclude={"version"}))
            }
        )
        workforce = FileTeamWorkforceStore(self.backend._organization)
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
        if definitions[AgentRole.CODER].permissions != plan.effective_target_permissions:
            raise RecoveryRejected("new Coder permissions differ from approved recovery")
        manager = self._manager(
            plan.source.scope,
            {
                draft.facts.original.task.id: draft.facts.original.task.branch_name,
                dispatch.task_id: dispatch.task.branch_name,
            },
        )
        coordinator = DispatchRoleWorktreeCoordinator(
            RoleWorktreeSession(manager, environment=self.environment)
        )
        target_path = (
            Path(self.config.platform_root)
            / "worktrees"
            / dispatch.repository_id
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
        if interruption is None:
            seed.seed(binding.worktree)
        else:
            interruption.prepare_workspace(binding.worktree)
        extra = (
            *_approved_parent_context(self.config, plan),
            *preserved_native_verdict_context(
                plan, contexts, FileArtifactStore(sidecar / "artifacts", read_only=True)
            ),
        )
        # Failed prerequisite Coder work must retain the separately approved repair objective,
        # not just its dirty files and write allowlist. Read the sealed prior manifest and grant.
        repair_root = sidecar / "state" / f"candidate-verification-{plan.source.scope.delivery_id}"
        verifications = (
            FileRecoveryStore(repair_root, scope=plan.source.scope)
            if repair_root.exists()
            else None
        )
        extra = (*extra, *preserved_verification_context(plan, contexts, verifications))
        if repair_root.exists():
            extra = (
                *extra,
                *preserved_prerequisite_context(
                    plan,
                    contexts,
                    FileRecoveryStore(repair_root, scope=plan.source.scope),
                ),
            )
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
            route_scope=(recovery_route,),
        )
