"""Complete baseline checks are shared only by one explicit read projection."""

import asyncio
import gc
import json
import weakref
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import AgentRole, Task, WorkItemStatus
from ai_software_engineer.domain.continuation import (
    InterruptionContinuationPolicy,
    task_intent_sha256,
)
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.domain.model import JsonValue
from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
    ProjectDeliveryIntake,
)
from ai_software_engineer.manager.dispatch import DeliveryAllocation
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationScope,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.projection.models import ArtifactHistoryFacts
from ai_software_engineer.recovery.models import CapturedChanges, digest
from ai_software_engineer.team_view.baseline_snapshot import BaselineBindingSnapshot
from ai_software_engineer.team_view.engineering_history import engineering_history
from ai_software_engineer.team_view.models import RoleQueueView, ScopeView, TaskView, TeamSnapshot
from ai_software_engineer.team_view.queue_reader import read_pending_baseline_continuation
from ai_software_engineer.team_view.reader import (
    ProductionTeamReader,
    _CandidateBranchCache,
    _continuation_history,
    _ModelRouteAttemptCache,
    _Native,
    _TaskReadSnapshot,
)
from ai_software_engineer.web_console.transport import _team_snapshot
from tests.manager.test_execution_baseline import authorize, setup
from tests.orchestration.test_continuation_records import make_receipt


@dataclass(frozen=True)
class _Fixture:
    sidecar: Path
    task: Task
    store: FileExecutionBaselineStore
    binding: ExecutionBaselineBinding
    receipt: ExecutionInterruptionReceipt


def _fixture(tmp_path: Path) -> _Fixture:
    fixture = setup(tmp_path)
    task = fixture.collector.facts.task.model_copy(
        update={"interruption_continuation_policy": InterruptionContinuationPolicy()}
    )
    facts = fixture.collector.facts.model_copy(
        update={
            "task": task,
            "scope": fixture.collector.facts.scope.model_copy(
                update={"repository_id": "repository_baseline_snapshot"}
            ),
        }
    )
    fixture.collector.facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    sidecar = tmp_path / "sidecar"
    root = sidecar / "state" / "execution-baselines" / task.id
    writer = FileExecutionBaselineStore(root)
    fixture.service.store = writer
    plan = fixture.service.propose(fixture.target)
    binding = fixture.service.execute(plan.plan_sha256, authority=authorize(plan))

    sample = make_receipt(tmp_path)
    assert isinstance(sample.capture, CapturedChanges)
    capture = sample.capture.to_capture()
    capture = replace(
        capture,
        worktree=replace(
            capture.worktree,
            task_id=task.id,
            head_revision=task.base_ref,
            branch=task.branch_name,
        ),
    )
    scope = ContinuationScope(
        team_id=binding.scope.team_id,
        project_id=binding.scope.project_id,
        repository_id=binding.scope.repository_id,
        requirement_id="delivery_baseline_snapshot",
        dispatch_sha256="c" * 64,
    )
    receipt = ExecutionInterruptionReceipt.create(
        **{
            **sample.to_wire(),
            "scope": scope,
            "request": sample.request.model_copy(
                update={"task_id": task.id, "source_revision": task.base_ref}
            ),
            "capture": CapturedChanges.from_capture(capture),
            "task_intent_sha256": task_intent_sha256(task),
        }
    )
    parent = sidecar / "state" / "continuations"
    parent.mkdir(parents=True, mode=0o700)
    continuation = FileContinuationStore.initialize(parent / task.id, task_id=task.id)
    continuation.put_receipt(receipt)
    (sidecar / "evaluations").mkdir()
    return _Fixture(
        sidecar, task, FileExecutionBaselineStore(root, read_only=True), binding, receipt
    )


def _ready() -> tuple[RoleQueueView, ...]:
    return (
        RoleQueueView(
            work_item_id="work_baseline_snapshot",
            role=AgentRole.CODER,
            attempt=1,
            status=WorkItemStatus.READY,
        ),
    )


