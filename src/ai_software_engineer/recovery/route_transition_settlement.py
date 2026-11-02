"""Preserve a never-invoked old route before creating a separately approved Task."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pymysql.cursors import DictCursor

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, TeamRole, WorkItemStatus
from ai_software_engineer.domain.execution_baseline import BaselineInputMode
from ai_software_engineer.domain.workforce import ModelPolicy
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.queued_delivery import validate_frozen_routes
from ai_software_engineer.orchestration.state_machine import apply_event, build_event
from ai_software_engineer.product import FileProductRecordStore
from ai_software_engineer.recovery.baseline_source import read_recovery_baseline_epochs
from ai_software_engineer.recovery.models import CapturedChanges, RecoveryScope
from ai_software_engineer.recovery.native import _parent
from ai_software_engineer.recovery.route_transition_claim import (
    RouteTransitionSettlement,
    UninvokedRouteClaimObservation,
    UninvokedRouteClaimReader,
    _time,
)
from ai_software_engineer.store.mysql_repository import (
    _decode_event,
    _decode_task,
    open_mysql_connection,
)
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, record_digest
from ai_software_engineer.work_queue.ports import QueueConflict
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


@dataclass(frozen=True, slots=True)
class RouteTransitionRetained:
    baseline_sha256: str
    inventory_sha256: str
    capture: CapturedChanges


class RouteTransitionSettlementService:
    """One Task-locked, queue-fenced old Task end; never runs the old route."""

    _NAMESPACE = "route-transition-settlements"

    def __init__(
        self,
        config: ProductionConfig,
        environment: Mapping[str, str],
        scope: RecoveryScope,
        *,
        queue: MySqlRoleQueue,
        policy_lookup: Callable[[str, str], ModelPolicy],
    ) -> None:
        if scope.team_id != config.team_id:
            raise ValueError("route-transition Team differs from production config")
        team = TeamWorkspace.initialize(
            config.platform_root,
            team_id=config.team_id,
            name=config.team_name,
            read_only=True,
        )
        project, repository = team.project_registry().locate_repository(scope.repository_id)
        if repository.manifest.repository_root != scope.repository_root:
            raise ValueError("route-transition repository registration changed")
        self.config, self.scope, self.queue = config, scope, queue
        self.team = team
        self.policy_lookup = policy_lookup
        self.dsn = config.require_mysql_dsn(environment)
        self.project_id = project.manifest.project_id
        self.sidecar = Path(repository.root)
        self.reader = UninvokedRouteClaimReader(self.dsn, self.sidecar)

    def inspect_retained(self, task: object) -> RouteTransitionRetained:
        """Read the full old draft against the latest consumed baseline."""
        from ai_software_engineer.domain.task import Task

        if not isinstance(task, Task) or task.repository != self.scope.repository_root:
            raise ValueError("route-transition Task repository differs from registration")
        epochs = read_recovery_baseline_epochs(
            self.sidecar, task, self.scope, project_id=self.project_id
        )
        if not epochs:
            raise ValueError("route-transition has no consumed execution baseline")
        binding = epochs[-1].binding
        if binding.input_mode is not BaselineInputMode.PRESERVE_DRAFT:
            raise ValueError("route-transition latest baseline does not preserve the draft")
        plans = FileExecutionBaselineStore(
            self.sidecar / "state/execution-baselines" / task.id, read_only=True
        )
        plan = plans.plan(binding.plan_sha256)
        manager = GitWorktreeManager(
            self.scope.repository_root,
            Path(self.config.platform_root) / "worktrees" / self.scope.repository_id,
            branch_names={task.id: task.branch_name},
        )
        worktree = manager.recover(
            WorktreeSpec(
                task_id=task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=binding.execution_source_revision,
            )
        )
        if (
            str(worktree.path) != binding.worktree_path
            or worktree.head_revision != binding.execution_source_revision
        ):
            raise ValueError("route-transition Coder worktree differs from latest baseline")
        inventory = capture_mutation_inventory(worktree.path)
        if inventory.sha256 != binding.after_inventory_sha256:
            raise ValueError("route-transition retained complete draft inventory changed")
        capture = CapturedChanges.from_capture(
            manager.capture_legacy_changes(
                worktree,
                plan.facts.permissions,
                denied_paths=plan.facts.denied_paths,
                base_revision=binding.execution_base_ref,
            )
        )
        if (
            capture.source_revision != binding.execution_source_revision
            or capture.worktree_path != binding.worktree_path
            or capture.base_revision != binding.execution_base_ref
            or not capture.files
            or capture_mutation_inventory(worktree.path) != inventory
        ):
            raise ValueError("route-transition retained Coder capture changed")
        return RouteTransitionRetained(
            baseline_sha256=binding.binding_sha256,
            inventory_sha256=inventory.sha256,
            capture=capture,
        )

    def settle(self, task_id: str) -> tuple[RouteTransitionSettlement, CapturedChanges]:
        """Seal exact source evidence before atomic Task/queue consumption."""
        guard = WorkerExecutionGuard()
        with guard.task_scope(self.sidecar / "state/queue-worker-locks", task_id):
            records = KnowledgeRecordStore(self.sidecar / "state/route-transition-settlements")
            existing = records.find(self._NAMESPACE, task_id, RouteTransitionSettlement)
            if existing is not None:
                existing.validate_integrity()
                if existing.scope != self.scope or existing.task_id != task_id:
                    raise QueueConflict("route-transition sealed decision scope changed")
                if self._committed(existing, guard):
                    checkpoint = self._require_checkpoint(
                        task_id, existing.task_revision, existing.checkpoint_sha256
                    )
                    if self._require_parent(checkpoint) != (
                        existing.parent_delivery_id,
                        existing.parent_checkpoint_sha256,
                    ):
                        raise QueueConflict("route-transition parent Requirement changed")
                    retained = self.inspect_retained(existing.task)
                    self._require_retained(existing, retained)
                    return existing, retained.capture
            observed = self.reader.inspect(task_id, guard)
            self._require_route_changed(observed)
            checkpoint = self._require_checkpoint(task_id, observed.task_revision)
            parent_id, parent_sha256 = self._require_parent(checkpoint)
            retained = self.inspect_retained(observed.task)
            current = self._current_facts(observed, retained, guard, (parent_id, parent_sha256))
            if current != observed:
                raise QueueConflict("route-transition facts changed before sealing")
            if existing is None:
                now = datetime.now(UTC)
                event = build_event(
                    observed.task,
                    TaskStatus.BLOCKED,
                    event_id="evt_route_transition_"
                    + digest((task_id, observed.task_event_history_sha256))[:40],
                    reason=(
                        "ROUTE_TRANSITION: frozen Coder route no longer matches the "
                        "configured provider; original claim was never invoked"
                    ),
                    source_revision=observed.step.boundary.source_revision,
                    attempt=observed.task.attempts,
                    occurred_at=now,
                )
                existing = RouteTransitionSettlement.create(
                    observed,
                    event,
                    scope=self.scope,
                    checkpoint_sha256=checkpoint.checkpoint_sha256,
                    parent_delivery_id=parent_id,
                    parent_checkpoint_sha256=parent_sha256,
                    execution_baseline_sha256=retained.baseline_sha256,
                    inventory_sha256=retained.inventory_sha256,
                    retained_capture_sha256=retained.capture.capture_sha256,
                )
            existing.validate_integrity()
            existing.require_observation(observed)
            if existing.checkpoint_sha256 != checkpoint.checkpoint_sha256:
                raise QueueConflict("route-transition checkpoint changed after sealing")
            if (existing.parent_delivery_id, existing.parent_checkpoint_sha256) != (
                parent_id,
                parent_sha256,
            ):
                raise QueueConflict("route-transition parent changed after sealing")
            self._require_retained(existing, retained)
            records.put(self._NAMESPACE, task_id, existing)
            self.queue.settle_uninvoked_route_claim(
                observed,
                existing,
                task_lock=guard,
                validate_current=lambda: self._current_facts(
                    observed, retained, guard, (parent_id, parent_sha256)
                ),
            )
            return existing, retained.capture

    def _require_checkpoint(
        self, task_id: str, task_revision: int, expected_sha256: str | None = None
    ) -> ProjectDeliveryCheckpoint:
        history = FileProjectDeliveryCheckpointStore(
            self.sidecar / "state/project-deliveries", read_only=True
        ).list(self.scope.delivery_id)
        if not history:
            raise QueueConflict("route-transition Requirement checkpoint is missing")
        checkpoint = history[-1]
        if (
            checkpoint.repository_id != self.scope.repository_id
            or checkpoint.repository_root != self.scope.repository_root
            or checkpoint.stage is not DeliveryStage.BLOCKED
            or checkpoint.task_id != task_id
            or checkpoint.task_revision != task_revision
            or checkpoint.task_status is not TaskStatus.IMPLEMENTING
            or checkpoint.candidate_revision is not None
            or (expected_sha256 is not None and checkpoint.checkpoint_sha256 != expected_sha256)
        ):
            raise QueueConflict("route-transition Requirement checkpoint differs")
        return checkpoint

    def _require_parent(
        self, checkpoint: ProjectDeliveryCheckpoint
    ) -> tuple[str | None, str | None]:
        if checkpoint.approval_id is None:
            raise QueueConflict("route-transition approved Product is missing")
        approval = FileProductRecordStore(
            self.sidecar / "state/product", read_only=True
        ).find_approval(checkpoint.approval_id)
        if approval is None:
            raise QueueConflict("route-transition Product approval is missing")
        return _parent(self.team, checkpoint, approval)

    def _require_route_changed(self, observed: UninvokedRouteClaimObservation) -> None:
        selection = observed.original_claim.model_selection
        policy = self.policy_lookup(selection.policy_id, selection.policy_version)
        try:
            validate_frozen_routes(
                AgentRole.CODER,
                selection,
                policy,
                self.config.routes_for(TeamRole.CODER),
                proxy_base_url=self.config.codex_cli_proxy_base_url,
            )
        except QueueConflict:
            return
        raise QueueConflict("frozen Coder route is still configured; use ordinary continuation")

    def _require_retained(
        self, settlement: RouteTransitionSettlement, retained: RouteTransitionRetained
    ) -> None:
        if (
            settlement.scope != self.scope
            or settlement.execution_baseline_sha256 != retained.baseline_sha256
            or settlement.inventory_sha256 != retained.inventory_sha256
            or settlement.retained_capture_sha256 != retained.capture.capture_sha256
        ):
            raise QueueConflict("route-transition sealed draft or scope changed")

    def _committed(
        self, settlement: RouteTransitionSettlement, guard: WorkerExecutionGuard
    ) -> bool:
        """Recognize only the exact atomic publication after a crash or replay."""
        guard.check_task_scope(settlement.task_id)
        with (
            closing(open_mysql_connection(self.dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            cursor.execute(
                "SELECT payload_json,revision,status FROM tasks WHERE id=%s",
                (settlement.task_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise QueueConflict("route-transition settled Task is missing")
            task = _decode_task(settlement.task_id, str(row["payload_json"]))
            if task == settlement.task and row["revision"] == settlement.task_revision:
                connection.rollback()
                return False
            if (
                task != apply_event(settlement.task, settlement.event)
                or row["status"] != TaskStatus.BLOCKED.value
                or row["revision"] != settlement.task_revision + 1
            ):
                raise QueueConflict("route-transition Task differs from sealed terminal event")
            cursor.execute(
                "SELECT event_id,revision,payload_json FROM state_events WHERE task_id=%s "
                "AND revision<=%s ORDER BY revision",
                (settlement.task_id, settlement.task_revision),
            )
            prior_events = tuple(cursor.fetchall())
            if (
                digest(
                    tuple(
                        (value["event_id"], value["revision"], value["payload_json"])
                        for value in prior_events
                    )
                )
                != settlement.task_event_history_sha256
            ):
                raise QueueConflict("route-transition preceding Task history changed")
            cursor.execute(
                "SELECT payload_json,revision FROM state_events WHERE event_id=%s",
                (settlement.event.event_id,),
            )
            event_row = cursor.fetchone()
            if (
                event_row is None
                or event_row["revision"] != settlement.task_revision + 1
                or _decode_event(str(event_row["payload_json"])) != settlement.event
            ):
                raise QueueConflict("route-transition terminal StateEvent differs")
            cursor.execute(
                "SELECT payload_json,status FROM work_queue_items WHERE id=%s",
                (settlement.work_item_id,),
            )
            item_row = cursor.fetchone()
            expected_item = settlement.work_item.model_copy(
                update={
                    "status": WorkItemStatus.CLOSED,
                    "wait_reason": None,
                    "wait_disposition": None,
                    "available_at": None,
                    "updated_at": settlement.event.occurred_at,
                }
            )
            if (
                item_row is None
                or item_row["status"] != WorkItemStatus.CLOSED.value
                or self.queue._decode_item({"id": settlement.work_item_id, **item_row})
                != expected_item
            ):
                raise QueueConflict("route-transition closed WorkItem differs")
            cursor.execute(
                "SELECT sequence,event_type,from_status,to_status,lease_id,payload_json,"
                "occurred_at FROM work_queue_events WHERE work_item_id=%s ORDER BY sequence",
                (settlement.work_item_id,),
            )
            queue_events = tuple(cursor.fetchall())
            queue_event = queue_events[-1] if queue_events else None
            if (
                queue_event is None
                or queue_event["event_type"] != "ROUTE_TRANSITION_SETTLED"
                or queue_event["from_status"] != WorkItemStatus.RETRY_SCHEDULED.value
                or queue_event["to_status"] != WorkItemStatus.CLOSED.value
            ):
                raise QueueConflict("route-transition queue terminal event differs")
            if (
                digest(
                    tuple(
                        (
                            value["sequence"],
                            value["event_type"],
                            value["from_status"],
                            value["to_status"],
                            value["lease_id"],
                            value["payload_json"],
                            _time(value["occurred_at"]).isoformat(),
                        )
                        for value in queue_events[:-1]
                    )
                )
                != settlement.queue_event_history_sha256
            ):
                raise QueueConflict("route-transition preceding queue history changed")
            detail = json.loads(str(queue_event["payload_json"]))["detail"]
            if detail != {
                "settlement_sha256": settlement.settlement_sha256,
                "previous_work_item_sha256": record_digest(settlement.work_item),
                "budget_refund": False,
                "model_result": False,
            }:
                raise QueueConflict("route-transition queue settlement digest differs")
            cursor.execute(
                "SELECT lease_id FROM work_queue_claims WHERE task_id=%s AND state='ACTIVE'",
                (settlement.task_id,),
            )
            if cursor.fetchone() is not None:
                raise QueueConflict("route-transition replay has a new active owner")
            connection.rollback()
        guard.check_task_scope(settlement.task_id)
        return True

    def _current_facts(
        self,
        observed: UninvokedRouteClaimObservation,
        retained: RouteTransitionRetained,
        guard: WorkerExecutionGuard,
        expected_parent: tuple[str | None, str | None],
    ) -> UninvokedRouteClaimObservation:
        current = self.reader.inspect(observed.task.id, guard)
        checkpoint = self._require_checkpoint(observed.task.id, observed.task_revision)
        if self._require_parent(checkpoint) != expected_parent:
            raise QueueConflict("route-transition parent Requirement changed during settlement")
        fresh = self.inspect_retained(current.task)
        if fresh != retained:
            raise QueueConflict("route-transition baseline or complete draft changed")
        return current
