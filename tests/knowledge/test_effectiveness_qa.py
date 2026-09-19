"""Independent offline quality observations produced by real bounded consultations."""

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents.models import AgentUsage
from ai_software_engineer.agents.structured import StructuredModelResult
from ai_software_engineer.knowledge.agents import (
    KnowledgeConsultation,
    KnowledgeConsultationService,
    KnowledgeModelCall,
)
from ai_software_engineer.knowledge.context import snapshot_from_sources
from ai_software_engineer.knowledge.evaluation import (
    KnowledgeEvaluationObservation,
    KnowledgeEvaluationReport,
    evaluate_knowledge,
)
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGap,
    KnowledgeGapRaised,
    KnowledgeGapService,
    KnowledgeResolution,
    KnowledgeResolutionSource,
)
from ai_software_engineer.knowledge.index import KnowledgeIndexer
from ai_software_engineer.knowledge.models import (
    KnowledgeCitation,
    KnowledgeDocument,
    KnowledgeEvidence,
    KnowledgeReadRequest,
    KnowledgeSearchRequest,
    KnowledgeSnapshot,
    digest,
    text_digest,
)
from ai_software_engineer.knowledge.retrieval import MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge.skills import KnowledgeSkillRegistry
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.knowledge.workflow import WorkflowSkillEvidence
from ai_software_engineer.knowledge_documents import (
    ProjectKnowledgeDocumentStore,
    TeamKnowledgeDocumentStore,
)
from ai_software_engineer.knowledge_selection import (
    TeamKnowledgeSelectionStore,
    effective_project_knowledge_paths,
)
from ai_software_engineer.learning import (
    DecideLearningProposal,
    LearningDecisionAction,
    LearningTarget,
    ProjectLearningStore,
)
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.knowledge.test_consultation import Model
from tests.knowledge.test_gaps import Approval
from tests.knowledge.test_retrieval_contract import binding, document, snapshot


class CorpusModel:
    """Deterministic model fixture reasons only over actual READ evidence."""

    def __init__(self, *, choose_background: bool = False) -> None:
        self.choose_background = choose_background

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        payload: Mapping[str, object]
        if output_schema["title"] == "KnowledgeIntent":
            payload = {"queries": ["refund payment"]}
            input_tokens, duration_ms = 10, 3
        else:
            evidence = tuple(
                KnowledgeEvidence.model_validate(value)
                for value in cast(list[object], input_payload["knowledge_evidence"])
            )
            chunks = tuple(item.chunk for item in evidence if item.chunk is not None)
            input_tokens, duration_ms = 20 + 10 * len(chunks), 6 + 5 * len(chunks)
            specs = tuple(chunk for chunk in chunks if chunk.citation.scope == "spec")
            background = tuple(chunk for chunk in chunks if chunk.citation.scope != "spec")
            decisive = background if self.choose_background else specs or background
            if not decisive:
                payload = {"status": "GAP", "gap_question": "What is the refund policy?"}
            elif len({chunk.content for chunk in decisive}) > 1:
                payload = {
                    "status": "GAP",
                    "gap_question": "Which conflicting refund policy is authoritative?",
                    "gap_reason": "CONFLICT",
                }
            else:
                payload = {
                    "status": "SUFFICIENT",
                    "claims": [
                        {
                            "statement": decisive[0].content,
                            "citations": [decisive[0].citation.to_wire()],
                        }
                    ],
                }
        return StructuredModelResult(
            payload=payload,
            duration_ms=duration_ms,
            usage=AgentUsage(
                input_tokens=input_tokens, output_tokens=3, total_tokens=input_tokens + 3
            ),
            provider="fixture-provider",
            model="read-evidence-model-v1",
        )


