"""Workflow gates backed by already sealed delivery artifacts, never model claims."""

from __future__ import annotations

from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.context import ContextStore
from ai_software_engineer.domain import Task, TaskStatus, TeamRole
from ai_software_engineer.domain.artifact import (
    Artifact,
    ImplementationReportArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.enums import QaReportStatus, ReviewVerdict
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.agents import (
    KnowledgeConsultation,
    consultation_integrity_matches,
    repository_inspection_gap,
)
from ai_software_engineer.knowledge.gaps import KnowledgeGapService
from ai_software_engineer.knowledge.models import (
    Digest,
    KnowledgeError,
    KnowledgeRunBinding,
    digest,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.knowledge.workflow import (
    SkillName,
    WorkflowGateFacts,
    WorkflowSkillRegistry,
)


class DeliveryWorkflowProof(DomainModel):
    task_id: str
    target_status: TaskStatus
    artifact_digests: tuple[tuple[str, Digest], ...]
    required_acceptance_ids: tuple[str, ...]
    covered_acceptance_ids: tuple[str, ...]
    independent_agent_ids: tuple[str, ...]
    consultation_binding: KnowledgeRunBinding | None = None
    final_context_id: str | None = None
    candidate_revision: str | None = None
    proof_sha256: Digest

    def validate_integrity(self) -> None:
        if self.proof_sha256 != digest(self.model_dump(mode="json", exclude={"proof_sha256"})):
            raise KnowledgeError("DELIVERY_PROOF_INTEGRITY")


class DeliveryWorkflowAdmission(DomainModel):
    """One-time upgrade boundary; never manufactures knowledge evidence for old work."""

    task_id: str
    contract_version: str = "active-knowledge-v1"
    legacy_artifact_digests: tuple[tuple[str, Digest], ...]


class KnowledgeDeliveryGate:
    def __init__(
        self, *, records: KnowledgeRecordStore, artifacts: ArtifactStore, contexts: ContextStore
    ) -> None:
        self.records, self.artifacts, self.contexts = records, artifacts, contexts

    def begin_task(self, task: Task) -> None:
        if self.records.find("delivery-admissions", task.id, DeliveryWorkflowAdmission) is not None:
            return
        legacy = []
        if task.status is not TaskStatus.NEW:
            for artifact in self.artifacts.list_for_task(task.id):
                context = self.contexts.get(artifact.context_manifest_id)
                if not any(s.name == "knowledge.consultation" for s in context.sections):
                    legacy.append((artifact.artifact_id, artifact.integrity.sha256))
        self.records.put(
            "delivery-admissions",
            task.id,
            DeliveryWorkflowAdmission(task_id=task.id, legacy_artifact_digests=tuple(legacy)),
        )

    def before_transition(
        self, task: Task, target: TaskStatus, artifact_ids: tuple[str, ...]
    ) -> None:
        if target not in {TaskStatus.QA, TaskStatus.REVIEW, TaskStatus.DONE}:
            return
        # Transitions may cite only their newest artifact. Resolve its exact
        # parent chain, never whichever report happens to be latest in a folder.
        pending = list(artifact_ids)
        resolved: dict[str, Artifact] = {}
        while pending:
            identity = pending.pop(0)
            if identity in resolved:
                continue
            if len(resolved) >= 128:
                raise KnowledgeError("WORKFLOW_LINEAGE_LIMIT")
            artifact = self.artifacts.get(identity)
            resolved[identity] = artifact
            pending.extend(artifact.parent_artifact_ids)
        artifacts = tuple(resolved.values())
        if any(artifact.task_id != task.id for artifact in artifacts):
            raise KnowledgeError("WORKFLOW_TASK_MISMATCH")
        implementation = next(
            (a for a in artifacts if isinstance(a, ImplementationReportArtifact)), None
        )
        qa = next((a for a in artifacts if isinstance(a, QaReportArtifact)), None)
        review = next((a for a in artifacts if isinstance(a, ReviewReportArtifact)), None)
        names: tuple[SkillName, ...]
        active: ImplementationReportArtifact | QaReportArtifact | ReviewReportArtifact | None
        if target is TaskStatus.QA:
            active = implementation
            names = ("implementation-check",)
        elif target is TaskStatus.REVIEW:
            active = qa
            names = ("acceptance-matrix", "test-gaps")
        else:
            active = review
            names = ("code-review", "spec-review")
        if active is None or implementation is None:
            raise KnowledgeError("WORKFLOW_ARTIFACT_MISSING")
        context = self.contexts.get(active.context_manifest_id)
        section = next(
            (item for item in context.sections if item.name == "knowledge.consultation"), None
        )
        if section is None:
            admission = self.records.find("delivery-admissions", task.id, DeliveryWorkflowAdmission)
            if (
                admission is not None
                and (active.artifact_id, active.integrity.sha256)
                in admission.legacy_artifact_digests
            ):
                # Ordinary Orchestrator contract/QA/Review validation still applies.
                # Only these exact artifacts predate the new knowledge gate.
                return
            raise KnowledgeError("WORKFLOW_CONSULTATION_MISSING")
        consultation = KnowledgeConsultation.model_validate_json(section.content)
        stored = self.records.get(
            "consultations", consultation.binding.run_id, KnowledgeConsultation
        )
        repository_gap_is_unresolved = bool(
            KnowledgeGapService(self.records).unresolved(consultation.binding)
        )
        consultation_is_usable = consultation.assessment.status == "SUFFICIENT" or (
            repository_inspection_gap(consultation) and not repository_gap_is_unresolved
        )
        if stored != consultation or not consultation_is_usable:
            raise KnowledgeError("WORKFLOW_CONSULTATION_INVALID")
        if not consultation_integrity_matches(consultation):
            raise KnowledgeError("WORKFLOW_CONSULTATION_INVALID")
        consultation.manifest.validate_integrity()
        parent = self.contexts.get(consultation.binding.context_manifest_id)
        if (
            context.task_id != task.id
            or context.role != active.producer.role
            or consultation.binding.task_id != task.id
            or consultation.binding.role.value != active.producer.role.value
            or consultation.binding.source_revision != context.source_revision
            or parent.source_revision != context.source_revision
            or parent.task_id != context.task_id
            or parent.role != context.role
            or context.sections != (*parent.sections, section)
            or context.budget
            != parent.budget.model_copy(
                update={"used_input_tokens": parent.budget.used_input_tokens + section.tokens}
            )
        ):
            raise KnowledgeError("WORKFLOW_CONTEXT_MISMATCH")
        required = tuple(sorted(item.id for item in task.acceptance_criteria))
        covered = tuple(
            sorted(item.criterion_id for item in implementation.content.acceptance_mapping)
        )
        candidate = implementation.source_revision
        if target in {TaskStatus.REVIEW, TaskStatus.DONE}:
            if (
                qa is None
                or qa.source_revision != candidate
                or qa.content.status is not QaReportStatus.PASS
            ):
                raise KnowledgeError("WORKFLOW_QA_REQUIRED")
            if not qa.content.tests_run:
                raise KnowledgeError("WORKFLOW_QA_TEST_EVIDENCE_REQUIRED")
            covered = tuple(sorted(item.criterion_id for item in qa.content.criteria_results))
        if target is TaskStatus.DONE and (
            review is None
            or review.source_revision != candidate
            or review.content.verdict is not ReviewVerdict.APPROVE
        ):
            raise KnowledgeError("WORKFLOW_REVIEW_REQUIRED")
        members = tuple(a.producer.agent_id for a in (implementation, qa, review) if a is not None)
        if len(set(members)) != len(members):
            raise KnowledgeError("WORKFLOW_INDEPENDENCE_REQUIRED")
        proof = DeliveryWorkflowProof(
            task_id=task.id,
            target_status=target,
            artifact_digests=tuple((a.artifact_id, a.integrity.sha256) for a in artifacts),
            required_acceptance_ids=required,
            covered_acceptance_ids=covered,
            independent_agent_ids=members,
            consultation_binding=consultation.binding,
            final_context_id=context.context_id,
            candidate_revision=candidate,
            proof_sha256="0" * 64,
        )
        proof = proof.model_copy(
            update={"proof_sha256": digest(proof.model_dump(mode="json", exclude={"proof_sha256"}))}
        )
        self.records.put("delivery-proofs", proof.proof_sha256, proof)
        registry = WorkflowSkillRegistry(self.records)
        facts = WorkflowGateFacts(
            binding=consultation.binding,
            knowledge_manifest_sha256=consultation.manifest.manifest_sha256,
            durable_evidence=("delivery-proof:" + proof.proof_sha256,),
            required_acceptance_ids=required,
            covered_acceptance_ids=covered,
            independent_agent_ids=members,
            final_context_id=context.context_id,
            candidate_revision=candidate,
            unresolved_blocking_gap_ids=tuple(
                gap.gap_id
                for gap in KnowledgeGapService(self.records).unresolved(consultation.binding)
            ),
        )
        receipts = tuple(registry.invoke(name, "v1", facts).evidence_sha256 for name in names)
        registry.require(consultation.binding, names, receipts)
        if target is TaskStatus.DONE:
            # Manager's completion check uses the same exact independently produced chain.
            binding = consultation.binding.model_copy(
                update={"role": TeamRole.MANAGER, "run_id": "run_finish_" + proof.proof_sha256[:32]}
            )
            manifest = consultation.manifest.model_copy(
                update={"binding": binding, "evidence_ids": (), "citations": ()}
            )
            manifest = manifest.model_copy(
                update={
                    "manifest_sha256": digest(
                        manifest.model_dump(mode="json", exclude={"manifest_sha256"})
                    )
                }
            )
            self.records.put("manifests", manifest.manifest_sha256, manifest)
            manager_facts = facts.model_copy(
                update={"binding": binding, "knowledge_manifest_sha256": manifest.manifest_sha256}
            )
            receipt = registry.invoke("finish-work", "v1", manager_facts)
            registry.require(binding, ("finish-work",), (receipt.evidence_sha256,))
