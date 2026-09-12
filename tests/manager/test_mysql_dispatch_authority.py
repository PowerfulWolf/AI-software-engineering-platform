"""MySQL integration contracts for atomic Manager dispatch."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pymysql
import pytest

from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.manager import MySqlDispatchAuthority
from ai_software_engineer.manager.dispatch import (
    DispatchAuthorityConflict,
    DispatchCommitConflict,
    DispatchCommitRecord,
    DispatchPreviewStale,
    DispatchWorkforceSnapshot,
    ManagerDispatchService,
    VerificationReservation,
)
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.scheduling import PortfolioScheduler
from ai_software_engineer.store.mysql_repository import MySqlTaskRepository, open_mysql_connection
from tests.manager.test_dispatch import _router
from tests.manager.test_dispatch_authority import _durable_facts

pytestmark = pytest.mark.mysql


@pytest.mark.parametrize("terminal", [TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.DONE])
def test_terminal_tasks_release_capacity_without_erasing_dispatch(
    tmp_path: Path, mysql_dsn: str, terminal: TaskStatus
) -> None:
    _, snapshot, record, plans, revisions = _durable_facts(tmp_path)
    authority = MySqlDispatchAuthority(
        mysql_dsn, request_revisions=revisions, planner_records=plans
    )
    authority.seed_snapshot(snapshot)
    authority.commit_if_current(record, expected_snapshot_sha256=snapshot.snapshot_sha256)
    before = authority.current_snapshot(repository_id=record.repository_id, task_id=record.task_id)
    assert {p.lease.id for p in record.phases} <= {x.id for x in before.active_leases}
    with MySqlTaskRepository(mysql_dsn) as repository:
        repository.create(record.task)
        repository.record_attempt(record.task_id, 1)
        stages = (
            (
                TaskStatus.PLANNING,
                TaskStatus.IMPLEMENTING,
                TaskStatus.QA,
                TaskStatus.REVIEW,
                terminal,
            )
            if terminal is TaskStatus.DONE
            else (TaskStatus.PLANNING, terminal)
        )
        for index, stage in enumerate(stages):
            task = repository.get(record.task_id)
            repository.append_event(
                build_event(
                    task,
                    stage,
                    event_id=f"evt_release_{record.task_id}_{index}",
                    reason="Capacity regression fixture",
                    source_revision=task.base_ref,
                    occurred_at=task.updated_at + timedelta(seconds=1),
                )
            )
    reopened = MySqlDispatchAuthority(mysql_dsn, request_revisions=revisions, planner_records=plans)
    after = reopened.current_snapshot(repository_id=record.repository_id, task_id=record.task_id)
    assert not any(x.task_id == record.task_id for x in after.active_leases)
    assert after.assignments == before.assignments
    assert reopened.get_commit(record.id) == record

    def build_verification(current: DispatchWorkforceSnapshot) -> VerificationReservation:
        phases = []
        for index, phase in enumerate(record.phases[1:]):
            assignment_id = f"assignment_verify_{index}"
            lease_id = f"lease_verify_{index}"
            phases.append(
                phase.model_copy(
                    update={
                        "assignment": phase.assignment.model_copy(
                            update={
                                "id": assignment_id,
                                "lease_id": lease_id,
                                "task_id": "task_verify_fixture",
                            }
                        ),
                        "lease": phase.lease.model_copy(
                            update={
                                "id": lease_id,
                                "assignment_id": assignment_id,
                                "task_id": "task_verify_fixture",
                            }
                        ),
                    }
                )
            )
        return VerificationReservation(
            plan_sha256="a" * 64,
            repository_id=record.repository_id,
            source_task_id=record.task_id,
            task_id="task_verify_fixture",
            workforce_snapshot_sha256=current.snapshot_sha256,
            phases=tuple(phases),
            committed_at=record.committed_at,
        )

    def validate_current(reservation: VerificationReservation | None) -> None:
        if reservation is not None:
            assert reservation.source_task_id == record.task_id

    def reserve() -> VerificationReservation:
        return reopened.reserve_verification(
            repository_id=record.repository_id,
            source_task_id=record.task_id,
            plan_sha256="a" * 64,
            validate_current=validate_current,
            build=build_verification,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, replay = tuple(pool.map(lambda _: reserve(), range(2)))
    assert first == replay
    active = reopened.current_snapshot(repository_id=record.repository_id, task_id=record.task_id)
    assert {lease.id for lease in active.active_leases} == {p.lease.id for p in first.phases}

    def validate_completion(reservation: VerificationReservation, digest: str) -> None:
        assert reservation == first and digest == "b" * 64

    for _ in range(2):
        reopened.complete_verification(
            plan_sha256="a" * 64,
            completion_sha256="b" * 64,
            validate_completion=validate_completion,
        )
    released = reopened.current_snapshot(repository_id=record.repository_id, task_id=record.task_id)
    assert not released.active_leases
    assert released.assignments == active.assignments
    with pytest.raises(DispatchAuthorityConflict, match="already completed"):
        reserve()


@pytest.fixture
def mysql_dsn() -> str:
    value = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not value:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    with closing(open_mysql_connection(value)) as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW TABLES LIKE 'verification_reservations'")
                if cursor.fetchone() is not None:
                    cursor.execute("DELETE FROM verification_reservations")
                cursor.execute("DELETE FROM dispatch_commits")
                cursor.execute("DELETE FROM dispatch_workforce_snapshots")
                # This module's fixture has a fixed Task ID; remove only its prior run.
                cursor.execute(
                    "DELETE FROM state_events WHERE task_id = %s", ("task_dispatch_001",)
                )
                cursor.execute("DELETE FROM tasks WHERE id = %s", ("task_dispatch_001",))
            connection.commit()
        except pymysql.ProgrammingError as error:
            connection.rollback()
            if not error.args or error.args[0] != 1146:
                raise
    return value


def test_mysql_authority_persists_atomic_bundle_and_reopens(
    tmp_path: Path,
    mysql_dsn: str,
) -> None:
    request, snapshot, record, plans, revisions = _durable_facts(tmp_path)
    authority = MySqlDispatchAuthority(
        mysql_dsn,
        request_revisions=revisions,
        planner_records=plans,
    )
    authority.seed_snapshot(snapshot)
    service = ManagerDispatchService(
        scheduler=PortfolioScheduler(),
        model_router=_router(),
        authority=authority,
        request_revisions=revisions,
        planner_records=plans,
    )

    assert service.commit_dispatch(request) == record
    reopened = MySqlDispatchAuthority(
        mysql_dsn,
        request_revisions=revisions,
        planner_records=plans,
    )
    assert reopened.get_commit(record.id) == record
    assert (
        reopened.commit_if_current(
            record,
            expected_snapshot_sha256=snapshot.snapshot_sha256,
        )
        == record
    )
    current = reopened.current_snapshot(repository_id=record.repository_id, task_id=record.task_id)
    assert current.work_item.status.value == "LEASED"
    assert {item.id for item in current.assignments} >= {
        phase.assignment.id for phase in record.phases
    }


def test_mysql_global_lock_rejects_competing_dispatch_commits(
    tmp_path: Path,
    mysql_dsn: str,
) -> None:
    request, snapshot, record, plans, revisions = _durable_facts(tmp_path)
    first = MySqlDispatchAuthority(
        mysql_dsn,
        request_revisions=revisions,
        planner_records=plans,
    )
    second = MySqlDispatchAuthority(
        mysql_dsn,
        request_revisions=revisions,
        planner_records=plans,
    )
    first.seed_snapshot(snapshot)
    changed = DispatchCommitRecord.create(
        repository_id=record.repository_id,
        execution_plan=request.execution_plan,
        preview=request.planning_preview,
        ready_request_revision=request.ready_request_revision,
        planner_run_record=request.planner_run_record,
        planner_checkpoint=request.planner_checkpoint,
        stage_authorization=request.stage_authorization,
        task=record.task,
        phases=(record.phases[0], record.phases[1], record.phases[2]),
        committed_at=record.committed_at + timedelta(seconds=1),
    )
    barrier = Barrier(2)

    def commit(
        authority: MySqlDispatchAuthority,
        candidate: DispatchCommitRecord,
    ) -> DispatchCommitRecord:
        barrier.wait(timeout=5)
        return authority.commit_if_current(
            candidate,
            expected_snapshot_sha256=snapshot.snapshot_sha256,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(commit, first, record),
            executor.submit(commit, second, changed),
        )
        outcomes: list[DispatchCommitRecord | Exception] = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=10))
            except Exception as error:
                outcomes.append(error)

    assert sum(isinstance(item, DispatchCommitRecord) for item in outcomes) == 1
    assert (
        sum(
            isinstance(item, (DispatchCommitConflict, DispatchAuthorityConflict))
            for item in outcomes
        )
        == 1
    )


def test_mysql_dispatch_rejects_stale_product_revision(
    tmp_path: Path,
    mysql_dsn: str,
) -> None:
    _, snapshot, record, plans, revisions = _durable_facts(tmp_path)
    authority = MySqlDispatchAuthority(
        mysql_dsn,
        request_revisions=revisions,
        planner_records=plans,
    )
    authority.seed_snapshot(snapshot)
    revisions.advance()

    with pytest.raises(DispatchPreviewStale, match="inside commit fence"):
        authority.commit_if_current(
            record,
            expected_snapshot_sha256=snapshot.snapshot_sha256,
        )