def _observe(
    records: KnowledgeRecordStore,
    frozen: KnowledgeSnapshot,
    *,
    case: str,
    enabled: bool,
    expected: tuple[KnowledgeCitation, ...],
    gap_expected: bool,
    choose_background: bool = False,
) -> KnowledgeEvaluationObservation:
    bound = binding(frozen)
    service = KnowledgeConsultationService(
        CorpusModel(choose_background=choose_background), records
    )
    reported_gap = False
    try:
        receipt = service.consult(
            bound, frozen, {"requirement": "Implement refund payment policy"}, timeout_seconds=10
        )
    except KnowledgeGapRaised as error:
        reported_gap = True
        assert error.gap.binding == bound
        receipt = records.get("consultations", bound.run_id, KnowledgeConsultation)
    calls = tuple(records.get("model-calls", key, KnowledgeModelCall) for key in receipt.call_ids)
    assert len(calls) == 2
    assert {call.phase for call in calls} == {"intent", "assessment"}
    assert all(call.binding == bound for call in calls)
    assert all(
        call.call_id == digest(call.model_dump(mode="json", exclude={"call_id"})) for call in calls
    )
    assert {call.provider for call in calls} == {"fixture-provider"}
    assert {call.model for call in calls} == {"read-evidence-model-v1"}
    claims = receipt.assessment.claims
    actual = tuple(citation for claim in claims for citation in claim.citations)
    assert set(actual) <= set(receipt.manifest.citations)
    versions = tuple(
        f"{record.definition.name}:{record.definition.version}"
        for record in records.list("workflow-evidence", WorkflowSkillEvidence)
    )
    covered = int(bool(claims) and all(citation in expected for citation in actual))
    return KnowledgeEvaluationObservation(
        case_id=case,
        condition="ENABLED" if enabled else "DISABLED",
        source_revision=bound.source_revision,
        context_manifest_id=bound.context_manifest_id,
        snapshot_sha256=frozen.snapshot_sha256,
        skill_versions=versions,
        provider="fixture-provider",
        model="read-evidence-model-v1",
        expected_citations=expected,
        allowed_citations=receipt.manifest.citations,
        actual_citations=actual,
        decisive_claims=len(claims),
        supported_claims=sum(
            all(citation in expected for citation in claim.citations) for claim in claims
        ),
        gap_expected=gap_expected,
        gap_reported=reported_gap,
        acceptance_total=1,
        acceptance_covered=covered,
        qa_rejected=bool(claims) and not bool(covered),
        review_rejected=False,
        token_count=sum(call.usage.total_tokens for call in calls if call.usage is not None),
        latency_ms=sum(call.duration_ms for call in calls),
    )


def _persist_replay(
    root: Path, observations: tuple[KnowledgeEvaluationObservation, ...]
) -> KnowledgeEvaluationReport:
    report = evaluate_knowledge(observations)
    report.validate_integrity()
    KnowledgeRecordStore(root).put("evaluations", report.report_sha256, report)
    restored = KnowledgeRecordStore(root).get(
        "evaluations", report.report_sha256, KnowledgeEvaluationReport
    )
    assert evaluate_knowledge(restored.observations) == restored
    return restored


def test_enabled_disabled_pair_uses_actual_reads_gaps_and_model_call_costs(tmp_path: Path) -> None:
    frozen = snapshot(document())
    expected = tuple(hit.citation for hit in MarkdownKnowledgeRetrieval().search(frozen, "payment"))
    enabled = _observe(
        KnowledgeRecordStore(tmp_path / "enabled"),
        frozen,
        case="refund-policy",
        enabled=True,
        expected=expected,
        gap_expected=False,
    )
    disabled = _observe(
        KnowledgeRecordStore(tmp_path / "disabled"),
        snapshot(),
        case="refund-policy",
        enabled=False,
        expected=(),
        gap_expected=True,
    )
    assert enabled.actual_citations == expected
    assert disabled.actual_citations == () and disabled.gap_reported
    assert enabled.acceptance_covered == 1 and disabled.acceptance_covered == 0
    report = _persist_replay(tmp_path / "reports", (enabled, disabled))
    assert report.passed
    assert report.citation_precision == report.gap_recall == 1
    assert report.hallucination_rate == report.scope_leakage_rate == 0
    assert report.additional_tokens == enabled.token_count - disabled.token_count == 10
    assert report.additional_latency_ms == enabled.latency_ms - disabled.latency_ms == 5


