"""Trace assembly from the three durable organization-owned stores."""

from pathlib import Path

import pytest

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.evaluation import (
    AdrStatus,
    EvaluationEngine,
    EvaluationTraceBuilder,
    EvaluationTraceContractError,
    EvaluationTraceNotFound,
    FileEvaluationEventStore,
)
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import NOW, make_task
from tests.evaluation.factories import make_case_started
from tests.evaluation.test_metrics import _trace


def test_trace_builder_loads_sqlite_events_and_sealed_artifacts(tmp_path: Path) -> None:
    expected = _trace()
    events = FileEvaluationEventStore(tmp_path / "evaluation-events")
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    with SqliteTaskRepository(tmp_path / "state.sqlite3") as repository:
        initial = make_task().model_copy(update={"base_ref": "a" * 40})
        repository.create(initial)
        repository.record_attempt(initial.id, 1)
        for state_event in expected.state_events:
            repository.append_event(state_event)
        for artifact in expected.artifacts:
            artifacts.put(seal_artifact(artifact, validated_at=NOW))
        for evaluation_event in expected.evaluation_events:
            events.append(evaluation_event)

        trace = EvaluationTraceBuilder(
            repository=repository,
            artifact_store=artifacts,
            event_store=events,
        ).build(expected.case.case_id)

    assert trace.task == expected.task
    assert trace.state_events == expected.state_events
    assert tuple(item.artifact_id for item in trace.artifacts) == (
        "art_impl_001",
        "art_plan_001",
        "art_qa_001",
        "art_review_001",
    )
    assert EvaluationEngine().evaluate((trace,)).cases[0].adr.status is AdrStatus.ELIGIBLE


def test_trace_builder_requires_one_case_start_event(tmp_path: Path) -> None:
    events = FileEvaluationEventStore(tmp_path / "evaluation-events")
    with SqliteTaskRepository(tmp_path / "state.sqlite3") as repository:
        builder = EvaluationTraceBuilder(
            repository=repository,
            artifact_store=FileArtifactStore(tmp_path / "artifacts"),
            event_store=events,
        )

        with pytest.raises(EvaluationTraceNotFound):
            builder.build("case_missing_001")


def test_trace_builder_rejects_case_base_that_differs_from_task(tmp_path: Path) -> None:
    events = FileEvaluationEventStore(tmp_path / "evaluation-events")
    started = make_case_started().model_copy(update={"base_revision": "c" * 40})
    events.append(started)
    with SqliteTaskRepository(tmp_path / "state.sqlite3") as repository:
        repository.create(make_task().model_copy(update={"base_ref": "a" * 40}))
        builder = EvaluationTraceBuilder(
            repository=repository,
            artifact_store=FileArtifactStore(tmp_path / "artifacts"),
            event_store=events,
        )

        with pytest.raises(EvaluationTraceContractError, match="base_revision"):
            builder.build(started.case_id)
