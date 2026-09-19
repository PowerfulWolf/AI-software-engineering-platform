"""The same frozen-snapshot contract applies to baseline and indexed adapters."""

from pathlib import Path

import pytest

from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.index import IndexedKnowledgeRetrieval
from ai_software_engineer.knowledge.models import (
    KnowledgeDocument,
    KnowledgeError,
    KnowledgeReadRequest,
    KnowledgeRunBinding,
    KnowledgeSearchRequest,
    KnowledgeSnapshot,
    text_digest,
)
from ai_software_engineer.knowledge.retrieval import KnowledgeRetrieval, MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge.skills import KnowledgeSkillRegistry
from ai_software_engineer.knowledge.store import KnowledgeRecordStore


def document(
    content: str = "# Payments\n\nRefunds require original payment ID.\n退款必须使用原支付单号。",
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id="doc_payments",
        scope="project",
        team_id="team_ai",
        project_id="project_payments",
        title="Payments",
        source_uri="knowledge://project_payments/payments",
        document_sha256=text_digest(content),
        content=content,
    )


def snapshot(*docs: KnowledgeDocument) -> KnowledgeSnapshot:
    return KnowledgeSnapshot.create(
        team_id="team_ai",
        project_id="project_payments",
        requirement_id="requirement_refund",
        repository_ids=("repository_payments",),
        documents=docs,
    )


def binding(frozen: KnowledgeSnapshot, role: TeamRole = TeamRole.CODER) -> KnowledgeRunBinding:
    return KnowledgeRunBinding(
        run_id="run_knowledge_001",
        task_id="task_knowledge_001",
        role=role,
        team_id=frozen.team_id,
        project_id=frozen.project_id,
        requirement_id=frozen.requirement_id,
        repository_ids=frozen.repository_ids,
        source_revision="a" * 40,
        context_manifest_id="ctx_" + "b" * 64,
        snapshot_sha256=frozen.snapshot_sha256,
    )


@pytest.fixture(params=[MarkdownKnowledgeRetrieval, IndexedKnowledgeRetrieval])
def retrieval(request: pytest.FixtureRequest) -> KnowledgeRetrieval:
    adapter_type: type[MarkdownKnowledgeRetrieval] | type[IndexedKnowledgeRetrieval] = request.param
    return adapter_type()


def test_baseline_exact_citations_and_chinese(retrieval: KnowledgeRetrieval) -> None:
    frozen = snapshot(document())
    adapter = retrieval
    for query in ("original payment", "原支付单号"):
        (hit,) = adapter.search(frozen, query, limit=1)
        chunk = adapter.read(frozen, hit.citation)
        assert hit.citation.document_sha256 == document().document_sha256
        assert chunk.citation.chunk_sha256 == text_digest(chunk.content)
    assert adapter.search(frozen, "unrelated-xyz") == ()
    assert adapter.search(snapshot(), "payment") == ()


def test_snapshot_isolation_and_integrity(retrieval: KnowledgeRetrieval) -> None:
    with pytest.raises(ValueError, match="cross-owner"):
        snapshot(document().model_copy(update={"project_id": "project_foreign"}))
    forged = snapshot(document()).model_copy(update={"snapshot_sha256": "0" * 64})
    with pytest.raises(KnowledgeError):
        retrieval.search(forged, "payment")


@pytest.mark.parametrize("role", list(TeamRole))
def test_role_registry_requires_actual_search_and_replays(
    tmp_path: Path, role: TeamRole, retrieval: KnowledgeRetrieval
) -> None:
    frozen = snapshot(document())
    bound = binding(frozen, role)
    records = KnowledgeRecordStore(tmp_path / "knowledge")
    registry = KnowledgeSkillRegistry(bound, frozen, retrieval, records)
    query = KnowledgeSearchRequest(operation_id="search_1", binding=bound, query="payment")
    found = registry.search_knowledge(query)
    found.validate_integrity()
    assert found.status == "HIT"
    request = KnowledgeReadRequest(
        operation_id="read_1",
        binding=bound,
        search_evidence_id=found.evidence_id,
        citation=found.hits[0].citation,
    )
    read = registry.read_knowledge(request)
    assert read.status == "READ"
    reopened = KnowledgeSkillRegistry(
        bound, frozen, retrieval, KnowledgeRecordStore(tmp_path / "knowledge")
    )
    assert reopened.search_knowledge(query) == found
    assert reopened.read_knowledge(request) == read
    assert reopened.manifest().citations == (found.hits[0].citation,)
    with pytest.raises(KnowledgeError, match="CONFLICT"):
        reopened.search_knowledge(query.model_copy(update={"query": "changed"}))
    refused = registry.read_knowledge(
        request.model_copy(update={"operation_id": "read_fake", "search_evidence_id": "a" * 64})
    )
    assert refused.status == "REJECTED" and refused.chunk is None


def test_denials_are_persisted_and_redacted(tmp_path: Path) -> None:
    frozen = snapshot(document("# Key\napi_key=sk-secret123456789012345678901234567890\n"))
    bound = binding(frozen)
    registry = KnowledgeSkillRegistry(
        bound, frozen, MarkdownKnowledgeRetrieval(), KnowledgeRecordStore(tmp_path / "knowledge")
    )
    request = KnowledgeSearchRequest(
        operation_id="foreign",
        query="sk-secret123456789012345678901234567890",
        binding=bound.model_copy(update={"project_id": "project_foreign"}),
    )
    result = registry.search_knowledge(request)
    assert result.status == "REJECTED" and not result.hits
    assert "sk-secret" not in result.model_dump_json()
    assert registry.manifest().evidence_ids == (result.evidence_id,)


def test_role_restrictions_and_digest_drift(tmp_path: Path) -> None:
    restricted = document().model_copy(update={"roles": (TeamRole.DESIGNER,)})
    frozen = snapshot(restricted)
    bound = binding(frozen)
    registry = KnowledgeSkillRegistry(
        bound, frozen, MarkdownKnowledgeRetrieval(), KnowledgeRecordStore(tmp_path / "knowledge")
    )
    result = registry.search_knowledge(
        KnowledgeSearchRequest(operation_id="hidden", binding=bound, query="payment")
    )
    assert result.status == "MISS"
    altered = frozen.model_copy(
        update={"documents": (document().model_copy(update={"content": "changed"}),)}
    )
    with pytest.raises((ValueError, KnowledgeError)):
        MarkdownKnowledgeRetrieval().search(altered, "changed")


def test_operation_replay_repairs_interrupted_evidence_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = snapshot(document())
    bound = binding(frozen)
    records = KnowledgeRecordStore(tmp_path)
    registry = KnowledgeSkillRegistry(bound, frozen, MarkdownKnowledgeRetrieval(), records)
    request = KnowledgeSearchRequest(operation_id="search_crash", binding=bound, query="payment")
    put = records.put

    def crash(namespace, key, value):  # type: ignore[no-untyped-def]
        if namespace == "evidence":
            raise OSError("interrupted evidence publication")
        return put(namespace, key, value)

    monkeypatch.setattr(records, "put", crash)
    with pytest.raises(OSError):
        registry.search_knowledge(request)
    reopened = KnowledgeSkillRegistry(
        bound, frozen, MarkdownKnowledgeRetrieval(), KnowledgeRecordStore(tmp_path)
    )
    hit = reopened.search_knowledge(request)
    read = reopened.read_knowledge(
        KnowledgeReadRequest(
            operation_id="read_after_restart",
            binding=bound,
            search_evidence_id=hit.evidence_id,
            citation=hit.hits[0].citation,
        )
    )
    assert read.status == "READ"
