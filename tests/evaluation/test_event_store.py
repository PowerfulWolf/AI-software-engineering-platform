"""Immutable Evaluation event persistence through public store seams."""

import json
from pathlib import Path

import pytest

from ai_software_engineer.evaluation import (
    EvaluationEventConflict,
    EvaluationEventCorruption,
    EvaluationEventNotFound,
    FileEvaluationEventStore,
    InMemoryEvaluationEventStore,
)
from tests.evaluation.factories import make_agent_run, make_case_started


@pytest.mark.parametrize("store_kind", ["memory", "file"])
def test_store_round_trips_exact_replay_and_orders_case_events(
    tmp_path: Path, store_kind: str
) -> None:
    store = (
        InMemoryEvaluationEventStore()
        if store_kind == "memory"
        else FileEvaluationEventStore(tmp_path / "evaluation-events")
    )
    started = make_case_started()
    run = make_agent_run()

    assert store.append(run) == run
    assert store.append(started) == started
    assert store.append(started) == started

    assert store.get(started.event_id) == started
    assert store.list_for_case(started.case_id) == (started, run)


@pytest.mark.parametrize("store_kind", ["memory", "file"])
def test_store_rejects_changed_payload_for_existing_event_id(
    tmp_path: Path, store_kind: str
) -> None:
    store = (
        InMemoryEvaluationEventStore()
        if store_kind == "memory"
        else FileEvaluationEventStore(tmp_path / "evaluation-events")
    )
    original = make_agent_run()
    changed = original.model_copy(update={"duration_ms": 999})
    store.append(original)

    with pytest.raises(EvaluationEventConflict):
        store.append(changed)

    assert store.get(original.event_id) == original


def test_file_store_rejects_invalid_lookup_and_persisted_tampering(tmp_path: Path) -> None:
    root = tmp_path / "evaluation-events"
    store = FileEvaluationEventStore(root)
    event = make_case_started()
    store.append(event)

    with pytest.raises(EvaluationEventNotFound):
        store.get("../escape")

    path = root / f"{event.event_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["event"]["task_id"] = "task_other_001"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationEventCorruption):
        store.get(event.event_id)
