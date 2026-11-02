"""Read an exactly settled route transition as a same-Requirement recovery source.

The sixth claim had no Run or Context. The only cited Run/Context is the earlier
accepted Coder progress, verified as historical input rather than failure.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import closing
from pathlib import Path

from pydantic import TypeAdapter
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.fallback import model_route_root
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.task import task_matches_dispatch
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.capacity_input_reader import (
    CapacityInputReader,
    UninvokedClaimBoundary,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.mysql_dispatch_authority import _decode_allocation
from ai_software_engineer.orchestration.state_machine import apply_event
from ai_software_engineer.read_record_scope import recovery_record_read_scope
from ai_software_engineer.recovery.allocation_lineage import resolve_planner_dispatch
from ai_software_engineer.recovery.baseline_source import (
    read_recovery_baseline_epochs,
    validate_pre_candidate_sources,
)
from ai_software_engineer.recovery.models import (
    CapturedChanges,
    RecoveryRejected,
    RecoveryScope,
    RecoverySource,
)
from ai_software_engineer.recovery.native import (
    NativeRecoverySource,
    _parent,
    _require_native_active,
    read_approved_stages,
)
from ai_software_engineer.recovery.progress_source import accepted_scope_progress
from ai_software_engineer.recovery.route_transition_claim import (
    RouteTransitionSettlement,
    _ReadOnlyRoleQueue,
    _time,
)
from ai_software_engineer.recovery.route_transition_settlement import (
    RouteTransitionSettlementService,
)
from ai_software_engineer.recovery.workspace_snapshot import _existing_task_scope
from ai_software_engineer.redaction import source_inspection_scope
from ai_software_engineer.repository_workspace import RepositoryWorkspaceManifest
from ai_software_engineer.runtime_workspace import (
    FileTeamWorkforceStore,
    TeamWorkforceWorkspace,
)
from ai_software_engineer.store.mysql_repository import (
    _decode_event,
    _decode_task,
    open_mysql_connection,
)
from ai_software_engineer.team_workspace import TeamWorkspace, _read_regular
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


def require_route_transition_capture(
    original: NativeRecoverySource,
    capture: CapturedChanges,
    current_capture: CapturedChanges,
) -> None:
    """The approved full patch and final inventory must equal the sealed draft."""
    sealed = original.route_transition_capture
    if sealed is None or capture != sealed or current_capture != sealed:
        raise RecoveryRejected("route-transition retained complete draft changed")


class RouteTransitionRecoverySourceReader:
    """Read-only, lock-held bridge from an old Task settlement to a new Plan."""

    def __init__(self, config: ProductionConfig, environment: Mapping[str, str]) -> None:
        self.config, self.environment = config, dict(environment)

    @source_inspection_scope()
    @recovery_record_read_scope()
    def discover(self, scope: RecoveryScope) -> NativeRecoverySource:
        return self._read(scope, None)

    @source_inspection_scope()
    @recovery_record_read_scope()
    def inspect(self, scope: RecoveryScope, settlement_sha256: str) -> NativeRecoverySource:
        TypeAdapter(Sha256).validate_python(settlement_sha256)
        return self._read(scope, settlement_sha256)

    def _read(self, scope: RecoveryScope, expected: str | None) -> NativeRecoverySource:
        try:
            scope = RecoveryScope.model_validate(scope.to_wire())
            if scope.team_id != self.config.team_id:
                raise ValueError("route-transition Team changed")
            team = TeamWorkspace.initialize(
                self.config.platform_root,
                team_id=scope.team_id,
                name=self.config.team_name,
                read_only=True,
            )
            project, repository = team.project_registry().locate_repository(scope.repository_id)
            _require_native_active(project, scope.delivery_id)
            root = Path(repository.root)
            manifest = RepositoryWorkspaceManifest.model_validate_json(
                _read_regular(root / "workspace.json", 64_000)
            )
            manifest.validate_binding(root)
            if (manifest.repository_id, manifest.repository_root) != (
                scope.repository_id,
                scope.repository_root,
            ):
                raise ValueError("route-transition registration changed")
            journal = FileProjectDeliveryCheckpointStore(
                root / "state/project-deliveries", read_only=True
            )
            history = journal.list(scope.delivery_id)
            if not history:
                raise ValueError("route-transition child checkpoint is missing")
            cp = history[-1]
            if (
                cp.stage is not DeliveryStage.BLOCKED
                or cp.task_status is not TaskStatus.IMPLEMENTING
                or cp.task_id is None
                or cp.dispatch_commit_id is None
                or cp.candidate_revision is not None
            ):
                raise ValueError("not the retained route-transition child checkpoint")
            records = KnowledgeRecordStore(
                root / "state/route-transition-settlements", read_only=True
            )
            settlement = records.find(
                "route-transition-settlements", cp.task_id, RouteTransitionSettlement
            )
            if settlement is None:
                raise ValueError("route-transition settlement is missing")
            settlement.validate_integrity()
            if expected is not None and settlement.settlement_sha256 != expected:
                raise ValueError("route-transition settlement digest differs")
            if (
                settlement.scope != scope
                or settlement.checkpoint_sha256 != cp.checkpoint_sha256
                or settlement.task_id != cp.task_id
                or settlement.task_revision != cp.task_revision
            ):
                raise ValueError("route-transition settlement scope or checkpoint differs")
            dsn = self.config.require_mysql_dsn(self.environment)
            queue = _ReadOnlyRoleQueue(dsn)
            workforce = FileTeamWorkforceStore(TeamWorkforceWorkspace.from_team(team))
            service = RouteTransitionSettlementService(
                self.config,
                self.environment,
                scope,
                queue=queue,
                policy_lookup=lambda policy_id, version: workforce.get_policy(
                    policy_id, version=version
                ),
            )
            guard = WorkerExecutionGuard()
            with _existing_task_scope(root / "state/queue-worker-locks", cp.task_id, guard):
                first = self._observe(
                    service,
                    settlement,
                    scope,
                    team,
                    project.manifest.project_id,
                    root,
                    history,
                    dsn,
                    guard,
                )
                second = self._observe(
                    service,
                    settlement,
                    scope,
                    team,
                    project.manifest.project_id,
                    root,
                    history,
                    dsn,
                    guard,
                )
                if first != second or journal.list(scope.delivery_id) != history:
                    raise ValueError("route-transition source changed during inspection")
                return first
        except Exception as error:
            raise RecoveryRejected("已收尾路由切换的原需求事实缺失、不安全或已变化") from error

    def _observe(
        self,
        service: RouteTransitionSettlementService,
        settlement: RouteTransitionSettlement,
        scope: RecoveryScope,
        team: TeamWorkspace,
        project_id: str,
        root: Path,
        history: tuple[ProjectDeliveryCheckpoint, ...],
        dsn: str,
        guard: WorkerExecutionGuard,
    ) -> NativeRecoverySource:
        guard.check_task_scope(settlement.task_id)
        if not service._committed(settlement, guard):
            raise ValueError("route-transition Task and queue settlement is not committed")
        service.require_changed_route(settlement)
        expired_reason = settlement.work_item.wait_reason
        if expired_reason is None or not expired_reason.startswith("lease_expired:"):
            raise ValueError("route-transition claim ending is missing")
        queue = _ReadOnlyRoleQueue(dsn)
        original_claim = queue.original_claim(expired_reason.removeprefix("lease_expired:"))
        if (
            original_claim.work_item.id != settlement.work_item_id
            or original_claim.work_item.attempt != settlement.work_item.attempt
            or original_claim.work_item.checkpoint_sequence
            != settlement.work_item.checkpoint_sequence
            or original_claim.work_item.dispatch_sequence + 1
            != settlement.work_item.dispatch_sequence
        ):
            raise ValueError("route-transition original claim generation changed")
        with (
            closing(open_mysql_connection(dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            cursor.execute(
                "SELECT state,acquired_at,last_heartbeat_at,expires_at,ended_at "
                "FROM work_queue_claims WHERE lease_id=%s",
                (original_claim.lease.id,),
            )
            claim_row = cursor.fetchone()
            if (
                claim_row is None
                or claim_row["state"] != "EXPIRED"
                or not (
                    _time(claim_row["acquired_at"])
                    <= _time(claim_row["last_heartbeat_at"])
                    <= _time(claim_row["expires_at"])
                    <= _time(claim_row["ended_at"])
                    <= settlement.event.occurred_at
                )
            ):
                raise ValueError("route-transition expired claim timing changed")
            connection.rollback()
        cp = history[-1]
        if (
            service._require_checkpoint(
                settlement.task_id, settlement.task_revision, settlement.checkpoint_sha256
            )
            != cp
        ):
            raise ValueError("route-transition child checkpoint changed")
        CapacityInputReader(
            state=root / "state",
            queue=queue,
            artifacts=FileArtifactStore(root / "artifacts", read_only=True),
            route_root=model_route_root(root),
            baselines=None,
        ).require_claim_not_started(
            UninvokedClaimBoundary(
                task_id=settlement.task_id,
                work_item_id=settlement.work_item_id,
                lease_id=original_claim.lease.id,
                role=AgentRole.CODER,
                attempt=settlement.work_item.attempt,
                checkpoint_sequence=settlement.work_item.checkpoint_sequence,
                dispatch_sequence=original_claim.work_item.dispatch_sequence,
                observed_at=_time(claim_row["ended_at"]),
                run_id=None,
                context_manifest_id=None,
            )
        )
        with (
            closing(open_mysql_connection(dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            allocations = {}
            for item in history:
                if item.dispatch_commit_id is None or item.dispatch_commit_id in allocations:
                    continue
                cursor.execute(
                    "SELECT * FROM dispatch_commits WHERE id=%s", (item.dispatch_commit_id,)
                )
                row = cursor.fetchone()
                if row is None:
                    raise ValueError("route-transition dispatch history is missing")
                allocation = _decode_allocation(row)
                if (
                    allocation.id != item.dispatch_commit_id
                    or allocation.dispatch_sha256 != item.dispatch_commit_sha256
                    or allocation.task_id != item.task_id
                ):
                    raise ValueError("route-transition dispatch history differs")
                allocations[item.dispatch_commit_id] = allocation
            dispatch_id = cp.dispatch_commit_id
            if dispatch_id is None:
                raise ValueError("route-transition dispatch is missing")
            dispatch = allocations[dispatch_id]
            planner = resolve_planner_dispatch(dispatch, allocations, history)
            cursor.execute(
                "SELECT payload_json,revision,status FROM tasks WHERE id=%s",
                (settlement.task_id,),
            )
            task_row = cursor.fetchone()
            if task_row is None:
                raise ValueError("route-transition Task is missing")
            task = _decode_task(settlement.task_id, task_row["payload_json"])
            if (
                task != apply_event(settlement.task, settlement.event)
                or task_row["revision"] != settlement.task_revision + 1
                or task_row["status"] != TaskStatus.BLOCKED.value
            ):
                raise ValueError("route-transition terminal Task differs")
            cursor.execute(
                "SELECT event_id,revision,payload_json FROM state_events "
                "WHERE task_id=%s ORDER BY revision",
                (settlement.task_id,),
            )
            rows = tuple(cursor.fetchall())
            if tuple(row["revision"] for row in rows) != tuple(
                range(1, settlement.task_revision + 2)
            ):
                raise ValueError("route-transition Task event history has a gap")
            events = tuple(_decode_event(row["payload_json"]) for row in rows)
            if (
                digest(
                    tuple(
                        (row["event_id"], row["revision"], row["payload_json"]) for row in rows[:-1]
                    )
                )
                != settlement.task_event_history_sha256
                or events[-1] != settlement.event
            ):
                raise ValueError("route-transition terminal event history differs")
            previous = TaskStatus.NEW
            previous_attempt = 0
            for row, event in zip(rows, events, strict=True):
                if (
                    event.event_id != row["event_id"]
                    or event.task_id != settlement.task_id
                    or event.from_status is not previous
                    or event.attempt < max(previous_attempt, 1)
                    or event.attempt > task.attempts
                ):
                    raise ValueError("route-transition Task event chain differs")
                previous, previous_attempt = event.to_status, event.attempt
            if previous is not TaskStatus.BLOCKED:
                raise ValueError("route-transition terminal Task event is missing")
            connection.rollback()
        if not task_matches_dispatch(task, dispatch.task):
            raise ValueError("route-transition Task intent differs from dispatch")
        epochs = read_recovery_baseline_epochs(root, task, scope, project_id=project_id)
        validate_pre_candidate_sources(task, events, epochs)
        if not epochs or epochs[-1].binding.binding_sha256 != settlement.execution_baseline_sha256:
            raise ValueError("route-transition final execution baseline differs")
        stages = read_approved_stages(
            self.config, root, scope, cp, task, planner, current_dispatch=dispatch
        )
        parent_id, parent_sha = _parent(team, cp, stages.approval)
        if (parent_id, parent_sha) != (
            settlement.parent_delivery_id,
            settlement.parent_checkpoint_sha256,
        ):
            raise ValueError("route-transition parent checkpoint differs")
        progress = accepted_scope_progress(root, task, events, task.base_ref)
        if progress is None:
            raise ValueError("route-transition historical accepted Coder progress is missing")
        retained = service.inspect_retained(task)
        service._require_retained(settlement, retained)
        binding = epochs[-1].binding
        plan = FileExecutionBaselineStore(
            root / "state/execution-baselines" / task.id, read_only=True
        ).plan(binding.plan_sha256)
        source = RecoverySource(
            scope=scope,
            task_id=task.id,
            task_revision=settlement.task_revision + 1,
            task_sha256=digest(task.to_wire()),
            checkpoint_sha256=cp.checkpoint_sha256,
            dispatch_sha256=dispatch.dispatch_sha256,
            preparation_sha256=stages.preparation.preparation_sha256,
            product_spec_sha256=stages.product.product_spec_sha256,
            approval_sha256=stages.approval.approval_sha256,
            technical_design_sha256=stages.design.technical_design_sha256,
            execution_plan_sha256=stages.plan.execution_plan_sha256,
            failed_run_id=None,
            failed_context_id=None,
            historical_progress_run_id=progress.producer.run_id,
            historical_progress_context_id=progress.context_manifest_id,
            base_revision=task.base_ref,
            execution_baseline_sha256=binding.binding_sha256,
            execution_base_revision=binding.execution_base_ref,
            route_transition_settlement_sha256=settlement.settlement_sha256,
            parent_delivery_id=parent_id,
            parent_checkpoint_sha256=parent_sha,
        )
        guard.check_task_scope(settlement.task_id)
        return NativeRecoverySource(
            source,
            plan.facts.permissions,
            plan.facts.denied_paths,
            stages.preparation,
            stages.product,
            stages.approval,
            stages.design,
            stages.plan,
            stages.request,
            task,
            binding.execution_source_revision,
            accepted_progress=progress,
            route_transition_capture=retained.capture,
        )
