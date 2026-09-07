"""MySQL allocation authority with one global reservation lock and Product fence."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from datetime import datetime
from typing import cast

import pymysql
from pydantic import ValidationError
from pymysql.connections import Connection

from ai_software_engineer.domain.enums import (
    ProjectRequestStatus,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.planning.models import PlannerRunOutcome
from ai_software_engineer.project_manager.dispatch import (
    DeliveryAllocation,
    DispatchAuthorityConflict,
    DispatchCommitConflict,
    DispatchCommitCorruption,
    DispatchCommitId,
    DispatchCommitNotFound,
    DispatchCommitPathError,
    DispatchCommitRecord,
    DispatchPlannerRecordReader,
    DispatchPreviewStale,
    DispatchSha256,
    DispatchWorkforceSnapshot,
    RecoveryDispatchRecord,
)
from ai_software_engineer.project_manager.dispatch_authority import (
    DispatchRevisionAuthority,
)
from ai_software_engineer.store.mysql_repository import (
    MySqlTaskRepository,
    _decode_task,
    open_mysql_connection,
)


class MySqlDispatchAuthority:
    """Publish dispatch bundles under a MySQL/InnoDB global reservation lock."""

    def __init__(
        self,
        dsn: str,
        *,
        request_revisions: DispatchRevisionAuthority,
        planner_records: DispatchPlannerRecordReader,
    ) -> None:
        self._dsn = dsn
        self._request_revisions = request_revisions
        self._planner_records = planner_records
        # Capacity is derived from durable Task outcomes, never from an Agent's claim.
        MySqlTaskRepository(dsn).close()
        with closing(open_mysql_connection(self._dsn)) as connection:
            try:
                with self._transaction(connection), connection.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS dispatch_authority_lock (
                            id TINYINT UNSIGNED PRIMARY KEY,
                            purpose VARCHAR(64) NOT NULL
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
                        """
                    )
                    cursor.execute(
                        """
                        INSERT INTO dispatch_authority_lock (id, purpose)
                        VALUES (1, 'global-allocation-reservation')
                        ON DUPLICATE KEY UPDATE purpose = VALUES(purpose)
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS dispatch_workforce_snapshots (
                            project_id VARCHAR(128) NOT NULL,
                            task_id VARCHAR(128) NOT NULL,
                            payload_json JSON NOT NULL,
                            snapshot_sha256 CHAR(64) NOT NULL,
                            PRIMARY KEY (project_id, task_id)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS dispatch_commits (
                            id VARCHAR(96) PRIMARY KEY,
                            project_id VARCHAR(128) NOT NULL,
                            task_id VARCHAR(128) NOT NULL,
                            payload_json JSON NOT NULL,
                            dispatch_sha256 CHAR(64) NOT NULL
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
                        """
                    )
            except pymysql.MySQLError as error:
                raise DispatchCommitPathError(
                    "cannot initialize MySQL dispatch authority"
                ) from error

    def seed_snapshot(self, snapshot: DispatchWorkforceSnapshot) -> DispatchWorkforceSnapshot:
        """Register immutable current workforce inputs before the first preview."""
        snapshot.validate_integrity()
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor() as cursor,
        ):
            self._lock_authority(cursor)
            cursor.execute(
                """
                SELECT project_id, task_id, payload_json, snapshot_sha256
                FROM dispatch_workforce_snapshots
                WHERE project_id = %s AND task_id = %s FOR UPDATE
                """,
                (snapshot.project_id, snapshot.task_id),
            )
            row = cast(Mapping[str, object] | None, cursor.fetchone())
            if row is not None:
                existing = _decode_snapshot(row)
                if existing != snapshot:
                    raise DispatchAuthorityConflict(
                        "workforce snapshot identity already has different facts"
                    )
                return existing
            cursor.execute(
                """
                INSERT INTO dispatch_workforce_snapshots
                    (project_id, task_id, payload_json, snapshot_sha256)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    snapshot.project_id,
                    snapshot.task_id,
                    _encode(snapshot),
                    snapshot.snapshot_sha256,
                ),
            )
            return snapshot

    def current_snapshot(
        self,
        *,
        project_id: ProjectId,
        task_id: TaskId,
    ) -> DispatchWorkforceSnapshot:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
        ):
            return self._current_snapshot(connection, project_id, task_id)

    def commit_if_current(
        self,
        record: DispatchCommitRecord,
        *,
        expected_snapshot_sha256: DispatchSha256,
    ) -> DispatchCommitRecord:
        """Fence Product and all workforce reservations before one atomic publish."""
        record.validate_integrity()
        with (
            self._request_revisions.request_revision_fence(),
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor() as cursor,
        ):
            self._lock_authority(cursor)
            cursor.execute(
                """
                SELECT id, project_id, task_id, payload_json, dispatch_sha256
                FROM dispatch_commits WHERE id = %s FOR UPDATE
                """,
                (record.id,),
            )
            existing_row = cast(Mapping[str, object] | None, cursor.fetchone())
            if existing_row is not None:
                existing = _decode_commit(existing_row)
                if existing != record:
                    raise DispatchCommitConflict(
                        f"dispatch commit {record.id} already has different content"
                    )
                return existing

            snapshot = self._current_snapshot(connection, record.project_id, record.task_id)
            if snapshot.snapshot_sha256 != expected_snapshot_sha256:
                raise DispatchAuthorityConflict(
                    "authoritative workforce snapshot changed before commit"
                )
            self._validate_handoff(record)
            self._validate_reservations(record, snapshot)
            try:
                cursor.execute(
                    """
                    INSERT INTO dispatch_commits
                        (id, project_id, task_id, payload_json, dispatch_sha256)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        record.id,
                        record.project_id,
                        record.task_id,
                        _encode(record),
                        record.dispatch_sha256,
                    ),
                )
            except pymysql.IntegrityError as error:
                raise DispatchCommitConflict(
                    f"dispatch commit {record.id} already exists"
                ) from error
            self._current_snapshot(connection, record.project_id, record.task_id)
            return record

    def get_commit(self, commit_id: DispatchCommitId) -> DispatchCommitRecord:
        record = self.get_allocation(commit_id)
        if not isinstance(record, DispatchCommitRecord):
            raise DispatchCommitCorruption("expected native Planner dispatch")
        return record

    def get_allocation(self, commit_id: DispatchCommitId) -> DeliveryAllocation:
        with closing(open_mysql_connection(self._dsn)) as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, project_id, task_id, payload_json, dispatch_sha256
                        FROM dispatch_commits WHERE id = %s
                        """,
                        (commit_id,),
                    )
                    row = cast(Mapping[str, object] | None, cursor.fetchone())
            except pymysql.MySQLError as error:
                raise DispatchCommitPathError("cannot read MySQL dispatch commit") from error
        if row is None:
            raise DispatchCommitNotFound(f"dispatch commit {commit_id} was not found")
        return _decode_allocation(row)

    def commit_recovery(
        self,
        *,
        project_id: ProjectId,
        task_id: TaskId,
        plan_sha256: DispatchSha256,
        validate_current: Callable[[RecoveryDispatchRecord | None], None],
        build: Callable[[DispatchWorkforceSnapshot], RecoveryDispatchRecord],
    ) -> RecoveryDispatchRecord:
        """Recheck recovery facts and recompute allocation inside the global fence."""
        commit_id = f"dispatch_commit_{plan_sha256}"
        with (
            self._request_revisions.request_revision_fence(),
            closing(open_mysql_connection(self._dsn)) as connection,
            self._transaction(connection),
            connection.cursor() as cursor,
        ):
            self._lock_authority(cursor)
            cursor.execute("SELECT * FROM dispatch_commits WHERE id = %s FOR UPDATE", (commit_id,))
            row = cast(Mapping[str, object] | None, cursor.fetchone())
            if row is not None:
                existing = _decode_allocation(row)
                if not isinstance(existing, RecoveryDispatchRecord):
                    raise DispatchCommitConflict("recovery identity belongs to native dispatch")
                validate_current(existing)
                return existing
            validate_current(None)
            snapshot = self._current_snapshot(connection, project_id, task_id)
            record = build(snapshot)
            record.validate_integrity()
            if (
                record.id != commit_id
                or record.project_id != project_id
                or record.task_id != task_id
                or record.workforce_snapshot_sha256 != snapshot.snapshot_sha256
            ):
                raise DispatchAuthorityConflict("recovery allocation differs from fenced inputs")
            self._validate_reservations(record, snapshot)
            validate_current(record)
            cursor.execute(
                "INSERT INTO dispatch_commits "
                "(id, project_id, task_id, payload_json, dispatch_sha256) VALUES (%s,%s,%s,%s,%s)",
                (record.id, project_id, task_id, _encode(record), record.dispatch_sha256),
            )
            self._current_snapshot(connection, project_id, task_id)
            return record

    def _current_snapshot(
        self,
        connection: Connection,
        project_id: ProjectId,
        task_id: TaskId,
    ) -> DispatchWorkforceSnapshot:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT project_id, task_id, payload_json, snapshot_sha256
                FROM dispatch_workforce_snapshots
                WHERE project_id = %s AND task_id = %s
                """,
                (project_id, task_id),
            )
            row = cast(Mapping[str, object] | None, cursor.fetchone())
            if row is None:
                raise DispatchAuthorityConflict(
                    f"workforce snapshot is not registered for {project_id}/{task_id}"
                )
            base = _decode_snapshot(row)
            if base.project_id != project_id or base.task_id != task_id:
                raise DispatchCommitCorruption(
                    "workforce snapshot row identity does not match its payload"
                )
            cursor.execute(
                """
                SELECT id, project_id, task_id, payload_json, dispatch_sha256
                FROM dispatch_commits ORDER BY id
                """
            )
            commit_rows = cast(tuple[Mapping[str, object], ...], cursor.fetchall())
            cursor.execute(
                """
                SELECT DISTINCT t.id, t.payload_json
                FROM tasks AS t JOIN dispatch_commits AS d ON d.task_id = t.id
                """
            )
            task_rows = cast(tuple[Mapping[str, object], ...], cursor.fetchall())
            terminal_tasks = {
                task.id
                for row in task_rows
                if (task := _decode_task(str(row["id"]), str(row["payload_json"]))).status
                in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}
            }

        assignments = {assignment.id: assignment for assignment in base.assignments}
        leases = {lease.id: lease for lease in base.active_leases}
        task_commit_time: datetime | None = None
        for commit_row in commit_rows:
            commit = _decode_allocation(commit_row)
            if commit.task_id == task_id:
                task_commit_time = commit.committed_at
            for phase in commit.phases:
                previous_assignment = assignments.setdefault(phase.assignment.id, phase.assignment)
                previous_lease = leases.setdefault(phase.lease.id, phase.lease)
                if previous_assignment != phase.assignment or previous_lease != phase.lease:
                    raise DispatchCommitCorruption(
                        "dispatch allocation identity has conflicting durable facts"
                    )
        work_item = base.work_item
        if task_commit_time is not None and work_item.status is WorkItemStatus.READY:
            work_item = work_item.model_copy(
                update={"status": WorkItemStatus.LEASED, "updated_at": task_commit_time}
            )
        return DispatchWorkforceSnapshot.create(
            project_id=base.project_id,
            task_id=base.task_id,
            work_item=work_item,
            agents=base.agents,
            active_leases=(
                lease for lease in leases.values() if lease.task_id not in terminal_tasks
            ),
            assignments=assignments.values(),
            model_policies=base.model_policies,
        )

    def _validate_handoff(self, record: DispatchCommitRecord) -> None:
        try:
            current = self._request_revisions.current_request_revision(record.project_request_id)
            run = self._planner_records.get_run(record.planner_run_id)
            checkpoint = self._planner_records.get_checkpoint(record.planner_run_id)
            plan = self._planner_records.get_execution_plan(record.execution_plan_id)
            current.validate_integrity()
            run.validate_integrity()
            checkpoint.validate_integrity()
            plan.validate_integrity()
        except (RuntimeError, ValueError) as error:
            raise DispatchPreviewStale(
                "complete Planner handoff cannot be verified inside commit fence"
            ) from error
        if (
            current.request.status is not ProjectRequestStatus.READY_FOR_DELIVERY
            or current.request.id != record.project_request_id
            or current.request.project_id != record.project_id
            or current.revision != record.ready_request_revision
            or current.request_revision_sha256 != record.ready_request_revision_sha256
            or run.outcome is not PlannerRunOutcome.READY_FOR_DELIVERY
            or run.project_id != record.project_id
            or run.request_id != record.project_request_id
            or run.run_record_sha256 != record.planner_run_record_sha256
            or run.design_checkpoint_sha256 != record.design_checkpoint_sha256
            or run.planning_authorization_sha256 != record.planning_authorization_sha256
            or run.execution_plan != plan
            or run.ready_request_revision != current
            or checkpoint.run_id != run.run_id
            or checkpoint.run_record_sha256 != run.run_record_sha256
            or checkpoint.design_checkpoint_sha256 != run.design_checkpoint_sha256
            or checkpoint.planning_authorization_sha256 != run.planning_authorization_sha256
            or checkpoint.execution_plan_id != plan.id
            or checkpoint.execution_plan_sha256 != plan.execution_plan_sha256
            or checkpoint.ready_request_revision != current.revision
            or checkpoint.ready_request_revision_sha256 != current.request_revision_sha256
            or checkpoint.checkpoint_sha256 != record.planner_checkpoint_sha256
            or plan.execution_plan_sha256 != record.execution_plan_sha256
        ):
            raise DispatchPreviewStale(
                "READY revision or complete Planner handoff changed inside commit fence"
            )

    @staticmethod
    def _validate_reservations(
        record: DeliveryAllocation,
        snapshot: DispatchWorkforceSnapshot,
    ) -> None:
        assignment_ids = {assignment.id for assignment in snapshot.assignments}
        lease_ids = {lease.id for lease in snapshot.active_leases}
        if any(phase.assignment.id in assignment_ids for phase in record.phases):
            raise DispatchAuthorityConflict("dispatch Assignment identity is already reserved")
        if any(phase.lease.id in lease_ids for phase in record.phases):
            raise DispatchAuthorityConflict("dispatch Lease identity is already reserved")

    @staticmethod
    def _lock_authority(cursor: object) -> None:
        typed = cast("pymysql.cursors.DictCursor", cursor)
        typed.execute("SELECT id FROM dispatch_authority_lock WHERE id = 1 FOR UPDATE")
        if typed.fetchone() is None:
            raise DispatchCommitCorruption("dispatch authority lock row is missing")

    @staticmethod
    @contextmanager
    def _transaction(connection: Connection) -> Iterator[None]:
        try:
            connection.begin()
            yield
        except (
            DispatchAuthorityConflict,
            DispatchCommitConflict,
            DispatchCommitCorruption,
        ):
            connection.rollback()
            raise
        except pymysql.MySQLError as error:
            connection.rollback()
            raise DispatchCommitPathError("MySQL dispatch transaction failed") from error
        except BaseException:
            connection.rollback()
            raise
        else:
            try:
                connection.commit()
            except pymysql.MySQLError as error:
                connection.rollback()
                raise DispatchCommitPathError("MySQL dispatch commit failed") from error


