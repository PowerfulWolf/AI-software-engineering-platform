"""Same-source capacity epochs preserve accepted progress, candidates and findings."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.artifacts import seal_artifact
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.artifact import (
    CoderProgressArtifact,
    Finding,
    ImplementationReportArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.enums import FindingSeverity, QaReportStatus, ReviewVerdict
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode, BaselinePurpose
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.git.worktree import WorktreeCaptureRejected
from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionReservation,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
    require_context_capacity_binding,
)
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.orchestration.context import FileRunContextBuilder
from ai_software_engineer.recovery.models import digest
from tests.domain.factories import (
    make_coder_progress_artifact,
    make_implementation_artifact,
    make_qa_artifact,
    make_review_artifact,
)
from tests.git.test_worktree import _git
from tests.manager.test_execution_baseline import Setup, setup
from tests.orchestration.test_runner import _definitions


def _capacity_setup(tmp_path: Path) -> Setup:
    fixture = setup(tmp_path)
    facts = fixture.collector.facts.model_copy(
        update={
            "target_native_rules_sha256": fixture.collector.facts.source_native_rules_sha256,
            "context_capacity_receipt_sha256": "c" * 64,
            "continuation": BaselineExecutionReservation(
                current_attempt=1,
                next_execution_attempt=1,
                retry_cause="uninvoked",
                reservation_already_applied=True,
            ),
            "source_artifact_ids": (
                "art_impl_001",
                "art_progress_001",
                "art_qa_001",
                "art_review_001",
            ),
            "implementation_artifact_id": "art_impl_001",
            "progress_artifact_id": "art_progress_001",
        }
    )
    fixture.collector.facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    return fixture


def _pause(plan: ExecutionBaselinePlan) -> BaselineOperatorAuthorization:
    return BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact capacity pause",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
    )


def test_capacity_epoch_keeps_descendant_candidate_progress_and_full_rejection_findings(
    tmp_path: Path,
) -> None:
    fixture = _capacity_setup(tmp_path)
    facts, source = fixture.collector.facts, fixture.worktree.head_revision
    assert source != facts.task.base_ref
    inventory = capture_mutation_inventory(fixture.worktree.path)
    plan = fixture.service.propose(None, purpose=BaselinePurpose.CONTEXT_CAPACITY_RESUME)
    binding = fixture.service.execute(plan.plan_sha256, authority=_pause(plan))
    assert binding.execution_base_ref == facts.task.base_ref
    assert binding.execution_source_revision == source
    assert binding.superseded_implementation_artifact_id is None
    assert binding.superseded_progress_artifact_id is None
    assert binding.source_artifact_ids == facts.source_artifact_ids
    assert capture_mutation_inventory(fixture.worktree.path) == inventory
    assert _git(fixture.worktree.path, "rev-parse", "HEAD") == source

    implementation_draft = make_implementation_artifact()
    implementation = seal_artifact(
        implementation_draft.model_copy(
            update={
                "source_revision": source,
                "content": implementation_draft.content.model_copy(update={"commit_sha": source}),
            }
        ),
        validated_at=datetime.now(UTC),
    )
    progress = seal_artifact(
        make_coder_progress_artifact().model_copy(update={"source_revision": source}),
        validated_at=datetime.now(UTC),
    )
    assert isinstance(implementation, ImplementationReportArtifact)
    assert isinstance(progress, CoderProgressArtifact)
    qa_draft, review_draft = make_qa_artifact(), make_review_artifact()
    qa_finding = Finding(
        finding_id="finding_qa_exact",
        severity=FindingSeverity.MAJOR,
        message="Preserve the exact QA rejected edge case",
        file="src/app.py",
        line=1,
        evidence_ids=(qa_draft.evidence[0].evidence_id,),
        recommendation="Fix the rejected edge case and rerun this exact evidence",
    )
    review_finding = Finding(
        finding_id="finding_review_exact",
        severity=FindingSeverity.MAJOR,
        message="Preserve the exact reviewer rejection",
        file="src/app.py",
        line=2,
        evidence_ids=(review_draft.evidence[0].evidence_id,),
        recommendation="Apply the original review finding before independent re-review",
    )
    qa = seal_artifact(
        qa_draft.model_copy(
            update={
                "source_revision": source,
                "content": qa_draft.content.model_copy(
                    update={"status": QaReportStatus.FAIL, "findings": (qa_finding,)}
                ),
            }
        ),
        validated_at=datetime.now(UTC),
    )
    review = seal_artifact(
        review_draft.model_copy(
            update={
                "source_revision": source,
                "content": review_draft.content.model_copy(
                    update={"verdict": ReviewVerdict.REJECT, "findings": (review_finding,)}
                ),
            }
        ),
        validated_at=datetime.now(UTC),
    )
    assert isinstance(qa, QaReportArtifact) and isinstance(review, ReviewReportArtifact)
    resolver = StoredCoderExecutionInputResolver(fixture.service.store)
    resolved = resolver.current(facts.task, implementation=implementation, progress=progress)
    assert resolved.source_revision == source and resolved.active_progress == progress
    assert resolved.superseded_artifact_ids == frozenset()
    context = FileRunContextBuilder(fixture.repository).build(
        facts.task,
        _definitions()[AgentRole.CODER],
        attempt=1,
        candidate_revision=resolved.source_revision,
        input_artifacts=(progress, qa, review),
    )
    contents = "\n".join(section.content for section in context.sections if not section.truncated)
    assert qa_finding.message in contents and review_finding.message in contents
    assert qa_finding.recommendation is not None and review_finding.recommendation is not None
    assert qa_finding.recommendation in contents and review_finding.recommendation in contents
    assert fixture.service.store.bindings_for_task(facts.task.id) == (binding,)


@pytest.mark.parametrize("drift", ["receipt", "source_artifacts", "source"])
def test_capacity_binding_cannot_graft_another_exact_plan_or_accepted_input(
    tmp_path: Path, drift: str
) -> None:
    fixture = _capacity_setup(tmp_path)
    plan = fixture.service.propose(None, purpose=BaselinePurpose.CONTEXT_CAPACITY_RESUME)
    binding = fixture.service.execute(plan.plan_sha256, authority=_pause(plan))
    variations: dict[str, dict[str, object]] = {
        "receipt": {"context_capacity_receipt_sha256": "d" * 64},
        "source_artifacts": {"source_artifact_ids": ("art_other_accepted",)},
        "source": {"execution_source_revision": "d" * 40, "prior_source_revision": "d" * 40},
    }
    grafted = binding.model_copy(update=variations[drift])
    grafted = grafted.model_copy(update={"binding_sha256": grafted.recompute_sha256()})
    grafted.validate_integrity()
    with pytest.raises(ValueError, match="容量恢复绑定"):
        require_context_capacity_binding(plan, grafted)


@pytest.mark.parametrize("drift", ["inventory", "facts", "direct_resume"])
def test_capacity_pause_refuses_drift_or_combined_resume_before_binding(
    tmp_path: Path, drift: str
) -> None:
    fixture = _capacity_setup(tmp_path)
    plan = fixture.service.propose(None, purpose=BaselinePurpose.CONTEXT_CAPACITY_RESUME)
    authority = _pause(plan)
    if drift == "direct_resume":
        with pytest.raises(ValueError, match="容量恢复"):
            BaselineOperatorAuthorization.for_plan(
                plan,
                principal=LocalOperatorPrincipal.trusted_local(),
                reference="unsafe direct resume",
                submitted_at=datetime.now(UTC),
                continuation_mode=BaselineContinuationMode.RESUME,
            )
        assert fixture.service.store.start(plan.plan_sha256) is None
        return
    if drift == "inventory":
        (fixture.worktree.path / "src/app.py").write_text("VALUE = 2\nEXTRA = 99\n")
    else:
        facts = fixture.collector.facts.model_copy(
            update={"context_capacity_receipt_sha256": "e" * 64}
        )
        fixture.collector.facts = facts.model_copy(
            update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
        )
    preserved = capture_mutation_inventory(fixture.worktree.path)
    with pytest.raises((ValueError, WorktreeCaptureRejected)):
        fixture.service.execute(plan.plan_sha256, authority=authority)
    assert capture_mutation_inventory(fixture.worktree.path) == preserved
    assert fixture.service.store.start(plan.plan_sha256) is None
    assert fixture.service.store.bindings_for_task(plan.facts.task.id) == ()
