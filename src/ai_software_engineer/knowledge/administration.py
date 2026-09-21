"""Trusted local human resolution channel over immutable Requirement gap facts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGap,
    KnowledgeGapService,
    KnowledgeResolution,
    KnowledgeResolutionSource,
)
from ai_software_engineer.knowledge.models import BoundedText, Digest, KnowledgeError, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.knowledge.views import KnowledgeGapView, read_gap_view
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.multi_directory.models import JointStage
from ai_software_engineer.multi_directory.retirement import RequirementRetirementStore
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.project_workspace import ProjectWorkspace


class ApproveKnowledgeResolution(DomainModel):
    gap_id: Digest
    answer: BoundedText
    sources: Annotated[tuple[KnowledgeResolutionSource, ...], Field(min_length=1, max_length=32)]
    approval_reference: NonEmptyStr
    disposition: Literal["REQUIREMENT_ONLY", "PROPOSE_LEARNING"] = "REQUIREMENT_ONLY"


class KnowledgeHumanActionEvent(DomainModel):
    kind: Literal["HumanActionEvent"] = "HumanActionEvent"
    action: Literal["APPROVE_KNOWLEDGE_RESOLUTION"] = "APPROVE_KNOWLEDGE_RESOLUTION"
    project_id: str
    requirement_id: str
    gap_id: Digest
    resolution: KnowledgeResolution
    actor: Literal["human:local-console"] = "human:local-console"
    event_sha256: Digest


def gap_stores(
    project: ProjectWorkspace, requirement_id: str, *, read_only: bool = False
) -> tuple[KnowledgeRecordStore, ...]:
    identity = TypeAdapter(DeliveryId).validate_python(requirement_id)
    current = JointJournal(project.requirements_root, read_only=True).current(identity)
    if current is None or current.project_id != project.manifest.project_id:
        raise KnowledgeError("REQUIREMENT_NOT_FOUND")
    roots = [project.requirements_root / identity / "knowledge"]
    roots.extend(
        project.root / "repositories" / p.result.repository_id / "knowledge" / "runs"
        for p in current.preparations
    )
    return tuple(KnowledgeRecordStore(root, read_only=read_only) for root in roots if root.is_dir())


def list_gaps(project: ProjectWorkspace, requirement_id: str) -> tuple[KnowledgeGap, ...]:
    gaps = tuple(
        gap
        for records in gap_stores(project, requirement_id, read_only=True)
        for gap in records.list("gaps", KnowledgeGap)
        if gap.binding.requirement_id == requirement_id
        and gap.binding.project_id == project.manifest.project_id
        and gap.binding.team_id == project.manifest.team_id
    )
    for gap in gaps:
        gap.validate_integrity()
    return gaps


def list_gap_views(project: ProjectWorkspace, requirement_id: str) -> tuple[KnowledgeGapView, ...]:
    current = JointJournal(project.requirements_root, read_only=True).current(requirement_id)
    if current is None:
        raise KnowledgeError("REQUIREMENT_NOT_FOUND")
    return tuple(
        read_gap_view(
            find_gap_records(project, requirement_id, gap.gap_id, read_only=True),
            gap,
            current_gap_id=(
                current.knowledge_gap_id if current.stage is JointStage.WAITING_HUMAN else None
            ),
        )
        for gap in list_gaps(project, requirement_id)
    )


def find_gap_records(
    project: ProjectWorkspace, requirement_id: str, gap_id: str, *, read_only: bool = False
) -> KnowledgeRecordStore:
    for records in gap_stores(project, requirement_id, read_only=read_only):
        gap = records.find("gaps", gap_id, KnowledgeGap)
        if (
            gap is not None
            and gap.binding.requirement_id == requirement_id
            and gap.binding.project_id == project.manifest.project_id
            and gap.binding.team_id == project.manifest.team_id
        ):
            gap.validate_integrity()
            return records
    raise KnowledgeError("GAP_NOT_FOUND")


class _LocalApproval:
    def __init__(self, resolution: KnowledgeResolution) -> None:
        self.resolution = resolution

    def require_approval(self, resolution: KnowledgeResolution) -> None:
        if resolution != self.resolution:
            raise KnowledgeError("HUMAN_APPROVAL_MISMATCH")


def approve_resolution(
    project: ProjectWorkspace, requirement_id: str, command: ApproveKnowledgeResolution
) -> KnowledgeResolution:
    project.validate_current()
    journal = JointJournal(project.requirements_root, read_only=True)
    current = journal.current(TypeAdapter(DeliveryId).validate_python(requirement_id))
    retirement = RequirementRetirementStore(
        project.requirements_root,
        team_id=project.manifest.team_id,
        team_manifest_sha256=project.manifest.team_manifest_sha256,
        project_id=project.manifest.project_id,
        project_manifest_sha256=project.manifest.manifest_sha256,
        read_only=True,
    )
    if (
        current is None
        or current.stage is not JointStage.WAITING_HUMAN
        or current.knowledge_gap_id != command.gap_id
        or requirement_id in retirement.retired_delivery_ids(journal)
    ):
        raise KnowledgeError("GAP_NOT_CURRENT")
    records = find_gap_records(project, requirement_id, command.gap_id)
    gap = records.get("gaps", command.gap_id, KnowledgeGap)
    provisional = KnowledgeResolution(
        gap_id=gap.gap_id,
        previous_run_id=gap.binding.run_id,
        answer=command.answer,
        sources=command.sources,
        approval_reference=command.approval_reference,
        approved_by="human:local-console",
        disposition=command.disposition,
        resolution_id="0" * 64,
    )
    resolution = provisional.model_copy(
        update={
            "resolution_id": digest(provisional.model_dump(mode="json", exclude={"resolution_id"}))
        }
    )
    resolution.validate_integrity()
    existing = records.find("gap-resolutions", gap.gap_id, KnowledgeResolution)
    if existing is not None and existing != resolution:
        raise KnowledgeError("RESOLUTION_CONFLICT")
    event = KnowledgeHumanActionEvent(
        project_id=project.manifest.project_id,
        requirement_id=requirement_id,
        gap_id=gap.gap_id,
        resolution=resolution,
        event_sha256="0" * 64,
    )
    event = event.model_copy(
        update={"event_sha256": digest(event.model_dump(mode="json", exclude={"event_sha256"}))}
    )
    records.put("human-actions", event.event_sha256, event)
    approved = KnowledgeGapService(records).resolve(resolution, _LocalApproval(resolution))
    if approved.disposition == "PROPOSE_LEARNING":
        from ai_software_engineer.learning import ProjectLearningStore

        ProjectLearningStore(project).propose_knowledge_resolution(records, approved.resolution_id)
    return approved
