"""Read-only successor source for exactly settled, exhausted UNKNOWN native work.

A real invocation remains UNKNOWN.  Its settlement authorizes no new execution;
only a separately approved RecoveryPlan can create a fresh Task in the same delivery.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.fallback import model_route_root
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentPermissions, AgentRole, Task, TaskStatus
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure
from ai_software_engineer.domain.stopped_unknown_budget import (
    STOPPED_UNKNOWN_BUDGET_REASON,
    StoppedUnknownBudgetSettlement,
)
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
)
from ai_software_engineer.manager.stopped_unknown_budget import verify_settled_stopped_unknown
from ai_software_engineer.multi_directory.history_observation import NativeHistoryJournal
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.read_record_scope import recovery_record_read_scope
from ai_software_engineer.recovery.baseline_source import (
    read_recovery_baseline_epochs,
    require_terminal_baseline_context,
)
from ai_software_engineer.recovery.models import (
    CapturedChanges,
    RecoveryRejected,
    RecoveryScope,
    RecoverySource,
    digest,
)
from ai_software_engineer.recovery.native import (
    NativeRecoverySource,
    NativeRecoverySourceReader,
    _parent,
    _require_native_active,
    read_approved_stages,
)
from ai_software_engineer.recovery.workspace_snapshot import (
    _existing_task_scope,
    _terminal_sql_facts,
)
from ai_software_engineer.redaction import source_inspection_scope
from ai_software_engineer.repository_workspace import RepositoryWorkspaceManifest
from ai_software_engineer.store.mysql_repository import _text, open_mysql_connection
from ai_software_engineer.team_workspace import TeamWorkspace, _read_regular, _reject_symlinks
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, record_digest
from ai_software_engineer.work_queue.models import QueuedWorkItem
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard

STOPPED_UNKNOWN_BUDGET_SUMMARY = STOPPED_UNKNOWN_BUDGET_REASON.removeprefix("BUDGET_EXHAUSTED: ")


@dataclass(frozen=True)
class _TaskSnapshot:
    """The complete current SQL snapshot; mutation ports deliberately refuse."""

    task: Task
    revision: int
    events: tuple[StateEvent, ...]

    def get(self, task_id: str) -> Task:
        if task_id != self.task.id:
            raise RecoveryRejected("stopped unknown source Task identity differs")
        return self.task

    def current_revision(self, task_id: str) -> int:
        self.get(task_id)
        return self.revision

    def list_events(self, task_id: str) -> tuple[StateEvent, ...]:
        self.get(task_id)
        return self.events

    def create(self, task: Task) -> None:
        raise RecoveryRejected("recovery source is read only")

    def append_event(self, event: StateEvent) -> None:
        raise RecoveryRejected("recovery source is read only")

    def record_attempt(self, task_id: str, attempt: int) -> None:
        raise RecoveryRejected("recovery source is read only")

    def record_retry_failure(self, task_id: str, failure: DeliveryRetryFailure) -> None:
        raise RecoveryRejected("recovery source is read only")


class _ReadOnlyRoleQueue(MySqlRoleQueue):
    """Use existing verified SELECT ports without initializing tables or schema."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn


def require_stopped_unknown_capture(
    original: NativeRecoverySource,
    capture: CapturedChanges,
    current_capture: CapturedChanges,
) -> None:
    """Bind the full Task-base patch and exact final Run-local stopped draft.

    The stopped mutation proof is relative to the final Coder Run's input HEAD.
    The successor needs the complete Task-base-to-current patch, which may also
    contain earlier committed Coder work.  Those patches have different bases
    and must never be compared as if they were the same observation.
    """
    retained = original.stopped_unknown_capture
    if retained is None:
        raise RecoveryRejected("stopped unknown source lost its full retained mutation capture")
    expected_files = tuple(
        (item.path, item.after.sha256) for item in retained.mutations if item.after is not None
    )
    complete_files = {(file.path, file.sha256) for file in capture.files}
    if (
        any(item.after is None for item in retained.mutations)
        or capture.base_revision != original.source.effective_base_revision
        or current_capture.base_revision is not None
        or any(
            (
                observed.task_id,
                observed.attempt,
                observed.source_revision,
                observed.worktree_path,
                observed.branch_name,
            )
            != (
                retained.task_id,
                retained.attempt,
                retained.source_revision,
                retained.worktree_path,
                retained.branch_name,
            )
            for observed in (capture, current_capture)
        )
        or current_capture.patch != retained.patch
        or current_capture.index_diff_sha256 != retained.index_diff_sha256
        or tuple((item.path, item.sha256) for item in current_capture.files) != expected_files
        or any((item.path, item.sha256) not in complete_files for item in current_capture.files)
    ):
        raise RecoveryRejected("恢复计划必须包含已封存的完整未知结果开发草稿")


