"""One capacity view while native allocations transfer execution to T046."""

from contextlib import closing
from datetime import datetime

from pymysql.cursors import DictCursor

from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.manager.dispatch import VerificationReservation
from ai_software_engineer.manager.mysql_dispatch_authority import _decode_allocation
from ai_software_engineer.store.mysql_repository import _decode_task, open_mysql_connection
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    WorkforceFacts,
    read_queue_workforce,
)
from ai_software_engineer.work_queue.ports import QueueCorruption


def lock_dispatch(cursor: DictCursor) -> None:
    cursor.execute("SELECT id FROM dispatch_authority_lock WHERE id=1 FOR UPDATE")
    if cursor.fetchone() is None:
        raise QueueCorruption("shared dispatch authority lock missing")


def legacy_capacity(cursor: DictCursor, now: datetime) -> WorkforceFacts:
    queued = read_queue_workforce(cursor, now)
    cursor.execute(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN "
        "('dispatch_commits','verification_reservations','tasks')"
    )
    present = {row["TABLE_NAME"] for row in cursor.fetchall()}
    assignments, leases = [], []
    terminal = set()
    if "tasks" in present:
        cursor.execute("SELECT id,payload_json FROM tasks")
        for row in cursor.fetchall():
            task = _decode_task(row["id"], row["payload_json"])
            if task.status in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}:
                terminal.add(task.id)
    if "dispatch_commits" in present:
        cursor.execute(
            "SELECT id,repository_id,task_id,payload_json,dispatch_sha256 FROM dispatch_commits"
        )
        for row in cursor.fetchall():
            allocation = _decode_allocation(row)
            for phase in allocation.phases:
                assignments.append(phase.assignment)
                if (
                    allocation.task_id not in terminal | queued.adopted_task_ids
                    and phase.lease.expires_at > now
                ):
                    leases.append(phase.lease)
    if "verification_reservations" in present:
        cursor.execute(
            "SELECT payload_json,completion_sha256,abandonment_sha256 "
            "FROM verification_reservations"
        )
        for row in cursor.fetchall():
            reservation = VerificationReservation.model_validate_json(row["payload_json"])
            reservation.validate_integrity()
            assignments.extend(phase.assignment for phase in reservation.phases)
            if row["completion_sha256"] is None and row["abandonment_sha256"] is None:
                leases.extend(
                    phase.lease for phase in reservation.phases if phase.lease.expires_at > now
                )
    return WorkforceFacts(tuple(assignments), tuple(leases), queued.adopted_task_ids)


def production_role_queue(dsn: str) -> MySqlRoleQueue:
    # Queue creation can precede the first native dispatch. Initialize only the
    # common authority lock here; no legacy records or verdicts are rewritten.
    with closing(open_mysql_connection(dsn)) as connection, connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS dispatch_authority_lock ("
            "id TINYINT UNSIGNED PRIMARY KEY,purpose VARCHAR(64) NOT NULL) "
            "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"
        )
        cursor.execute(
            "INSERT IGNORE INTO dispatch_authority_lock (id,purpose) "
            "VALUES (1,'global-allocation-reservation')"
        )
        connection.commit()
    return MySqlRoleQueue(dsn, capacity_reader=legacy_capacity, authority_lock=lock_dispatch)
