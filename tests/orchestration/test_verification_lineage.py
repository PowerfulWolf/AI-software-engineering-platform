"""Same candidate bytes never make a replaced role verdict current again."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.domain import (
    AgentRole,
    Finding,
    FindingSeverity,
    ImplementationReportArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
    ReviewVerdict,
    Task,
    TaskStatus,
)
from ai_software_engineer.domain.agent import DELIVERY_ROLE_INPUTS
from ai_software_engineer.orchestration import (
    FileRunContextBuilder,
    RetryDeliveryResult,
    RetryingOrchestrator,
)
from ai_software_engineer.store import SqliteTaskRepository
from tests.orchestration.test_retry import AttemptIdentityFactory, ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions, _task

_CANDIDATE = "b" * 40


class _SameCandidateAdapter(ScriptedAdapter):
    """Independent roles revise their reports while Coder preserves candidate bytes."""

    def run(self, request: AgentRequest) -> AgentResult:
        result = super().run(request)
        artifact = result.artifact
        assert artifact is not None
        if isinstance(artifact, ImplementationReportArtifact):
            artifact = artifact.model_copy(
                update={
                    "source_revision": _CANDIDATE,
                    "content": artifact.content.model_copy(update={"commit_sha": _CANDIDATE}),
                }
            )
        if isinstance(artifact, (QaReportArtifact, ReviewReportArtifact)):
            assert request.expected_parent_artifact_ids is not None
            assert request.expected_supersedes_by_kind is not None
            artifact = artifact.model_copy(
                update={
                    "parent_artifact_ids": request.expected_parent_artifact_ids,
                    "supersedes": request.expected_supersedes_by_kind[artifact.kind],
                }
            )
        if isinstance(artifact, ReviewReportArtifact) and request.attempt == 1:
            artifact = artifact.model_copy(
                update={
                    "content": artifact.content.model_copy(
                        update={
                            "verdict": ReviewVerdict.REJECT,
                            "findings": (
                                Finding(
                                    finding_id="finding_review_missing_implementation_explanation",
                                    severity=FindingSeverity.MAJOR,
                                    message=(
                                        "The implementation report does not explain "
                                        "the acceptance evidence."
                                    ),
                                    evidence_ids=(artifact.evidence[0].evidence_id,),
                                    recommendation=(
                                        "Explain the existing implementation "
                                        "without changing candidate bytes."
                                    ),
                                ),
                            ),
                        }
                    )
                }
            )
        return result.model_copy(update={"artifact": artifact})


class _CrashAtSecondVerification(RetryingOrchestrator):
    crash_at: TaskStatus | None = None

    def _transition(
        self,
        task: Task,
        to_status: TaskStatus,
        *,
        reason: str,
        source_revision: str,
        attempt: int,
        artifact_ids: tuple[str, ...] = (),
    ) -> tuple[Task, str]:
        result = super()._transition(
            task,
            to_status,
            reason=reason,
            source_revision=source_revision,
            attempt=attempt,
            artifact_ids=artifact_ids,
        )
        if attempt == 2 and to_status is self.crash_at:
            raise KeyboardInterrupt("crash after the durable same-SHA verification checkpoint")
        return result


def _runner(
    root: Path,
    repository: SqliteTaskRepository,
    adapter: _SameCandidateAdapter,
    *,
    crash_at: TaskStatus | None = None,
) -> _CrashAtSecondVerification:
    runner = _CrashAtSecondVerification(
        repository=repository,
        artifact_store=FileArtifactStore(root / "artifacts"),
        context_builder=FileRunContextBuilder(root / "project"),
        agent_adapter=adapter,
        agent_definitions={
            role: definition.model_copy(update={"input_artifacts": DELIVERY_ROLE_INPUTS[role]})
            for role, definition in _definitions().items()
        },
        identities=AttemptIdentityFactory(),
        clock=_clock,
    )
    runner.crash_at = crash_at
    return runner


@pytest.mark.parametrize("restart_at", [None, TaskStatus.QA, TaskStatus.REVIEW])
def test_replaced_implementation_and_qa_require_fresh_review_even_at_the_same_candidate(
    tmp_path: Path,
    restart_at: TaskStatus | None,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    task = _task(project)
    database = tmp_path / "state.sqlite3"
    first = _SameCandidateAdapter()
    old_bytes: dict[Path, bytes] = {}
    with SqliteTaskRepository(database) as repository:
        repository.create(task)
        runner = _runner(tmp_path, repository, first, crash_at=restart_at)
        if restart_at is None:
            outcome = runner.run_task(task.id)
        else:
            with pytest.raises(KeyboardInterrupt, match="durable same-SHA"):
                runner.run_task(task.id)
            assert repository.get(task.id).status is restart_at
            old_bytes = {
                path: path.read_bytes() for path in (tmp_path / "artifacts").rglob("*.json")
            }
            outcome = None
    second = _SameCandidateAdapter()
    if restart_at is not None:
        with SqliteTaskRepository(database) as repository:
            outcome = _runner(tmp_path, repository, second).run_task(task.id)
    assert isinstance(outcome, RetryDeliveryResult)
    assert outcome.task.status is TaskStatus.DONE
    assert outcome.task.attempts == 2
    assert outcome.candidate_revision == _CANDIDATE
    assert outcome.artifact_ids == (
        "art_plan_001",
        "art_impl_002",
        "art_qa_002",
        "art_review_002",
    )
    requests = (*first.requests, *second.requests)
    assert tuple(request.role for request in requests) == (
        AgentRole.ORCHESTRATOR,
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    )
    assert len({request.run_id for request in requests}) == len(requests)
    assert len({request.context_manifest_id for request in requests}) == len(requests)
    qa2 = next(
        request for request in requests if request.role is AgentRole.QA and request.attempt == 2
    )
    review2 = next(
        request
        for request in requests
        if request.role is AgentRole.REVIEWER and request.attempt == 2
    )
    assert qa2.source_revision == review2.source_revision == _CANDIDATE
    assert qa2.expected_parent_artifact_ids == ("art_impl_002",)
    assert review2.expected_parent_artifact_ids == ("art_qa_002",)
    assert "art_qa_001" in qa2.input_artifact_ids
    assert "art_review_001" in review2.input_artifact_ids
    store = FileArtifactStore(tmp_path / "artifacts")
    old_review = store.get("art_review_001")
    new_review = store.get("art_review_002")
    new_qa = store.get("art_qa_002")
    new_implementation = store.get("art_impl_002")
    assert isinstance(old_review, ReviewReportArtifact)
    assert isinstance(new_review, ReviewReportArtifact)
    assert isinstance(new_qa, QaReportArtifact)
    assert isinstance(new_implementation, ImplementationReportArtifact)
    assert old_review.content.verdict is ReviewVerdict.REJECT
    assert new_review.content.verdict is ReviewVerdict.APPROVE
    assert new_implementation.supersedes == "art_impl_001"
    assert new_qa.supersedes == "art_qa_001"
    assert new_review.supersedes == "art_review_001"
    assert new_review.parent_artifact_ids == (new_qa.artifact_id,)
    assert new_qa.parent_artifact_ids == (new_implementation.artifact_id,)
    assert (
        len(
            {
                new_implementation.producer.agent_id,
                new_qa.producer.agent_id,
                new_review.producer.agent_id,
            }
        )
        == 3
    )
    assert all(path.read_bytes() == content for path, content in old_bytes.items())
    with SqliteTaskRepository(database) as repository:
        events = repository.list_events(task.id)
    assert tuple(event.to_status for event in events) == (
        TaskStatus.PLANNING,
        TaskStatus.IMPLEMENTING,
        TaskStatus.QA,
        TaskStatus.REVIEW,
        TaskStatus.IMPLEMENTING,
        TaskStatus.QA,
        TaskStatus.REVIEW,
        TaskStatus.DONE,
    )
    assert events[-1].artifact_ids == outcome.artifact_ids
