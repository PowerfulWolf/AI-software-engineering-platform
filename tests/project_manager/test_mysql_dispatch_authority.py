"""MySQL integration contracts for atomic Project Manager dispatch."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pymysql
import pytest

from ai_software_engineer.project_manager import MySqlDispatchAuthority
from ai_software_engineer.project_manager.dispatch import (
    DispatchAuthorityConflict,
    DispatchCommitConflict,
    DispatchCommitRecord,
    DispatchPreviewStale,
    ProjectManagerDispatchService,
)
from ai_software_engineer.scheduling import PortfolioScheduler
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from tests.project_manager.test_dispatch import _router
from tests.project_manager.test_dispatch_authority import _durable_facts

pytestmark = pytest.mark.mysql


@pytest.fixture
def mysql_dsn() -> str:
    value = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not value:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    with closing(open_mysql_connection(value)) as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM dispatch_commits")
                cursor.execute("DELETE FROM dispatch_workforce_snapshots")
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
    service = ProjectManagerDispatchService(
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
    current = reopened.current_snapshot(project_id=record.project_id, task_id=record.task_id)
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
        project_id=record.project_id,
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
