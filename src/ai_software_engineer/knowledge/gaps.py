"""Immutable knowledge gaps, Manager routes and trusted resolution lineage."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, model_validator

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.knowledge.models import (
    BoundedText,
    Digest,
    KnowledgeCitation,
    KnowledgeError,
    KnowledgeEvidence,
    KnowledgeRunBinding,
    KnowledgeRunManifest,
    digest,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.redaction import redact_text

GapRoute = Literal[
    "USER", "PRODUCT", "DESIGNER", "RESEARCH", "ACCEPT_RISK", "WAITING_HUMAN", "WAITING_DEPENDENCY"
]


class KnowledgeGap(DomainModel):
    kind: Literal["knowledge_gap"] = "knowledge_gap"
    schema_version: Literal["v0.1"] = "v0.1"
    binding: KnowledgeRunBinding
    question: BoundedText
    required_decision: BoundedText
    reason: Literal["MISSING", "CONFLICT", "STALE", "UNVERIFIABLE"]
    severity: Literal["BLOCKING", "NON_BLOCKING"]
    impact: BoundedText
    risk: Literal["low", "medium", "high"]
    evidence_ids: Annotated[tuple[Digest, ...], Field(min_length=1)]
    manifest_sha256: Digest
    gap_id: Digest

    def validate_integrity(self) -> None:
        if self.gap_id != digest(self.model_dump(mode="json", exclude={"gap_id"})):
            raise KnowledgeError("GAP_INTEGRITY")


class KnowledgeGapRouting(DomainModel):
    gap_id: Digest
    route: GapRoute
    rationale: BoundedText
    waiting_status: Literal["WAITING_HUMAN", "WAITING_DEPENDENCY"]
    routing_sha256: Digest


class KnowledgeResolutionSource(DomainModel):
    uri: NonEmptyStr
    sha256: Digest
    content: BoundedText

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        from ai_software_engineer.knowledge.models import text_digest

        if text_digest(self.content) != self.sha256:
            raise ValueError("resolution source digest mismatch")
        return self


class KnowledgeResolution(DomainModel):
    kind: Literal["knowledge_resolution"] = "knowledge_resolution"
    schema_version: Literal["v0.1"] = "v0.1"
    gap_id: Digest
    previous_run_id: NonEmptyStr
    answer: BoundedText
    sources: Annotated[tuple[KnowledgeResolutionSource, ...], Field(min_length=1, max_length=32)]
    approval_reference: NonEmptyStr
    approved_by: NonEmptyStr
    disposition: Literal["REQUIREMENT_ONLY", "PROPOSE_LEARNING"] = "REQUIREMENT_ONLY"
    resolution_id: Digest

    def validate_integrity(self) -> None:
        KnowledgeResolution.model_validate(self.to_wire())
        if self.resolution_id != digest(self.model_dump(mode="json", exclude={"resolution_id"})):
            raise KnowledgeError("RESOLUTION_INTEGRITY")
        # Validate before either the human-action journal or resolution store writes.
        if redact_text(self.model_dump_json()).text != self.model_dump_json():
            raise KnowledgeError("RESOLUTION_REQUIRES_REDACTION")


class KnowledgeResume(DomainModel):
    gap_id: Digest
    resolution_id: Digest
    previous_binding: KnowledgeRunBinding
    new_binding: KnowledgeRunBinding
    previous_resume_sha256: Digest | None = None
    resume_sha256: Digest


class KnowledgeApprovalPort(Protocol):
    """Trusted human channel verifies the exact proposed resolution, not model prose."""

    def require_approval(self, resolution: KnowledgeResolution) -> None: ...


class KnowledgeWaitPort(Protocol):
    """Manager-owned queue authority must release a held Lease when marking a wait."""

    def wait(self, binding: KnowledgeRunBinding, routing: KnowledgeGapRouting) -> None: ...


class KnowledgeGapService:
    def __init__(self, records: KnowledgeRecordStore) -> None:
        self._records = records

    def report(
        self,
        *,
        manifest: KnowledgeRunManifest,
        question: str,
        required_decision: str,
        reason: Literal["MISSING", "CONFLICT", "STALE", "UNVERIFIABLE"],
        severity: Literal["BLOCKING", "NON_BLOCKING"],
        impact: str,
        risk: Literal["low", "medium", "high"],
    ) -> KnowledgeGap:
        manifest.validate_integrity()
        if (
            self._records.get("manifests", manifest.manifest_sha256, KnowledgeRunManifest)
            != manifest
        ):
            raise KnowledgeError("GAP_MANIFEST")
        for evidence_id in manifest.evidence_ids:
            fact = self._records.get("evidence", evidence_id, KnowledgeEvidence)
            fact.validate_integrity()
            if fact.binding != manifest.binding:
                raise KnowledgeError("GAP_EVIDENCE_SCOPE")
        provisional = KnowledgeGap(
            binding=manifest.binding,
            question=redact_text(question).text,
            required_decision=redact_text(required_decision).text,
            reason=reason,
            severity=severity,
            impact=redact_text(impact).text,
            risk=risk,
            evidence_ids=manifest.evidence_ids,
            manifest_sha256=manifest.manifest_sha256,
            gap_id="0" * 64,
        )
        sealed = provisional.model_copy(
            update={"gap_id": digest(provisional.model_dump(mode="json", exclude={"gap_id"}))}
        )
        return self._records.put("gaps", sealed.gap_id, sealed)

    def route(
        self,
        gap_id: str,
        route: GapRoute,
        rationale: str,
        wait_port: KnowledgeWaitPort | None = None,
    ) -> KnowledgeGapRouting:
        gap = self._records.get("gaps", gap_id, KnowledgeGap)
        gap.validate_integrity()
        provisional = KnowledgeGapRouting(
            gap_id=gap_id,
            route=route,
            rationale=redact_text(rationale).text,
            waiting_status="WAITING_DEPENDENCY"
            if route in {"PRODUCT", "DESIGNER", "RESEARCH", "WAITING_DEPENDENCY"}
            else "WAITING_HUMAN",
            routing_sha256="0" * 64,
        )
        sealed = provisional.model_copy(
            update={
                "routing_sha256": digest(
                    provisional.model_dump(mode="json", exclude={"routing_sha256"})
                )
            }
        )
        sealed = self._records.put("gap-routes", gap_id, sealed)
        if wait_port is not None:
            wait_port.wait(gap.binding, sealed)
        return sealed

    def resolve(
        self, resolution: KnowledgeResolution, approval: KnowledgeApprovalPort
    ) -> KnowledgeResolution:
        resolution.validate_integrity()
        gap = self._records.get("gaps", resolution.gap_id, KnowledgeGap)
        gap.validate_integrity()
        if resolution.previous_run_id != gap.binding.run_id:
            raise KnowledgeError("RESOLUTION_LINEAGE")
        approval.require_approval(resolution)
        if redact_text(resolution.answer).text != resolution.answer or any(
            redact_text(source.content).text != source.content for source in resolution.sources
        ):
            raise KnowledgeError("RESOLUTION_REQUIRES_REDACTION")
        self._records.put("resolutions", resolution.resolution_id, resolution)
        return self._records.put("gap-resolutions", resolution.gap_id, resolution)

    def resume(self, gap_id: str, new_binding: KnowledgeRunBinding) -> KnowledgeResume:
        gap = self._records.get("gaps", gap_id, KnowledgeGap)
        gap.validate_integrity()
        resolution = self._records.get("gap-resolutions", gap_id, KnowledgeResolution)
        resolution.validate_integrity()
        previous = gap.binding
        comparable = {"run_id", "context_manifest_id"}
        previous_resume = None
        if previous.source_revision != new_binding.source_revision:
            # The first recovery must still use the exact failed candidate. After
            # that succeeds, the approved Requirement facts can inform a later
            # candidate without pretending that it is the original interrupted run.
            for applied in self._records.list("gap-resumes", KnowledgeResume):
                if applied.resume_sha256 != digest(
                    applied.model_dump(mode="json", exclude={"resume_sha256"})
                ):
                    raise KnowledgeError("RESUME_INTEGRITY")
                if (
                    applied.gap_id == gap_id
                    and applied.resolution_id == resolution.resolution_id
                    and applied.previous_binding == previous
                    and applied.new_binding.source_revision == previous.source_revision
                ):
                    previous_resume = applied.resume_sha256
                    comparable.add("source_revision")
                    break
        if (
            previous.model_dump(exclude=comparable) != new_binding.model_dump(exclude=comparable)
            or previous.run_id == new_binding.run_id
            or previous.context_manifest_id == new_binding.context_manifest_id
        ):
            raise KnowledgeError("RESUME_REQUIRES_NEW_RUN_CONTEXT")
        provisional = KnowledgeResume(
            gap_id=gap_id,
            resolution_id=resolution.resolution_id,
            previous_binding=previous,
            new_binding=new_binding,
            previous_resume_sha256=previous_resume,
            resume_sha256="0" * 64,
        )
        sealed = provisional.model_copy(
            update={
                "resume_sha256": digest(
                    provisional.model_dump(mode="json", exclude={"resume_sha256"})
                )
            }
        )
        return self._records.put("gap-resumes", new_binding.run_id + ":" + gap_id, sealed)

    def unresolved(self, binding: KnowledgeRunBinding) -> tuple[KnowledgeGap, ...]:
        gaps = tuple(
            gap
            for gap in self._records.list("gaps", KnowledgeGap)
            if gap.binding.requirement_id == binding.requirement_id
            and gap.binding.project_id == binding.project_id
            and gap.binding.team_id == binding.team_id
            and gap.severity == "BLOCKING"
            and self._records.find("gap-resolutions", gap.gap_id, KnowledgeResolution) is None
        )
        for gap in gaps:
            gap.validate_integrity()
        return gaps


class KnowledgeGapRaised(KnowledgeError):
    def __init__(self, gap: KnowledgeGap) -> None:
        self.gap = gap
        super().__init__(f"KNOWLEDGE_GAP:{gap.gap_id}")


class KnowledgeClaim(DomainModel):
    """A model assertion must cite a chunk actually read by this run."""

    statement: BoundedText
    citations: Annotated[tuple[KnowledgeCitation, ...], Field(min_length=1)]
