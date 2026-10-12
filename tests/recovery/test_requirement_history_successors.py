"""Warm exact-byte receipts retain the original complex successor policies."""

from pathlib import Path

import pytest

from ai_software_engineer.domain import TeamRole
from ai_software_engineer.domain.coordination import (
    ManagerCoordinationAdvice,
    ManagerCoordinationDraft,
)
from ai_software_engineer.execution import CommandResult
from ai_software_engineer.knowledge.context import snapshot_from_sources
from ai_software_engineer.knowledge.gaps import KnowledgeGap
from ai_software_engineer.knowledge.models import KnowledgeRunBinding
from ai_software_engineer.knowledge.models import digest as knowledge_digest
from ai_software_engineer.knowledge.recheck import DesignKnowledgeRecheck
from ai_software_engineer.manager.stage_coordination import stage_facts_sha256
from ai_software_engineer.multi_directory.history_observation import NativeHistoryJournal
from ai_software_engineer.multi_directory.models import (
    Candidate,
    IntegrationEvidence,
    IntegrationRetryApproval,
    IntegrationRetryProposal,
    JointCheckpoint,
    JointStage,
    digest,
)
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.read_record_scope import recovery_record_read_scope
from tests.manager.test_joint_contracts import checkpoint
from tests.manager.test_joint_planner_feedback import _done_child


def _successor(previous: JointCheckpoint, **changes: object) -> JointCheckpoint:
    return JointCheckpoint.seal(
        {
            **previous.to_wire(),
            "sequence": previous.sequence + 1,
            "previous_checkpoint_sha256": previous.checkpoint_sha256,
            **changes,
        }
    )


@pytest.mark.parametrize("fault", ("coordination", "approval"))
def test_warm_resealed_tail_keeps_exact_advice_and_approved_product_rules(
    tmp_path: Path, fault: str
) -> None:
    first = checkpoint(tmp_path)
    journal = JointJournal(tmp_path / "history")
    journal.append(first, expected=None)
    advice = ManagerCoordinationAdvice(
        requirement_id=first.delivery_id,
        stage=first.stage.value,
        source_facts_sha256=stage_facts_sha256(first),
        source_checkpoint_sha256=first.checkpoint_sha256,
        input_sha256="0" * 64,
        manager_run_id="run_advice",
        provider="offline",
        model="offline",
        draft=ManagerCoordinationDraft(
            action="WAITING_HUMAN",
            summary="Inspect the original facts",
            next_action="Review current evidence",
            responsible_actor="engineering authority",
            resume_condition="The exact source facts remain current",
        ),
    )
    second = _successor(first, coordination=advice if fault == "coordination" else None)
    journal.append(second, expected=first.checkpoint_sha256)
    compact = NativeHistoryJournal(journal.root, read_only=True)
    with recovery_record_read_scope():
        assert compact.native_prefix(first.delivery_id).current == second
        if fault == "coordination":
            changed = JointCheckpoint.seal(
                {
                    **second.to_wire(),
                    "coordination": advice.model_copy(update={"source_facts_sha256": "f" * 64}),
                }
            )
            message = "unchanged source facts"
        else:
            assert second.approval is not None
            changed = JointCheckpoint.seal(
                {
                    **second.to_wire(),
                    "approval": second.approval.model_copy(update={"reference": "new approval"}),
                }
            )
            message = "approved joint product is immutable"
        # External corruption deliberately bypasses append, which already rejects
        # this change. The fixed read codec must independently reject it as well.
        (journal.directory(first.delivery_id) / "000002.json").write_text(changed.model_dump_json())
        with pytest.raises(ValueError, match=message):
            compact.native_prefix(first.delivery_id)


def _integration_checkpoint(tmp_path: Path, *, completed: bool) -> JointCheckpoint:
    cp = checkpoint(tmp_path)
    assert cp.plan is not None
    children = tuple(_done_child(cp, index) for index in range(len(cp.scope.units)))
    candidates = tuple(
        Candidate(unit_id=child.unit_id, revision=child.checkpoint.candidate_revision or "missing")
        for child in children
    )
    evidence = IntegrationEvidence(
        plan_sha256=digest(cp.plan),
        candidates=candidates,
        checks=tuple(
            CommandResult(
                argv=check.argv,
                cwd=str(tmp_path),
                returncode=0 if completed else 1,
                stdout="Ran 1 test" if completed else "",
                stderr="" if completed else "One assertion failed",
                duration_ms=1,
            )
            for check in cp.plan.integration_checks
        ),
    )
    return JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "stage": JointStage.DONE if completed else JointStage.BLOCKED,
            "children": children,
            "integration": evidence,
            "attempts": {"integration": 3},
        }
    )


