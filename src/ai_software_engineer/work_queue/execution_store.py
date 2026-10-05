"""Transactional acceptance and immutable inputs for production role Workers.

The queue owns scheduling facts; TaskOrchestrator still owns verdict validation.
Filesystem output becomes recoverable only after an owner-fenced receipt commits.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Self, cast

from pydantic import TypeAdapter, ValidationError, model_validator
from pymysql.cursors import DictCursor

from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.artifacts.ports import ArtifactRef
from ai_software_engineer.domain.artifact import Artifact, Sha256
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
)
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.identity import ContextId, RepositoryId, RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import Task, TaskId
from ai_software_engineer.domain.workforce import (
    LeaseId,
    RoleAssignment,
    TaskLease,
    validate_assignment_independence,
)
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store.mysql_repository import _decode_task, _encode, open_mysql_connection
from ai_software_engineer.work_queue.models import (
    CheckpointSequence,
    QueueArtifactReceipt,
    QueueClaim,
    QueueCompletion,
    QueuedWorkItem,
    WorkItemId,
)
from ai_software_engineer.work_queue.mysql import MySqlPersistentWorkQueue
from ai_software_engineer.work_queue.ports import (
    QueueConflict,
    QueueCorruption,
    QueueLeaseLost,
    QueueNotFound,
)

if TYPE_CHECKING:
    from ai_software_engineer.manager.verifier_preparation import VerifierPreparationIntent


def record_digest(value: DomainModel) -> str:
    return hashlib.sha256(
        json.dumps(
            value.to_wire(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


class RoleQueueAdmission(DomainModel):
    kind: Literal["role_queue_admission"] = "role_queue_admission"
    task_id: TaskId
    repository_id: RepositoryId
    allocation_sha256: Sha256
    legacy_artifacts: tuple[QueueArtifactReceipt, ...]

    @model_validator(mode="after")
    def unique_receipts(self) -> Self:
        ensure_unique((r.artifact_id for r in self.legacy_artifacts), "legacy Artifact IDs")
        return self


class QueuedRoleStep(DomainModel):
    kind: Literal["queued_role_step"] = "queued_role_step"
    work_item: QueuedWorkItem
    boundary: RoleRunBoundary
    allocation_sha256: Sha256

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        item, boundary = self.work_item, self.boundary
        if (item.task_id, item.role, item.attempt, item.checkpoint_sequence) != (
            boundary.task_id,
            boundary.role,
            boundary.attempt,
            boundary.checkpoint_sequence,
        ):
            raise ValueError("queued step does not bind its work item")
        return self


class AcceptedRoleArtifact(DomainModel):
    kind: Literal["accepted_role_artifact"] = "accepted_role_artifact"
    task_id: TaskId
    work_item_id: WorkItemId
    lease_id: LeaseId
    dispatch_sequence: CheckpointSequence
    checkpoint_sequence: CheckpointSequence
    run_id: RunId
    context_manifest_id: ContextId
    source_revision: NonEmptyStr
    receipt: QueueArtifactReceipt


@dataclass(frozen=True)
class WorkforceFacts:
    assignments: tuple[RoleAssignment, ...] = ()
    leases: tuple[TaskLease, ...] = ()
    adopted_task_ids: frozenset[str] = frozenset()


CapacityReader = Callable[[DictCursor, datetime], WorkforceFacts]
AuthorityLock = Callable[[DictCursor], None]
_TABLES = (
    "work_queue_admissions",
    "work_queue_steps",
    "work_queue_accepted_artifacts",
    "work_queue_execution_baselines",
)
_CANCELLATION_DIGEST = TypeAdapter(Sha256)
_TERMINAL_TASK_STATUSES = frozenset({TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.DONE})


def read_queue_workforce(cursor: DictCursor, now: datetime) -> WorkforceFacts:
    """Read-only compatibility seam; absence means no queue adoption has occurred."""
    cursor.execute(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='work_queue_admissions'"
    )
    table_row = cursor.fetchone()
    if table_row is None:
        return WorkforceFacts()
    if table_row.get("TABLE_NAME") != "work_queue_admissions":
        raise QueueCorruption("unexpected queue table discovery row")
    cursor.execute("SELECT id,task_id,payload_json,sha256 FROM work_queue_admissions")
    adopted = frozenset(_decode(row, RoleQueueAdmission).task_id for row in cursor.fetchall())
    cursor.execute("SELECT assignment_json,lease_json,state,expires_at FROM work_queue_claims")
    assignments, leases = [], []
    for row in cursor.fetchall():
        assignment = RoleAssignment.model_validate_json(row["assignment_json"])
        lease = TaskLease.model_validate_json(row["lease_json"])
        if lease.assignment_id != assignment.id or lease.agent_id != assignment.agent_id:
            raise QueueCorruption("queue workforce identity mismatch")
        assignments.append(assignment)
        if row["state"] == "ACTIVE" and lease.expires_at > now:
            leases.append(lease)
    return WorkforceFacts(tuple(assignments), tuple(leases), adopted)


class MySqlRoleQueue(MySqlPersistentWorkQueue):
    @contextmanager
    def idle_task_scope(self, task_id: str) -> Iterator[DictCursor]:
        """Fence a controlled same-Task Git action against new role claims."""
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self._lock_authority(cursor)
            cursor.execute("SELECT id FROM tasks WHERE id=%s FOR UPDATE", (task_id,))
            if cursor.fetchone() is None:
                raise QueueNotFound(task_id)
            cursor.execute(
                "SELECT lease_id FROM work_queue_claims WHERE task_id=%s "
                "AND state='ACTIVE' FOR UPDATE",
                (task_id,),
            )
            if cursor.fetchone() is not None:
                raise QueueLeaseLost(
                    "baseline action requires all owned role claims to be released"
                )
            yield cursor

    def original_claim(self, lease_id: str) -> QueueClaim:
        """Read the original CLAIMED event, never reconstruct it from current work."""
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT assignment_json,lease_json,model_selection_json,worker_id "
                "FROM work_queue_claims WHERE lease_id=%s",
                (lease_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise QueueNotFound(lease_id)
            cursor.execute(
                "SELECT payload_json,occurred_at FROM work_queue_events "
                "WHERE lease_id=%s AND event_type='CLAIMED' ORDER BY sequence",
                (lease_id,),
            )
            events = cursor.fetchall()
            if len(events) != 1:
                raise QueueCorruption("original claim has no unique immutable claim event")
            event = events[0]
            payload = json.loads(str(event["payload_json"]))
            return QueueClaim.model_validate(
                {
                    "work_item": payload["work_item"],
                    "assignment": json.loads(str(row["assignment_json"])),
                    "lease": json.loads(str(row["lease_json"])),
                    "model_selection": json.loads(str(row["model_selection_json"])),
                    "worker_id": row["worker_id"],
                    "claimed_at": event["occurred_at"],
                }
            )

    def claims_for_work_item(self, work_item_id: str) -> tuple[QueueClaim, ...]:
        """Return exact immutable claim identities, never infer from role/attempt."""
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT lease_id FROM work_queue_claims WHERE work_item_id=%s ORDER BY lease_id",
                (work_item_id,),
            )
            lease_ids = tuple(str(row["lease_id"]) for row in cursor.fetchall())
        return tuple(self.original_claim(identity) for identity in lease_ids)

    def step_for_claim(self, claim: QueueClaim) -> QueuedRoleStep:
        """Resolve the source that preceded the immutable CLAIMED event, by SQL order."""
        original = self.original_claim(claim.lease.id)
        if original != claim:
            raise QueueConflict("historical source request changed its original claim")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT sequence FROM work_queue_events WHERE lease_id=%s AND event_type='CLAIMED'",
                (claim.lease.id,),
            )
            rows = cursor.fetchall()
            if len(rows) != 1:
                raise QueueCorruption("claim source has no unique event sequence")
            cursor.execute(
                "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
                "AND event_type='EXECUTION_BASELINE_REBOUND' AND sequence<%s "
                "ORDER BY sequence DESC LIMIT 1",
                (claim.work_item.id, rows[0]["sequence"]),
            )
            event = cursor.fetchone()
        baseline_sha = None
        if event is not None:
            payload = json.loads(str(event["payload_json"]))
            baseline_sha = str(payload["detail"]["binding_sha256"])
        return self.step_for_invocation(claim.work_item.id, baseline_sha)

    def preparation_resume_consumed(
        self,
        intent: VerifierPreparationIntent,
        claim: QueueClaim,
    ) -> bool:
        from ai_software_engineer.work_queue.preparation_resume import preparation_resume_consumed

        return preparation_resume_consumed(self, self._dsn, intent, claim)

    """T046 plus explicit native-reservation adoption and accepted-output receipts."""

    def resolve_wait(self, resolution: DeliveryResolution) -> QueuedWorkItem:
        """Consume sealed engineering proof with Task, queue and budget in one fence."""
        resolution.validate_integrity()
        now = self._clock()
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self._lock_authority(cursor)
            current = self._get_locked(cursor, resolution.work_item_id, lock=True)
            cursor.execute(
                "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
                "AND event_type='WAIT_RESOLVED' ORDER BY sequence DESC FOR UPDATE",
                (current.id,),
            )
            for prior in cursor.fetchall():
                payload = json.loads(str(prior["payload_json"]))
                detail = payload.get("detail", {})
                if detail.get("resolution_sha256") == resolution.resolution_sha256:
                    if detail.get("resolution") != resolution.to_wire():
                        raise QueueCorruption(
                            "consumed engineering decision changed its exact body"
                        )
                    return self._get_locked(cursor, str(detail["next_work_item_id"]), lock=True)
            disposition = current.wait_disposition
            if (
                current.status
                not in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
                or disposition is None
                or disposition.disposition_sha256 != resolution.expected_disposition_sha256
                or current.task_id != resolution.task_id
            ):
                raise QueueConflict("engineering decision does not match the current wait")
            cursor.execute(
                "SELECT payload_json,revision FROM tasks WHERE id=%s FOR UPDATE", (current.task_id,)
            )
            row = cursor.fetchone()
            if row is None:
                raise QueueCorruption("waiting Task is missing")
            task = _decode_task(current.task_id, str(row["payload_json"]))
            step = self.step(current.id)
            if (
                task.status in {TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.DONE}
                or task_intent_sha256(task) != resolution.expected_task_intent_sha256
                or digest(task.to_wire()) != resolution.task_snapshot_sha256
                or row["revision"] != resolution.task_revision
                or resolution.task_revision != resolution.expected_checkpoint_sequence
                or record_digest(step) != resolution.step_sha256
                or step.boundary.source_revision != resolution.expected_source_revision
            ):
                raise QueueConflict("engineering decision Task or source facts drifted")
            cursor.execute(
                "SELECT lease_id FROM work_queue_claims WHERE work_item_id=%s "
                "AND state='ACTIVE' FOR UPDATE",
                (current.id,),
            )
            if cursor.fetchone() is not None:
                raise QueueLeaseLost("a live claim prevents engineering wait resolution")
            if resolution.resolution_kind in {
                DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
                DeliveryResolutionKind.REVERIFY_CANDIDATE,
                DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION,
            }:
                if current.role not in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER):
                    raise QueueConflict("wait does not belong to a delivery role")
                failure = resolution.retry_failure
                if resolution.resolution_kind is DeliveryResolutionKind.REVERIFY_CANDIDATE:
                    verification = resolution.verification_retry
                    if (
                        current.role is not AgentRole.QA
                        or verification is None
                        or verification.candidate_revision != step.boundary.source_revision
                        or task.work_budget_exhausted
                        or task.attempts >= task.max_attempts
                    ):
                        raise QueueConflict("候选复验缺少精确 QA 证据或冻结工作额度")
                    cursor.execute(
                        "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
                        "WHERE task_id=%s",
                        (task.id,),
                    )
                    accepted = tuple(
                        _decode(record, AcceptedRoleArtifact) for record in cursor.fetchall()
                    )
                    if not any(
                        record.work_item_id == current.id
                        and record.receipt.artifact_id == verification.previous_qa_artifact_id
                        and record.receipt.sha256 == verification.previous_qa_sha256
                        and record.source_revision == verification.candidate_revision
                        and record.run_id == verification.previous_run_id
                        and record.context_manifest_id == verification.previous_context_manifest_id
                        for record in accepted
                    ):
                        raise QueueConflict("候选复验没有原 QA 的精确接纳记录")
                    updated_task = Task.model_validate(
                        {**task.to_wire(), "attempts": task.attempts + 1}
                    )
                elif (
                    resolution.resolution_kind is DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION
                ):
                    preparation = resolution.verifier_preparation
                    if (
                        current.role not in {AgentRole.QA, AgentRole.REVIEWER}
                        or preparation is None
                        or preparation.native_execution_state != "FINISHED"
                        or preparation.candidate_revision != step.boundary.source_revision
                        or task.work_budget_exhausted
                        or task.attempts >= task.max_attempts
                    ):
                        raise QueueConflict("验证准备重试缺少精确已终结证据或冻结工作额度")
                    updated_task = Task.model_validate(
                        {**task.to_wire(), "attempts": task.attempts + 1}
                    )
                elif resolution.retry_cause == "provider_transient":
                    if (
                        failure is None
                        or failure.role is not current.role
                        or failure.attempt != task.attempts
                    ):
                        raise QueueConflict(
                            "new execution requires the exact sealed interruption budget fact"
                        )
                    updated_task = task.with_retry_failure(failure)
                elif resolution.retry_cause == "local_execution_limit":
                    if (
                        failure is not None
                        or task.work_budget_exhausted
                        or task.attempts >= task.max_attempts
                    ):
                        raise QueueConflict("local interruption has no frozen work allowance")
                    updated_task = Task.model_validate(
                        {**task.to_wire(), "attempts": task.attempts + 1}
                    )
                else:
                    raise QueueConflict("retry requires a typed sealed interruption cause")
                if updated_task.attempts <= task.attempts:
                    raise QueueConflict("no frozen execution allowance remains")
                cursor.execute(
                    "UPDATE tasks SET payload_json=%s WHERE id=%s",
                    (_encode(updated_task.to_wire()), task.id),
                )
                identity = "work_" + resolution.resolution_sha256
                next_item = QueuedWorkItem.model_validate(
                    {
                        **current.to_wire(),
                        "id": identity,
                        "attempt": updated_task.attempts,
                        "status": WorkItemStatus.READY,
                        "wait_reason": None,
                        "wait_disposition": None,
                        "available_at": None,
                        "parent_work_item_id": current.id,
                        "dispatch_sequence": 0,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                boundary = RoleRunBoundary(
                    task.id,
                    current.role,
                    updated_task.attempts,
                    resolution.task_revision,
                    resolution.expected_source_revision,
                )
                next_step = QueuedRoleStep(
                    work_item=next_item,
                    boundary=boundary,
                    allocation_sha256=step.allocation_sha256,
                )
                _put(cursor, "work_queue_steps", identity, task.id, next_step)
                next_item = self._enqueue_locked(cursor, next_item)
                settled = current.model_copy(
                    update={
                        "status": WorkItemStatus.CLOSED,
                        "updated_at": now,
                        "wait_reason": None,
                        "wait_disposition": None,
                    }
                )
            else:
                if resolution.retry_failure is not None:
                    raise QueueConflict("noninvoking resolution cannot add a retry failure")
                if resolution.resolution_kind is DeliveryResolutionKind.REPLAY_RECORDED_RESULT:
                    original = resolution.original_authority
                    if original is None:
                        raise QueueConflict(
                            "result replay requires the original producer authority"
                        )
                    claim = self.original_claim(original.lease.id)
                    if (
                        claim.assignment != original.assignment
                        or claim.lease != original.lease
                        or claim.model_selection != original.model_selection
                        or (
                            claim.work_item.id,
                            claim.work_item.role,
                            claim.work_item.attempt,
                            claim.work_item.checkpoint_sequence,
                        )
                        != (current.id, current.role, current.attempt, current.checkpoint_sequence)
                        or current.preferred_agent_id != original.assignment.agent_id
                    ):
                        raise QueueConflict("result replay changed the original frozen producer")
                next_item = current.model_copy(
                    update={
                        "status": WorkItemStatus.READY,
                        "updated_at": now,
                        "wait_reason": None,
                        "wait_disposition": None,
                        "dispatch_sequence": current.dispatch_sequence + 1,
                    }
                )
                settled = next_item
            self._update_item(cursor, settled)
            self._append_event(
                cursor,
                settled,
                from_status=current.status,
                event_type="WAIT_RESOLVED",
                lease_id=None,
                occurred_at=now,
                detail={
                    "resolution_sha256": resolution.resolution_sha256,
                    "next_work_item_id": next_item.id,
                    "resolution": resolution.to_wire(),
                    "budget_refund": False,
                },
            )
            return next_item

    def __init__(
        self,
        dsn: str,
        *,
        capacity_reader: CapacityReader | None = None,
        authority_lock: AuthorityLock | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._capacity_reader = capacity_reader
        self._external_lock = authority_lock
        self._clock = clock or (lambda: datetime.now(UTC))
        super().__init__(dsn)
        with (
            closing(open_mysql_connection(dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            for table in _TABLES:
                cursor.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} (id VARCHAR(128) PRIMARY KEY, "
                    "task_id VARCHAR(128) NOT NULL, payload_json JSON NOT NULL, "
                    f"sha256 CHAR(64) NOT NULL, KEY ix_{table}_task(task_id)) "
                    "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"
                )
                cursor.execute(f"SHOW COLUMNS FROM {table}")
                if {row["Field"] for row in cursor.fetchall()} != {
                    "id",
                    "task_id",
                    "payload_json",
                    "sha256",
                }:
                    raise QueueCorruption("unexpected role queue record schema")

    def _lock_authority(self, cursor: object) -> None:
        typed = cast(DictCursor, cursor)
        if self._external_lock is not None:
            self._external_lock(typed)
        super()._lock_authority(typed)

    def _external_facts(self, cursor: DictCursor, now: datetime) -> WorkforceFacts:
        return (
            self._capacity_reader(cursor, now)
            if self._capacity_reader is not None
            else WorkforceFacts()
        )

    def list_active_leases(self, *, now: datetime) -> tuple[TaskLease, ...]:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            external = self._external_facts(cursor, now)
        return (*super().list_active_leases(now=now), *external.leases)

    def list_assignments(self) -> tuple[RoleAssignment, ...]:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            external = self._external_facts(cursor, datetime.now(UTC))
        return (*super().list_assignments(), *external.assignments)

    def _validate_capacity_locked(
        self, cursor: object, assignment: RoleAssignment, *, agent_capacity: int, now: datetime
    ) -> None:
        facts = self._external_facts(cast(DictCursor, cursor), now)
        used = sum(
            lease.capacity_units for lease in facts.leases if lease.agent_id == assignment.agent_id
        )
        super()._validate_capacity_locked(
            cursor, assignment, agent_capacity=agent_capacity - used, now=now
        )
        try:
            validate_assignment_independence(assignment, facts.assignments)
        except ValueError as error:
            raise QueueConflict(str(error)) from error

    def admit(self, admission: RoleQueueAdmission, step: QueuedRoleStep) -> None:
        if (
            admission.task_id != step.boundary.task_id
            or admission.allocation_sha256 != step.allocation_sha256
            or admission.repository_id != step.work_item.repository_id
        ):
            raise QueueConflict("admission does not bind step")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self._lock_authority(cursor)
            _put(cursor, "work_queue_admissions", admission.task_id, admission.task_id, admission)
            _put(cursor, "work_queue_steps", step.work_item.id, admission.task_id, step)
            self._enqueue_locked(cursor, step.work_item)

    def admission(self, task_id: str) -> RoleQueueAdmission | None:
        return self._find("work_queue_admissions", task_id, RoleQueueAdmission)

    def step(self, work_item_id: str) -> QueuedRoleStep:
        from ai_software_engineer.work_queue.baseline import effective_step

        return effective_step(self, self.original_step(work_item_id))

    def step_for_invocation(self, work_item_id: str, baseline_sha256: str | None) -> QueuedRoleStep:
        from ai_software_engineer.work_queue.baseline import effective_step

        return effective_step(
            self, self.original_step(work_item_id), baseline_sha256=baseline_sha256, latest=False
        )

    def original_step(self, work_item_id: str) -> QueuedRoleStep:
        step = self._find("work_queue_steps", work_item_id, QueuedRoleStep)
        if step is None:
            raise QueueNotFound("role step binding missing")
        if step.work_item.id != work_item_id:
            raise QueueCorruption("role step identity mismatch")
        return step

    def items_for_task(self, task_id: str) -> tuple[QueuedWorkItem, ...]:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT id,payload_json FROM work_queue_items WHERE task_id=%s "
                "ORDER BY checkpoint_sequence,attempt,id",
                (task_id,),
            )
            return tuple(self._decode_item(row) for row in cursor.fetchall())

    def cancellation_fence(self, cursor: DictCursor, task_id: str) -> None:
        """Fence a user-cancelled Task mutation against current execution authority.

        The caller owns all historical Task process locks and has already sealed
        the exact deletion receipt. This callback is compatible with the existing
        MySqlTaskRepository mutation fence; it neither terminates Task state nor
        releases a claim itself.
        """
        self._lock_authority(cursor)
        self._require_cancelled_task_idle(cursor, task_id, now=self._clock())

    def close_cancelled_task(
        self,
        task: Task,
        *,
        expected_items: tuple[QueuedWorkItem, ...],
        cancellation_sha256: str,
        now: datetime,
    ) -> tuple[QueuedWorkItem, ...]:
        """Close abandoned work only after the exact Task was durably terminated.

        Cancellation is not a Worker execution or a completion verdict. No claim,
        Assignment, successor Run or accepted Artifact is created. Existing closed
        work and immutable retry/wait history retain their original facts.
        """
        self._require_aware(now, "cancellation clock")
        digest = _CANCELLATION_DIGEST.validate_python(cancellation_sha256)
        if task.status not in _TERMINAL_TASK_STATUSES:
            raise QueueConflict("取消队列前必须先将任务按审计事件结束")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self._lock_authority(cursor)
            cursor.execute(
                "SELECT id,status,payload_json FROM tasks WHERE id=%s FOR UPDATE", (task.id,)
            )
            task_row = cursor.fetchone()
            if task_row is None:
                raise QueueNotFound("取消队列的任务不存在")
            current_task = self._decode_model(task_row, "payload_json", Task)
            if task_row["id"] != current_task.id or task_row["status"] != current_task.status.value:
                raise QueueCorruption("取消队列的任务索引与正文不一致")
            if current_task.to_wire() != task.to_wire():
                raise QueueConflict("取消队列的任务快照已变化")
            if now < task.updated_at:
                raise QueueConflict("取消队列的时间早于任务结束时间")
            items = self.verify_cancelled_inventory(
                cursor, task, expected_items, cancellation_sha256=digest, now=now
            )
            # A stale event timestamp must not conceal a currently valid lease,
            # and a caller-supplied future timestamp cannot skip a live owner.
            live_now = self._clock()
            self._require_aware(live_now, "cancellation authority clock")
            expired_claims = self._require_cancelled_task_idle(
                cursor, task.id, now=min(now, live_now)
            )
            item_by_id = {item.id: item for item in items}
            for row in expired_claims:
                claim_item = item_by_id.get(self._text(row, "work_item_id"))
                assignment = self._decode_model(row, "assignment_json", RoleAssignment)
                if claim_item is None or assignment.repository_id != claim_item.repository_id:
                    raise QueueCorruption("取消队列的租约与仓库工作项不一致")
            for row in expired_claims:
                self._release_claim(
                    cursor, self._text(row, "lease_id"), state="EXPIRED", ended_at=now
                )
            closed_items = []
            for item in items:
                if item.status is WorkItemStatus.CLOSED:
                    closed_items.append(item)
                    continue
                closed = item.model_copy(
                    update={
                        "status": WorkItemStatus.CLOSED,
                        "wait_reason": None,
                        "wait_disposition": None,
                        "available_at": None,
                        "updated_at": now,
                    }
                )
                self._update_item(cursor, closed)
                self._append_event(
                    cursor,
                    closed,
                    from_status=item.status,
                    event_type="REQUIREMENT_CANCELLED",
                    lease_id=None,
                    occurred_at=now,
                    detail={
                        "cancellation_sha256": digest,
                        "task_sha256": record_digest(task),
                        "previous_work_item": item.to_wire(),
                        "expired_lease_ids": [
                            self._text(row, "lease_id")
                            for row in expired_claims
                            if row["work_item_id"] == item.id
                        ],
                    },
                )
                closed_items.append(closed)
            return tuple(closed_items)

    def verify_cancelled_inventory(
        self,
        cursor: DictCursor,
        task: Task,
        expected_items: tuple[QueuedWorkItem, ...],
        *,
        cancellation_sha256: str,
        now: datetime,
    ) -> tuple[QueuedWorkItem, ...]:
        """Fence the receipt's exact queue inventory, including partial replay.

        This shares the caller's SQL transaction. The deletion application uses
        it in the Task mutation fence as well as the queue close transaction, so
        an unclaimed scheduling change cannot expand the sealed cancellation.
        """
        self._require_aware(now, "cancellation inventory clock")
        digest = _CANCELLATION_DIGEST.validate_python(cancellation_sha256)
        self._lock_authority(cursor)
        expected = {item.id: item for item in expected_items}
        if len(expected) != len(expected_items) or any(
            item.task_id != task.id or item.repository_scopes != (task.repository,)
            for item in expected_items
        ):
            raise QueueConflict("删除凭据的队列范围与任务不一致")
        cursor.execute(
            "SELECT id,task_id,repository_id,status,payload_json FROM work_queue_items "
            "WHERE task_id=%s ORDER BY checkpoint_sequence,attempt,id FOR UPDATE",
            (task.id,),
        )
        items = tuple(self._cancellation_item(row, task) for row in cursor.fetchall())
        if {item.id for item in items} != set(expected):
            raise QueueConflict("删除凭据封存后的队列范围已变化")
        repository_ids = {item.repository_id for item in items}
        if len(repository_ids) > 1:
            raise QueueCorruption("取消队列的任务跨越了不同仓库")
        cursor.execute(
            "SELECT id,task_id,payload_json,sha256 FROM work_queue_admissions "
            "WHERE id=%s FOR UPDATE",
            (task.id,),
        )
        admission_row = cursor.fetchone()
        if admission_row is not None:
            admission = _decode(admission_row, RoleQueueAdmission)
            if any(item.repository_id != admission.repository_id for item in items):
                raise QueueCorruption("取消队列的仓库与原始派发不一致")
        for item in items:
            original = expected[item.id]
            if now < item.updated_at:
                raise QueueConflict("取消队列的时间早于最近的调度事实")
            replay = self._check_cancellation_replay(cursor, item, digest)
            if item == original:
                continue
            closed = original.model_copy(
                update={
                    "status": WorkItemStatus.CLOSED,
                    "wait_reason": None,
                    "wait_disposition": None,
                    "available_at": None,
                    "updated_at": now,
                }
            )
            if original.status is WorkItemStatus.CLOSED or item != closed or not replay:
                raise QueueConflict("删除凭据封存后的队列事实已变化")
        return items

    def _require_cancelled_task_idle(
        self, cursor: DictCursor, task_id: str, *, now: datetime
    ) -> tuple[Mapping[str, object], ...]:
        self._require_aware(now, "cancellation authority clock")
        cursor.execute(
            "SELECT lease_id,work_item_id,task_id,assignment_json,lease_json,expires_at "
            "FROM work_queue_claims WHERE state='ACTIVE' AND "
            "(task_id=%s OR work_item_id IN "
            "(SELECT id FROM work_queue_items WHERE task_id=%s)) "
            "ORDER BY lease_id FOR UPDATE",
            (task_id, task_id),
        )
        rows = tuple(cursor.fetchall())
        for row in rows:
            lease = self._decode_model(row, "lease_json", TaskLease)
            assignment = self._decode_model(row, "assignment_json", RoleAssignment)
            if (
                row["task_id"] != task_id
                or lease.task_id != task_id
                or assignment.task_id != task_id
                or row["lease_id"] != lease.id
                or assignment.lease_id != lease.id
                or lease.assignment_id != assignment.id
                or lease.agent_id != assignment.agent_id
                or self._parse_time(self._text(row, "expires_at")) != lease.expires_at
            ):
                raise QueueCorruption("取消任务的租约身份或时限不一致")
            if lease.expires_at > now:
                raise QueueConflict("任务仍有有效执行租约, 不能删除需求")
        if any(
            lease.task_id == task_id and lease.expires_at > now
            for lease in self._external_facts(cursor, now).leases
        ):
            raise QueueConflict("任务仍有有效执行租约, 不能删除需求")
        return rows

    def _cancellation_item(self, row: Mapping[str, object], task: Task) -> QueuedWorkItem:
        item = self._decode_item(row)
        if (
            row["task_id"] != item.task_id
            or item.task_id != task.id
            or row["repository_id"] != item.repository_id
            or row["status"] != item.status.value
            or item.repository_scopes != (task.repository,)
        ):
            raise QueueCorruption("取消队列的工作项与任务仓库不一致")
        return item

    def _check_cancellation_replay(
        self, cursor: DictCursor, item: QueuedWorkItem, digest: str
    ) -> bool:
        cursor.execute(
            "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
            "AND event_type='REQUIREMENT_CANCELLED' ORDER BY sequence DESC LIMIT 1 FOR UPDATE",
            (item.id,),
        )
        row = cursor.fetchone()
        if row is None:
            return False
        try:
            payload: object = json.loads(self._text(row, "payload_json"))
            if not isinstance(payload, dict) or not isinstance(payload.get("detail"), dict):
                raise ValueError("invalid cancellation event")
            detail = payload["detail"]
            saved_digest = _CANCELLATION_DIGEST.validate_python(detail["cancellation_sha256"])
            saved_item = QueuedWorkItem.model_validate(payload["work_item"])
        except (KeyError, ValueError, TypeError, ValidationError) as error:
            raise QueueCorruption("需求取消事件正文损坏") from error
        if saved_item != item or item.status is not WorkItemStatus.CLOSED:
            raise QueueCorruption("需求取消事件与当前队列事实不一致")
        if saved_digest != digest:
            raise QueueConflict("已取消工作项绑定了另一份删除凭据")
        return True

    def _find[T: DomainModel](self, table: str, key: str, model: type[T]) -> T | None:
        if table not in _TABLES:
            raise ValueError("unknown queue record table")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                f"SELECT id,task_id,payload_json,sha256 FROM {table} WHERE id=%s", (key,)
            )
            row = cursor.fetchone()
            return _decode(row, model) if row is not None else None

    def assert_owner(
        self, cursor: DictCursor, claim: QueueClaim, token: str, *, now: datetime
    ) -> None:
        self._lock_authority(cursor)
        current = self._get_locked(cursor, claim.work_item.id, lock=True)
        if current.dispatch_sequence != claim.work_item.dispatch_sequence:
            raise QueueLeaseLost("Worker generation changed")
        self._require_active_claim(cursor, current.id, claim.lease.id, token, now=now)

    @contextmanager
    def fence(self, claim: QueueClaim, token: str) -> Iterator[DictCursor]:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self.assert_owner(cursor, claim, token, now=datetime.now(UTC))
            yield cursor
            self._require_active_claim(
                cursor, claim.work_item.id, claim.lease.id, token, now=datetime.now(UTC)
            )

    def accept_artifact(
        self, claim: QueueClaim, token: str, store: ArtifactStore, artifact: Artifact
    ) -> ArtifactRef:
        if (
            artifact.task_id != claim.work_item.task_id
            or artifact.producer.role is not claim.work_item.role
            or artifact.producer.agent_id != claim.assignment.agent_id
        ):
            raise QueueConflict("Artifact does not belong to claimed role")
        with self.fence(claim, token) as cursor:
            reference = store.put(artifact)
            persisted = store.get(reference.artifact_id)
            if persisted != artifact:
                raise QueueCorruption("Artifact readback changed")
            accepted = AcceptedRoleArtifact(
                task_id=artifact.task_id,
                work_item_id=claim.work_item.id,
                lease_id=claim.lease.id,
                dispatch_sequence=claim.work_item.dispatch_sequence,
                checkpoint_sequence=claim.work_item.checkpoint_sequence,
                run_id=artifact.producer.run_id,
                context_manifest_id=artifact.context_manifest_id,
                source_revision=artifact.source_revision,
                receipt=QueueArtifactReceipt(
                    artifact_id=reference.artifact_id, sha256=reference.sha256
                ),
            )
            _put(
                cursor,
                "work_queue_accepted_artifacts",
                reference.artifact_id,
                artifact.task_id,
                accepted,
            )
            return reference

    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT id,task_id,payload_json,sha256 FROM work_queue_accepted_artifacts "
                "WHERE task_id=%s ORDER BY id",
                (task_id,),
            )
            return tuple(_decode(row, AcceptedRoleArtifact) for row in cursor.fetchall())

    def finish(
        self,
        claim: QueueClaim,
        token: str,
        *,
        next_step: QueuedRoleStep | None,
        now: datetime,
        guard: Callable[[], None] | None = None,
    ) -> QueueCompletion:
        self._require_aware(now, "completion clock")
        receipts = tuple(
            item.receipt
            for item in self.accepted(claim.work_item.task_id)
            if item.work_item_id == claim.work_item.id
        )
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor(DictCursor) as cursor,
        ):
            self._lock_authority(cursor)
            current = self._get_locked(cursor, claim.work_item.id, lock=True)
            expires_at = None
            if current.status is not WorkItemStatus.CLOSED:
                if guard is not None:
                    guard()
                if current.dispatch_sequence != claim.work_item.dispatch_sequence:
                    raise QueueLeaseLost("Worker generation changed")
                active = self._require_active_claim(
                    cursor, current.id, claim.lease.id, token, now=self._clock()
                )
                expires_at = self._parse_time(self._text(active, "expires_at"))
            if next_step is not None:
                _put(
                    cursor,
                    "work_queue_steps",
                    next_step.work_item.id,
                    claim.work_item.task_id,
                    next_step,
                )
            result = self._complete_locked(
                cursor,
                claim.work_item.id,
                lease_id=claim.lease.id,
                owner_token=token,
                receipts=receipts,
                next_work_item=next_step.work_item if next_step else None,
                now=now,
            )
            # 'now' is the deterministic event/next-step timestamp, not proof
            # that the lease survived SQL lock waits. The authority lock prevents
            # renewal/reclaim here, so check the locked lease's expiry again before
            # commit; rejection rolls back completion and successor publication.
            if expires_at is not None:
                if guard is not None:
                    guard()
                if self._clock() >= expires_at:
                    raise QueueLeaseLost("Lease expired during queue completion")
            return result


def _put(cursor: DictCursor, table: str, key: str, task_id: str, record: DomainModel) -> None:
    cursor.execute(
        f"SELECT id,task_id,payload_json,sha256 FROM {table} WHERE id=%s FOR UPDATE", (key,)
    )
    existing = cursor.fetchone()
    if existing is not None:
        if _decode(existing, type(record)) != record:
            raise QueueConflict("immutable queue record changed")
        return
    cursor.execute(
        f"INSERT INTO {table}(id,task_id,payload_json,sha256) VALUES (%s,%s,%s,%s)",
        (
            key,
            task_id,
            json.dumps(record.to_wire(), sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            record_digest(record),
        ),
    )


def _decode[T: DomainModel](row: dict[str, object], model: type[T]) -> T:
    from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption

    payload = row["payload_json"]
    if not isinstance(payload, str):
        raise QueueCorruption("queue record payload is not text")
    try:
        record = model.model_validate_json(payload)
    except ValidationError as error:
        raise QueueCorruption("invalid queue record contract") from error
    if isinstance(record, RoleQueueAdmission):
        key, task_id = record.task_id, record.task_id
    elif isinstance(record, QueuedRoleStep):
        key, task_id = record.work_item.id, record.boundary.task_id
    elif isinstance(record, AcceptedRoleArtifact):
        key, task_id = record.receipt.artifact_id, record.task_id
    elif isinstance(record, BaselineQueueConsumption):
        key, task_id = record.binding.binding_sha256, record.task_id
    else:
        raise QueueCorruption("unknown queue record model")
    if row["id"] != key or row["task_id"] != task_id:
        raise QueueCorruption("queue record indexed identity mismatch")
    if record_digest(record) != row["sha256"]:
        raise QueueCorruption("queue record digest mismatch")
    return record
