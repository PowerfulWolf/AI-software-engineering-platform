"""Finite evaluation and native Task facts are reused only inside one SQL read."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.evaluation import (
    CaseStartedEvent,
    EvaluationEvent,
    EvaluationEventCorruption,
    FileEvaluationEventStore,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
    ProjectDeliveryIntake,
)
from ai_software_engineer.team_view.models import ScopeView, TaskView
from ai_software_engineer.team_view.reader import (
    _CandidateBranchCache,
    _EvaluationEventCache,
    _ModelRouteAttemptCache,
    _Native,
    _TaskReadSnapshot,
)


def _event(number: int, *, task_id: str = "task_snapshot") -> CaseStartedEvent:
    return CaseStartedEvent(
        event_id=f"evalevt_snapshot_{number}",
        case_id="case_snapshot",
        task_id=task_id,
        occurred_at=datetime(2026, 10, 9, tzinfo=UTC) + timedelta(seconds=number),
        base_revision="a" * 40,
        model_id="test_model",
        prompt_version="v0.1",
        spec_version="v0.1",
        test_entrypoints=("pytest",),
    )


def test_evaluation_cache_reads_each_event_once_and_keeps_a_finite_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = FileEvaluationEventStore(tmp_path / "evaluations")
    first, other = _event(1), _event(2, task_id="task_other")
    writer.append(first)
    writer.append(other)
    original = FileEvaluationEventStore.get
    calls: list[str] = []

    def get(store: FileEvaluationEventStore, event_id: str) -> EvaluationEvent:
        calls.append(event_id)
        return original(store, event_id)

    cache = _EvaluationEventCache()
    with monkeypatch.context() as patch:
        patch.setattr(FileEvaluationEventStore, "get", get)
        assert cache.events(tmp_path / "evaluations") == (first, other)
        assert cache.events(tmp_path / "evaluations") == (first, other)
    assert calls == [first.event_id, other.event_id]

    later = _event(3)
    writer.append(later)
    assert cache.events(tmp_path / "evaluations") == (first, other)
    assert _EvaluationEventCache().events(tmp_path / "evaluations") == (first, other, later)


@pytest.mark.parametrize("change", ["body", "symlink"])
def test_new_evaluation_cache_rechecks_event_digest_and_path(tmp_path: Path, change: str) -> None:
    root = tmp_path / "evaluations"
    writer = FileEvaluationEventStore(root)
    event = _event(1)
    writer.append(event)
    assert _EvaluationEventCache().events(root) == (event,)
    path = root / f"{event.event_id}.json"
    if change == "body":
        path.write_bytes(path.read_bytes().replace(b"test_model", b"fake_model"))
    else:
        external = tmp_path / "external.json"
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
    with pytest.raises((EvaluationEventCorruption, ValueError)):
        _EvaluationEventCache().events(root)


def _native_and_base(tmp_path: Path) -> tuple[_Native, TaskView]:
    now = datetime.now(UTC)
    intake = ProjectDeliveryIntake.create(
        delivery_id="delivery_task_snapshot",
        repository_id="repository_task_snapshot",
        repository_root=str(tmp_path / "repository"),
        title="Task snapshot",
        requirement="Preserve independently verified history.",
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
    native = _Native(checkpoint, intake, tmp_path / "sidecar", (checkpoint,), "team_snapshot")
    base = TaskView(
        id=intake.delivery_id,
        project_id="project_snapshot",
        request_id="delivery_multi_snapshot",
        title=intake.title,
        scope=ScopeView(root=intake.repository_root, selected_paths=(".",)),
        status=checkpoint.stage,
        checkpoint_stage=checkpoint.stage,
        terminal=False,
        last_activity=now,
        next_action="Prepare the repository",
    )
    return native, base


def test_task_projection_reuses_only_exact_scope_base_and_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native, base = _native_and_base(tmp_path)
    calls: list[str] = []
    cursor = cast(DictCursor, object())
    snapshot = _TaskReadSnapshot(cursor, _ModelRouteAttemptCache(), _CandidateBranchCache())

    def read(
        source: _Native, current_cursor: DictCursor, view: TaskView, **kwargs: object
    ) -> TaskView:
        assert current_cursor is cursor
        calls.append(source.checkpoint.checkpoint_sha256)
        return view

    monkeypatch.setattr("ai_software_engineer.team_view.reader._read_task_details", read)
    assert snapshot.read(native, base) == base
    assert snapshot.read(native, base) == base
    assert len(calls) == 1

    other_scope = base.model_copy(update={"project_id": "project_other"})
    assert snapshot.read(native, other_scope) == other_scope
    assert len(calls) == 2
    changed_checkpoint = ProjectDeliveryCheckpoint.create(
        **{
            **native.checkpoint.to_wire(),
            "checkpoint_sha256": "0" * 64,
            "sequence": 2,
            "previous_checkpoint_sha256": native.checkpoint.checkpoint_sha256,
        }
    )
    changed_native = _Native(
        changed_checkpoint,
        native.intake,
        native.sidecar,
        (*native.history, changed_checkpoint),
        native.team_id,
    )
    assert snapshot.read(changed_native, base) == base
    assert len(calls) == 3
    fresh = _TaskReadSnapshot(cursor, _ModelRouteAttemptCache(), _CandidateBranchCache())
    assert fresh.read(native, base) == base
    assert len(calls) == 4
