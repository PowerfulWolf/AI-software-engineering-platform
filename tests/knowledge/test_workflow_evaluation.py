from pathlib import Path

import pytest

from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.evaluation import (
    KnowledgeEvaluationObservation,
    evaluate_knowledge,
)
from ai_software_engineer.knowledge.models import KnowledgeError, KnowledgeSearchRequest
from ai_software_engineer.knowledge.retrieval import MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge.skills import KnowledgeSkillRegistry
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.knowledge.workflow import WorkflowGateFacts, WorkflowSkillRegistry
from tests.knowledge.test_retrieval_contract import binding, document, snapshot


@pytest.mark.parametrize("role", (TeamRole.CODER, TeamRole.QA, TeamRole.REVIEWER))
def test_workflow_cannot_expand_role_or_skip_evidence(tmp_path: Path, role: TeamRole) -> None:
    frozen = snapshot(document())
    bound = binding(frozen, role)
    store = KnowledgeRecordStore(tmp_path)
    skills = KnowledgeSkillRegistry(bound, frozen, MarkdownKnowledgeRetrieval(), store)
    skills.search_knowledge(
        KnowledgeSearchRequest(binding=bound, operation_id="query", query="payment")
    )
    manifest = skills.manifest()
    workflows = WorkflowSkillRegistry(store)
    facts = WorkflowGateFacts(
        binding=bound, knowledge_manifest_sha256=manifest.manifest_sha256, durable_evidence=()
    )
    name = workflows.definitions(role)[0].name
    assert workflows.invoke(name, "v1", facts).status == "REJECTED"
    with pytest.raises(KnowledgeError):
        workflows.invoke("finish-work", "v1", facts)
    with pytest.raises(KnowledgeError):
        workflows.invoke(name, "uninstalled", facts)
    with pytest.raises(KnowledgeError):
        workflows.require(bound, (name,), ())
    passed = workflows.invoke(
        name,
        "v1",
        facts.model_copy(
            update={"durable_evidence": ("knowledge-manifest:" + manifest.manifest_sha256,)}
        ),
    )
    workflows.require(bound, (name,), (passed.evidence_sha256,))
    with pytest.raises(KnowledgeError):
        workflows.invoke(name, "v1", facts.model_copy(update={"durable_evidence": ("fabricated",)}))


@pytest.mark.parametrize(
    "case",
    ("answer", "disabled", "foreign", "missing", "conflict", "retired", "spec-vs-background"),
)
def test_good_base_bad_effectiveness_corpus(case: str) -> None:
    frozen = snapshot(document())
    citation = MarkdownKnowledgeRetrieval().search(frozen, "payment")[0].citation
    gap_expected = case in {"disabled", "missing", "conflict", "retired"}
    leakage = case == "foreign"
    wrong_kind = case == "spec-vs-background"
    observed = KnowledgeEvaluationObservation(
        case_id=case,
        condition="DISABLED" if case == "disabled" else "ENABLED",
        source_revision="a" * 40,
        context_manifest_id="ctx_" + "b" * 64,
        snapshot_sha256=frozen.snapshot_sha256,
        skill_versions=("before-dev:v1",),
        provider="fixture",
        model="scripted",
        expected_citations=() if gap_expected or wrong_kind else (citation,),
        allowed_citations=() if gap_expected or leakage else (citation,),
        actual_citations=() if gap_expected else (citation,),
        decisive_claims=0 if gap_expected else 1,
        supported_claims=0 if gap_expected or leakage or wrong_kind else 1,
        gap_expected=gap_expected,
        gap_reported=gap_expected,
        acceptance_total=1,
        acceptance_covered=0 if gap_expected else 1,
        qa_rejected=False,
        review_rejected=False,
        token_count=10,
        latency_ms=1,
    )
    report = evaluate_knowledge((observed,))
    report.validate_integrity()
    assert report.passed == (not leakage and not wrong_kind)
    assert evaluate_knowledge((observed,)) == report
    if gap_expected:
        assert not evaluate_knowledge((observed.model_copy(update={"gap_reported": False}),)).passed
