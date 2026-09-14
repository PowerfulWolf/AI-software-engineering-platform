"""Delivery failures become evidence-backed proposals, never silent policy changes."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain.artifact import Finding
from ai_software_engineer.domain.enums import (
    FindingSeverity,
    QaCriterionStatus,
    QaReportStatus,
    QaTestStatus,
)
from ai_software_engineer.learning import (
    DecideLearningProposal,
    LearningDecisionAction,
    LearningError,
    LearningTarget,
    ProjectLearningStore,
)
from ai_software_engineer.spec_documents import ProjectSpecDocumentStore
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.domain.factories import (
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def _project_with_failure(tmp_path: Path):
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_learn", name="Learn")
    project = team.project_registry().register(project_id="project_learn", name="Learn")
    code = tmp_path / "code"
    code.mkdir()
    repository = project.repository_registry().register(code)
    artifacts = FileArtifactStore(repository.directory("artifacts"))
    artifacts.put(seal_artifact(make_plan_artifact(), validated_at=NOW))
    artifacts.put(seal_artifact(make_implementation_artifact(), validated_at=NOW))
    template = make_qa_artifact()
    finding = Finding(
        finding_id="finding_missing_regression",
        severity=FindingSeverity.MAJOR,
        code="MISSING_REGRESSION",
        message="The edge case has no regression test.",
        evidence_ids=("ev_qa_tests",),
        recommendation="Require a regression test for every reproduced defect.",
    )
    qa = template.model_copy(
        update={
            "content": template.content.model_copy(
                update={
                    "status": QaReportStatus.FAIL,
                    "criteria_results": tuple(
                        item.model_copy(update={"status": QaCriterionStatus.FAIL})
                        for item in template.content.criteria_results
                    ),
                    "tests_run": tuple(
                        item.model_copy(update={"status": QaTestStatus.FAIL})
                        for item in template.content.tests_run
                    ),
                    "findings": (finding,),
                }
            )
        }
    )
    artifacts.put(seal_artifact(qa, validated_at=NOW))
    return project


def test_collect_is_idempotent_and_human_approval_publishes_active_spec(
    tmp_path: Path,
) -> None:
    project = _project_with_failure(tmp_path)
    store = ProjectLearningStore(project)

    first = store.collect(collected_at=NOW)
    replay = store.collect(collected_at=NOW)

    assert replay == first
    assert len(first) == 1
    proposal = first[0].proposal
    assert proposal.occurrence_count == 1
    assert proposal.evidence[0].artifact_id == "art_qa_001"
    assert ProjectSpecDocumentStore(project).active() == ()

    decided = store.decide(
        proposal.proposal_id,
        DecideLearningProposal(
            proposal_sha256=proposal.proposal_sha256,
            action=LearningDecisionAction.APPROVE,
            target=LearningTarget.SPEC,
            operator_id="human_owner",
            rationale="This failure should be prevented in future work.",
        ),
        decided_at=NOW,
    )

    assert decided.decision is not None
    assert decided.decision.published_uri is not None
    assert (
        project.root / "specs" / "learning" / proposal.proposal_id / "authorization.json"
    ).is_file()
    active = ProjectSpecDocumentStore(project).active()
    assert len(active) == 1
    assert "regression test" in active[0].body_markdown


def test_rejected_learning_does_not_publish_project_memory(tmp_path: Path) -> None:
    project = _project_with_failure(tmp_path)
    store = ProjectLearningStore(project)
    proposal = store.collect(collected_at=NOW)[0].proposal

    view = store.decide(
        proposal.proposal_id,
        DecideLearningProposal(
            proposal_sha256=proposal.proposal_sha256,
            action=LearningDecisionAction.REJECT,
            target=LearningTarget.KNOWLEDGE,
            operator_id="human_owner",
            rationale="This is specific to one implementation and is not reusable.",
        ),
        decided_at=NOW,
    )

    assert view.decision is not None and view.decision.published_uri is None
    assert not (project.root / "knowledge" / "selection.json").exists()


def test_collection_fails_closed_when_source_artifact_is_corrupt(tmp_path: Path) -> None:
    project = _project_with_failure(tmp_path)
    repository = project.repository_registry().discover()[0]
    artifact = repository.directory("artifacts") / "art_qa_001.json"
    artifact.write_text("{}")

    with pytest.raises(LearningError, match="cannot be trusted"):
        ProjectLearningStore(project).collect(collected_at=NOW)


def test_approved_publication_can_resume_after_authorization_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project_with_failure(tmp_path)
    store = ProjectLearningStore(project)
    proposal = store.collect(collected_at=NOW)[0].proposal
    command = DecideLearningProposal(
        proposal_sha256=proposal.proposal_sha256,
        action=LearningDecisionAction.APPROVE,
        target=LearningTarget.SPEC,
        operator_id="human_owner",
        rationale="Approve this exact prevention rule.",
    )
    publish = ProjectLearningStore._publish

    def interrupt_publication(*_args: object) -> str:
        raise OSError("simulated interruption")

    monkeypatch.setattr(ProjectLearningStore, "_publish", interrupt_publication)
    with pytest.raises(LearningError, match="could not be completed"):
        store.decide(proposal.proposal_id, command, decided_at=NOW)

    directory = project.root / "specs" / "learning" / proposal.proposal_id
    assert (directory / "authorization.json").is_file()
    assert not (directory / "decision.json").exists()

    monkeypatch.setattr(ProjectLearningStore, "_publish", publish)
    completed = store.decide(proposal.proposal_id, command, decided_at=NOW)

    assert completed.authorization is not None
    assert completed.decision is not None
    assert ProjectSpecDocumentStore(project).active()