def test_conflicting_reads_report_gap_without_inventing_a_winner(tmp_path: Path) -> None:
    first = document("# Refund\nPayment refund window is 5 days.")
    second = document("# Refund\nPayment refund window is 10 days.").model_copy(
        update={
            "document_id": "doc_conflict",
            "source_uri": "knowledge://project_payments/conflict",
        }
    )
    frozen = snapshot(first, second)
    records = KnowledgeRecordStore(tmp_path / "run")
    observed = _observe(
        records, frozen, case="conflict", enabled=True, expected=(), gap_expected=True
    )
    receipt = records.get("consultations", binding(frozen).run_id, KnowledgeConsultation)
    assert {citation.document_id for citation in receipt.manifest.citations} == {
        first.document_id,
        second.document_id,
    }
    assert receipt.assessment.gap_reason == "CONFLICT"
    assert observed.gap_reported and not observed.actual_citations
    assert _persist_replay(tmp_path / "reports", (observed,)).passed


@pytest.mark.parametrize("choose_background", (False, True))
def test_spec_background_distinction_is_measured_from_real_citations(
    tmp_path: Path, choose_background: bool
) -> None:
    background = document("# Payment refunds\nPrevious refunds used store credit.")
    spec = document("# Payment refunds\nRefunds MUST use original payment identity.").model_copy(
        update={"document_id": "spec_refund", "scope": "spec", "source_uri": "spec://refund/v1"}
    )
    frozen = snapshot(background, spec)
    expected = tuple(
        hit.citation
        for hit in MarkdownKnowledgeRetrieval().search(frozen, "payment")
        if hit.citation.scope == "spec"
    )
    observed = _observe(
        KnowledgeRecordStore(tmp_path / "run"),
        frozen,
        case="spec-vs-background",
        enabled=True,
        expected=expected,
        gap_expected=False,
        choose_background=choose_background,
    )
    assert {citation.scope for citation in observed.actual_citations} == {
        "project" if choose_background else "spec"
    }
    report = _persist_replay(tmp_path / "reports", (observed,))
    assert report.passed is not choose_background
    assert report.citation_precision == (0 if choose_background else 1)


def test_foreign_project_probe_is_denied_and_cannot_supply_missing_answer(tmp_path: Path) -> None:
    foreign = document().model_copy(update={"project_id": "project_foreign"})
    foreign_snapshot = KnowledgeSnapshot.create(
        team_id=foreign.team_id,
        project_id="project_foreign",
        requirement_id="requirement_foreign",
        repository_ids=("repository_foreign",),
        documents=(foreign,),
    )
    (foreign_hit,) = MarkdownKnowledgeRetrieval().search(foreign_snapshot, "payment")
    frozen = snapshot()
    bound = binding(frozen)
    records = KnowledgeRecordStore(tmp_path / "run")
    skills = KnowledgeSkillRegistry(bound, frozen, MarkdownKnowledgeRetrieval(), records)
    rejected = skills.search_knowledge(
        KnowledgeSearchRequest(
            binding=bound.model_copy(update={"project_id": "project_foreign"}),
            operation_id="foreign_probe",
            query="payment",
        )
    )
    assert rejected.status == "REJECTED" and rejected.hits == ()
    refused_read = skills.read_knowledge(
        KnowledgeReadRequest(
            binding=bound,
            operation_id="foreign_read",
            search_evidence_id=rejected.evidence_id,
            citation=foreign_hit.citation,
        )
    )
    assert refused_read.status == "REJECTED" and refused_read.chunk is None
    observed = _observe(
        records, frozen, case="foreign", enabled=True, expected=(), gap_expected=True
    )
    assert observed.gap_reported and observed.actual_citations == ()
    assert _persist_replay(tmp_path / "reports", (observed,)).passed


def test_real_retirement_removes_answer_from_new_snapshot_and_preserves_history(
    tmp_path: Path,
) -> None:
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_ai", name="QA")
    indexer = KnowledgeIndexer(team)
    indexer.enqueue(filename="refund.md", content=b"# Refunds\nUse original payment identity.")
    indexer.tick()
    (imported,) = TeamKnowledgeDocumentStore(team).list()
    TeamKnowledgeSelectionStore(team).save((imported.normalized_relative_path,))
    indexer.tick()
    selected: tuple[KnowledgeDocument, ...] = indexer.current_documents()
    assert len(selected) == 1
    historical = snapshot(*selected)
    (hit,) = MarkdownKnowledgeRetrieval().search(historical, "payment")
    TeamKnowledgeDocumentStore(team).retire(imported.document_id)
    indexer.tick()
    assert (
        imported.document_id in TeamKnowledgeDocumentStore(team).retirement().retired_document_ids
    )
    current = snapshot(*indexer.current_documents())
    assert current.documents == ()
    records = KnowledgeRecordStore(tmp_path / "run")
    bound = binding(current)
    skills = KnowledgeSkillRegistry(bound, current, MarkdownKnowledgeRetrieval(), records)
    missed = skills.search_knowledge(
        KnowledgeSearchRequest(binding=bound, operation_id="retired_probe", query="payment")
    )
    refused = skills.read_knowledge(
        KnowledgeReadRequest(
            binding=bound,
            operation_id="retired_read",
            search_evidence_id=missed.evidence_id,
            citation=hit.citation,
        )
    )
    assert missed.status == "MISS" and refused.status == "REJECTED"
    observed = _observe(
        records, current, case="retired", enabled=True, expected=(), gap_expected=True
    )
    assert _persist_replay(tmp_path / "reports", (observed,)).passed
    assert MarkdownKnowledgeRetrieval().read(historical, hit.citation).citation == hit.citation


