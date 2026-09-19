from pathlib import Path

import pytest

from ai_software_engineer.knowledge.gaps import (
    KnowledgeGapService,
    KnowledgeResolution,
    KnowledgeResolutionSource,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeSearchRequest,
    digest,
    text_digest,
)
from ai_software_engineer.knowledge.retrieval import MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge.skills import KnowledgeSkillRegistry
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from tests.knowledge.test_retrieval_contract import binding, snapshot


class Approval:
    def __init__(self, expected: KnowledgeResolution) -> None:
        self.expected = expected

    def require_approval(self, resolution: KnowledgeResolution) -> None:
        if resolution != self.expected:
            raise KnowledgeError("NOT_APPROVED")


def test_gap_resolution_fresh_process_lineage_and_exact_replay(tmp_path: Path) -> None:
    records = KnowledgeRecordStore(tmp_path)
    frozen = snapshot()
    bound = binding(frozen)
    skills = KnowledgeSkillRegistry(bound, frozen, MarkdownKnowledgeRetrieval(), records)
    skills.search_knowledge(
        KnowledgeSearchRequest(operation_id="search_missing", binding=bound, query="refund SLA")
    )
    gaps = KnowledgeGapService(records)
    gap = gaps.report(
        manifest=skills.manifest(),
        question="What is the refund SLA?",
        required_decision="Specify SLA",
        reason="MISSING",
        severity="BLOCKING",
        impact="Acceptance cannot be decided",
        risk="high",
    )
    assert gaps.unresolved(bound) == (gap,)
    assert (
        gaps.route(gap.gap_id, "USER", "Business decision required").waiting_status
        == "WAITING_HUMAN"
    )
    answer = "Refunds finish in 5 days."
    provisional = KnowledgeResolution(
        gap_id=gap.gap_id,
        previous_run_id=bound.run_id,
        answer=answer,
        sources=(
            KnowledgeResolutionSource(
                uri="human://decision/123", sha256=text_digest(answer), content=answer
            ),
        ),
        approval_reference="human_event_123",
        approved_by="human:owner",
        resolution_id="0" * 64,
    )
    resolution = provisional.model_copy(
        update={
            "resolution_id": digest(provisional.model_dump(mode="json", exclude={"resolution_id"}))
        }
    )
    with pytest.raises(KnowledgeError):
        gaps.resume(gap.gap_id, bound)
    assert gaps.resolve(resolution, Approval(resolution)) == resolution
    reopened = KnowledgeGapService(KnowledgeRecordStore(tmp_path))
    assert reopened.resolve(resolution, Approval(resolution)) == resolution
    assert reopened.unresolved(bound) == ()
    with pytest.raises(KnowledgeError):
        reopened.resume(gap.gap_id, bound)
    fresh = bound.model_copy(
        update={"run_id": "run_knowledge_002", "context_manifest_id": "ctx_" + "c" * 64}
    )
    resumed = reopened.resume(gap.gap_id, fresh)
    assert resumed.previous_binding == bound and resumed.resolution_id == resolution.resolution_id
    assert reopened.resume(gap.gap_id, fresh) == resumed
    with pytest.raises(KnowledgeError):
        reopened.resume(gap.gap_id, fresh.model_copy(update={"project_id": "project_other"}))
