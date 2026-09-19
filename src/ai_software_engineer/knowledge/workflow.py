"""Versioned Team workflow gates; definitions never grant tools or execute proposals."""

from __future__ import annotations

from typing import Literal

from ai_software_engineer.domain.enums import TaskStatus, TeamRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.knowledge.models import (
    Digest,
    KnowledgeError,
    KnowledgeRunBinding,
    KnowledgeRunManifest,
    digest,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore

SkillName = Literal[
    "start",
    "planning-gate",
    "recovery",
    "finish-work",
    "knowledge-facts",
    "before-dev",
    "architecture-check",
    "plan",
    "implementation-check",
    "learning-proposal",
    "acceptance-matrix",
    "test-gaps",
    "code-review",
    "spec-review",
    "break-loop",
]

_ROLES: dict[TeamRole, tuple[SkillName, ...]] = {
    TeamRole.MANAGER: ("start", "planning-gate", "recovery", "finish-work", "break-loop"),
    TeamRole.PRODUCT: ("knowledge-facts",),
    TeamRole.DESIGNER: ("before-dev", "architecture-check"),
    TeamRole.PLANNER: ("plan",),
    TeamRole.CODER: ("before-dev", "implementation-check", "learning-proposal"),
    TeamRole.QA: ("acceptance-matrix", "test-gaps"),
    TeamRole.REVIEWER: ("code-review", "spec-review", "break-loop"),
}

_DELIVERY_TARGETS: dict[SkillName, TaskStatus] = {
    "implementation-check": TaskStatus.QA,
    "acceptance-matrix": TaskStatus.REVIEW,
    "test-gaps": TaskStatus.REVIEW,
    "code-review": TaskStatus.DONE,
    "spec-review": TaskStatus.DONE,
    "finish-work": TaskStatus.DONE,
}

_STAGE_SKILLS: frozenset[SkillName] = frozenset(
    {"start", "architecture-check", "plan", "planning-gate", "recovery", "break-loop"}
)


class WorkflowSkillDefinition(DomainModel):
    name: SkillName
    version: Literal["v1"] = "v1"
    role: TeamRole
    input_contract: Literal["WorkflowGateFacts"] = "WorkflowGateFacts"
    output_contract: Literal["WorkflowSkillEvidence"] = "WorkflowSkillEvidence"
    failure_policy: Literal["BLOCK"] = "BLOCK"
    executable_kind: Literal["deterministic_gate"] = "deterministic_gate"
    ports: tuple[Literal["read_knowledge_evidence", "read_durable_delivery_facts"], ...] = (
        "read_knowledge_evidence",
        "read_durable_delivery_facts",
    )


class WorkflowGateFacts(DomainModel):
    """Application-verified facts, never a model's declaration of success."""

    binding: KnowledgeRunBinding
    knowledge_manifest_sha256: Digest
    durable_evidence: tuple[NonEmptyStr, ...]
    required_acceptance_ids: tuple[NonEmptyStr, ...] = ()
    covered_acceptance_ids: tuple[NonEmptyStr, ...] = ()
    independent_agent_ids: tuple[NonEmptyStr, ...] = ()
    unresolved_blocking_gap_ids: tuple[Digest, ...] = ()
    final_context_id: str | None = None
    candidate_revision: str | None = None


class WorkflowSkillEvidence(DomainModel):
    definition: WorkflowSkillDefinition
    facts: WorkflowGateFacts
    status: Literal["PASSED", "REJECTED"]
    reasons: tuple[str, ...]
    evidence_sha256: Digest

    def validate_integrity(self) -> None:
        if self.evidence_sha256 != digest(
            self.model_dump(mode="json", exclude={"evidence_sha256"})
        ):
            raise KnowledgeError("SKILL_EVIDENCE_INTEGRITY")


class WorkflowSkillRegistry:
    def __init__(self, records: KnowledgeRecordStore) -> None:
        self._records = records

    @staticmethod
    def definitions(role: TeamRole) -> tuple[WorkflowSkillDefinition, ...]:
        return tuple(
            WorkflowSkillDefinition(name=name, role=role)
            for name in dict.fromkeys(("knowledge-facts", *_ROLES[role]))
        )

    def invoke(
        self, name: SkillName, version: str, facts: WorkflowGateFacts
    ) -> WorkflowSkillEvidence:
        definition = next(
            (item for item in self.definitions(facts.binding.role) if item.name == name), None
        )
        if definition is None or definition.version != version:
            raise KnowledgeError("SKILL_ROLE_OR_VERSION_DENIED")
        manifest = self._records.get(
            "manifests", facts.knowledge_manifest_sha256, KnowledgeRunManifest
        )
        manifest.validate_integrity()
        if manifest.binding != facts.binding:
            raise KnowledgeError("SKILL_CONTEXT_MISMATCH")
        for reference in facts.durable_evidence:
            if reference.startswith("delivery-proof:"):
                from ai_software_engineer.knowledge.delivery import DeliveryWorkflowProof

                proof = self._records.get(
                    "delivery-proofs",
                    reference.removeprefix("delivery-proof:"),
                    DeliveryWorkflowProof,
                )
                proof.validate_integrity()
                expected_binding = proof.consultation_binding
                if name == "finish-work" and expected_binding is not None:
                    expected_binding = expected_binding.model_copy(
                        update={
                            "role": TeamRole.MANAGER,
                            "run_id": "run_finish_" + proof.proof_sha256[:32],
                        }
                    )
                if (
                    proof.task_id != facts.binding.task_id
                    or proof.target_status != _DELIVERY_TARGETS.get(name)
                    or expected_binding != facts.binding
                    or not proof.final_context_id
                    or proof.final_context_id != facts.final_context_id
                    or not proof.candidate_revision
                    or proof.candidate_revision != facts.candidate_revision
                    or proof.required_acceptance_ids != facts.required_acceptance_ids
                    or proof.covered_acceptance_ids != facts.covered_acceptance_ids
                    or proof.independent_agent_ids != facts.independent_agent_ids
                ):
                    raise KnowledgeError("SKILL_DELIVERY_PROOF_MISMATCH")
                continue
            if reference.startswith("stage-proof:"):
                from ai_software_engineer.knowledge.stages import StageWorkflowProof
                from ai_software_engineer.multi_directory.models import JointCheckpoint

                proof_stage = self._records.get(
                    "stage-proofs", reference.removeprefix("stage-proof:"), StageWorkflowProof
                )
                proof_stage.validate_integrity()
                if (
                    self._records.get(
                        "stage-checkpoints",
                        proof_stage.checkpoint.checkpoint_sha256,
                        JointCheckpoint,
                    )
                    != proof_stage.checkpoint
                ):
                    raise KnowledgeError("SKILL_STAGE_PROOF_MISMATCH")
                proof_stage.validate_for(name, facts)
                continue
            if reference == "knowledge-manifest:" + manifest.manifest_sha256:
                continue
            if not reference.startswith("knowledge-evidence:"):
                raise KnowledgeError("SKILL_EVIDENCE_UNVERIFIED")
            evidence_id = reference.removeprefix("knowledge-evidence:")
            if evidence_id not in manifest.evidence_ids:
                raise KnowledgeError("SKILL_EVIDENCE_UNVERIFIED")
        reasons = []
        if name in _STAGE_SKILLS and not any(
            ref.startswith("stage-proof:") for ref in facts.durable_evidence
        ):
            reasons.append("DURABLE_STAGE_PROOF_REQUIRED")
        if name in _DELIVERY_TARGETS and (
            not facts.required_acceptance_ids
            or not any(ref.startswith("delivery-proof:") for ref in facts.durable_evidence)
        ):
            reasons.append("DURABLE_DELIVERY_PROOF_REQUIRED")
        if not facts.durable_evidence:
            reasons.append("MISSING_EVIDENCE")
        if facts.unresolved_blocking_gap_ids:
            reasons.append("UNRESOLVED_KNOWLEDGE_GAP")
        if set(facts.required_acceptance_ids) != set(facts.covered_acceptance_ids):
            reasons.append("ACCEPTANCE_COVERAGE")
        if name == "finish-work" and (
            len(facts.independent_agent_ids) != 3 or len(set(facts.independent_agent_ids)) != 3
        ):
            reasons.append("INDEPENDENT_VERIFICATION_REQUIRED")
        provisional = WorkflowSkillEvidence(
            definition=definition,
            facts=facts,
            status="REJECTED" if reasons else "PASSED",
            reasons=tuple(reasons),
            evidence_sha256="0" * 64,
        )
        sealed = provisional.model_copy(
            update={
                "evidence_sha256": digest(
                    provisional.model_dump(mode="json", exclude={"evidence_sha256"})
                )
            }
        )
        return self._records.put("workflow-evidence", sealed.evidence_sha256, sealed)

    def require(
        self,
        binding: KnowledgeRunBinding,
        required: tuple[SkillName, ...],
        evidence_ids: tuple[str, ...],
    ) -> None:
        facts = tuple(
            self._records.get("workflow-evidence", key, WorkflowSkillEvidence)
            for key in evidence_ids
        )
        for fact in facts:
            fact.validate_integrity()
            if (
                fact.facts.binding != binding
                or fact.status != "PASSED"
                or fact.definition not in self.definitions(binding.role)
            ):
                raise KnowledgeError("WORKFLOW_GATE_REJECTED")
        if not set(required) <= {fact.definition.name for fact in facts}:
            raise KnowledgeError("WORKFLOW_GATE_MISSING")
