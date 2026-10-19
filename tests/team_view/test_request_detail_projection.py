"""Selected Request bodies only assemble their real current native work."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.domain.enums import TaskStatus
from ai_software_engineer.manager.delivery_checkpoint import (
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.dispatch import VerificationReservation
from ai_software_engineer.multi_directory.models import ChildDelivery, JointCheckpoint
from ai_software_engineer.multi_directory.retirement import RequirementRetirementStore
from ai_software_engineer.recovery.models import digest as read_state_digest
from ai_software_engineer.team_view import reader as read_module
from ai_software_engineer.team_view.models import TaskView, TeamReadError, TeamSnapshot
from ai_software_engineer.team_view.read_models import (
    RequestDetail,
    TeamDetail,
    TeamDetailNotFound,
    TeamDetailQuery,
    TeamDetailSource,
    TeamSummary,
)
from ai_software_engineer.team_view.reader import ProductionTeamReader, _Native, _TaskReadSnapshot
from tests.manager.test_dispatch import RecordingDispatchStore, _facts, _service
from tests.team_view.test_live import _bytes, _historical_child_fixture, _put_unstarted_child
from tests.team_view.test_task_read_snapshot import _native_and_base


class _Cursor:
    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *arguments: object) -> None:
        pass

    def execute(self, sql: str, arguments: object = None) -> None:
        assert sql.startswith(("SET TRANSACTION", "START TRANSACTION", "SELECT plan_sha256"))

    def fetchall(self) -> tuple[()]:
        return ()


class _Connection:
    def cursor(self, cursor_type: object) -> _Cursor:
        return _Cursor()

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def _dispatch(
    store: FileProjectDeliveryCheckpointStore, checkpoint: ProjectDeliveryCheckpoint
) -> ProjectDeliveryCheckpoint:
    suffix = checkpoint.delivery_id.removeprefix("delivery_")
    return store.put(
        ProjectDeliveryCheckpoint.create(
            **{
                **checkpoint.to_wire(),
                "sequence": checkpoint.sequence + 1,
                "previous_checkpoint_sha256": checkpoint.checkpoint_sha256,
                "product_spec_id": "product_spec_reads",
                "product_spec_sha256": "1" * 64,
                "approval_id": "approval_reads",
                "approval_sha256": "2" * 64,
                "technical_design_id": "design_reads",
                "technical_design_sha256": "3" * 64,
                "execution_plan_id": "plan_reads",
                "execution_plan_sha256": "4" * 64,
                "planning_preview_id": "preview_reads",
                "planning_preview_sha256": "5" * 64,
                "dispatch_commit_id": f"dispatch_{suffix}",
                "dispatch_commit_sha256": "6" * 64,
                "task_id": f"task_{suffix}",
                "task_revision": 1,
                "task_status": TaskStatus.BLOCKED,
                "checkpointed_at": checkpoint.checkpointed_at + timedelta(seconds=1),
            }
        )
    )


def test_request_body_omits_discarded_tasks_and_final_source_rechecks_current_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, journal, parent, store = _historical_child_fixture(tmp_path)
    first = parent.children[0].checkpoint
    for number in range(12):
        child = (
            first
            if number == 0
            else _put_unstarted_child(
                store,
                delivery_id=f"delivery_prior_{number}",
                repository_id=first.repository_id,
                repository_root=first.repository_root,
                recorded_at=first.checkpointed_at + timedelta(minutes=number),
                failure_summary=f"Current failure {number}",
            )
        )
        child = _dispatch(store, child)
        parent = journal.append(
            JointCheckpoint.seal(
                {
                    **parent.to_wire(),
                    "sequence": parent.sequence + 1,
                    "previous_checkpoint_sha256": parent.checkpoint_sha256,
                    "children": (
                        ChildDelivery(unit_id=parent.scope.units[0].id, checkpoint=child),
                    ),
                }
            ),
            expected=parent.checkpoint_sha256,
        )
    standalone = _put_unstarted_child(
        store,
        delivery_id="delivery_unrelated_standalone",
        repository_id=first.repository_id,
        repository_root=first.repository_root,
        recorded_at=first.checkpointed_at,
    )
    calls: list[str] = []
    connections = 0

    def connect(dsn: str) -> _Connection:
        nonlocal connections
        connections += 1
        return _Connection()

    def read(
        snapshot: _TaskReadSnapshot,
        native: _Native,
        base: TaskView,
        **kwargs: object,
    ) -> TaskView:
        calls.append(native.checkpoint.delivery_id)
        if native.checkpoint.task_id is None:
            return base
        return base.model_copy(
            update={
                "task_id": native.checkpoint.task_id,
                "task_revision": 1,
                "task_intent_sha256": "8" * 64,
            }
        )

    monkeypatch.setattr(read_module, "open_mysql_connection", connect)
    monkeypatch.setattr(type(config), "require_mysql_dsn", lambda config, environment: "test-only")
    monkeypatch.setattr(_TaskReadSnapshot, "read", read)
    monkeypatch.setattr(read_module, "_active_successor_dispatch", lambda *arguments: None)
    reader = ProductionTeamReader(config, {})
    full = reader.snapshot()
    assert len(calls) == 13
    compact = reader.summary()
    saved = _bytes(Path(config.platform_root))
    for identity in (parent.delivery_id, standalone.delivery_id):
        calls.clear()
        connections = 0
        source = next(
            request.detail_source for request in compact.requests if request.id == identity
        )
        detail = reader.detail(TeamDetailQuery.from_source(source))
        assert isinstance(detail, RequestDetail)
        assert detail.resource == next(
            request for request in full.requests if request.id == identity
        )
        expected_native = child.delivery_id if identity == parent.delivery_id else identity
        assert calls == [expected_native, expected_native]
        assert connections == 2, "the source fence must independently recheck current SQL facts"
        assert detail.scope == source
    assert _bytes(Path(config.platform_root)) == saved


@pytest.mark.parametrize("change", ["native", "ancestor", "retired", "ownership"])
def test_source_fence_rechecks_complete_bytes_retirement_and_real_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    config, journal, parent, native_store = _historical_child_fixture(tmp_path)
    reader = ProductionTeamReader(config, {})
    query = TeamDetailQuery.from_source(reader.summary().requests[0].detail_source)
    original = reader._read_snapshot
    observations = 0

    def read(
        project_id: str | None,
        *,
        summary_only: bool = False,
        detail_query: TeamDetailQuery | None = None,
        source_query: TeamDetailQuery | None = None,
        joint_reads: read_module._DetailJournalReads | None = None,
    ) -> TeamSnapshot | TeamSummary | TeamDetail | TeamDetailSource:
        nonlocal observations
        result = original(
            project_id,
            summary_only=summary_only,
            detail_query=detail_query,
            source_query=source_query,
            joint_reads=joint_reads,
        )
        observations += 1
        if observations == 1:
            if change == "native":
                path = next(native_store._root.rglob("000001.json"))
                path.write_bytes(path.read_bytes() + b"corrupt")
            elif change == "ancestor":
                path = journal.directory(parent.delivery_id) / "000001.json"
                path.write_bytes(path.read_bytes().replace(b"K1", b"K2"))
            elif change == "retired":
                RequirementRetirementStore(
                    journal.root,
                    team_id=parent.team_id,
                    team_manifest_sha256=parent.team_manifest_sha256,
                    project_id=parent.project_id,
                    project_manifest_sha256=parent.project_manifest_sha256,
                ).retire(parent, reason="deleted", retired_at=parent.submitted_at)
            else:
                journal.append(
                    JointCheckpoint.seal(
                        {**parent.to_wire(), "delivery_id": "delivery_multi_foreign_owner"}
                    ),
                    expected=None,
                )
        return result

    monkeypatch.setattr(reader, "_read_snapshot", read)
    expected = TeamDetailNotFound if change == "retired" else TeamReadError
    with pytest.raises(expected):
        reader.detail(query)
    assert observations == 1, "the second observation must reject before publishing a source"


@pytest.mark.parametrize("failed_observation", [1, 2])
def test_current_task_validation_failure_is_not_hidden_by_request_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_observation: int
) -> None:
    config, _, parent, store = _historical_child_fixture(tmp_path)
    reader = ProductionTeamReader(config, {})
    _dispatch(store, parent.children[0].checkpoint)

    observations = 0

    def failed(
        snapshot: _TaskReadSnapshot, native: _Native, base: TaskView, **kwargs: object
    ) -> TaskView:
        nonlocal observations
        observations += 1
        if observations == failed_observation:
            raise ValueError("current engineering authority changed")
        return base.model_copy(
            update={
                "task_id": native.checkpoint.task_id,
                "task_revision": 1,
                "task_intent_sha256": "8" * 64,
            }
        )

    monkeypatch.setattr(read_module, "open_mysql_connection", lambda dsn: _Connection())
    monkeypatch.setattr(type(config), "require_mysql_dsn", lambda config, environment: "test-only")
    monkeypatch.setattr(_TaskReadSnapshot, "read", failed)
    monkeypatch.setattr(read_module, "_active_successor_dispatch", lambda *args: None)
    # Build the source directly from the real original journal observation; no
    # successful Task projection is assumed by this corruption test.
    query = TeamDetailQuery(
        team_id=parent.team_id,
        project_id=parent.project_id,
        request_id=parent.delivery_id,
        kind="request",
        id=parent.delivery_id,
        expected_requirement_checkpoint_sha256=parent.checkpoint_sha256,
        expected_resource_checkpoint_sha256=parent.checkpoint_sha256,
        expected_resource_state_sha256=read_state_digest(
            {"checkpoint_sha256": parent.checkpoint_sha256}
        ),
    )
    with pytest.raises(TeamReadError) as error:
        reader.detail(query)
    assert isinstance(error.value.__cause__, ValueError)
    assert str(error.value.__cause__) == "current engineering authority changed"
    assert observations == failed_observation


def test_predispatch_request_source_observation_needs_no_sql_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _, _, _ = _historical_child_fixture(tmp_path)
    reader = ProductionTeamReader(config, {})
    query = TeamDetailQuery.from_source(reader.summary().requests[0].detail_source)

    def unexpected(dsn: str) -> _Connection:
        raise AssertionError("Request source must not query SQL")

    monkeypatch.setattr(read_module, "open_mysql_connection", unexpected)
    result = reader._read_snapshot(query.project_id, source_query=query)
    assert result == query.source()


@pytest.mark.parametrize(
    "invalid_excluded", [None, "json", "missing-source", "repository", "release", "row-key"]
)
def test_selected_request_verifications_omit_body_only_after_complete_reservation_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_excluded: str | None
) -> None:
    request, workforce = _facts(tmp_path)
    dispatch = _service(RecordingDispatchStore(), workforce, request).commit_dispatch(request)
    native, base = _native_and_base(tmp_path)
    native = replace(
        native,
        checkpoint=native.checkpoint.model_copy(update={"repository_id": dispatch.repository_id}),
    )
    other = replace(
        native,
        checkpoint=native.checkpoint.model_copy(update={"delivery_id": "delivery_other_request"}),
    )
    rows: list[dict[str, object]] = []
    for number in (1, 2):
        task_id = f"task_verification_request_{number}"
        repository_id = (
            "repository_foreign"
            if number == 2 and invalid_excluded == "repository"
            else dispatch.repository_id
        )
        phases = tuple(
            phase.model_copy(
                update={
                    "assignment": phase.assignment.model_copy(
                        update={"task_id": task_id, "repository_id": repository_id}
                    ),
                    "lease": phase.lease.model_copy(update={"task_id": task_id}),
                }
            )
            for phase in dispatch.phases[1:]
        )
        reservation = VerificationReservation(
            plan_sha256=str(number) * 64,
            repository_id=repository_id,
            source_task_id=f"task_source_{number}",
            task_id=task_id,
            workforce_snapshot_sha256=dispatch.workforce_snapshot_sha256,
            phases=phases,
            committed_at=dispatch.committed_at,
        )
        row: dict[str, object] = {
            "plan_sha256": reservation.plan_sha256,
            "payload_json": reservation.model_dump_json(),
            "completion_sha256": None,
            "abandonment_sha256": None,
        }
        if number == 2:
            if invalid_excluded == "json":
                row["payload_json"] = "{}"
            elif invalid_excluded == "release":
                row.update(completion_sha256="3" * 64, abandonment_sha256="4" * 64)
            elif invalid_excluded == "row-key":
                row["plan_sha256"] = "5" * 64
        rows.append(row)

    class Cursor:
        def execute(self, sql: str) -> None:
            assert sql.startswith("SELECT plan_sha256")

        def fetchall(self) -> tuple[dict[str, object], ...]:
            return tuple(rows)

    source_reads: list[str] = []
    verification_reads: list[str] = []

    def source_read(source: _Native, *args: object, **kwargs: object) -> TaskView:
        source_reads.append(source.checkpoint.delivery_id)
        return base.model_copy(update={"task_id": "task_source_1"})

    def verification_read(
        source: _Native,
        request_id: str,
        source_scope: object,
        reservation: VerificationReservation,
        *args: object,
        **kwargs: object,
    ) -> TaskView:
        verification_reads.append(source.checkpoint.delivery_id)
        return base.model_copy(update={"task_id": reservation.task_id})

    monkeypatch.setattr(read_module, "_read_task", source_read)
    monkeypatch.setattr(read_module, "_verification_view", verification_read)
    sources = {
        "task_source_1": (native, base.request_id, base.scope),
        "task_source_2": (other, "delivery_other_request", base.scope),
    }
    if invalid_excluded == "missing-source":
        del sources["task_source_2"]

    def read() -> tuple[TaskView, ...]:
        return read_module._read_verifications(
            cast(DictCursor, Cursor()),
            sources,
            team_id="team_test",
            project_id="project_test",
            selected_source_delivery_ids=frozenset({native.checkpoint.delivery_id}),
        )

    if invalid_excluded is None:
        assert len(read()) == 1
        assert source_reads == verification_reads == [native.checkpoint.delivery_id]
    else:
        with pytest.raises(ValueError):
            read()
        assert other.checkpoint.delivery_id not in source_reads + verification_reads