def _require_settlement_audit(
    rows: tuple[Mapping[str, object], ...],
    settlement: StoppedUnknownBudgetSettlement,
    closed: QueuedWorkItem,
) -> None:
    if len(rows) != 1:
        raise ValueError("stopped unknown settlement audit is missing or ambiguous")
    row = rows[0]
    expected = {
        "work_item": closed.to_wire(),
        "detail": {
            "settlement_sha256": settlement.settlement_sha256,
            "previous_work_item_sha256": settlement.expected_item_sha256,
            "budget_refund": False,
        },
    }
    if (
        row["work_item_id"] != closed.id
        or row["event_type"] != "STOPPED_BUDGET_SETTLED"
        or row["from_status"] != settlement.work_item.status.value
        or row["to_status"] != closed.status.value
        or row["lease_id"] is not None
        or MySqlRoleQueue._parse_time(_text(row, "occurred_at")) != settlement.event.occurred_at
        or json.loads(_text(row, "payload_json")) != expected
    ):
        raise ValueError("stopped unknown settlement audit differs")


class StoppedUnknownRecoverySourceReader:
    def __init__(self, config: ProductionConfig, environment: Mapping[str, str]) -> None:
        self.config, self.environment = config, dict(environment)
        self.native = NativeRecoverySourceReader(config, environment)

    @source_inspection_scope()
    @recovery_record_read_scope()
    def discover(self, scope: RecoveryScope) -> NativeRecoverySource:
        return self._read(scope, None)

    @source_inspection_scope()
    @recovery_record_read_scope()
    def inspect(self, scope: RecoveryScope, settlement_sha256: str) -> NativeRecoverySource:
        return self._read(scope, settlement_sha256)

    def _read(self, scope: RecoveryScope, settlement_sha256: str | None) -> NativeRecoverySource:
        journals: dict[Path, JointJournal] = {}
        try:
            if settlement_sha256 is not None:
                TypeAdapter(Sha256).validate_python(settlement_sha256)
            return self._inspect(
                RecoveryScope.model_validate(scope.to_wire()), settlement_sha256, journals
            )
        except Exception as error:
            raise RecoveryRejected("已停止未知结果的额度收尾事实缺失、不安全或已变化") from error
        finally:
            for journal in journals.values():
                journal._verified.clear()
            journals.clear()

    def _inspect(
        self,
        scope: RecoveryScope,
        settlement_sha256: str | None,
        journals: dict[Path, JointJournal],
    ) -> NativeRecoverySource:
        if scope.team_id != self.config.team_id:
            raise ValueError("stopped unknown Team differs")
        team = TeamWorkspace.initialize(
            self.config.platform_root,
            team_id=scope.team_id,
            name=self.config.team_name,
            read_only=True,
        )
        project, repository = team.project_registry().locate_repository(scope.repository_id)
        journals[project.requirements_root] = NativeHistoryJournal(
            project.requirements_root, read_only=True
        )
        _require_native_active(
            project, scope.delivery_id, journal=journals[project.requirements_root]
        )
        root = repository.root
        manifest = RepositoryWorkspaceManifest.model_validate_json(
            _read_regular(root / "workspace.json", 64_000)
        )
        manifest.validate_binding(root)
        if (
            manifest.repository_id != scope.repository_id
            or manifest.repository_root != scope.repository_root
        ):
            raise ValueError("stopped unknown repository binding differs")
        journal = FileProjectDeliveryCheckpointStore(
            root / "state/project-deliveries", read_only=True
        )
        history = journal.list(scope.delivery_id)
        cp = history[-1]
        if (
            cp.stage is not DeliveryStage.BLOCKED
            or cp.task_status is not TaskStatus.BLOCKED
            or cp.candidate_revision is not None
            or cp.failure_summary != STOPPED_UNKNOWN_BUDGET_SUMMARY
        ):
            raise ValueError("not the exact stopped unknown exhausted checkpoint")
        records = KnowledgeRecordStore(root / "state/delivery-preflight", read_only=True)
        if settlement_sha256 is None:
            matches = tuple(
                value
                for value in records.list(
                    "stopped-unknown-budget-settlements", StoppedUnknownBudgetSettlement
                )
                if value.task.id == cp.task_id
            )
            if len(matches) != 1:
                raise ValueError("stopped unknown settlement is missing or ambiguous")
            settlement = matches[0]
        else:
            settlement = records.get(
                "stopped-unknown-budget-settlements",
                settlement_sha256,
                StoppedUnknownBudgetSettlement,
            )
        settlement.validate_integrity()
        stopped = settlement.stopped_execution
        request = stopped.invocation_start.request
        bound = stopped.capture_start.scope
        if (bound.team_id, bound.project_id, bound.repository_id, bound.requirement_id) != (
            scope.team_id,
            project.manifest.project_id,
            scope.repository_id,
            scope.delivery_id,
        ) or settlement.task.id != cp.task_id:
            raise ValueError("stopped unknown settlement belongs to another scope")
        guard = WorkerExecutionGuard()
        with _existing_task_scope(root / "state/queue-worker-locks", settlement.task.id, guard):
            facts = self.native._sql(
                cp, history, sidecar=root, project_id=project.manifest.project_id
            )
            task, revision, dispatch, planner, events = facts
            if (
                bound.dispatch_sha256 != dispatch.dispatch_sha256
                or events[-1] != settlement.event
                or settlement.event.reason != STOPPED_UNKNOWN_BUDGET_REASON
            ):
                raise ValueError("stopped unknown terminal event changed")
            epochs = read_recovery_baseline_epochs(
                root, task, scope, project_id=project.manifest.project_id
            )
            stages = read_approved_stages(
                self.config, root, scope, cp, task, planner, current_dispatch=dispatch
            )
            _reject_symlinks(root / "contexts")
            _read_regular(root / "contexts" / f"{request.context_manifest_id}.json", 8_000_000)
            context = FileContextStore(root / "contexts", read_only=True).get(
                request.context_manifest_id
            )
            if (context.task_id, context.role, context.attempt, context.source_revision) != (
                task.id,
                AgentRole.CODER,
                task.attempts,
                request.source_revision,
            ):
                raise ValueError("stopped unknown original Context differs")
            sections = tuple(section for section in context.sections if section.name == "policy")
            if len(sections) != 1 or sections[0].truncated:
                raise ValueError("stopped unknown Context lacks its exact policy")
            policy = json.loads(sections[0].content)
            denied = TypeAdapter(tuple[str, ...]).validate_python(policy.pop("denied_paths"))
            permissions = AgentPermissions.model_validate(policy)
            if (
                permissions != request.permissions
                or permissions.can_merge
                or permissions.can_change_state
                or task.constraints is None
                or permissions.write_paths != task.constraints.allowed_paths
                or denied != task.constraints.denied_paths
            ):
                raise ValueError("stopped unknown Coder policy differs from approved Task")
            baseline = require_terminal_baseline_context(
                root,
                task,
                context,
                epochs,
                run_id=request.run_id,
                request_sha256=digest(request.to_wire()),
                attempt=request.attempt,
                source_revision=request.source_revision,
            )
            parent_id, parent_sha = _parent(team, cp, stages.approval, journals=journals)
            source = RecoverySource(
                scope=scope,
                task_id=task.id,
                task_revision=revision,
                task_sha256=digest(task.to_wire()),
                checkpoint_sha256=cp.checkpoint_sha256,
                dispatch_sha256=dispatch.dispatch_sha256,
                preparation_sha256=stages.preparation.preparation_sha256,
                product_spec_sha256=stages.product.product_spec_sha256,
                approval_sha256=stages.approval.approval_sha256,
                technical_design_sha256=stages.design.technical_design_sha256,
                execution_plan_sha256=stages.plan.execution_plan_sha256,
                failed_run_id=request.run_id,
                failed_context_id=context.context_id,
                base_revision=task.base_ref,
                execution_baseline_sha256=baseline.binding_sha256 if baseline else None,
                execution_base_revision=baseline.execution_base_ref if baseline else None,
                stopped_unknown_settlement_sha256=settlement.settlement_sha256,
                parent_delivery_id=parent_id,
                parent_checkpoint_sha256=parent_sha,
            )
            dsn = self.config.require_mysql_dsn(self.environment)
            queue = _ReadOnlyRoleQueue(dsn)
            manager = GitWorktreeManager(
                scope.repository_root,
                Path(self.config.platform_root) / "worktrees" / scope.repository_id,
                branch_names={task.id: task.branch_name},
            )
            sql_before = self._queue_facts(dsn, source, settlement)
            if sql_before[:3] != (task, revision, events):
                raise ValueError("stopped unknown SQL facts differ")
            captured = verify_settled_stopped_unknown(
                settlement,
                repository=_TaskSnapshot(task, revision, events),
                queue=queue,
                state=root / "state",
                route_root=model_route_root(root),
                artifacts=FileArtifactStore(root / "artifacts", read_only=True),
                git=manager,
                guard=guard,
            )
            if (
                self._queue_facts(dsn, source, settlement) != sql_before
                or journal.list(scope.delivery_id) != history
                or self.native._sql(
                    cp, history, sidecar=root, project_id=project.manifest.project_id
                )
                != facts
                or read_recovery_baseline_epochs(
                    root, task, scope, project_id=project.manifest.project_id
                )
                != epochs
                or read_approved_stages(
                    self.config, root, scope, cp, task, planner, current_dispatch=dispatch
                )
                != stages
                or _parent(team, cp, stages.approval, journals=journals) != (parent_id, parent_sha)
            ):
                raise ValueError("stopped unknown facts changed during inspection")
            # The final observation follows the complete second source/target read;
            # it rechecks actual native stop and full current inventory once more.
            if (
                verify_settled_stopped_unknown(
                    settlement,
                    repository=_TaskSnapshot(task, revision, events),
                    queue=queue,
                    state=root / "state",
                    route_root=model_route_root(root),
                    artifacts=FileArtifactStore(root / "artifacts", read_only=True),
                    git=manager,
                    guard=guard,
                )
                != captured
            ):
                raise ValueError("stopped unknown retained input changed")
            return NativeRecoverySource(
                source,
                permissions,
                denied,
                stages.preparation,
                stages.product,
                stages.approval,
                stages.design,
                stages.plan,
                stages.request,
                task,
                request.source_revision,
                stopped_unknown_capture=captured,
            )

    @staticmethod
    def _queue_facts(
        dsn: str, source: RecoverySource, settlement: StoppedUnknownBudgetSettlement
    ) -> tuple[object, ...]:
        connection = open_mysql_connection(dsn)
        try:
            with connection.cursor(DictCursor) as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                facts = _terminal_sql_facts(
                    cursor, source, settlement.stopped_execution.capture_start
                )
                if (
                    facts[4] != settlement.step
                    or record_digest(facts[5]) != settlement.closed_item_sha256
                ):
                    raise ValueError("stopped unknown closed queue snapshot differs")
                cursor.execute(
                    "SELECT * FROM work_queue_events "
                    "WHERE work_item_id=%s AND event_type='STOPPED_BUDGET_SETTLED' "
                    "ORDER BY sequence",
                    (settlement.work_item.id,),
                )
                _require_settlement_audit(tuple(cursor.fetchall()), settlement, facts[5])
                return facts
        finally:
            connection.rollback()
            connection.close()
