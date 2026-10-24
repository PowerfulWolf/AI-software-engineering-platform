"""Private native counters belong to exact verified continuation deletion scope."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.multi_directory.purge_state import (
    StateDeletionScope,
    task_state_directories,
)
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.native_observation import NativeExecutionObservation
from ai_software_engineer.recovery.models import digest
from tests.domain.factories import make_task
from tests.orchestration.test_continuation_records import NOW, make_receipt
from tests.orchestration.test_native_continuation import claim
from tests.orchestration.test_native_observation_store import output_observation


def _records(tmp_path: Path) -> tuple[Path, FileContinuationStore, StateDeletionScope]:
    """Use real immutable writers and typed synthetic facts without an OS execution."""
    receipt = make_receipt(tmp_path)
    task = make_task().model_copy(
        update={"id": receipt.request.task_id, "repository": str(tmp_path)}
    )
    start = ExecutionCaptureStart.create(
        scope=receipt.scope,
        request=receipt.request,
        claim=claim(task, receipt.request.attempt),
        task_intent_sha256=receipt.task_intent_sha256,
        task_revision=receipt.task_revision,
        policy_sha256=receipt.policy_sha256,
        worktree_path=str(tmp_path / "worktree"),
        inventory_before=receipt.inventory_before,
        started_at=NOW - timedelta(seconds=2),
    )
    stop = ExecutionCaptureStop.create(
        task_id=task.id,
        run_id=receipt.request.run_id,
        capture_start_sha256=start.start_sha256,
        process_stop=receipt.process_stop,
        output_present=False,
        cause=receipt.cause,
        original_error_code=receipt.original_error_code,
    )
    sidecar = tmp_path / "sidecar"
    parent = sidecar / "state/continuations"
    parent.mkdir(parents=True)
    store = FileContinuationStore.initialize(parent / task.id, task_id=task.id)
    store.put_capture_start(start)
    store.put_capture_stop(stop)
    store.put_native_observation(
        NativeExecutionObservation.from_capture(
            start=start,
            stop=stop,
            output=output_observation(),
            recorded_at=stop.process_stop.stopped_at,
        )
    )
    expected = StateDeletionScope(
        team_id=receipt.scope.team_id,
        project_id=receipt.scope.project_id,
        repository_id=receipt.scope.repository_id,
        repository_root=str(tmp_path),
        requirement_ids=frozenset({receipt.scope.requirement_id}),
        task_ids=frozenset({task.id}),
    )
    return sidecar, store, expected


def test_native_observation_joins_complete_owned_directory_and_preserves_foreign_task(
    tmp_path: Path,
) -> None:
    sidecar, store, expected = _records(tmp_path)
    root = sidecar / "state/continuations" / next(iter(expected.task_ids))
    foreign = root.parent / "task_foreign_001"
    foreign.mkdir()
    untouched = foreign / "unknown.json"
    untouched.write_text("foreign Task data")
    before = {path.name: path.read_bytes() for path in root.iterdir()}

    assert task_state_directories(sidecar, expected) == (root,)
    assert any(name.startswith("native-observation-") for name in before)
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    assert untouched.read_text() == "foreign Task data"
    assert store.receipts_for_task(next(iter(expected.task_ids))) == ()
    assert store.admissions_for_task(next(iter(expected.task_ids))) == ()

    (root / "unknown.json").write_text("{}")
    with pytest.raises(ValueError, match="unsupported continuation record"):
        task_state_directories(sidecar, expected)
    assert untouched.exists() and all((root / name).exists() for name in before)


@pytest.mark.parametrize(
    "field", ["team_id", "project_id", "repository_id", "repository_root", "requirement_ids"]
)
def test_native_observation_continuation_requires_exact_deletion_scope(
    tmp_path: Path, field: str
) -> None:
    sidecar, _, expected = _records(tmp_path)
    foreign = expected.model_copy(
        update={field: frozenset({"foreign"}) if field == "requirement_ids" else "foreign"}
    )
    with pytest.raises(ValueError, match="differs"):
        task_state_directories(sidecar, foreign)


@pytest.mark.parametrize("tamper", ["filename", "task_id", "scope", "capture_stop"])
def test_native_observation_filename_body_and_original_stop_are_revalidated_before_deletion(
    tmp_path: Path, tamper: str
) -> None:
    sidecar, store, expected = _records(tmp_path)
    root = sidecar / "state/continuations" / next(iter(expected.task_ids))
    path = next(root.glob("native-observation-*.json"))
    run_id = path.stem.removeprefix("native-observation-")
    read = store.native_observation(run_id)
    assert read.record is not None

    if tamper == "filename":
        path.rename(root / "native-observation-run_foreign_001.json")
    elif tamper == "capture_stop":
        original_stop = store.capture_stop(run_id)
        changed_stop = ExecutionCaptureStop.create(
            **{**original_stop.to_wire(), "output_present": True}
        )
        (root / f"capture-stop-{run_id}.json").write_text(
            json.dumps({"record": changed_stop.to_wire(), "sha256": digest(changed_stop.to_wire())})
        )
    else:
        wire = read.record.to_wire()
        if tamper == "task_id":
            wire["task_id"] = "task_foreign_001"
        else:
            wire["scope"] = {
                **read.record.scope.to_wire(),
                "requirement_id": "delivery_foreign_001",
            }
        wire["observation_sha256"] = digest(
            {key: value for key, value in wire.items() if key != "observation_sha256"}
        )
        path.write_text(json.dumps({"record": wire, "sha256": digest(wire)}))

    before = {item.name: item.read_bytes() for item in root.iterdir()}
    with pytest.raises(ContinuationRejected):
        task_state_directories(sidecar, expected)
    assert {item.name: item.read_bytes() for item in root.iterdir()} == before
