"""Reconstruct exact, role-visible READ evidence for a compact delivery Context."""

import json

from ai_software_engineer.context import ContextBundle, ContextSection
from ai_software_engineer.knowledge.agents import (
    KnowledgeConsultation,
    consultation_integrity_matches,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeEvidence,
    KnowledgeSnapshot,
    digest,
    text_digest,
)
from ai_software_engineer.knowledge.retrieval import MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge.store import KnowledgeRecordStore


def requires_frozen_reads(context: ContextBundle) -> bool:
    return any(section.name.startswith("source:native.reference.") for section in context.sections)


def retrieved_context_section(
    consultation: KnowledgeConsultation, records: KnowledgeRecordStore
) -> ContextSection:
    """Verify immutable reads against their original snapshot, then deduplicate.

    Used both when building Context and by the independent delivery gate. A model
    claim or a current worktree read cannot substitute for these frozen bytes.
    """
    binding, manifest = consultation.binding, consultation.manifest
    manifest.validate_integrity()
    if (
        not consultation_integrity_matches(consultation)
        or manifest.binding != binding
        or manifest.snapshot_sha256 != binding.snapshot_sha256
    ):
        raise KnowledgeError("CONTEXT_READ_BINDING")
    snapshot = records.get("snapshots", binding.snapshot_sha256, KnowledgeSnapshot)
    snapshot.validate_integrity()
    if (
        snapshot.team_id,
        snapshot.project_id,
        snapshot.requirement_id,
        snapshot.repository_ids,
        snapshot.snapshot_sha256,
    ) != (
        binding.team_id,
        binding.project_id,
        binding.requirement_id,
        binding.repository_ids,
        binding.snapshot_sha256,
    ):
        raise KnowledgeError("CONTEXT_READ_SNAPSHOT")
    allowed = KnowledgeSnapshot.create(
        team_id=snapshot.team_id,
        project_id=snapshot.project_id,
        requirement_id=snapshot.requirement_id,
        repository_ids=snapshot.repository_ids,
        documents=tuple(d for d in snapshot.documents if not d.roles or binding.role in d.roles),
    )
    evidence = []
    for identity in manifest.evidence_ids:
        item = records.get("evidence", identity, KnowledgeEvidence)
        item.validate_integrity()
        if item.evidence_id != identity or item.binding != binding:
            raise KnowledgeError("CONTEXT_READ_EVIDENCE")
        evidence.append(item)
    reads = sorted(
        (item for item in evidence if item.status == "READ"), key=lambda r: r.operation_id
    )
    if tuple(item.chunk.citation for item in reads if item.chunk is not None) != manifest.citations:
        raise KnowledgeError("CONTEXT_READ_CITATIONS")
    unique = []
    seen = set()
    for item in reads:
        chunk = item.chunk
        if (
            item.operation != "read_knowledge"
            or chunk is None
            or not any(
                prior.operation == "search_knowledge"
                and prior.status == "HIT"
                and chunk.citation in tuple(hit.citation for hit in prior.hits)
                for prior in evidence
            )
            or chunk != MarkdownKnowledgeRetrieval().read(allowed, chunk.citation)
        ):
            raise KnowledgeError("CONTEXT_READ_CONTENT")
        key = digest(chunk.citation.to_wire())
        if key not in seen:
            seen.add(key)
            unique.append(item.to_wire())
    content = json.dumps(unique, ensure_ascii=False, sort_keys=True)
    return ContextSection(
        name="knowledge.reads",
        uri="knowledge://reads/" + manifest.manifest_sha256,
        content=content,
        sha256=text_digest(content),
        tokens=(len(content) + 3) // 4,
        priority=50,
    )
