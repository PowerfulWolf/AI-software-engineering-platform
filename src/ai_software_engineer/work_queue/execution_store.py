"""Transactional acceptance and immutable inputs for production role Workers.

The queue owns scheduling facts; TaskOrchestrator still owns verdict validation.
Filesystem output becomes recoverable only after an owner-fenced receipt commits.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self, cast

from pydantic import ValidationError, model_validator
from pymysql.cursors import DictCursor

from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.artifacts.ports import ArtifactRef
from ai_software_engineer.domain.artifact import Artifact, Sha256
from ai_software_engineer.domain.enums import WorkItemStatus
from ai_software_engineer.domain.identity import ContextId, RepositoryId, RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.domain.workforce import (
    LeaseId,
    RoleAssignment,
    TaskLease,
    validate_assignment_independence,
)
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store.mysql_repository import open_mysql_connection
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
_TABLES = ("work_queue_admissions", "work_queue_steps", "work_queue_accepted_artifacts")


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
    """T046 plus explicit native-reservation adoption and accepted-output receipts."""

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
    else:
        raise QueueCorruption("unknown queue record model")
    if row["id"] != key or row["task_id"] != task_id:
        raise QueueCorruption("queue record indexed identity mismatch")
    if record_digest(record) != row["sha256"]:
        raise QueueCorruption("queue record digest mismatch")
    return record
