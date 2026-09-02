"""Production SQLite dispatch authority transaction and fence tests."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event, RLock

import pytest

from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.project_delivery import ExecutionPlan, ExecutionPlanId
from ai_software_engineer.planning.models import PlannerCommitCheckpoint, PlannerRunRecord
from ai_software_engineer.planning.store import FileExecutionPlanStore
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.project_manager.dispatch import (
    CommitDispatchRequest,
    DispatchAuthorityConflict,
    DispatchCommitConflict,
    DispatchCommitRecord,
    DispatchPreviewStale,
    DispatchWorkforceSnapshot,
    ProjectManagerDispatchService,
)
from ai_software_engineer.project_manager.dispatch_authority import SqliteDispatchAuthority
from ai_software_engineer.scheduling import PortfolioScheduler
from tests.project_manager.test_dispatch import (
    RecordingDispatchStore,
    _facts,
    _router,
    _service,
)


class FencedRevisionAuthority:
    def __init__(self, revision: ProjectRequestRevision) -> None:
        self.revision = revision
        self._lock = RLock()

    @contextmanager
    def request_revision_fence(self) -> Iterator[None]:
        with self._lock:
            yield

    def current_request_revision(self, request_id: str) -> ProjectRequestRevision:
        assert request_id == self.revision.request.id
        return self.revision

    def advance(self) -> None:
        with self.request_revision_fence():
            current = self.revision
            changed = type(current.request).create(
                request_id=current.request.id,
                project_id=current.request.project_id,
                preparation_sha256=current.request.preparation_sha256,
                title=current.request.title,
                original_request=current.request.original_request,
                status=current.request.status,
                created_at=current.request.created_at,
                updated_at=current.request.updated_at + timedelta(seconds=1),
            )
            self.revision = ProjectRequestRevision.create(
                changed,
                revision=current.revision + 1,
                supersedes_sha256=current.request_revision_sha256,
                recorded_at=changed.updated_at,
            )


class BlockingPlannerReader:
    def __init__(self, inner: FileExecutionPlanStore) -> None:
        self._inner = inner
        self.entered = Event()
        self.release = Event()

    def get_run(self, run_id: RunId | str) -> PlannerRunRecord:
        self.entered.set()
        assert self.release.wait(timeout=5)
        return self._inner.get_run(run_id)

    def get_checkpoint(self, run_id: RunId | str) -> PlannerCommitCheckpoint:
        return self._inner.get_checkpoint(run_id)

    def get_execution_plan(self, plan_id: ExecutionPlanId | str) -> ExecutionPlan:
        return self._inner.get_execution_plan(plan_id)


def _durable_facts(
    tmp_path: Path,
) -> tuple[
    CommitDispatchRequest,
    DispatchWorkforceSnapshot,
    DispatchCommitRecord,
    FileExecutionPlanStore,
    FencedRevisionAuthority,
]:
    request, snapshot = _facts(tmp_path)
    memory = RecordingDispatchStore()
    record = _service(memory, snapshot, request).commit_dispatch(request)
    plans = FileExecutionPlanStore(tmp_path / "planner")
    plans.put_execution_plan(request.execution_plan)
    plans.put_run(request.planner_run_record)
    plans.put_checkpoint(request.planner_checkpoint)
    revisions = FencedRevisionAuthority(request.ready_request_revision)
    return request, snapshot, record, plans, revisions


def test_authority_atomically_persists_allocations_and_exact_replay(tmp_path: Path) -> None:
    request, snapshot, record, plans, revisions = _durable_facts(tmp_path)
    authority = SqliteDispatchAuthority(
        (tmp_path / "dispatch.sqlite3").resolve(),
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
    assert (
        authority.commit_if_current(
            record,
            expected_snapshot_sha256=snapshot.snapshot_sha256,
        )
        == record
    )
    assert authority.get_commit(record.id) == record
    current = authority.current_snapshot(
        project_id=record.project_id,
        task_id=record.task_id,
    )
    assert current.work_item.status.value == "LEASED"
    assert {item.id for item in current.assignments} >= {
        phase.assignment.id for phase in record.phases
    }
    assert {item.id for item in current.active_leases} >= {
        phase.lease.id for phase in record.phases
    }


def test_two_authority_instances_cannot_publish_competing_reservations(
    tmp_path: Path,
) -> None:
    request, snapshot, record, plans, revisions = _durable_facts(tmp_path)
    database = (tmp_path / "dispatch.sqlite3").resolve()
    first = SqliteDispatchAuthority(
        database,
        request_revisions=revisions,
        planner_records=plans,
    )
    second = SqliteDispatchAuthority(
        database,
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
        authority: SqliteDispatchAuthority,
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


def test_ready_revision_writer_cannot_enter_inside_allocation_commit_fence(
    tmp_path: Path,
) -> None:
    _, snapshot, record, plans, revisions = _durable_facts(tmp_path)
    blocking = BlockingPlannerReader(plans)
    authority = SqliteDispatchAuthority(
        (tmp_path / "dispatch.sqlite3").resolve(),
        request_revisions=revisions,
        planner_records=blocking,
    )
    authority.seed_snapshot(snapshot)
    advanced = Event()

    def commit() -> DispatchCommitRecord:
        return authority.commit_if_current(
            record,
            expected_snapshot_sha256=snapshot.snapshot_sha256,
        )

    def advance() -> None:
        revisions.advance()
        advanced.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        commit_future = executor.submit(commit)
        assert blocking.entered.wait(timeout=5)
        advance_future = executor.submit(advance)
        assert not advanced.wait(timeout=0.1)
        blocking.release.set()
        assert commit_future.result(timeout=5) == record
        advance_future.result(timeout=5)
        assert advanced.is_set()


def test_ready_revision_changed_before_commit_is_rejected(tmp_path: Path) -> None:
    _, snapshot, record, plans, revisions = _durable_facts(tmp_path)
    authority = SqliteDispatchAuthority(
        (tmp_path / "dispatch.sqlite3").resolve(),
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