def test_approved_resolution_learning_prevents_same_gap_for_future_requirement(
    tmp_path: Path,
) -> None:
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_ai", name="QA")
    project = team.project_registry().register(project_id="project_payments", name="Payments")
    records = KnowledgeRecordStore(tmp_path / "original-run")
    frozen = snapshot()
    original_binding = binding(frozen)
    with pytest.raises(KnowledgeGapRaised) as raised:
        KnowledgeConsultationService(Model(), records).consult(
            original_binding, frozen, {"requirement": "refund payment"}, timeout_seconds=10
        )
    gap = raised.value.gap
    answer = "All refunds MUST use the original payment ID."
    resolution = KnowledgeResolution(
        gap_id=gap.gap_id,
        previous_run_id=gap.binding.run_id,
        answer=answer,
        sources=(
            KnowledgeResolutionSource(
                uri="human://approved/refund-policy", content=answer, sha256=text_digest(answer)
            ),
        ),
        approval_reference="human:approved-refund-policy",
        approved_by="human:fixture-owner",
        disposition="PROPOSE_LEARNING",
        resolution_id="0" * 64,
    )
    resolution = resolution.model_copy(
        update={
            "resolution_id": digest(resolution.model_dump(mode="json", exclude={"resolution_id"}))
        }
    )
    KnowledgeGapService(records).resolve(resolution, Approval(resolution))
    learning = ProjectLearningStore(project)
    proposal = learning.propose_knowledge_resolution(records, resolution.resolution_id)
    assert ProjectKnowledgeDocumentStore(project).list() == ()
    assert effective_project_knowledge_paths(project) == ()
    # Publication is a second exact human decision; resolution approval alone is insufficient.
    decided = learning.decide(
        proposal.proposal_id,
        DecideLearningProposal(
            proposal_sha256=proposal.proposal_sha256,
            action=LearningDecisionAction.APPROVE,
            target=LearningTarget.KNOWLEDGE,
            operator_id="human_owner",
            rationale="Publish the verified answer for future refund requirements.",
        ),
        decided_at=datetime(2026, 9, 19, tzinfo=UTC),
    )
    assert decided.decision is not None and decided.decision.published_uri is not None
    paths = effective_project_knowledge_paths(project)
    assert len(paths) == 1
    sources = project.knowledge_sources(paths)
    future = snapshot_from_sources(
        team_id=team.manifest.team_id,
        project_id=project.manifest.project_id,
        requirement_id="requirement_future_refund",
        repository_ids=frozen.repository_ids,
        sources=tuple((frozen.repository_ids[0], source) for source in sources),
    )
    assert future.snapshot_sha256 != frozen.snapshot_sha256
    future_records = KnowledgeRecordStore(tmp_path / "future-run")
    receipt = KnowledgeConsultationService(Model(), future_records).consult(
        binding(future), future, {"requirement": "refund payment"}, timeout_seconds=10
    )
    assert receipt.assessment.status == "SUFFICIENT"
    assert receipt.assessment.claims
    assert all(
        answer in MarkdownKnowledgeRetrieval().read(future, citation).content
        for claim in receipt.assessment.claims
        for citation in claim.citations
    )
    assert future_records.list("gaps", KnowledgeGap) == ()
    assert records.get("gaps", gap.gap_id, KnowledgeGap) == gap
    assert MarkdownKnowledgeRetrieval().search(frozen, "original payment") == ()
