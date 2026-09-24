"""Deterministic upstream workflow gates over verified Requirement journal facts."""

from __future__ import annotations

from typing import Literal

from ai_software_engineer.domain.enums import TaskStatus, TeamRole
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.context import snapshot_from_sources
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGap,
    KnowledgeGapService,
    KnowledgeResolution,
)
from ai_software_engineer.knowledge.models import (
    Digest,
    KnowledgeError,
    KnowledgeRunBinding,
    KnowledgeRunManifest,
    KnowledgeSnapshot,
    digest,
)
from ai_software_engineer.knowledge.recheck import rechecked_gap_ids
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.knowledge.workflow import (
    SkillName,
    WorkflowGateFacts,
    WorkflowSkillEvidence,
    WorkflowSkillRegistry,
)
from ai_software_engineer.manager.delivery_checkpoint import DeliveryFailureCode, DeliveryStage
from ai_software_engineer.manager.preparation import PrepareProjectStatus
from ai_software_engineer.multi_directory.models import (
    JointCheckpoint,
    JointExecutionPlan,
    JointStage,
    JointTechnicalDesign,
)
from ai_software_engineer.multi_directory.models import digest as stage_digest
from ai_software_engineer.multi_directory.planning import (
    compile_joint_plan,
    joint_planning_decision,
)
from ai_software_engineer.multi_directory.store import JointJournal

StageSkillName = Literal[
    "start", "architecture-check", "planning-gate", "plan", "recovery", "break-loop"
]
_ROLES: dict[StageSkillName, TeamRole] = {
    "start": TeamRole.MANAGER,
    "architecture-check": TeamRole.DESIGNER,
    "planning-gate": TeamRole.MANAGER,
    "plan": TeamRole.PLANNER,
    "recovery": TeamRole.MANAGER,
    "break-loop": TeamRole.MANAGER,
}


def repeated_child_failure(checkpoint: JointCheckpoint) -> bool:
    """Only native durable failure/attempt facts qualify; a pause is not a repeated failure."""
    if checkpoint.stage is not JointStage.BLOCKED or checkpoint.plan is None:
        return False
    prepared = {item.unit_id: item.result for item in checkpoint.preparations}
    units = {unit.id: unit for unit in checkpoint.scope.units}
    failed = False
    for child in checkpoint.children:
        native = child.checkpoint
        native.validate_integrity()
        if (
            child.unit_id not in prepared
            or child.unit_id not in units
            or (
                native.repository_id != prepared[child.unit_id].repository_id
                or native.repository_root != units[child.unit_id].root
            )
        ):
            raise KnowledgeError("STAGE_CHILD_BINDING")
        if (
            native.stage in {DeliveryStage.BLOCKED, DeliveryStage.FAILED}
            and native.task_status in {TaskStatus.BLOCKED, TaskStatus.FAILED}
            and (
                native.failure_code is DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED
                or native.stage_attempts.delivering >= 2
            )
        ):
            failed = True
    return failed


def _snapshot(checkpoint: JointCheckpoint) -> KnowledgeSnapshot:
    return snapshot_from_sources(
        team_id=checkpoint.team_id,
        project_id=checkpoint.project_id,
        requirement_id=checkpoint.delivery_id,
        repository_ids=tuple(sorted(p.result.repository_id for p in checkpoint.preparations)),
        sources=tuple(
            (prepared.result.repository_id, source)
            for prepared in checkpoint.preparations
            for source in prepared.context_sources
        ),
    )