@pytest.mark.parametrize("fault", ("source", "removed", "budget"))
def test_warm_integration_retry_preserves_exact_approval_and_consumed_budget(
    tmp_path: Path, fault: str
) -> None:
    first = _integration_checkpoint(tmp_path, completed=False)
    assert first.integration is not None
    approved = IntegrationRetryApproval(
        proposal=IntegrationRetryProposal(
            checkpoint_sha256=first.checkpoint_sha256, candidates=first.integration.candidates
        ),
        reference="approved-one-exact-retry",
        approved_at=first.submitted_at,
    )
    second = _successor(first, integration_retry_approval=approved)
    third = _successor(second, attempts={"integration": 4})
    journal = JointJournal(tmp_path / "history")
    for previous, cp in ((None, first), (first, second), (second, third)):
        journal.append(cp, expected=previous.checkpoint_sha256 if previous else None)
    compact = NativeHistoryJournal(journal.root, read_only=True)
    with recovery_record_read_scope():
        compact.native_prefix(first.delivery_id)
        if fault == "source":
            changed = JointCheckpoint.seal(
                {
                    **second.to_wire(),
                    "integration_retry_approval": approved.model_copy(
                        update={
                            "proposal": approved.proposal.model_copy(
                                update={"checkpoint_sha256": "f" * 64}
                            )
                        }
                    ),
                }
            )
        elif fault == "removed":
            changed = _successor(third, integration_retry_approval=None)
        else:
            changed = _successor(third, attempts={"integration": 3})
        (journal.directory(first.delivery_id) / f"{changed.sequence:06d}.json").write_text(
            changed.model_dump_json()
        )
        with pytest.raises(ValueError, match=r"exact immutable approval|cannot be reset"):
            compact.native_prefix(first.delivery_id)


def test_warm_knowledge_recheck_requires_exact_previous_wait_handoff(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.approval is not None
    snapshot = snapshot_from_sources(
        team_id=cp.team_id,
        project_id=cp.project_id,
        requirement_id=cp.delivery_id,
        repository_ids=tuple(sorted(p.result.repository_id for p in cp.preparations)),
        sources=(),
    )
    gap = KnowledgeGap(
        binding=KnowledgeRunBinding(
            run_id="run_original_design",
            role=TeamRole.DESIGNER,
            team_id=cp.team_id,
            project_id=cp.project_id,
            requirement_id=cp.delivery_id,
            repository_ids=snapshot.repository_ids,
            source_revision=knowledge_digest(
                tuple((u.id, u.base_revision) for u in cp.scope.units)
            ),
            context_manifest_id="ctx_" + "0" * 64,
            snapshot_sha256=snapshot.snapshot_sha256,
        ),
        question="Which verification is required?",
        required_decision="Inspect the existing engineering rules",
        reason="UNVERIFIABLE",
        severity="BLOCKING",
        impact="Design cannot continue before inspection",
        risk="medium",
        evidence_ids=("0" * 64,),
        manifest_sha256="0" * 64,
        gap_id="0" * 64,
    )
    gap = gap.model_copy(
        update={"gap_id": knowledge_digest(gap.model_dump(mode="json", exclude={"gap_id"}))}
    )
    first = JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "stage": JointStage.WAITING_HUMAN,
            "knowledge_wait_stage": JointStage.DESIGNING,
            "knowledge_gap_id": gap.gap_id,
            "design": None,
            "plan": None,
        }
    )
    recheck = DesignKnowledgeRecheck(
        gap=gap,
        source_checkpoint_sha256=first.checkpoint_sha256,
        product_spec_sha256=cp.approval.product_spec_sha256,
        operator_id="engineer",
        request_reference="inspect-current-rules",
        requested_at=cp.submitted_at,
    )
    second = _successor(
        first,
        stage=JointStage.DESIGNING,
        knowledge_wait_stage=None,
        knowledge_gap_id=None,
        knowledge_rechecks=(recheck,),
    )
    journal = JointJournal(tmp_path / "history")
    journal.append(first, expected=None)
    journal.append(second, expected=first.checkpoint_sha256)
    compact = NativeHistoryJournal(journal.root, read_only=True)
    with recovery_record_read_scope():
        compact.native_prefix(first.delivery_id)
        changed = JointCheckpoint.seal(
            {
                **second.to_wire(),
                "knowledge_rechecks": (
                    recheck.model_copy(update={"source_checkpoint_sha256": "f" * 64}),
                ),
            }
        )
        (journal.directory(first.delivery_id) / "000002.json").write_text(changed.model_dump_json())
        with pytest.raises(ValueError, match="exact upstream handoff"):
            compact.native_prefix(first.delivery_id)


def test_warm_completed_delivery_still_rejects_any_append(tmp_path: Path) -> None:
    first = _integration_checkpoint(tmp_path, completed=True)
    journal = JointJournal(tmp_path / "history")
    journal.append(first, expected=None)
    compact = NativeHistoryJournal(journal.root, read_only=True)
    with recovery_record_read_scope():
        compact.native_prefix(first.delivery_id)
        changed = _successor(first, next_action="Attempt to reopen completed delivery")
        (journal.directory(first.delivery_id) / "000002.json").write_text(changed.model_dump_json())
        with pytest.raises(ValueError, match="completed joint delivery is immutable"):
            compact.native_prefix(first.delivery_id)
