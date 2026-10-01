"""Inspect a stopped workspace before a separately approved replacement Run."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import JsonValue
from pymysql.cursors import DictCursor

from ai_software_engineer.agents import AgentRequest, FileModelRouteAttemptStore
from ai_software_engineer.agents.execution import current_execution_guard
from ai_software_engineer.agents.fallback import model_route_root
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    PlanArtifact,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import task_matches_dispatch
from ai_software_engineer.domain.workforce import TaskLease
from ai_software_engineer.git import (
    GitWorkspaceError,
    GitWorktreeManager,
    WorkspacePolicyError,
    WorktreeRef,
)
from ai_software_engineer.recovery.context import validate_reapply_context
from ai_software_engineer.recovery.current import NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.interruption_records import (
    RecoveryInterruptionInvocation,
    RecoveryInterruptionPlan,
)
from ai_software_engineer.recovery.models import (
    CapturedChanges,
    RecoveryPlan,
    RecoveryRejected,
    digest,
)
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.store.mysql_repository import (
    _decode_event,
    _decode_task,
    open_mysql_connection,
)
from ai_software_engineer.team_workspace import _reject_symlinks
from ai_software_engineer.work_queue.execution_store import (
    QueuedRoleStep,
    RoleQueueAdmission,
    _decode,
)
from ai_software_engineer.work_queue.models import QueuedWorkItem
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard

if TYPE_CHECKING:
    from ai_software_engineer.recovery.entry import NativeRecoveryEntry


class _QueueEventPayload(DomainModel):
    work_item: QueuedWorkItem
    detail: dict[str, JsonValue]


def _stopped_workspace_capture(
    manager: GitWorktreeManager,
    seed: CapturedChanges,
    permissions: AgentPermissions,
    denied_paths: tuple[str, ...],
    expected: RecoveryInterruptionPlan | None,
) -> CapturedChanges | None:
    """Seal a first proposal or verify its exact bytes; the caller owns the Task lock."""
    original = seed.to_capture()
    try:
        if expected is not None:
            approved = expected.stopped_capture or seed
            capture = approved.to_capture()
            if (
                capture.worktree != original.worktree
                or capture.base_revision != original.base_revision
            ):
                raise RecoveryRejected("interruption capture workspace identity differs from seed")
            manager.verify_capture(capture, permissions, denied_paths=denied_paths)
            return expected.stopped_capture
        observed = manager.capture_changes(
            original.worktree,
            permissions,
            denied_paths=denied_paths,
            base_revision=original.base_revision,
        )
    except (GitWorkspaceError, WorkspacePolicyError) as error:
        raise RecoveryRejected(
            "interrupted workspace cannot satisfy its exact capture and current policy"
        ) from error
    return None if observed == original else CapturedChanges.from_capture(observed)


class RecoveryInterruptionService:
    def __init__(self, entry: NativeRecoveryEntry, store: FileRecoveryStore, plan: RecoveryPlan):
        from ai_software_engineer.recovery.entry import _repository_sidecar

        self.entry, self.store, self.original = entry, store, plan
        self.sidecar = _repository_sidecar(entry.config, plan.source.scope.repository_id)
        self.locks = self.sidecar / "state/queue-worker-locks"

    def inspect(
        self,
        *,
        expected: RecoveryInterruptionPlan | None = None,
        claimed: WorkerExecutionGuard | None = None,
    ) -> RecoveryInterruptionPlan:
        """Caller owns either the stopped-Task inspection lock or the actual Worker lock."""
        original, store = self.original, self.store
        try:
            store.get_interruption_invocation(original.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            raise RecoveryRejected("replacement invocation already admitted; inspect its result")
        facts = NativeRecoveryFactsVerifier(self.entry.config, self.entry.environment).inspect(
            original
        )
        authorization = store.get_authorization(original.plan_sha256)
        sealed = store.get_task_record(original.plan_sha256)
        seed = store.get_seed(original.plan_sha256)
        invocation = store.get_invocation(original.plan_sha256)
        dispatch = self.entry._dispatch_for(store, original)
        if (
            not authorization.decision.approved
            or sealed.authorization_sha256 != authorization.authorization_sha256
            or seed.recovery_plan_sha256 != original.plan_sha256
            or seed.dispatch_sha256 != dispatch.dispatch_sha256
            or invocation.recovery_plan_sha256 != original.plan_sha256
            or invocation.seed_record_sha256 != seed.record_sha256
        ):
            raise RecoveryRejected("original recovery approval or seed lineage differs")
        manager = self.entry._manager(
            original.source.scope, {sealed.task.id: sealed.task.branch_name}
        )
        stopped_capture = _stopped_workspace_capture(
            manager,
            seed.capture,
            original.effective_target_permissions,
            original.denied_paths,
            expected,
        )
        prior_context = FileContextStore(self.sidecar / "contexts", read_only=True).get(
            invocation.context_manifest_id
        )
        if (
            prior_context.task_id != sealed.task.id
            or prior_context.attempt != 1
            or prior_context.role is not AgentRole.CODER
            or prior_context.source_revision != sealed.task.base_ref
        ):
            raise RecoveryRejected("original invocation context changed")
        validate_reapply_context(original, prior_context)
        for artifact in FileArtifactStore(self.sidecar / "artifacts", read_only=True).list_for_task(
            sealed.task.id
        ):
            if not isinstance(artifact, PlanArtifact):
                raise RecoveryRejected("interrupted Task already has delivery output")
        routes = model_route_root(self.sidecar)
        _reject_symlinks(routes)
        if routes.exists():
            route_store = FileModelRouteAttemptStore(routes, read_only=True)
            for directory in routes.iterdir():
                _reject_symlinks(directory)
                if any(
                    r.task_id == sealed.task.id for r in route_store.list_for_run(directory.name)
                ):
                    raise RecoveryRejected("interrupted Task has a completed model route")
        dsn = self.entry.config.require_mysql_dsn(self.entry.environment)
        with closing(open_mysql_connection(dsn)) as connection:
            try:
                with connection.cursor(DictCursor) as cursor:
                    cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                    cursor.execute("SELECT * FROM tasks WHERE id=%s", (sealed.task.id,))
                    row = cursor.fetchone()
                    if row is None:
                        raise RecoveryRejected("interrupted Task is missing")
                    task = _decode_task(sealed.task.id, row["payload_json"])
                    revision = row["revision"]
                    if (
                        task.status is not TaskStatus.IMPLEMENTING
                        or task.attempts != 1
                        or row["status"] != task.status.value
                        or not task_matches_dispatch(task, dispatch.task)
                    ):
                        raise RecoveryRejected("interrupted Task checkpoint changed")
                    cursor.execute(
                        "SELECT * FROM state_events WHERE task_id=%s ORDER BY revision", (task.id,)
                    )
                    rows = cursor.fetchall()
                    events = tuple(_decode_event(r["payload_json"]) for r in rows)
                    if (
                        [r["revision"] for r in rows] != list(range(1, revision + 1))
                        or len(events) != 2
                        or tuple((e.from_status, e.to_status, e.attempt) for e in events)
                        != (
                            (TaskStatus.NEW, TaskStatus.PLANNING, 1),
                            (TaskStatus.PLANNING, TaskStatus.IMPLEMENTING, 1),
                        )
                        or any(
                            e.task_id != task.id or e.source_revision != task.base_ref
                            for e in events
                        )
                    ):
                        raise RecoveryRejected("interrupted Task event history changed")
                    cursor.execute(
                        "SELECT id FROM work_queue_accepted_artifacts WHERE task_id=%s", (task.id,)
                    )
                    if cursor.fetchone() is not None:
                        raise RecoveryRejected("interrupted Task has accepted output")
                    cursor.execute(
                        "SELECT payload_json FROM work_queue_items WHERE task_id=%s", (task.id,)
                    )
                    items = tuple(
                        QueuedWorkItem.model_validate_json(r["payload_json"])
                        for r in cursor.fetchall()
                    )
                    if len(items) != 1:
                        raise RecoveryRejected("interrupted Task queue is ambiguous")
                    item = items[0]
                    cursor.execute("SELECT * FROM work_queue_admissions WHERE id=%s", (task.id,))
                    admission_row = cursor.fetchone()
                    cursor.execute("SELECT * FROM work_queue_steps WHERE id=%s", (item.id,))
                    step_row = cursor.fetchone()
                    if admission_row is None or step_row is None:
                        raise RecoveryRejected("interrupted queue admission is missing")
                    admission = _decode(admission_row, RoleQueueAdmission)
                    step = _decode(step_row, QueuedRoleStep)
                    if (
                        admission.task_id != task.id
                        or admission.repository_id != dispatch.repository_id
                        or admission.allocation_sha256 != dispatch.dispatch_sha256
                        or step.allocation_sha256 != dispatch.dispatch_sha256
                        or step.boundary.task_id != task.id
                        or step.boundary.checkpoint_sequence != revision
                        or step.boundary.source_revision != task.base_ref
                        or step.work_item.id != item.id
                    ):
                        raise RecoveryRejected("interrupted queue admission lineage changed")
                    if (
                        item.role is not AgentRole.CODER
                        or item.attempt != 1
                        or item.checkpoint_sequence != revision
                        or item.repository_id != original.source.scope.repository_id
                    ):
                        raise RecoveryRejected("interrupted work item identity changed")
                    cursor.execute(
                        "SELECT lease_id,lease_json,state,expires_at FROM work_queue_claims "
                        "WHERE task_id=%s ORDER BY acquired_at,lease_id",
                        (task.id,),
                    )
                    claims = cursor.fetchall()
                    if not claims:
                        raise RecoveryRejected("interrupted invocation has no original claim")
                    old = claims[0]
                    lease = TaskLease.model_validate_json(old["lease_json"])
                    if (
                        lease.task_id != task.id
                        or lease.id != old["lease_id"]
                        or lease.expires_at.isoformat() != old["expires_at"]
                        or lease.expires_at > datetime.now(UTC)
                    ):
                        raise RecoveryRejected("original claim is not expired")
                    cursor.execute(
                        "SELECT payload_json FROM work_queue_events "
                        "WHERE work_item_id=%s AND lease_id=%s AND event_type='CLAIMED'",
                        (item.id, lease.id),
                    )
                    claimed_events = cursor.fetchall()
                    if len(claimed_events) != 1:
                        raise RecoveryRejected("original claim event is missing or ambiguous")
                    original_item = _QueueEventPayload.model_validate_json(
                        claimed_events[0]["payload_json"]
                    ).work_item
                    mutable = {
                        "status",
                        "dispatch_sequence",
                        "wait_reason",
                        "available_at",
                        "updated_at",
                    }
                    if (
                        original_item.status is not WorkItemStatus.LEASED
                        or original_item.model_dump(exclude=mutable)
                        != item.model_dump(exclude=mutable)
                    ):
                        raise RecoveryRejected("original claim does not bind this work item")
                    generation = original_item.dispatch_sequence
                    if expected is not None and expected.dispatch_sequence != generation:
                        raise RecoveryRejected("original claim generation changed")
                    if old["state"] == "EXPIRED":
                        cursor.execute(
                            "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
                            "AND lease_id=%s AND event_type='LEASE_EXPIRED'",
                            (item.id, lease.id),
                        )
                        expired_events = cursor.fetchall()
                        if len(expired_events) != 1:
                            raise RecoveryRejected("expired claim event is missing or ambiguous")
                        requeued = _QueueEventPayload.model_validate_json(
                            expired_events[0]["payload_json"]
                        ).work_item
                        if (
                            requeued.status is not WorkItemStatus.RETRY_SCHEDULED
                            or requeued.dispatch_sequence != generation + 1
                            or requeued.wait_reason != f"lease_expired:{lease.id}"
                            or requeued.model_dump(exclude=mutable)
                            != item.model_dump(exclude=mutable)
                        ):
                            raise RecoveryRejected("expired claim event lineage changed")
                    if claimed is None:
                        if (
                            len(claims) != 1
                            or old["state"] not in {"ACTIVE", "EXPIRED"}
                            or not (
                                (
                                    item.status is WorkItemStatus.RUNNING
                                    and item.dispatch_sequence == generation
                                )
                                or (
                                    old["state"] == "EXPIRED"
                                    and item.status is WorkItemStatus.RETRY_SCHEDULED
                                    and item.dispatch_sequence == generation + 1
                                    and item.wait_reason == f"lease_expired:{lease.id}"
                                )
                            )
                        ):
                            raise RecoveryRejected("another execution owns the interrupted Task")
                    else:
                        claimed.check()
                        if claimed.lease is None or not claimed.inherited_fds:
                            raise RecoveryRejected("replacement requires owned Task lock and lease")
                        claim = claimed.lease.claim
                        if (
                            len(claims) != 2
                            or old["state"] != "EXPIRED"
                            or claims[-1]["lease_id"] != claim.lease.id
                            or claims[-1]["state"] != "ACTIVE"
                            or claim.work_item.id != item.id
                            or item.dispatch_sequence != generation + 1
                            or claim.work_item.dispatch_sequence != item.dispatch_sequence
                            or item.status is not WorkItemStatus.RUNNING
                        ):
                            raise RecoveryRejected("replacement Worker generation changed")
            finally:
                connection.rollback()
        value = RecoveryInterruptionPlan(
            scope=original.source.scope,
            recovery_plan_sha256=original.plan_sha256,
            authorization_sha256=authorization.authorization_sha256,
            seed_record_sha256=seed.record_sha256,
            stopped_capture=stopped_capture,
            invocation_record_sha256=invocation.record_sha256,
            task_id=task.id,
            task_sha256=digest(task.to_wire()),
            events_sha256=digest(tuple(e.to_wire() for e in events)),
            task_revision=revision,
            dispatch_sha256=dispatch.dispatch_sha256,
            work_item_id=item.id,
            dispatch_sequence=generation,
            expired_lease=lease,
            created_at=expected.created_at if expected else datetime.now(UTC),
            plan_sha256="0" * 64,
        )
        value = value.model_copy(update={"plan_sha256": value.recompute_sha256()})
        value.validate_integrity()
        if expected is not None and value != expected:
            raise RecoveryRejected("interruption facts no longer match the exact plan")
        if facts.target.repository_workspace_root != str(self.sidecar):
            raise RecoveryRejected("interruption sidecar binding changed")
        return value

    def propose(self) -> RecoveryInterruptionPlan:
        try:
            expected = self.store.get_interruption_plan(self.original.plan_sha256)
        except RecoveryRecordMissing:
            expected = None
        task_id = self.store.get_task_record(self.original.plan_sha256).task.id
        with WorkerExecutionGuard().task_scope(self.locks, task_id):
            plan = self.inspect(expected=expected)
            return self.store.put_interruption_plan(plan)

    def prepare_workspace(self, target: WorktreeRef) -> None:
        """Reopen the approved retained workspace without seeding or rewriting its receipt."""
        plan = self.store.get_interruption_plan(self.original.plan_sha256)
        with WorkerExecutionGuard().task_scope(self.locks, plan.task_id):
            seed = self.store.get_seed(self.original.plan_sha256)
            if seed.capture.to_capture().worktree != target:
                raise RecoveryRejected("interruption seed belongs to another target workspace")
            self.inspect(expected=plan)

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None:
        """InitialWorkspaceAdmission implementation, called under the new real Worker."""
        plan = self.store.get_interruption_plan(self.original.plan_sha256)
        approval = self.store.get_interruption_authorization(self.original.plan_sha256)
        seed = self.store.get_seed(self.original.plan_sha256)
        old = self.store.get_invocation(self.original.plan_sha256)
        guard = current_execution_guard()
        if not isinstance(guard, WorkerExecutionGuard):
            raise RecoveryRejected("replacement invocation requires a claimed Worker")
        if (
            not approval.decision.approved
            or request.task_id != plan.task_id
            or request.role is not AgentRole.CODER
            or request.attempt != 1
            or request.source_revision != self.original.target_base_revision
            or request.permissions != self.original.effective_target_permissions
            or request.run_id == old.run_id
            or str(workspace_root) != seed.capture.worktree_path
        ):
            raise RecoveryRejected("replacement request differs from approved interruption")
        context = FileContextStore(self.sidecar / "contexts", read_only=True).get(
            request.context_manifest_id
        )
        if (
            context.task_id != request.task_id
            or context.role is not request.role
            or context.attempt != request.attempt
            or context.source_revision != request.source_revision
        ):
            raise RecoveryRejected("replacement context identity mismatch")
        validate_reapply_context(self.original, context)
        self.inspect(expected=plan, claimed=guard)
        assert guard.lease is not None
        claim = guard.lease.claim
        record = RecoveryInterruptionInvocation(
            plan_sha256=plan.plan_sha256,
            authorization_sha256=approval.authorization_sha256,
            previous_invocation_sha256=old.record_sha256,
            request=request,
            lease_id=claim.lease.id,
            dispatch_sequence=claim.work_item.dispatch_sequence,
            admitted_at=datetime.now(UTC),
            record_sha256="0" * 64,
        )
        record = record.model_copy(update={"record_sha256": record.recompute_sha256()})
        with guard.write_scope():
            self.store.put_interruption_invocation(self.original.plan_sha256, record)