def _projections(
    fixture: _Fixture, snapshot: BaselineBindingSnapshot | None = None
) -> tuple[object, ...]:
    history = engineering_history(
        fixture.sidecar,
        fixture.task,
        fixture.binding.scope,
        fixture.receipt.scope.requirement_id,
        baseline_bindings=snapshot,
    )
    queue = read_pending_baseline_continuation(
        cast(DictCursor, object()),  # No saved continuation: returns before any SQL.
        task=fixture.task,
        task_revision=1,
        scope=fixture.binding.scope,
        baselines=fixture.store,
        views=_ready(),
        baseline_bindings=snapshot,
    )
    interruption = _continuation_history(
        fixture.sidecar, fixture.task, fixture.receipt.scope, baseline_bindings=snapshot
    )
    return history, queue, interruption


def test_three_actual_projections_validate_the_complete_binding_prefix_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    original = FileExecutionBaselineStore.bindings_for_task
    calls: list[tuple[Path, str]] = []

    def counted(
        store: FileExecutionBaselineStore, task_id: str
    ) -> tuple[ExecutionBaselineBinding, ...]:
        calls.append((store.root, task_id))
        return original(store, task_id)

    monkeypatch.setattr(FileExecutionBaselineStore, "bindings_for_task", counted)
    saved = {path: path.read_bytes() for path in fixture.sidecar.rglob("*.json")}
    expected = _projections(fixture)
    assert calls == [(fixture.store.root, fixture.task.id)] * 3
    calls.clear()
    assert _projections(fixture, BaselineBindingSnapshot()) == expected
    assert calls == [(fixture.store.root, fixture.task.id)]
    assert saved == {path: path.read_bytes() for path in fixture.sidecar.rglob("*.json")}


def test_snapshot_separates_exact_roots_and_tasks_and_rejects_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_writer = FileExecutionBaselineStore(tmp_path / "first")
    second_writer = FileExecutionBaselineStore(tmp_path / "second")
    first = FileExecutionBaselineStore(first_writer.root, read_only=True)
    second = FileExecutionBaselineStore(second_writer.root, read_only=True)
    original = FileExecutionBaselineStore.bindings_for_task
    calls: list[tuple[Path, str]] = []

    def counted(
        store: FileExecutionBaselineStore, task_id: str
    ) -> tuple[ExecutionBaselineBinding, ...]:
        calls.append((store.root, task_id))
        return original(store, task_id)

    monkeypatch.setattr(FileExecutionBaselineStore, "bindings_for_task", counted)
    snapshot = BaselineBindingSnapshot()
    for _ in range(2):
        assert snapshot.bindings_for_task(first, "task_one") == ()
        assert snapshot.bindings_for_task(first, "task_two") == ()
        assert snapshot.bindings_for_task(second, "task_one") == ()
    assert calls == [(first.root, "task_one"), (first.root, "task_two"), (second.root, "task_one")]
    with pytest.raises(ValueError, match="read-only"):
        snapshot.bindings_for_task(first_writer, "task_one")
    assert len(calls) == 3


def test_failed_read_is_not_registered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    writer = FileExecutionBaselineStore(tmp_path / "records")
    readonly = FileExecutionBaselineStore(writer.root, read_only=True)
    original = FileExecutionBaselineStore.bindings_for_task
    calls = 0

    def fail_once(
        store: FileExecutionBaselineStore, task_id: str
    ) -> tuple[ExecutionBaselineBinding, ...]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("corrupt initial prefix")
        return original(store, task_id)

    monkeypatch.setattr(FileExecutionBaselineStore, "bindings_for_task", fail_once)
    snapshot = BaselineBindingSnapshot()
    with pytest.raises(ValueError, match="corrupt initial"):
        snapshot.bindings_for_task(readonly, "task_retry")
    assert snapshot.bindings_for_task(readonly, "task_retry") == ()
    assert snapshot.bindings_for_task(readonly, "task_retry") == ()
    assert calls == 2


