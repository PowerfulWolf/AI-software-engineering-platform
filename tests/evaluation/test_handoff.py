"""Human-readable DONE/BLOCKED handoff bundles through public seams."""

from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.evaluation import (
    FileHandoffStore,
    HandoffBuilder,
    HandoffContractError,
    HandoffCorruption,
    HandoffNotReady,
    HandoffOutcome,
)
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import CANDIDATE_SHA, NOW, make_task
from tests.evaluation.test_metrics import _trace


def _persist_trace(
    tmp_path: Path, *, terminal: TaskStatus = TaskStatus.DONE
) -> tuple[SqliteTaskRepository, FileArtifactStore]:
    expected = _trace(terminal=terminal, regression=None)
    repository = SqliteTaskRepository(tmp_path / "state.sqlite3")
    initial = make_task().model_copy(update={"base_ref": "a" * 40})
    repository.create(initial)
    repository.record_attempt(initial.id, 1)
    for event in expected.state_events:
        repository.append_event(event)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    selected = expected.artifacts if terminal is TaskStatus.DONE else expected.artifacts[:3]
    for artifact in selected:
        artifacts.put(seal_artifact(artifact, validated_at=NOW))
    return repository, artifacts


def test_done_handoff_contains_candidate_gates_evidence_and_review_argv(tmp_path: Path) -> None:
    repository, artifacts = _persist_trace(tmp_path)
    try:
        bundle = HandoffBuilder(
            repository=repository,
            artifact_store=artifacts,
            clock=lambda: NOW + timedelta(days=2),
        ).build("task_domain_001")
    finally:
        repository.close()

    assert bundle.outcome is HandoffOutcome.DONE
    assert bundle.candidate_revision == CANDIDATE_SHA
    assert bundle.qa_status == "PASS"
    assert bundle.review_verdict == "APPROVE"
    assert tuple(item.artifact_id for item in bundle.artifacts) == (
        "art_plan_001",
        "art_impl_001",
        "art_qa_001",
        "art_review_001",
    )
    assert bundle.criteria[0].status == "PASS"
    assert bundle.criteria[0].evidence_ids == ("ev_qa_tests",)
    assert bundle.changed_files[0].path == "src/ai_software_engineer/domain/task.py"
    assert any(evidence.evidence_id == "ev_review_diff" for evidence in bundle.evidence)
    assert bundle.review_commands[0].argv == (
        "git",
        "diff",
        "--stat",
        "--end-of-options",
        f"{'a' * 40}..{CANDIDATE_SHA}",
        "--",
    )


def test_blocked_handoff_explains_reason_and_safe_next_action(tmp_path: Path) -> None:
    repository, artifacts = _persist_trace(tmp_path, terminal=TaskStatus.BLOCKED)
    try:
        bundle = HandoffBuilder(
            repository=repository,
            artifact_store=artifacts,
            clock=lambda: NOW + timedelta(days=2),
        ).build("task_domain_001")
    finally:
        repository.close()

    assert bundle.outcome is HandoffOutcome.BLOCKED
    assert bundle.blocked_reason == "evaluation fixture"
    assert bundle.candidate_revision == CANDIDATE_SHA
    assert bundle.review_verdict is None
    assert bundle.next_actions
    assert "terminal record" in bundle.next_actions[-1]


def test_handoff_builder_rejects_non_terminal_task_and_broken_done_chain(
    tmp_path: Path,
) -> None:
    with SqliteTaskRepository(tmp_path / "new.sqlite3") as repository:
        repository.create(make_task())
        builder = HandoffBuilder(
            repository=repository,
            artifact_store=FileArtifactStore(tmp_path / "new-artifacts"),
            clock=lambda: NOW,
        )
        with pytest.raises(HandoffNotReady):
            builder.build("task_domain_001")

    repository, artifacts = _persist_trace(tmp_path / "broken")
    missing_review = Path(tmp_path / "broken" / "artifacts" / "art_review_001.json")
    missing_review.unlink()
    try:
        with pytest.raises(HandoffContractError, match="delivery chain"):
            HandoffBuilder(
                repository=repository,
                artifact_store=artifacts,
                clock=lambda: NOW,
            ).build("task_domain_001")
    finally:
        repository.close()


def test_handoff_store_preserves_first_observation_and_detects_markdown_tampering(
    tmp_path: Path,
) -> None:
    repository, artifacts = _persist_trace(tmp_path / "delivery")
    try:
        first = HandoffBuilder(
            repository=repository,
            artifact_store=artifacts,
            clock=lambda: NOW + timedelta(days=2),
        ).build("task_domain_001")
        replay = HandoffBuilder(
            repository=repository,
            artifact_store=artifacts,
            clock=lambda: NOW + timedelta(days=3),
        ).build("task_domain_001")
    finally:
        repository.close()
    assert replay.handoff_id == first.handoff_id
    store = FileHandoffStore(tmp_path / "handoffs")

    reference = store.put(first)
    replay_reference = store.put(replay)

    assert replay_reference == reference
    assert store.get(first.handoff_id) == first
    assert reference.markdown_path.read_text(encoding="utf-8").startswith(
        "# Handoff: Implement typed domain contracts"
    )

    reference.markdown_path.write_text("tampered", encoding="utf-8")
    with pytest.raises(HandoffCorruption):
        store.get(first.handoff_id)
