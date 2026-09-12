"""MySQL/InnoDB implementation of the organization PersistentWorkQueue."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pymysql
from pydantic import TypeAdapter, ValidationError
from pymysql.connections import Connection

from ai_software_engineer.domain.enums import WorkItemStatus
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.workforce import (
    ModelSelection,
    RoleAssignment,
    TaskLease,
    validate_assignment_independence,
)
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue.models import (
    LeaseWorkerId,
    QueueArtifactReceipt,
    QueueClaim,
    QueueCompletion,
    QueuedWorkItem,
    WorkItemId,
)
from ai_software_engineer.work_queue.ports import (
    QueueConflict,
    QueueCorruption,
    QueueError,
    QueueNotFound,
)

_RISK_RANK = {"low": 0, "normal": 1, "high": 2, "critical": 3}
_ACTIVE_STATUSES = frozenset({WorkItemStatus.LEASED, WorkItemStatus.RUNNING})
_WAIT_STATUSES = frozenset({WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY})
_WORKER_ADAPTER = TypeAdapter(LeaseWorkerId)


class MySqlPersistentWorkQueue:
    """Durable Run queue with owner-fenced Lease lifecycle operations."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._initialize_schema()

    def enqueue(self, item: QueuedWorkItem) -> QueuedWorkItem:
        """Publish a schedulable or explicitly waiting item with exact-replay semantics."""
        self._validate_enqueue_status(item)
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor() as cursor,
        ):
            self._lock_authority(cursor)
            return self._enqueue_locked(cursor, item)

    def get(self, work_item_id: WorkItemId | str) -> QueuedWorkItem:
        with closing(open_mysql_connection(self._dsn)) as connection:
            try:
                with connection.cursor() as cursor:
                    item = self._get_locked(cursor, str(work_item_id), lock=False)
            except pymysql.MySQLError as error:
                raise QueueError("failed to read WorkItem") from error
        return item

    def list_schedulable(self, *, now: datetime, limit: int = 100) -> tuple[QueuedWorkItem, ...]:
        self._require_aware(now, "queue clock")
        if limit < 1 or limit > 1000:
            raise ValueError("queue list limit must be between 1 and 1000")
        now_key = self._time_key(now)
        with closing(open_mysql_connection(self._dsn)) as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, payload_json FROM work_queue_items
                        WHERE status = 'READY'
                           OR (status = 'RETRY_SCHEDULED' AND available_at <= %s)
                        ORDER BY priority DESC, risk_rank DESC, created_at ASC, id ASC
                        LIMIT %s
                        """,
                        (now_key, limit),
                    )
                    rows = cast(tuple[Mapping[str, object], ...], cursor.fetchall())
            except pymysql.MySQLError as error:
                raise QueueError("failed to list schedulable WorkItems") from error
        return tuple(self._decode_item(row) for row in rows)

    def list_active_leases(self, *, now: datetime) -> tuple[TaskLease, ...]:
        self._require_aware(now, "lease clock")
        with closing(open_mysql_connection(self._dsn)) as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT lease_json FROM work_queue_claims
                        WHERE state = 'ACTIVE' AND expires_at > %s
                        ORDER BY lease_id ASC
                        """,
                        (self._time_key(now),),
                    )
                    rows = cast(tuple[Mapping[str, object], ...], cursor.fetchall())
            except pymysql.MySQLError as error:
                raise QueueError("failed to list active Leases") from error
        return tuple(self._decode_model(row, "lease_json", TaskLease) for row in rows)

    def list_assignments(self) -> tuple[RoleAssignment, ...]:
        with closing(open_mysql_connection(self._dsn)) as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT assignment_json FROM work_queue_claims ORDER BY lease_id ASC"
                    )
                    rows = cast(tuple[Mapping[str, object], ...], cursor.fetchall())
            except pymysql.MySQLError as error:
                raise QueueError("failed to list queue Assignments") from error
        return tuple(self._decode_model(row, "assignment_json", RoleAssignment) for row in rows)

    def claim(
        self,
        item: QueuedWorkItem,
        *,
        assignment: RoleAssignment,
        lease: TaskLease,
        model_selection: ModelSelection,
        worker_id: LeaseWorkerId | str,
        owner_token: str,
        agent_capacity: int,
        now: datetime,
    ) -> QueueClaim:
        """Atomically reserve one current item and one unit of Agent capacity."""
        self._require_aware(now, "claim clock")
        typed_worker_id = _WORKER_ADAPTER.validate_python(worker_id)
        token_digest = self._token_digest(owner_token)
        if agent_capacity < 1 or agent_capacity > 16:
            raise ValueError("agent_capacity must be between 1 and 16")
        self._validate_allocation(item, assignment, lease, model_selection, now=now)

        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor() as cursor,
        ):
            self._lock_authority(cursor)
            current = self._get_locked(cursor, item.id, lock=True)
            if current != item:
                raise QueueConflict(f"WorkItem {item.id} changed before claim")
            if not self._is_schedulable(current, now=now):
                raise QueueConflict(f"WorkItem {item.id} is not schedulable")
            self._validate_capacity_locked(
                cursor,
                assignment,
                agent_capacity=agent_capacity,
                now=now,
            )
            self._validate_independence_locked(cursor, assignment)
            claimed_item = current.model_copy(
                update={
                    "status": WorkItemStatus.LEASED,
                    "wait_reason": None,
                    "available_at": None,
                    "updated_at": now,
                }
            )
            cursor.execute(
                "UPDATE work_queue_items SET payload_json=%s,status=%s,available_at=NULL,"
                "updated_at=%s,version=version+1 WHERE id=%s",
                (
                    self._encode(claimed_item),
                    claimed_item.status.value,
                    self._time_key(now),
                    claimed_item.id,
                ),
            )
            try:
                cursor.execute(
                    """
                    INSERT INTO work_queue_claims
                        (lease_id, work_item_id, task_id, agent_id, worker_id,
                         owner_token_sha256, assignment_json, lease_json, model_selection_json,
                         capacity_units, state, acquired_at, expires_at, last_heartbeat_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ACTIVE',%s,%s,%s)
                    """,
                    (
                        lease.id,
                        claimed_item.id,
                        claimed_item.task_id,
                        assignment.agent_id,
                        typed_worker_id,
                        token_digest,
                        self._encode(assignment),
                        self._encode(lease),
                        self._encode(model_selection),
                        lease.capacity_units,
                        self._time_key(lease.acquired_at),
                        self._time_key(lease.expires_at),
                        self._time_key(now),
                    ),
                )
            except pymysql.IntegrityError as error:
                raise QueueConflict("Lease or Assignment identity is already claimed") from error
            self._append_event(
                cursor,
                claimed_item,
                from_status=current.status,
                event_type="CLAIMED",
                lease_id=lease.id,
                occurred_at=now,
            )
            return QueueClaim(
                work_item=claimed_item,
                assignment=assignment,
                lease=lease,
                model_selection=model_selection,
                worker_id=typed_worker_id,
                claimed_at=now,
            )

    def start(
        self,
        work_item_id: WorkItemId | str,
        *,
        lease_id: str,
        owner_token: str,
        now: datetime,
    ) -> QueuedWorkItem:
        """Move a claimed item to RUNNING under its live owner token."""
        self._require_aware(now, "start clock")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor() as cursor,
        ):
            self._lock_authority(cursor)
            current = self._get_locked(cursor, str(work_item_id), lock=True)
            self._require_active_claim(cursor, current.id, lease_id, owner_token, now=now)
            if current.status is WorkItemStatus.RUNNING:
                return current
            if current.status is not WorkItemStatus.LEASED:
                raise QueueConflict("only a LEASED WorkItem can start")
            started = current.model_copy(
                update={"status": WorkItemStatus.RUNNING, "updated_at": now}
            )
            self._update_item(cursor, started)
            self._append_event(
                cursor,
                started,
                from_status=current.status,
                event_type="STARTED",
                lease_id=lease_id,
                occurred_at=now,
            )
            return started

    def renew(
        self,
        work_item_id: WorkItemId | str,
        *,
        lease_id: str,
        owner_token: str,
        now: datetime,
        expires_at: datetime,
    ) -> TaskLease:
        """Extend a live Lease; an expired Lease cannot be resurrected."""
        self._require_aware(now, "renew clock")
        self._require_aware(expires_at, "renew expiry")
        if expires_at <= now:
            raise ValueError("renewed Lease expiry must be later than now")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor() as cursor,
        ):
            self._lock_authority(cursor)
            current = self._get_locked(cursor, str(work_item_id), lock=True)
            row = self._require_active_claim(cursor, current.id, lease_id, owner_token, now=now)
            if current.status not in _ACTIVE_STATUSES:
                raise QueueConflict("only LEASED or RUNNING work can renew")
            lease = self._decode_model(row, "lease_json", TaskLease)
            renewed = lease.model_copy(update={"expires_at": expires_at})
            cursor.execute(
                "UPDATE work_queue_claims SET lease_json=%s,expires_at=%s,"
                "last_heartbeat_at=%s WHERE lease_id=%s",
                (
                    self._encode(renewed),
                    self._time_key(expires_at),
                    self._time_key(now),
                    lease_id,
                ),
            )
            return renewed

    def complete(
        self,
        work_item_id: WorkItemId | str,
        *,
        lease_id: str,
        owner_token: str,
        artifacts: Sequence[QueueArtifactReceipt],
        next_work_item: QueuedWorkItem | None,
        now: datetime,
    ) -> QueueCompletion:
        """Close current work and publish its next role Run in one transaction."""
        self._require_aware(now, "completion clock")
        receipts = tuple(artifacts)
        if len({item.artifact_id for item in receipts}) != len(receipts):
            raise ValueError("completion Artifact IDs must be unique")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor() as cursor,
        ):
            self._lock_authority(cursor)
            current = self._get_locked(cursor, str(work_item_id), lock=True)
            if current.status is WorkItemStatus.CLOSED:
                return self._replay_completion(
                    cursor,
                    current,
                    lease_id=lease_id,
                    owner_token=owner_token,
                    artifacts=receipts,
                    next_work_item=next_work_item,
                )
            self._require_active_claim(cursor, current.id, lease_id, owner_token, now=now)
            if current.status not in _ACTIVE_STATUSES:
                raise QueueConflict("only active work can complete")
            if next_work_item is not None:
                if (
                    next_work_item.task_id != current.task_id
                    or next_work_item.parent_work_item_id != current.id
                    or next_work_item.created_at < now
                ):
                    raise QueueConflict("next WorkItem does not follow the current queue fact")
                self._validate_enqueue_status(next_work_item)
            closed = current.model_copy(update={"status": WorkItemStatus.CLOSED, "updated_at": now})
            self._update_item(cursor, closed)
            self._release_claim(cursor, lease_id, state="RELEASED", ended_at=now)
            published = (
                self._enqueue_locked(cursor, next_work_item) if next_work_item is not None else None
            )
            self._append_event(
                cursor,
                closed,
                from_status=current.status,
                event_type="COMPLETED",
                lease_id=lease_id,
                occurred_at=now,
                detail={
                    "artifacts": [item.to_wire() for item in receipts],
                    "next_work_item": (published.to_wire() if published is not None else None),
                },
            )
            return QueueCompletion(
                work_item=closed,
                artifacts=receipts,
                next_work_item=published,
                completed_at=now,
            )

    def _replay_completion(
        self,
        cursor: object,
        current: QueuedWorkItem,
        *,
        lease_id: str,
        owner_token: str,
        artifacts: tuple[QueueArtifactReceipt, ...],
        next_work_item: QueuedWorkItem | None,
    ) -> QueueCompletion:
        typed = cast("pymysql.cursors.DictCursor", cursor)
        typed.execute(
            "SELECT owner_token_sha256,state FROM work_queue_claims "
            "WHERE lease_id=%s AND work_item_id=%s FOR UPDATE",
            (lease_id, current.id),
        )
        claim_row = cast(Mapping[str, object] | None, typed.fetchone())
        if (
            claim_row is None
            or self._text(claim_row, "owner_token_sha256") != self._token_digest(owner_token)
            or self._text(claim_row, "state") != "RELEASED"
        ):
            raise QueueConflict("completed Lease owner or state changed")
        typed.execute(
            "SELECT payload_json,occurred_at FROM work_queue_events "
            "WHERE work_item_id=%s AND lease_id=%s AND event_type='COMPLETED' "
            "ORDER BY sequence DESC LIMIT 1 FOR UPDATE",
            (current.id, lease_id),
        )
        event_row = cast(Mapping[str, object] | None, typed.fetchone())
        if event_row is None:
            raise QueueCorruption("closed WorkItem has no completion event")
        try:
            payload: object = json.loads(self._text(event_row, "payload_json"))
            if not isinstance(payload, dict) or not isinstance(payload.get("detail"), dict):
                raise TypeError("completion detail is not an object")
            detail = cast(dict[str, object], payload["detail"])
            stored_artifacts = tuple(
                QueueArtifactReceipt.model_validate(value)
                for value in cast(list[object], detail["artifacts"])
            )
            next_payload = detail.get("next_work_item")
            stored_next = (
                QueuedWorkItem.model_validate(next_payload) if next_payload is not None else None
            )
        except (KeyError, TypeError, ValidationError, json.JSONDecodeError) as error:
            raise QueueCorruption("completion event payload is invalid") from error
        if stored_artifacts != artifacts or stored_next != next_work_item:
            raise QueueConflict("completion replay has different content")
        return QueueCompletion(
            work_item=current,
            artifacts=stored_artifacts,
            next_work_item=stored_next,
            completed_at=self._parse_time(self._text(event_row, "occurred_at")),
        )

    def wait(
        self,
        work_item_id: WorkItemId | str,
        *,
        lease_id: str,
        owner_token: str,
        status: WorkItemStatus,
        reason: str,
        now: datetime,
    ) -> QueuedWorkItem:
        """Release capacity while preserving a recoverable human/dependency checkpoint."""
        if status not in _WAIT_STATUSES:
            raise ValueError("wait status must be WAITING_HUMAN or WAITING_DEPENDENCY")
        if not reason:
            raise ValueError("wait reason must be non-empty")
        return self._release_to_status(
            str(work_item_id),
            lease_id=lease_id,
            owner_token=owner_token,
            status=status,
            reason=reason,
            now=now,
            available_at=None,
            event_type="WAITING",
        )

    def retry(
        self,
        work_item_id: WorkItemId | str,
        *,
        lease_id: str,
        owner_token: str,
        reason: str,
        now: datetime,
        available_at: datetime,
    ) -> QueuedWorkItem:
        """Release capacity and schedule the same Run after a bounded delay."""
        self._require_aware(available_at, "retry availability")
        if available_at <= now:
            raise ValueError("retry available_at must be later than now")
        if not reason:
            raise ValueError("retry reason must be non-empty")
        return self._release_to_status(
            str(work_item_id),
            lease_id=lease_id,
            owner_token=owner_token,
            status=WorkItemStatus.RETRY_SCHEDULED,
            reason=reason,
            now=now,
            available_at=available_at,
            event_type="RETRY_SCHEDULED",
        )

    def make_ready(self, work_item_id: WorkItemId | str, *, now: datetime) -> QueuedWorkItem:
        """Resume explicitly waiting work after a verified external signal."""
        self._require_aware(now, "resume clock")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor() as cursor,
        ):
            self._lock_authority(cursor)
            current = self._get_locked(cursor, str(work_item_id), lock=True)
            if current.status not in {*_WAIT_STATUSES, WorkItemStatus.RETRY_SCHEDULED}:
                raise QueueConflict("only waiting or retry work can become READY")
            if self._active_claim_exists(cursor, current.id):
                raise QueueCorruption("waiting WorkItem retained an active Lease")
            ready = current.model_copy(
                update={
                    "status": WorkItemStatus.READY,
                    "dispatch_sequence": current.dispatch_sequence + 1,
                    "wait_reason": None,
                    "available_at": None,
                    "updated_at": now,
                }
            )
            self._update_item(cursor, ready)
            self._append_event(
                cursor,
                ready,
                from_status=current.status,
                event_type="READY",
                lease_id=None,
                occurred_at=now,
            )
            return ready

    def reclaim_expired(self, *, now: datetime, retry_at: datetime) -> tuple[QueuedWorkItem, ...]:
        """Fence expired owners and return their unfinished work to delayed scheduling."""
        self._require_aware(now, "reclaim clock")
        self._require_aware(retry_at, "reclaim retry clock")
        if retry_at <= now:
            raise ValueError("reclaim retry_at must be later than now")
        reclaimed: list[QueuedWorkItem] = []
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor() as cursor,
        ):
            self._lock_authority(cursor)
            cursor.execute(
                """
                SELECT lease_id,work_item_id FROM work_queue_claims
                WHERE state='ACTIVE' AND expires_at <= %s
                ORDER BY expires_at ASC, lease_id ASC FOR UPDATE
                """,
                (self._time_key(now),),
            )
            rows = cast(tuple[Mapping[str, object], ...], cursor.fetchall())
            for row in rows:
                lease_id = self._text(row, "lease_id")
                item_id = self._text(row, "work_item_id")
                current = self._get_locked(cursor, item_id, lock=True)
                if current.status not in _ACTIVE_STATUSES:
                    raise QueueCorruption("active Lease belongs to a non-active WorkItem")
                retry = current.model_copy(
                    update={
                        "status": WorkItemStatus.RETRY_SCHEDULED,
                        "dispatch_sequence": current.dispatch_sequence + 1,
                        "wait_reason": f"lease_expired:{lease_id}",
                        "available_at": retry_at,
                        "updated_at": now,
                    }
                )
                self._update_item(cursor, retry)
                self._release_claim(cursor, lease_id, state="EXPIRED", ended_at=now)
                self._append_event(
                    cursor,
                    retry,
                    from_status=current.status,
                    event_type="LEASE_EXPIRED",
                    lease_id=lease_id,
                    occurred_at=now,
                )
                reclaimed.append(retry)
        return tuple(reclaimed)

    def _release_to_status(
        self,
        work_item_id: str,
        *,
        lease_id: str,
        owner_token: str,
        status: WorkItemStatus,
        reason: str,
        now: datetime,
        available_at: datetime | None,
        event_type: str,
    ) -> QueuedWorkItem:
        self._require_aware(now, "release clock")
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor() as cursor,
        ):
            self._lock_authority(cursor)
            current = self._get_locked(cursor, work_item_id, lock=True)
            self._require_active_claim(cursor, current.id, lease_id, owner_token, now=now)
            if current.status not in _ACTIVE_STATUSES:
                raise QueueConflict("only active work can release its Lease")
            released = current.model_copy(
                update={
                    "status": status,
                    "dispatch_sequence": (
                        current.dispatch_sequence + 1
                        if status is WorkItemStatus.RETRY_SCHEDULED
                        else current.dispatch_sequence
                    ),
                    "wait_reason": reason,
                    "available_at": available_at,
                    "updated_at": now,
                }
            )
            self._update_item(cursor, released)
            self._release_claim(cursor, lease_id, state="RELEASED", ended_at=now)
            self._append_event(
                cursor,
                released,
                from_status=current.status,
                event_type=event_type,
                lease_id=lease_id,
                occurred_at=now,
            )
            return released

    def _initialize_schema(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS work_queue_authority_lock (
                id TINYINT UNSIGNED PRIMARY KEY,
                purpose VARCHAR(64) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
            """,
            """
            INSERT INTO work_queue_authority_lock (id,purpose)
            VALUES (1,'persistent-work-queue')
            ON DUPLICATE KEY UPDATE purpose=VALUES(purpose)
            """,
            """
            CREATE TABLE IF NOT EXISTS work_queue_items (
                id VARCHAR(128) PRIMARY KEY,
                task_id VARCHAR(128) NOT NULL,
                repository_id VARCHAR(128) NOT NULL,
                role VARCHAR(32) NOT NULL,
                attempt SMALLINT UNSIGNED NOT NULL,
                checkpoint_sequence INT UNSIGNED NOT NULL,
                status VARCHAR(32) NOT NULL,
                priority SMALLINT UNSIGNED NOT NULL,
                risk_rank TINYINT UNSIGNED NOT NULL,
                available_at VARCHAR(40) NULL,
                payload_json JSON NOT NULL,
                version INT UNSIGNED NOT NULL DEFAULT 0,
                created_at VARCHAR(40) NOT NULL,
                updated_at VARCHAR(40) NOT NULL,
                UNIQUE KEY uq_work_queue_run
                    (task_id,role,attempt,checkpoint_sequence),
                KEY ix_work_queue_schedulable
                    (status,available_at,priority,risk_rank,created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
            """,
            """
            CREATE TABLE IF NOT EXISTS work_queue_claims (
                lease_id VARCHAR(128) PRIMARY KEY,
                work_item_id VARCHAR(128) NOT NULL,
                task_id VARCHAR(128) NOT NULL,
                agent_id VARCHAR(128) NOT NULL,
                worker_id VARCHAR(128) NOT NULL,
                owner_token_sha256 CHAR(64) NOT NULL,
                assignment_json JSON NOT NULL,
                lease_json JSON NOT NULL,
                model_selection_json JSON NOT NULL,
                capacity_units TINYINT UNSIGNED NOT NULL,
                state VARCHAR(16) NOT NULL,
                acquired_at VARCHAR(40) NOT NULL,
                expires_at VARCHAR(40) NOT NULL,
                last_heartbeat_at VARCHAR(40) NOT NULL,
                ended_at VARCHAR(40) NULL,
                KEY ix_work_queue_active_agent (agent_id,state,expires_at),
                KEY ix_work_queue_item_claims (work_item_id,state),
                KEY ix_work_queue_task_claims (task_id),
                CONSTRAINT fk_work_queue_claim_item FOREIGN KEY (work_item_id)
                    REFERENCES work_queue_items(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
            """,
            """
            CREATE TABLE IF NOT EXISTS work_queue_events (
                sequence BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                work_item_id VARCHAR(128) NOT NULL,
                event_type VARCHAR(32) NOT NULL,
                from_status VARCHAR(32) NULL,
                to_status VARCHAR(32) NOT NULL,
                lease_id VARCHAR(128) NULL,
                payload_json JSON NOT NULL,
                occurred_at VARCHAR(40) NOT NULL,
                KEY ix_work_queue_events_item (work_item_id,sequence),
                CONSTRAINT fk_work_queue_event_item FOREIGN KEY (work_item_id)
                    REFERENCES work_queue_items(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
            """,
        )
        with closing(open_mysql_connection(self._dsn)) as connection:
            try:
                with self._transaction(connection), connection.cursor() as cursor:
                    for statement in statements:
                        cursor.execute(statement)
            except pymysql.MySQLError as error:
                raise QueueError("cannot initialize PersistentWorkQueue") from error

    def _enqueue_locked(self, cursor: object, item: QueuedWorkItem) -> QueuedWorkItem:
        typed = cast("pymysql.cursors.DictCursor", cursor)
        typed.execute(
            "SELECT id,payload_json FROM work_queue_items WHERE id=%s FOR UPDATE", (item.id,)
        )
        row = cast(Mapping[str, object] | None, typed.fetchone())
        if row is not None:
            existing = self._decode_item(row)
            if existing != item:
                raise QueueConflict(f"WorkItem {item.id} already has different content")
            return existing
        try:
            typed.execute(
                """
                INSERT INTO work_queue_items
                    (id,task_id,repository_id,role,attempt,checkpoint_sequence,status,priority,
                     risk_rank,available_at,payload_json,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    item.id,
                    item.task_id,
                    item.repository_id,
                    item.role.value,
                    item.attempt,
                    item.checkpoint_sequence,
                    item.status.value,
                    item.priority,
                    _RISK_RANK[item.risk.value],
                    self._time_key(item.available_at) if item.available_at is not None else None,
                    self._encode(item),
                    self._time_key(item.created_at),
                    self._time_key(item.updated_at),
                ),
            )
        except pymysql.IntegrityError as error:
            raise QueueConflict("WorkItem Run identity is already registered") from error
        self._append_event(
            typed,
            item,
            from_status=None,
            event_type="ENQUEUED",
            lease_id=None,
            occurred_at=item.updated_at,
        )
        return item

    def _get_locked(self, cursor: object, work_item_id: str, *, lock: bool) -> QueuedWorkItem:
        typed = cast("pymysql.cursors.DictCursor", cursor)
        suffix = " FOR UPDATE" if lock else ""
        typed.execute(
            f"SELECT id,payload_json FROM work_queue_items WHERE id=%s{suffix}",
            (work_item_id,),
        )
        row = cast(Mapping[str, object] | None, typed.fetchone())
        if row is None:
            raise QueueNotFound(work_item_id)
        return self._decode_item(row)

    def _validate_capacity_locked(
        self,
        cursor: object,
        assignment: RoleAssignment,
        *,
        agent_capacity: int,
        now: datetime,
    ) -> None:
        typed = cast("pymysql.cursors.DictCursor", cursor)
        typed.execute(
            """
            SELECT COALESCE(SUM(capacity_units),0) AS used_capacity
            FROM work_queue_claims
            WHERE agent_id=%s AND state='ACTIVE' AND expires_at > %s
            """,
            (assignment.agent_id, self._time_key(now)),
        )
        row = cast(Mapping[str, object], typed.fetchone())
        used = row["used_capacity"]
        if isinstance(used, Decimal) and used == used.to_integral_value():
            used = int(used)
        if not isinstance(used, int) or isinstance(used, bool):
            raise QueueCorruption("active Agent capacity is not an integer")
        if used + assignment.capacity_units > agent_capacity:
            raise QueueConflict(f"Agent {assignment.agent_id} has no queue capacity")

    def _validate_independence_locked(self, cursor: object, candidate: RoleAssignment) -> None:
        typed = cast("pymysql.cursors.DictCursor", cursor)
        typed.execute(
            "SELECT assignment_json FROM work_queue_claims WHERE task_id=%s ORDER BY lease_id",
            (candidate.task_id,),
        )
        rows = cast(tuple[Mapping[str, object], ...], typed.fetchall())
        existing = tuple(self._decode_model(row, "assignment_json", RoleAssignment) for row in rows)
        try:
            validate_assignment_independence(candidate, existing)
        except ValueError as error:
            raise QueueConflict(str(error)) from error

    def _require_active_claim(
        self,
        cursor: object,
        work_item_id: str,
        lease_id: str,
        owner_token: str,
        *,
        now: datetime,
    ) -> Mapping[str, object]:
        typed = cast("pymysql.cursors.DictCursor", cursor)
        typed.execute("SELECT * FROM work_queue_claims WHERE lease_id=%s FOR UPDATE", (lease_id,))
        row = cast(Mapping[str, object] | None, typed.fetchone())
        if row is None:
            raise QueueConflict("Lease does not exist")
        if (
            self._text(row, "work_item_id") != work_item_id
            or self._text(row, "state") != "ACTIVE"
            or self._text(row, "owner_token_sha256") != self._token_digest(owner_token)
        ):
            raise QueueConflict("Lease owner or state changed")
        if self._parse_time(self._text(row, "expires_at")) <= now:
            raise QueueConflict("Lease expired before lifecycle operation")
        return row

    def _active_claim_exists(self, cursor: object, work_item_id: str) -> bool:
        typed = cast("pymysql.cursors.DictCursor", cursor)
        typed.execute(
            "SELECT lease_id FROM work_queue_claims "
            "WHERE work_item_id=%s AND state='ACTIVE' LIMIT 1 FOR UPDATE",
            (work_item_id,),
        )
        return typed.fetchone() is not None

    @staticmethod
    def _release_claim(cursor: object, lease_id: str, *, state: str, ended_at: datetime) -> None:
        typed = cast("pymysql.cursors.DictCursor", cursor)
        typed.execute(
            "UPDATE work_queue_claims SET state=%s,ended_at=%s WHERE lease_id=%s",
            (state, MySqlPersistentWorkQueue._time_key(ended_at), lease_id),
        )
        if typed.rowcount != 1:
            raise QueueCorruption("Lease release did not update exactly one row")

    def _update_item(self, cursor: object, item: QueuedWorkItem) -> None:
        typed = cast("pymysql.cursors.DictCursor", cursor)
        typed.execute(
            "UPDATE work_queue_items SET payload_json=%s,status=%s,available_at=%s,"
            "updated_at=%s,version=version+1 WHERE id=%s",
            (
                self._encode(item),
                item.status.value,
                self._time_key(item.available_at) if item.available_at is not None else None,
                self._time_key(item.updated_at),
                item.id,
            ),
        )
        if typed.rowcount != 1:
            raise QueueCorruption("WorkItem update did not change exactly one row")

    def _append_event(
        self,
        cursor: object,
        item: QueuedWorkItem,
        *,
        from_status: WorkItemStatus | None,
        event_type: str,
        lease_id: str | None,
        occurred_at: datetime,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        typed = cast("pymysql.cursors.DictCursor", cursor)
        payload = {
            "work_item": item.to_wire(),
            "detail": dict(detail or {}),
        }
        typed.execute(
            """
            INSERT INTO work_queue_events
                (work_item_id,event_type,from_status,to_status,lease_id,payload_json,occurred_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                item.id,
                event_type,
                from_status.value if from_status is not None else None,
                item.status.value,
                lease_id,
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                self._time_key(occurred_at),
            ),
        )

    @staticmethod
    def _validate_enqueue_status(item: QueuedWorkItem) -> None:
        if item.status not in {
            WorkItemStatus.READY,
            WorkItemStatus.RETRY_SCHEDULED,
            WorkItemStatus.WAITING_HUMAN,
            WorkItemStatus.WAITING_DEPENDENCY,
        }:
            raise ValueError("new WorkItem must be ready, retry-scheduled, or waiting")

    @staticmethod
    def _validate_allocation(
        item: QueuedWorkItem,
        assignment: RoleAssignment,
        lease: TaskLease,
        selection: ModelSelection,
        *,
        now: datetime,
    ) -> None:
        if (
            assignment.task_id != item.task_id
            or assignment.repository_id != item.repository_id
            or assignment.role is not item.role
            or assignment.attempt != item.attempt
            or lease.assignment_id != assignment.id
            or lease.id != assignment.lease_id
            or lease.task_id != item.task_id
            or lease.agent_id != assignment.agent_id
            or lease.acquired_at != now
            or lease.expires_at <= now
            or selection.selected_at > now
        ):
            raise QueueConflict("allocation does not match current WorkItem")

    @staticmethod
    def _is_schedulable(item: QueuedWorkItem, *, now: datetime) -> bool:
        return item.status is WorkItemStatus.READY or (
            item.status is WorkItemStatus.RETRY_SCHEDULED
            and item.available_at is not None
            and item.available_at <= now
        )

    @staticmethod
    def _lock_authority(cursor: object) -> None:
        typed = cast("pymysql.cursors.DictCursor", cursor)
        typed.execute("SELECT id FROM work_queue_authority_lock WHERE id=1 FOR UPDATE")
        if typed.fetchone() is None:
            raise QueueCorruption("WorkQueue authority lock is missing")

    @staticmethod
    def _decode_item(row: Mapping[str, object]) -> QueuedWorkItem:
        try:
            item = QueuedWorkItem.model_validate_json(
                MySqlPersistentWorkQueue._text(row, "payload_json")
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise QueueCorruption("invalid queued WorkItem payload") from error
        if MySqlPersistentWorkQueue._text(row, "id") != item.id:
            raise QueueCorruption("WorkItem row identity does not match payload")
        return item

    @staticmethod
    def _decode_model[ModelT: DomainModel](
        row: Mapping[str, object], key: str, model: type[ModelT]
    ) -> ModelT:
        try:
            return model.model_validate_json(MySqlPersistentWorkQueue._text(row, key))
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise QueueCorruption(f"invalid {key} payload") from error

    @staticmethod
    def _encode(model: DomainModel) -> str:
        return json.dumps(
            model.to_wire(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @staticmethod
    def _token_digest(owner_token: str) -> str:
        if (
            not isinstance(owner_token, str)
            or len(owner_token) < 16
            or any(ord(character) < 32 for character in owner_token)
        ):
            raise ValueError("Lease owner token must contain at least 16 visible characters")
        return hashlib.sha256(owner_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _require_aware(value: datetime, label: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{label} must be timezone-aware")

    @staticmethod
    def _time_key(value: datetime) -> str:
        MySqlPersistentWorkQueue._require_aware(value, "stored time")
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _parse_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise QueueCorruption("stored queue time is invalid") from error
        MySqlPersistentWorkQueue._require_aware(parsed, "stored time")
        return parsed

    @staticmethod
    def _text(row: Mapping[str, object], key: str) -> str:
        value = row[key]
        if not isinstance(value, str):
            raise QueueCorruption(f"MySQL column {key} is not text")
        return value

    @staticmethod
    @contextmanager
    def _transaction(connection: Connection) -> Iterator[None]:
        try:
            connection.begin()
            yield
        except (QueueError, ValidationError, ValueError):
            connection.rollback()
            raise
        except pymysql.MySQLError as error:
            connection.rollback()
            raise QueueError("PersistentWorkQueue transaction failed") from error
        except BaseException:
            connection.rollback()
            raise
        else:
            try:
                connection.commit()
            except pymysql.MySQLError as error:
                connection.rollback()
                raise QueueError("PersistentWorkQueue commit failed") from error


__all__ = ["MySqlPersistentWorkQueue"]