def test_new_snapshot_observes_binding_append_after_captured_empty_prefix(tmp_path: Path) -> None:
    root = tmp_path / "sidecar" / "state" / "execution-baselines" / "task_domain_001"
    FileExecutionBaselineStore(root)
    readonly = FileExecutionBaselineStore(root, read_only=True)
    old = BaselineBindingSnapshot()
    assert old.bindings_for_task(readonly, "task_domain_001") == ()
    fixture = _fixture(tmp_path)
    assert old.bindings_for_task(fixture.store, fixture.task.id) == ()
    assert BaselineBindingSnapshot().bindings_for_task(fixture.store, fixture.task.id) == (
        fixture.binding,
    )


@pytest.mark.parametrize("change", ["plan", "authority", "capture", "symlink"])
def test_new_snapshot_rechecks_historical_facts_and_paths(tmp_path: Path, change: str) -> None:
    fixture = _fixture(tmp_path)
    captured = BaselineBindingSnapshot()
    assert captured.bindings_for_task(fixture.store, fixture.task.id) == (fixture.binding,)
    namespace = "baseline-authorities" if change == "authority" else "baseline-plans"
    path = fixture.store.root / fixture.store.records._name(namespace, fixture.binding.plan_sha256)
    if change == "symlink":
        external = tmp_path / "external.json"
        path.rename(external)
        path.symlink_to(external)
    else:
        envelope = json.loads(path.read_bytes())
        if change == "authority":
            envelope["record"]["reference"] = "changed authority"
        elif change == "capture":
            envelope["record"]["complete_capture"]["patch"] += "\nchanged capture\n"
        else:
            envelope["record"]["prepared_source_revision"] = "f" * 40
        envelope["sha256"] = digest(envelope["record"])
        path.write_text(json.dumps(envelope), encoding="utf-8")
    assert captured.bindings_for_task(fixture.store, fixture.task.id) == (fixture.binding,)
    with pytest.raises((ValueError, KnowledgeError)):
        BaselineBindingSnapshot().bindings_for_task(fixture.store, fixture.task.id)


class _TaskCursor:
    def __init__(self, task: Task) -> None:
        self.row: dict[str, JsonValue] = {
            "payload_json": task.model_dump_json(),
            "status": task.status.value,
            "revision": 0,
        }

    def execute(self, query: str, args: object = None) -> int:
        assert query.startswith(("SELECT * FROM tasks ", "SELECT * FROM state_events "))
        return 0

    def fetchone(self) -> dict[str, JsonValue]:
        return self.row

    def fetchall(self) -> list[dict[str, JsonValue]]:
        return []


