"""Prove a legacy retrieval scope without rewriting it or ignoring real drift."""

from ai_software_engineer.context import ContextStore
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.gaps import KnowledgeGap
from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeRunBinding,
    KnowledgeSnapshot,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline import ProjectSpecBaseline


def legacy_delivery_gaps(
    records: KnowledgeRecordStore,
    *,
    task_id: str,
    role: TeamRole,
    team_id: str,
    project_id: str,
    repository_id: str,
    source_revision: str,
) -> tuple[KnowledgeGap, ...]:
    """Read only the exact historical verifier scope retained by the runtime."""
    if not task_id.startswith("task_continue_") or role not in {
        TeamRole.QA,
        TeamRole.REVIEWER,
    }:
        return ()
    gaps = tuple(
        gap
        for gap in records.list("gaps", KnowledgeGap, limit=512)
        if (
            gap.binding.task_id,
            gap.binding.requirement_id,
            gap.binding.team_id,
            gap.binding.project_id,
            gap.binding.repository_ids,
            gap.binding.role,
            gap.binding.source_revision,
        )
        == (task_id, task_id, team_id, project_id, (repository_id,), role, source_revision)
    )
    for gap in gaps:
        gap.validate_integrity()
        if records.get("gaps", gap.gap_id, KnowledgeGap) != gap:
            raise KnowledgeError("LEGACY_KNOWLEDGE_SCOPE_CHANGED")
    return gaps


def require_delivery_requirement_scope(
    binding: KnowledgeRunBinding,
    expected_requirement_id: str,
    *,
    records: KnowledgeRecordStore,
) -> None:
    """Check native Requirement ownership plus an exact, proven legacy gap scope.

    The caller must separately establish that the Task belongs to the expected
    Requirement. A continuation-shaped Task ID alone never authorizes legacy scope.
    """
    if binding.requirement_id == expected_requirement_id:
        return
    if (
        not expected_requirement_id.startswith("delivery_multi_")
        or binding.task_id is None
        or binding.requirement_id != binding.task_id
        or len(binding.repository_ids) != 1
    ):
        raise KnowledgeError("LEGACY_KNOWLEDGE_SCOPE_CHANGED")
    gaps = legacy_delivery_gaps(
        records,
        task_id=binding.task_id,
        role=binding.role,
        team_id=binding.team_id,
        project_id=binding.project_id,
        repository_id=binding.repository_ids[0],
        source_revision=binding.source_revision,
    )
    if not any(gap.binding.snapshot_sha256 == binding.snapshot_sha256 for gap in gaps):
        raise KnowledgeError("LEGACY_KNOWLEDGE_SCOPE_CHANGED")
    historical = records.get("snapshots", binding.snapshot_sha256, KnowledgeSnapshot)
    historical.validate_integrity()
    if (
        historical.team_id,
        historical.project_id,
        historical.requirement_id,
        historical.repository_ids,
    ) != (
        binding.team_id,
        binding.project_id,
        binding.requirement_id,
        binding.repository_ids,
    ):
        raise KnowledgeError("LEGACY_KNOWLEDGE_SCOPE_CHANGED")


def retain_legacy_snapshot(
    current: KnowledgeSnapshot,
    gap: KnowledgeGap,
    *,
    contexts: ContextStore,
    records: KnowledgeRecordStore,
) -> KnowledgeSnapshot:
    """Allow only missing native bodies already attested by the original baseline.

    Caller has established the same continuation Task/role/candidate. Retrieval keeps
    its original snapshot; the ordinary current Context still carries the full rules.
    Newly selected knowledge, modified documents and unproven sources remain errors.
    """
    gap.validate_integrity()
    if gap.binding.snapshot_sha256 == current.snapshot_sha256:
        return current
    historical = records.get("snapshots", gap.binding.snapshot_sha256, KnowledgeSnapshot)
    historical.validate_integrity()
    if (
        historical.team_id,
        historical.project_id,
        historical.requirement_id,
        historical.repository_ids,
    ) != (
        current.team_id,
        current.project_id,
        current.requirement_id,
        current.repository_ids,
    ):
        raise KnowledgeError("LEGACY_KNOWLEDGE_SCOPE_CHANGED")
    context = contexts.get(gap.binding.context_manifest_id)
    if (
        context.task_id != gap.binding.task_id
        or context.role.value != gap.binding.role.value
        or context.source_revision != gap.binding.source_revision
        or any(s.uri.startswith("joint://") for s in context.sections)
    ):
        raise KnowledgeError("LEGACY_KNOWLEDGE_SCOPE_CHANGED")
    baselines = tuple(s for s in context.sections if s.name == "source:project.baseline")
    if len(baselines) != 1 or baselines[0].truncated:
        raise KnowledgeError("LEGACY_KNOWLEDGE_SCOPE_CHANGED")
    baseline = ProjectSpecBaseline.model_validate_json(baselines[0].content)
    baseline.validate_integrity()
    if (
        current.repository_ids != (baseline.repository_id,)
        or baselines[0].uri != f"baseline://{baseline.repository_id}/{baseline.baseline_sha256}"
    ):
        raise KnowledgeError("LEGACY_KNOWLEDGE_SCOPE_CHANGED")
    references = {(ref.uri, ref.sha256) for ref in baseline.opaque_project_sources}
    old = {(doc.scope, doc.document_id): doc for doc in historical.documents}
    new = {(doc.scope, doc.document_id): doc for doc in current.documents}
    if any(new.get(key) != document for key, document in old.items()):
        raise KnowledgeError("LEGACY_KNOWLEDGE_SCOPE_CHANGED")
    for key, document in new.items():
        if key in old:
            continue
        if (
            document.scope != "repository"
            or (
                document.source_uri,
                document.document_sha256,
            )
            not in references
        ):
            raise KnowledgeError("LEGACY_KNOWLEDGE_SCOPE_CHANGED")
    return historical
