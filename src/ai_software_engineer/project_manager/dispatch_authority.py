"""SQLite allocation authority with a Product-revision commit fence."""

from __future__ import annotations

import json
import sqlite3
from contextlib import AbstractContextManager, closing
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from ai_software_engineer.domain.enums import ProjectRequestStatus, WorkItemStatus
from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.project_delivery import ProjectRequestId
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.planning.models import PlannerRunOutcome
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.project_manager.dispatch import (
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
)


class DispatchRevisionAuthority(Protocol):
    """Product head reader whose writers share one cross-domain fence."""

    def current_request_revision(
        self, request_id: ProjectRequestId | str
    ) -> ProjectRequestRevision: ...

    def request_revision_fence(self) -> AbstractContextManager[None]: ...


class SqliteDispatchAuthority:
    """Atomically compare workforce facts and reserve all delivery roles.

    Lock ordering is part of the contract: acquire the Product revision fence first,
    then SQLite ``BEGIN IMMEDIATE``. Every Product revision writer uses the same fence,
    while every dispatch reservation writer uses this database transaction.
    """

    def __init__(
        self,
        database: str | Path,
        *,
        request_revisions: DispatchRevisionAuthority,
        planner_records: DispatchPlannerRecordReader,
    ) -> None:
        configured = Path(database).expanduser()
        if not configured.is_absolute():
            raise DispatchCommitPathError("dispatch authority database must be absolute")
        configured.parent.mkdir(parents=True, exist_ok=True)
        if configured.is_symlink() or configured.parent.is_symlink():
            raise DispatchCommitPathError("dispatch authority database path cannot be a symlink")
        self._database = configured.resolve(strict=False)
        self._request_revisions = request_revisions
        self._planner_records = planner_records
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS dispatch_workforce_snapshots (
                    project_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    snapshot_sha256 TEXT NOT NULL,
                    PRIMARY KEY (project_id, task_id)
                );
                CREATE TABLE IF NOT EXISTS dispatch_commits (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    dispatch_sha256 TEXT NOT NULL
                );
                """
            )

    def seed_snapshot(self, snapshot: DispatchWorkforceSnapshot) -> DispatchWorkforceSnapshot:
        """Register immutable current workforce inputs before the first preview."""
        snapshot.validate_integrity()
        payload = _encode(snapshot)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT project_id, task_id, payload_json, snapshot_sha256
                    FROM dispatch_workforce_snapshots
                    WHERE project_id = ? AND task_id = ?
                    """,
                    (snapshot.project_id, snapshot.task_id),
                ).fetchone()
                if row is not None:
                    existing = _decode_snapshot(row)
                    if existing != snapshot:
                        raise DispatchAuthorityConflict(
                            "workforce snapshot identity already has different facts"
                        )
                    connection.commit()
                    return existing
                connection.execute(
                    """
                    INSERT INTO dispatch_workforce_snapshots
                        (project_id, task_id, payload_json, snapshot_sha256)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        snapshot.project_id,
                        snapshot.task_id,
                        payload,
                        snapshot.snapshot_sha256,
                    ),
                )
                connection.commit()
                return snapshot
            except Exception:
                connection.rollback()
                raise

    def current_snapshot(
        self,
        *,
        project_id: ProjectId,
        task_id: TaskId,
    ) -> DispatchWorkforceSnapshot:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            try:
                snapshot = self._current_snapshot(connection, project_id, task_id)
                connection.commit()
                return snapshot
            except Exception:
                connection.rollback()
                raise

    def commit_if_current(
        self,
        record: DispatchCommitRecord,
        *,
        expected_snapshot_sha256: DispatchSha256,
    ) -> DispatchCommitRecord:
        """Fence READY and workforce facts, then publish one allocation commit point."""
        record.validate_integrity()
        with (
            self._request_revisions.request_revision_fence(),
            closing(self._connect()) as connection,
        ):
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing_row = connection.execute(
                    """
                        SELECT id, project_id, task_id, payload_json, dispatch_sha256
                        FROM dispatch_commits WHERE id = ?
                        """,
                    (record.id,),
                ).fetchone()
                if existing_row is not None:
                    existing = _decode_commit(existing_row)
                    if existing != record:
                        raise DispatchCommitConflict(
                            f"dispatch commit {record.id} already has different content"
                        )
                    connection.commit()
                    return existing

                snapshot = self._current_snapshot(connection, record.project_id, record.task_id)
                if snapshot.snapshot_sha256 != expected_snapshot_sha256:
                    raise DispatchAuthorityConflict(
                        "authoritative workforce snapshot changed before commit"
                    )
                self._validate_handoff(record)
                self._validate_reservations(record, snapshot)
                connection.execute(
                    """
                        INSERT INTO dispatch_commits
                            (id, project_id, task_id, payload_json, dispatch_sha256)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                    (
                        record.id,
                        record.project_id,
                        record.task_id,
                        _encode(record),
                        record.dispatch_sha256,
                    ),
                )
                # Force full decode/merge before the commit point becomes visible.
                self._current_snapshot(connection, record.project_id, record.task_id)
                connection.commit()
                return record
            except Exception:
                connection.rollback()
                raise

    def get_commit(self, commit_id: DispatchCommitId) -> DispatchCommitRecord:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, project_id, task_id, payload_json, dispatch_sha256
                FROM dispatch_commits WHERE id = ?
                """,
                (commit_id,),
            ).fetchone()
        if row is None:
            raise DispatchCommitNotFound(f"dispatch commit {commit_id} was not found")
        return _decode_commit(row)

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
        record: DispatchCommitRecord,
        snapshot: DispatchWorkforceSnapshot,
    ) -> None:
        assignment_ids = {assignment.id for assignment in snapshot.assignments}
        lease_ids = {lease.id for lease in snapshot.active_leases}
        if any(phase.assignment.id in assignment_ids for phase in record.phases):
            raise DispatchAuthorityConflict("dispatch Assignment identity is already reserved")
        if any(phase.lease.id in lease_ids for phase in record.phases):
            raise DispatchAuthorityConflict("dispatch Lease identity is already reserved")

    def _current_snapshot(
        self,
        connection: sqlite3.Connection,
        project_id: ProjectId,
        task_id: TaskId,
    ) -> DispatchWorkforceSnapshot:
        row = connection.execute(
            """
            SELECT project_id, task_id, payload_json, snapshot_sha256
            FROM dispatch_workforce_snapshots
            WHERE project_id = ? AND task_id = ?
            """,
            (project_id, task_id),
        ).fetchone()
        if row is None:
            raise DispatchAuthorityConflict(
                f"workforce snapshot is not registered for {project_id}/{task_id}"
            )
        base = _decode_snapshot(row)
        if base.project_id != project_id or base.task_id != task_id:
            raise DispatchCommitCorruption(
                "workforce snapshot row identity does not match its payload"
            )
        assignments = {assignment.id: assignment for assignment in base.assignments}
        leases = {lease.id: lease for lease in base.active_leases}
        task_commit_time: datetime | None = None
        for commit_row in connection.execute(
            """
            SELECT id, project_id, task_id, payload_json, dispatch_sha256
            FROM dispatch_commits ORDER BY id
            """
        ):
            commit = _decode_commit(commit_row)
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
            active_leases=leases.values(),
            assignments=assignments.values(),
            model_policies=base.model_policies,
        )

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self._database, isolation_level=None, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            return connection
        except sqlite3.Error as error:
            raise DispatchCommitPathError(
                f"cannot open dispatch authority database: {error}"
            ) from error


def _encode(model: DispatchWorkforceSnapshot | DispatchCommitRecord) -> str:
    return json.dumps(
        model.to_wire(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _decode_snapshot(row: sqlite3.Row) -> DispatchWorkforceSnapshot:
    try:
        snapshot = DispatchWorkforceSnapshot.model_validate_json(row["payload_json"])
        snapshot.validate_integrity()
        if (
            row["project_id"] != snapshot.project_id
            or row["task_id"] != snapshot.task_id
            or row["snapshot_sha256"] != snapshot.snapshot_sha256
        ):
            raise ValueError("snapshot row digest does not match")
        return snapshot
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise DispatchCommitCorruption("invalid authoritative workforce snapshot") from error


def _decode_commit(row: sqlite3.Row) -> DispatchCommitRecord:
    try:
        record = DispatchCommitRecord.model_validate_json(row["payload_json"])
        record.validate_integrity()
        if (
            row["id"] != record.id
            or row["project_id"] != record.project_id
            or row["task_id"] != record.task_id
            or row["dispatch_sha256"] != record.dispatch_sha256
        ):
            raise ValueError("dispatch row digest does not match")
        return record
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise DispatchCommitCorruption("invalid authoritative dispatch commit") from error


__all__ = ["DispatchRevisionAuthority", "SqliteDispatchAuthority"]
