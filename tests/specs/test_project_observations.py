"""Ordinary delivery discoveries are proposals, not self-approved memory or verdicts."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain.artifact import (
    Artifact,
    ProjectObservation,
    validate_artifact,
)
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.context import snapshot_from_sources
from ai_software_engineer.knowledge.models import (
    KnowledgeReadRequest,
    KnowledgeSearchRequest,
    KnowledgeSnapshot,
)
from ai_software_engineer.knowledge.retrieval import MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge.skills import KnowledgeSkillRegistry
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.knowledge_selection import effective_project_knowledge_paths
from ai_software_engineer.learning import (
    DecideLearningProposal,
    LearningDecisionAction,
    LearningError,
    LearningProposal,
    LearningTarget,
    LearningTrigger,
    ProjectLearningStore,
)
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.contracts.test_json_schema_contracts import _assert_invalid, _assert_valid
from tests.domain.factories import (
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_review_artifact,
)
from tests.knowledge.test_retrieval_contract import binding
from tests.specs.test_learning import NOW


@pytest.mark.parametrize(
    "factory", (make_implementation_artifact, make_qa_artifact, make_review_artifact)
)
def test_observations_bind_report_evidence_without_changing_legacy_bytes(
    factory: Callable[[], Artifact],
) -> None:
    original = factory()
    original_wire = original.to_wire()
    original_content = original_wire["content"]
    assert isinstance(original_content, dict)
    assert "project_observations" not in original_content
    assert validate_artifact(original_wire, original.kind).to_wire() == original_wire
    observation = ProjectObservation(
        observation_id="refund_identity",
        title="Refund identity",
        fact="Refunds use the original payment ID.",
        applicability="Refund processing in this repository, not other payment providers.",
        evidence_ids=(original.evidence[0].evidence_id,),
    )
    content = original.content.model_copy(update={"project_observations": (observation,)})
    reported = original.model_copy(update={"content": content})
    validated = validate_artifact(reported.to_wire(), original.kind)
    _assert_valid(validated.to_wire(), f"{original.kind.value}.schema.json")
    invalid = observation.model_copy(update={"evidence_ids": ("ev_invented",)})
    with pytest.raises(ValueError, match="unknown Evidence"):
        validate_artifact(
            reported.model_copy(
                update={"content": content.model_copy(update={"project_observations": (invalid,)})}
            ).to_wire(),
            original.kind,
        )


def test_observation_requires_bounded_nonempty_evidence() -> None:
    with pytest.raises(ValueError):
        ProjectObservation(
            observation_id="empty",
            title="No evidence",
            fact="Assumption",
            applicability="All projects",
            evidence_ids=(),
        )


@pytest.mark.parametrize("role", tuple(TeamRole))
def test_requirement_a_discovery_needs_approval_before_requirement_b_can_retrieve(
    tmp_path: Path, role: TeamRole
) -> None:
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_ai", name="Team")
    project = team.project_registry().register(project_id="project_payments", name="Payments")
    code = tmp_path / "code"
    code.mkdir()
    repository = project.repository_registry().register(code)
    artifacts = FileArtifactStore(repository.directory("artifacts"))
    artifacts.put(seal_artifact(make_plan_artifact(), validated_at=NOW))
    original = make_implementation_artifact()
    observation = ProjectObservation(
        observation_id="refund_identity",
        title="Refund identity",
        fact="Refunds use the original payment ID. token=never-publish-this-value",
        applicability="Refund processing in the payments repository.",
        evidence_ids=(original.evidence[0].evidence_id,),
    )
    artifact = seal_artifact(
        original.model_copy(
            update={
                "content": original.content.model_copy(
                    update={"project_observations": (observation,)}
                )
            }
        ),
        validated_at=NOW,
    )
    artifacts.put(artifact)
    store = ProjectLearningStore(project)
    (view,) = store.collect(collected_at=NOW)
    assert store.collect(collected_at=NOW + timedelta(days=1)) == (view,)
    proposal = view.proposal
    assert proposal.trigger is LearningTrigger.PROJECT_OBSERVATION
    assert proposal.suggested_target is LearningTarget.KNOWLEDGE
    assert "never-publish-this-value" not in proposal.model_dump_json()
    _assert_valid(proposal.to_wire(), "learning-proposal.schema.json")
    mismatched = proposal.to_wire() | {"trigger": "KNOWLEDGE_RESOLUTION"}
    with pytest.raises(ValueError, match="trigger and evidence"):
        LearningProposal.model_validate(mismatched)
    _assert_invalid(mismatched, "learning-proposal.schema.json")
    assert "Observed failure" not in proposal.as_markdown()
    assert effective_project_knowledge_paths(project) == ()
    foreign = team.project_registry().register(project_id="project_other", name="Other")
    assert ProjectLearningStore(foreign).list() == ()
    with pytest.raises(LearningError):
        ProjectLearningStore(foreign).decide(
            proposal.proposal_id,
            DecideLearningProposal(
                proposal_sha256=proposal.proposal_sha256,
                action=LearningDecisionAction.APPROVE,
                target=LearningTarget.KNOWLEDGE,
                operator_id="owner",
                rationale="Approve scoped background.",
            ),
        )

    def snapshot(requirement: str) -> KnowledgeSnapshot:
        return snapshot_from_sources(
            team_id=team.manifest.team_id,
            project_id=project.manifest.project_id,
            requirement_id=requirement,
            repository_ids=(repository.repository_id,),
            sources=tuple(
                (repository.repository_id, source)
                for source in project.knowledge_sources(effective_project_knowledge_paths(project))
            ),
        )

    historical = snapshot("requirement_original")
    approval = DecideLearningProposal(
        proposal_sha256=proposal.proposal_sha256,
        action=LearningDecisionAction.APPROVE,
        target=LearningTarget.KNOWLEDGE,
        operator_id="owner",
        rationale="Approve scoped background, not a delivery verdict.",
    )
    artifact_path = repository.directory("artifacts") / f"{artifact.artifact_id}.json"
    saved = artifact_path.read_bytes()
    artifact_path.write_text("{}")
    with pytest.raises(LearningError, match="source cannot be trusted"):
        store.decide(proposal.proposal_id, approval, decided_at=NOW)
    assert store.list()[0].authorization is None
    artifact_path.write_bytes(saved)
    with pytest.raises(LearningError, match="exact proposal"):
        store.decide(
            proposal.proposal_id,
            approval.model_copy(update={"proposal_sha256": "0" * 64}),
            decided_at=NOW,
        )
    store.decide(proposal.proposal_id, approval, decided_at=NOW)
    future = snapshot("requirement_future")
    bound = binding(future, role)
    skills = KnowledgeSkillRegistry(
        bound, future, MarkdownKnowledgeRetrieval(), KnowledgeRecordStore(tmp_path / "run")
    )
    found = skills.search_knowledge(
        KnowledgeSearchRequest(binding=bound, operation_id="search", query="original payment")
    )
    assert found.hits
    read = skills.read_knowledge(
        KnowledgeReadRequest(
            binding=bound,
            operation_id="read",
            search_evidence_id=found.evidence_id,
            citation=found.hits[0].citation,
        )
    )
    assert read.chunk is not None
    assert "original payment ID" in read.chunk.content
    assert MarkdownKnowledgeRetrieval().search(historical, "original payment") == ()
    assert artifacts.get(artifact.artifact_id) == artifact