def _encode(model: DispatchWorkforceSnapshot | DeliveryAllocation) -> str:
    return json.dumps(
        model.to_wire(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _decode_snapshot(row: Mapping[str, object]) -> DispatchWorkforceSnapshot:
    try:
        snapshot = DispatchWorkforceSnapshot.model_validate_json(_text(row, "payload_json"))
        snapshot.validate_integrity()
        if (
            _text(row, "project_id") != snapshot.project_id
            or _text(row, "task_id") != snapshot.task_id
            or _text(row, "snapshot_sha256") != snapshot.snapshot_sha256
        ):
            raise ValueError("snapshot row digest does not match")
        return snapshot
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise DispatchCommitCorruption("invalid authoritative workforce snapshot") from error


def _decode_commit(row: Mapping[str, object]) -> DispatchCommitRecord:
    record = _decode_allocation(row)
    if not isinstance(record, DispatchCommitRecord):
        raise DispatchCommitCorruption("expected native Planner dispatch")
    return record


def _decode_allocation(row: Mapping[str, object]) -> DeliveryAllocation:
    try:
        payload = json.loads(_text(row, "payload_json"))
        record: DeliveryAllocation
        if isinstance(payload, dict) and payload.get("kind") == "recovery_dispatch":
            record = RecoveryDispatchRecord.model_validate(payload)
        else:
            record = DispatchCommitRecord.model_validate(payload)
        record.validate_integrity()
        if (
            _text(row, "id") != record.id
            or _text(row, "project_id") != record.project_id
            or _text(row, "task_id") != record.task_id
            or _text(row, "dispatch_sha256") != record.dispatch_sha256
        ):
            raise ValueError("dispatch row digest does not match")
        return record
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise DispatchCommitCorruption("invalid authoritative dispatch commit") from error


def _text(row: Mapping[str, object], key: str) -> str:
    value = row[key]
    if not isinstance(value, str):
        raise DispatchCommitCorruption(f"MySQL dispatch column {key} is not text")
    return value


__all__ = ["MySqlDispatchAuthority"]