def _read_snapshot_fixture(
    fixture: _Fixture, monkeypatch: pytest.MonkeyPatch
) -> tuple[_TaskReadSnapshot, _Native, TaskView, DeliveryAllocation]:
    import ai_software_engineer.team_view.queue_reader as queue_reader
    import ai_software_engineer.team_view.reader as reader

    now = datetime(2026, 10, 10, tzinfo=UTC)
    intake = ProjectDeliveryIntake.create(
        delivery_id=fixture.receipt.scope.requirement_id,
        repository_id=fixture.binding.scope.repository_id,
        repository_root=fixture.task.repository,
        title=fixture.task.title,
        requirement=fixture.task.description,
        submitted_at=now,
    )
    checkpoint = ProjectDeliveryCheckpoint.create(
        delivery_id=intake.delivery_id,
        sequence=1,
        repository_id=intake.repository_id,
        repository_root=intake.repository_root,
        stage=DeliveryStage.PREPARING,
        stage_attempts=DeliveryStageAttempts(),
        next_action=DeliveryNextAction.PREPARE_PROJECT,
        checkpointed_at=now,
    )
    native = _Native(
        checkpoint, intake, fixture.sidecar, (checkpoint,), fixture.binding.scope.team_id
    )
    base = TaskView(
        id=intake.delivery_id,
        project_id=fixture.binding.scope.project_id,
        request_id=intake.delivery_id,
        title=intake.title,
        scope=ScopeView(root=intake.repository_root, selected_paths=(".",)),
        status="IMPLEMENTING",
        checkpoint_stage="DELIVERING",
        terminal=False,
        last_activity=now,
        next_action="Continue saved progress",
    )
    # This test's varying adapter supplies only existing read-only SQL facts. The
    # real _read_task_details and all three filesystem projections still execute.
    dispatch = cast(
        DeliveryAllocation,
        SimpleNamespace(
            task=fixture.task,
            task_id=fixture.task.id,
            repository_id=intake.repository_id,
            dispatch_sha256=fixture.receipt.scope.dispatch_sha256,
            phases=(),
        ),
    )
    monkeypatch.setattr(
        reader, "_read_accepted_artifact_history", lambda *a, **kw: ArtifactHistoryFacts()
    )
    monkeypatch.setattr(reader, "_read_runs", lambda *a, **kw: ())
    monkeypatch.setattr(queue_reader, "read_role_queue", lambda *a, **kw: _ready())
    reads = _TaskReadSnapshot(
        cast(DictCursor, _TaskCursor(fixture.task)),
        _ModelRouteAttemptCache(),
        _CandidateBranchCache(),
    )
    return reads, native, base, dispatch


def test_task_read_snapshot_wires_all_three_real_projections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    reads, native, base, dispatch = _read_snapshot_fixture(fixture, monkeypatch)
    original = FileExecutionBaselineStore.bindings_for_task
    calls: list[tuple[Path, str]] = []

    def counted(
        store: FileExecutionBaselineStore, task_id: str
    ) -> tuple[ExecutionBaselineBinding, ...]:
        calls.append((store.root, task_id))
        return original(store, task_id)

    monkeypatch.setattr(FileExecutionBaselineStore, "bindings_for_task", counted)
    view = reads.read(native, base, dispatch_override=dispatch)
    assert view.task_id == fixture.task.id
    assert any(entry.id.startswith("baseline_") for entry in view.timeline)
    assert any(entry.id.startswith("interruption_") for entry in view.timeline)
    assert calls == [(fixture.store.root, fixture.task.id)]
    assert reads.read(native, base, dispatch_override=dispatch) is view
    fresh, native, base, dispatch = _read_snapshot_fixture(fixture, monkeypatch)
    assert fresh.read(native, base, dispatch_override=dispatch) == view
    assert calls == [(fixture.store.root, fixture.task.id)] * 2


@pytest.mark.parametrize("failure", [False, True])
def test_http_read_releases_snapshot_bindings_after_success_or_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    fixture = _fixture(tmp_path)
    references: list[weakref.ReferenceType[BaselineBindingSnapshot]] = []
    projected: list[TaskView] = []

    def snapshot(reader: ProductionTeamReader, project_id: str | None) -> TeamSnapshot:
        reads, native, base, dispatch = _read_snapshot_fixture(fixture, monkeypatch)
        references.append(weakref.ref(reads._baselines))
        view = reads.read(native, base, dispatch_override=dispatch)
        projected.append(view)
        if failure:
            raise ValueError("projection failed after complete prefix validation")
        return TeamSnapshot(
            as_of=datetime.now(UTC), team_id="team_snapshot", team_name="Snapshot", tasks=(view,)
        )

    monkeypatch.setattr(ProductionTeamReader, "_snapshot", snapshot)
    reader = ProductionTeamReader(cast(ProductionConfig, object()), {})
    response = asyncio.run(_team_snapshot(reader, None, Lock()))
    assert response.status_code == (503 if failure else 200)
    assert projected and any(entry.id.startswith("baseline_") for entry in projected[0].timeline)
    gc.collect()
    assert references and all(reference() is None for reference in references)
