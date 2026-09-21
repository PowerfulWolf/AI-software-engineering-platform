"""Upstream skills require verified stage facts and persisted receipts, not consultation."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.knowledge.stages import StageWorkflowGate, StageWorkflowProof
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.knowledge.workflow import WorkflowSkillEvidence, WorkflowSkillRegistry
from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.planning import joint_planning_decision
from ai_software_engineer.multi_directory.service import JointDeliveryService
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.manager.test_joint_planner_feedback import DeliveryReached, PlanningBackend
from tests.manager.test_single_repository_acceptance import _single_checkpoint
from tests.planning.test_joint_gate import _seed


def _gate(tmp_path: Path, checkpoint: JointCheckpoint) -> StageWorkflowGate:
    journal = JointJournal(tmp_path / "journal")
    journal.append(checkpoint, expected=None)
    return StageWorkflowGate(journal, KnowledgeRecordStore(tmp_path / "knowledge"))


def test_start_requires_complete_preparation_and_replays_exact_receipt(tmp_path: Path) -> None:
    base = _single_checkpoint(tmp_path)
    cp = JointCheckpoint.seal(
        {
            **base.to_wire(),
            "stage": JointStage.PREPARING,
            "product_spec": None,
            "approval": None,
            "design": None,
            "plan": None,
            "children": (),
            "integration": None,
        }
    )
    gate = _gate(tmp_path, cp)
    evidence = gate.require("start", cp)
    assert evidence.status == "PASSED"
    assert gate.require("start", cp) == evidence
    proof = gate.records.list("stage-proofs", StageWorkflowProof)[0]
    proof.validate_integrity()
    assert proof.checkpoint == cp and proof.skill_name == "start"
    missing = cp.model_copy(update={"preparations": ()})
    with pytest.raises(KnowledgeError, match="NOT_CURRENT"):
        gate.require("start", missing)


def test_architecture_gate_cannot_approve_write_escape(tmp_path: Path) -> None:
    base = _single_checkpoint(tmp_path)
    assert base.design is not None
    cp = JointCheckpoint.seal(
        {
            **base.to_wire(),
            "stage": JointStage.DESIGNING,
            "design": None,
            "plan": None,
            "children": (),
            "integration": None,
        }
    )
    gate = _gate(tmp_path, cp)
    candidate = base.design
    evidence = gate.require("architecture-check", cp, design=candidate)
    assert evidence.facts.covered_acceptance_ids == ("ac_001_001",)
    unit = candidate.units[0]
    bad_component = unit.design.components[0].model_copy(update={"affected_paths": ("../escape",)})
    bad = candidate.model_copy(
        update={
            "units": (
                unit.model_copy(
                    update={
                        "design": unit.design.model_copy(update={"components": (bad_component,)})
                    }
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="selected directories"):
        gate.require("architecture-check", cp, design=bad)
    assert len(gate.records.list("stage-proofs", StageWorkflowProof)) == 1


def test_simple_service_requires_planning_receipts_with_zero_planner_calls(tmp_path: Path) -> None:
    service, backend, seed = _seed(tmp_path)
    with pytest.raises(DeliveryReached):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    assert backend.inputs == []
    records = KnowledgeRecordStore(service.journal.directory(seed.delivery_id) / "knowledge")
    receipts = records.list("workflow-evidence", WorkflowSkillEvidence)
    assert {item.definition.name for item in receipts} == {"planning-gate", "plan"}
    assert all(item.status == "PASSED" for item in receipts)
    for proof in records.list("stage-proofs", StageWorkflowProof):
        proof.validate_integrity()
        assert proof.checkpoint in service.journal.history(seed.delivery_id)


def test_missing_stage_receipt_prevents_repository_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, seed = _seed(tmp_path)

    def reject(*_: object, **__: object) -> None:
        raise KnowledgeError("WORKFLOW_GATE_MISSING")

    monkeypatch.setattr(WorkflowSkillRegistry, "require", reject)
    with pytest.raises(KnowledgeError, match="WORKFLOW_GATE_MISSING"):
        service.resume(ResumeProjectDelivery(delivery_id=seed.delivery_id))
    current = service.journal.current(seed.delivery_id)
    assert current is not None and current.stage is JointStage.PLANNING
    assert current.plan is None and not current.children


def test_resealed_proof_cannot_change_context_or_claim_false_coverage(tmp_path: Path) -> None:
    base = _single_checkpoint(tmp_path)
    planning = JointCheckpoint.seal(
        {
            **base.to_wire(),
            "stage": JointStage.PLANNING,
            "plan": None,
            "children": (),
            "integration": None,
        }
    )
    cp = JointCheckpoint.seal(
        {
            **planning.to_wire(),
            "planning_decision": joint_planning_decision(planning),
        }
    )
    gate = _gate(tmp_path, cp)
    receipt = gate.require("planning-gate", cp)
    proof = gate.records.list("stage-proofs", StageWorkflowProof)[0]
    for changes in (
        {"binding": proof.binding.model_copy(update={"source_revision": "f" * 40})},
        {"covered_acceptance_ids": ("ac_fake",)},
    ):
        forged = proof.model_copy(update=changes)
        forged = forged.model_copy(
            update={
                "proof_sha256": digest(forged.model_dump(mode="json", exclude={"proof_sha256"}))
            }
        )
        with pytest.raises(KnowledgeError, match="STAGE_PROOF"):
            forged.validate_integrity()
    with pytest.raises(KnowledgeError, match="MISMATCH"):
        proof.validate_for("plan", receipt.facts)
    WorkflowSkillRegistry(KnowledgeRecordStore(gate.records.root)).require(
        receipt.facts.binding, ("planning-gate",), (receipt.evidence_sha256,)
    )


def test_failure_analysis_and_recovery_require_actual_failure_facts(tmp_path: Path) -> None:
    cp = _single_checkpoint(tmp_path)
    gate = _gate(tmp_path, cp)
    for name in ("break-loop", "recovery"):
        assert gate.require(name, cp).status == "PASSED"
    healthy = JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "stage": JointStage.PLANNING,
            "plan": None,
            "children": (),
            "integration": None,
        }
    )
    other = _gate(tmp_path / "healthy", healthy)
    with pytest.raises(KnowledgeError, match="FAILURE_FACTS_REQUIRED"):
        other.require("break-loop", healthy)
    with pytest.raises(KnowledgeError, match="RECOVERY_CHECKPOINT"):
        other.require("recovery", healthy)


def test_intake_start_gate_runs_before_ready_for_discussion(tmp_path: Path) -> None:
    base = _single_checkpoint(tmp_path)
    assert base.plan is not None
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Project")
    service = JointDeliveryService(backend=PlanningBackend(base.plan), team=team, project=project)
    cp = JointCheckpoint.seal(
        {
            **base.to_wire(),
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "stage": JointStage.PREPARING,
            "product_spec": None,
            "approval": None,
            "design": None,
            "plan": None,
            "children": (),
            "integration": None,
        }
    )
    service.journal.append(cp, expected=None)
    result = service.resume(ResumeProjectDelivery(delivery_id=cp.delivery_id)).checkpoint
    assert result.stage is JointStage.READY_FOR_DISCUSSION
    records = KnowledgeRecordStore(service.journal.directory(cp.delivery_id) / "knowledge")
    assert [p.skill_name for p in records.list("stage-proofs", StageWorkflowProof)] == ["start"]


def test_repeated_native_child_failure_requires_break_loop_without_changing_verdict(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.domain.enums import TaskStatus
    from ai_software_engineer.knowledge.stages import repeated_child_failure
    from ai_software_engineer.manager.delivery_checkpoint import (
        DeliveryFailureCode,
        DeliveryNextAction,
        DeliveryStage,
        ProjectDeliveryCheckpoint,
    )

    base = _single_checkpoint(tmp_path)
    child = base.children[0]
    failed = ProjectDeliveryCheckpoint.create(
        **{
            **child.checkpoint.to_wire(),
            "stage": DeliveryStage.BLOCKED,
            "task_status": TaskStatus.BLOCKED,
            "failure_code": DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED,
            "failure_summary": "Three Coder attempts exhausted after native verification.",
            "next_action": DeliveryNextAction.REQUEST_HUMAN,
        }
    )
    cp = JointCheckpoint.seal(
        {
            **base.to_wire(),
            "integration": None,
            "children": (child.model_copy(update={"checkpoint": failed}),),
        }
    )
    assert repeated_child_failure(cp)
    gate = _gate(tmp_path, cp)
    receipt = gate.require("break-loop", cp)
    assert receipt.status == "PASSED"
    proof = gate.records.list("stage-proofs", StageWorkflowProof)[0]
    assert proof.checkpoint.children[0].checkpoint == failed
    assert cp.children[0].checkpoint.task_status is TaskStatus.BLOCKED


def test_knowledge_recovery_requires_exact_approved_resolution_lineage(tmp_path: Path) -> None:
    from ai_software_engineer.knowledge.gaps import (
        KnowledgeGapService,
        KnowledgeResolution,
        KnowledgeResolutionSource,
    )
    from ai_software_engineer.knowledge.models import KnowledgeSearchRequest, text_digest
    from ai_software_engineer.knowledge.retrieval import MarkdownKnowledgeRetrieval
    from ai_software_engineer.knowledge.skills import KnowledgeSkillRegistry
    from ai_software_engineer.knowledge.stages import _snapshot
    from tests.knowledge.test_gaps import Approval
    from tests.knowledge.test_retrieval_contract import binding

    base = _single_checkpoint(tmp_path)
    frozen = _snapshot(base)
    bound = binding(frozen)
    records = KnowledgeRecordStore(tmp_path / "knowledge")
    skills = KnowledgeSkillRegistry(bound, frozen, MarkdownKnowledgeRetrieval(), records)
    skills.search_knowledge(
        KnowledgeSearchRequest(operation_id="missing_sla", binding=bound, query="refund SLA")
    )
    gaps = KnowledgeGapService(records)
    gap = gaps.report(
        manifest=skills.manifest(),
        question="SLA?",
        required_decision="Supply SLA",
        reason="MISSING",
        severity="BLOCKING",
        impact="Cannot complete",
        risk="high",
    )
    cp = JointCheckpoint.seal(
        {
            **base.to_wire(),
            "stage": JointStage.WAITING_HUMAN,
            "knowledge_gap_id": gap.gap_id,
            "knowledge_wait_stage": JointStage.PLANNING,
        }
    )
    gate = _gate(tmp_path, cp)
    with pytest.raises(KnowledgeError, match="RESOLUTION_REQUIRED"):
        gate.require("recovery", cp, gap=gap)
    resolution = KnowledgeResolution(
        gap_id=gap.gap_id,
        previous_run_id=gap.binding.run_id,
        answer="Five days",
        sources=(
            KnowledgeResolutionSource(
                uri="human://decision/approved",
                sha256=text_digest("Five days"),
                content="Five days",
            ),
        ),
        approval_reference="human_action_exact",
        approved_by="human_owner",
        resolution_id="0" * 64,
    )
    resolution = resolution.model_copy(
        update={
            "resolution_id": digest(resolution.model_dump(mode="json", exclude={"resolution_id"}))
        }
    )
    gaps.resolve(resolution, Approval(resolution))
    assert gate.require("recovery", cp, gap=gap, resolution=resolution).status == "PASSED"
    forged = resolution.model_copy(update={"previous_run_id": "run_foreign_001"})
    forged = forged.model_copy(
        update={"resolution_id": digest(forged.model_dump(mode="json", exclude={"resolution_id"}))}
    )
    with pytest.raises(KnowledgeError, match="RESOLUTION_NOT_COMMITTED"):
        gate.require("recovery", cp, gap=gap, resolution=forged)

    current = JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "sequence": cp.sequence + 1,
            "previous_checkpoint_sha256": cp.checkpoint_sha256,
            "next_action": "Current checkpoint advanced after the knowledge wait.",
        }
    )
    gate.journal.append(current, expected=cp.checkpoint_sha256)
    assert (
        gate.require(
            "recovery",
            cp,
            gap=gap,
            resolution=resolution,
            historical=True,
        ).status
        == "PASSED"
    )
    with pytest.raises(KnowledgeError, match="HISTORICAL_ONLY_RECOVERY"):
        gate.require("architecture-check", cp, historical=True)


def test_service_requires_architecture_receipt_before_design_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _single_checkpoint(tmp_path)
    assert base.plan is not None and base.design is not None
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Project")
    backend = PlanningBackend(base.plan)
    service = JointDeliveryService(backend=backend, team=team, project=project)
    cp = JointCheckpoint.seal(
        {
            **base.to_wire(),
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "stage": JointStage.DESIGNING,
            "design": None,
            "plan": None,
            "children": (),
            "integration": None,
        }
    )
    service.journal.append(cp, expected=None)
    monkeypatch.setattr(service, "_produce", lambda *_: base.design)
    with pytest.raises(DeliveryReached):
        service.resume(ResumeProjectDelivery(delivery_id=cp.delivery_id))
    records = KnowledgeRecordStore(service.journal.directory(cp.delivery_id) / "knowledge")
    assert {p.skill_name for p in records.list("stage-proofs", StageWorkflowProof)} == {
        "architecture-check",
        "planning-gate",
        "plan",
    }
    assert backend.inputs == []


def test_historical_planning_feedback_cannot_mask_later_integration_failure(tmp_path: Path) -> None:
    from ai_software_engineer.multi_directory.models import digest as joint_digest
    from ai_software_engineer.multi_directory.planning import compile_joint_plan, rejection_feedback

    base = _single_checkpoint(tmp_path)
    assert base.plan is not None and base.integration is not None
    feedback = rejection_feedback(base.plan, "PlanCoverageError")
    planning = JointCheckpoint.seal(
        {
            **base.to_wire(),
            "stage": JointStage.PLANNING,
            "plan": None,
            "planning_feedback": feedback,
            "integration": None,
        }
    )
    revised = compile_joint_plan(planning, base.plan)
    failed = JointCheckpoint.seal(
        {
            **base.to_wire(),
            "planning_feedback": feedback,
            "plan": revised,
            "integration": base.integration.model_copy(
                update={"plan_sha256": joint_digest(revised)}
            ),
        }
    )
    gate = _gate(tmp_path, failed)
    assert gate.require("break-loop", failed).status == "PASSED"
    assert gate.require("recovery", failed).status == "PASSED"