class StageWorkflowProof(DomainModel):
    """Full facts permit replay of the gate; a digest or PASSED flag alone cannot."""

    skill_name: StageSkillName
    binding: KnowledgeRunBinding
    checkpoint: JointCheckpoint
    design: JointTechnicalDesign | None = None
    plan: JointExecutionPlan | None = None
    gap: KnowledgeGap | None = None
    resolution: KnowledgeResolution | None = None
    required_acceptance_ids: tuple[str, ...] = ()
    covered_acceptance_ids: tuple[str, ...] = ()
    proof_sha256: Digest

    def expected_binding(self) -> KnowledgeRunBinding:
        checkpoint = self.checkpoint
        identity = digest(
            (
                checkpoint.checkpoint_sha256,
                self.skill_name,
                stage_digest(self.design) if self.design else None,
                stage_digest(self.plan) if self.plan else None,
                self.gap.gap_id if self.gap else None,
                self.resolution.resolution_id if self.resolution else None,
            )
        )
        frozen = _snapshot(checkpoint)
        return KnowledgeRunBinding(
            run_id="run_stage_" + identity[:32],
            role=_ROLES[self.skill_name],
            team_id=checkpoint.team_id,
            project_id=checkpoint.project_id,
            requirement_id=checkpoint.delivery_id,
            repository_ids=frozen.repository_ids,
            source_revision=digest(tuple((u.id, u.base_revision) for u in checkpoint.scope.units)),
            context_manifest_id="ctx_" + identity,
            snapshot_sha256=frozen.snapshot_sha256,
        )

    def validate_integrity(self) -> None:
        StageWorkflowProof.model_validate(self.to_wire())
        self.checkpoint.validate_integrity()
        if self.proof_sha256 != digest(self.model_dump(mode="json", exclude={"proof_sha256"})):
            raise KnowledgeError("STAGE_PROOF_INTEGRITY")
        if self.binding != self.expected_binding():
            raise KnowledgeError("STAGE_PROOF_BINDING")
        required, covered = self.validated_coverage()
        if (self.required_acceptance_ids, self.covered_acceptance_ids) != (required, covered):
            raise KnowledgeError("STAGE_PROOF_COVERAGE")

    def validated_coverage(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        cp = self.checkpoint
        if self.skill_name != "architecture-check" and self.design is not None:
            raise KnowledgeError("STAGE_PROOF_UNEXPECTED_DESIGN")
        if self.skill_name != "plan" and self.plan is not None:
            raise KnowledgeError("STAGE_PROOF_UNEXPECTED_PLAN")
        if self.skill_name != "recovery" and (self.gap is not None or self.resolution is not None):
            raise KnowledgeError("STAGE_PROOF_UNEXPECTED_RESOLUTION")
        if self.skill_name == "start":
            if cp.stage is not JointStage.PREPARING:
                raise KnowledgeError("STAGE_START_CHECKPOINT")
            units = {unit.id: unit for unit in cp.scope.units}
            if {p.unit_id for p in cp.preparations} != set(units):
                raise KnowledgeError("STAGE_PREPARATION_INCOMPLETE")
            for prepared in cp.preparations:
                fact = prepared.result.preparation
                if prepared.result.status is not PrepareProjectStatus.PREPARED or fact is None:
                    raise KnowledgeError("STAGE_PREPARATION_INCOMPLETE")
                fact.validate_integrity()
                if (
                    (fact.team_id, fact.project_id, fact.repository_id)
                    != (cp.team_id, cp.project_id, prepared.result.repository_id)
                    or fact.repository_root != units[prepared.unit_id].root
                    or units[prepared.unit_id].base_revision is None
                ):
                    raise KnowledgeError("STAGE_PREPARATION_BINDING")
            return (), ()
        if self.skill_name == "recovery":
            self._validate_recovery()
            return (), ()
        if self.skill_name == "break-loop":
            if not self._failure_facts():
                raise KnowledgeError("STAGE_FAILURE_FACTS_REQUIRED")
            return (), ()
        if cp.product_spec is None or cp.approval is None:
            raise KnowledgeError("STAGE_APPROVED_PRODUCT_REQUIRED")
        required = tuple(sorted(cp.product_spec.acceptance_ids()))
        if self.skill_name == "architecture-check":
            if cp.stage is not JointStage.DESIGNING or self.design is None:
                raise KnowledgeError("STAGE_DESIGN_REQUIRED")
            self.design.validate_for(cp.scope, cp.product_spec)
            # Legacy proofs without an explicit readiness declaration remain replayable.
            if self.design.blocking_issues is not None:
                self.design.require_ready()
            covered = tuple(
                sorted(
                    {
                        item.acceptance_criterion_id
                        for unit in self.design.units
                        for item in unit.design.acceptance_mappings
                    }
                )
            )
            return required, covered
        if cp.stage is not JointStage.PLANNING or cp.design is None:
            raise KnowledgeError("STAGE_PLANNING_CHECKPOINT")
        if cp.planning_decision != joint_planning_decision(cp):
            raise KnowledgeError("STAGE_PLANNING_DECISION")
        if self.skill_name == "planning-gate":
            covered = tuple(
                sorted(
                    {
                        item.acceptance_criterion_id
                        for unit in cp.design.units
                        for item in unit.design.acceptance_mappings
                    }
                )
            )
            return required, covered
        if self.plan is None:
            raise KnowledgeError("STAGE_PLAN_REQUIRED")
        self.plan.validate_for(cp.scope, cp.product_spec, cp.design)
        if compile_joint_plan(cp, self.plan) != self.plan:
            raise KnowledgeError("STAGE_PLAN_COMPILATION")
        covered = tuple(
            sorted(
                {
                    criterion
                    for unit in self.plan.units
                    if unit.plan.work_graph is not None
                    for package in unit.plan.work_graph.packages
                    for criterion in package.acceptance_criterion_ids
                }
            )
        )
        return required, covered

    def _failure_facts(self) -> bool:
        cp = self.checkpoint
        if cp.stage is JointStage.PLANNING and cp.planning_feedback is not None:
            if cp.design is None:
                raise KnowledgeError("STAGE_FEEDBACK_CHECKPOINT")
            if cp.planning_feedback.previous_plan.design_sha256 != stage_digest(cp.design):
                raise KnowledgeError("STAGE_FEEDBACK_DESIGN")
            return True
        if repeated_child_failure(cp):
            return True
        return (
            cp.stage is JointStage.BLOCKED
            and cp.integration is not None
            and cp.plan is not None
            and cp.integration.plan_sha256 == stage_digest(cp.plan)
            and any(check.returncode != 0 for check in cp.integration.checks)
        )

    def _validate_recovery(self) -> None:
        cp = self.checkpoint
        if cp.stage is JointStage.WAITING_HUMAN and cp.knowledge_gap_id is not None:
            if self.gap is None or self.resolution is None or cp.knowledge_wait_stage is None:
                raise KnowledgeError("STAGE_KNOWLEDGE_RESOLUTION_REQUIRED")
            self.gap.validate_integrity()
            self.resolution.validate_integrity()
            if (
                self.gap.gap_id != cp.knowledge_gap_id
                or self.resolution.gap_id != self.gap.gap_id
                or self.resolution.previous_run_id != self.gap.binding.run_id
                or (
                    self.gap.binding.team_id,
                    self.gap.binding.project_id,
                    self.gap.binding.requirement_id,
                )
                != (cp.team_id, cp.project_id, cp.delivery_id)
                or not set(self.gap.binding.repository_ids) <= set(self.binding.repository_ids)
            ):
                raise KnowledgeError("STAGE_RESOLUTION_BINDING")
            return
        if self.gap is not None or self.resolution is not None:
            raise KnowledgeError("STAGE_RESOLUTION_CHECKPOINT")
        if cp.stage is not JointStage.BLOCKED or cp.plan is None:
            raise KnowledgeError("STAGE_RECOVERY_CHECKPOINT")
        if self._failure_facts():
            return
        if not cp.children:
            raise KnowledgeError("STAGE_RECOVERY_FACTS_REQUIRED")
        for child in cp.children:
            child.checkpoint.validate_integrity()
        if all(child.checkpoint.stage is DeliveryStage.DONE for child in cp.children):
            raise KnowledgeError("STAGE_RECOVERY_FACTS_REQUIRED")

    def validate_for(self, name: SkillName, facts: WorkflowGateFacts) -> None:
        if (
            name != self.skill_name
            or facts.binding != self.binding
            or facts.required_acceptance_ids != self.required_acceptance_ids
            or facts.covered_acceptance_ids != self.covered_acceptance_ids
            or facts.independent_agent_ids
            or facts.final_context_id
            or facts.candidate_revision
        ):
            raise KnowledgeError("SKILL_STAGE_PROOF_MISMATCH")


class StageWorkflowGate:
    """Publishes required receipts before the next stage action, without a model call."""

    def __init__(self, journal: JointJournal, records: KnowledgeRecordStore) -> None:
        self.journal, self.records = journal, records

    def require(
        self,
        name: StageSkillName,
        checkpoint: JointCheckpoint,
        *,
        design: JointTechnicalDesign | None = None,
        plan: JointExecutionPlan | None = None,
        gap: KnowledgeGap | None = None,
        resolution: KnowledgeResolution | None = None,
        resolution_records: KnowledgeRecordStore | None = None,
        historical: bool = False,
    ) -> WorkflowSkillEvidence:
        if historical and name != "recovery":
            raise KnowledgeError("STAGE_HISTORICAL_ONLY_RECOVERY")
        current = self.journal.current(checkpoint.delivery_id)
        if current != checkpoint and not (
            historical
            and current is not None
            and any(
                item.checkpoint_sha256 == checkpoint.checkpoint_sha256
                for item in self.journal.history(checkpoint.delivery_id)
            )
        ):
            raise KnowledgeError("STAGE_CHECKPOINT_NOT_CURRENT")
        if gap is not None and resolution is not None:
            source = resolution_records or self.records
            if (
                source.get("gaps", gap.gap_id, KnowledgeGap) != gap
                or source.get("gap-resolutions", gap.gap_id, KnowledgeResolution) != resolution
            ):
                raise KnowledgeError("STAGE_RESOLUTION_NOT_COMMITTED")
        frozen = _snapshot(checkpoint)
        placeholder = KnowledgeRunBinding(
            run_id="run_stage_pending",
            role=_ROLES[name],
            team_id=checkpoint.team_id,
            project_id=checkpoint.project_id,
            requirement_id=checkpoint.delivery_id,
            repository_ids=frozen.repository_ids,
            source_revision="pending",
            context_manifest_id="ctx_" + "0" * 64,
            snapshot_sha256=frozen.snapshot_sha256,
        )
        provisional = StageWorkflowProof(
            skill_name=name,
            binding=placeholder,
            checkpoint=checkpoint,
            design=design,
            plan=plan,
            gap=gap,
            resolution=resolution,
            proof_sha256="0" * 64,
        )
        provisional = provisional.model_copy(update={"binding": provisional.expected_binding()})
        required, covered = provisional.validated_coverage()
        provisional = provisional.model_copy(
            update={
                "required_acceptance_ids": required,
                "covered_acceptance_ids": covered,
            }
        )
        proof = provisional.model_copy(
            update={
                "proof_sha256": digest(
                    provisional.model_dump(mode="json", exclude={"proof_sha256"})
                )
            }
        )
        proof.validate_integrity()
        self.records.put("snapshots", frozen.snapshot_sha256, frozen)
        self.records.put("stage-checkpoints", checkpoint.checkpoint_sha256, checkpoint)
        self.records.put("stage-proofs", proof.proof_sha256, proof)
        provisional_manifest = KnowledgeRunManifest(
            binding=proof.binding,
            snapshot_sha256=frozen.snapshot_sha256,
            evidence_ids=(),
            citations=(),
            manifest_sha256="0" * 64,
        )
        manifest = provisional_manifest.model_copy(
            update={
                "manifest_sha256": digest(
                    provisional_manifest.model_dump(mode="json", exclude={"manifest_sha256"})
                )
            }
        )
        self.records.put("manifests", manifest.manifest_sha256, manifest)
        facts = WorkflowGateFacts(
            binding=proof.binding,
            knowledge_manifest_sha256=manifest.manifest_sha256,
            durable_evidence=("stage-proof:" + proof.proof_sha256,),
            required_acceptance_ids=required,
            covered_acceptance_ids=covered,
            unresolved_blocking_gap_ids=tuple(
                item.gap_id
                for item in KnowledgeGapService(self.records).unresolved(proof.binding)
                if item.gap_id
                not in rechecked_gap_ids(checkpoint.knowledge_rechecks or (), proof.binding)
            ),
        )
        registry = WorkflowSkillRegistry(self.records)
        evidence = registry.invoke(name, "v1", facts)
        registry.require(proof.binding, (name,), (evidence.evidence_sha256,))
        return evidence
