"""Actual Git preservation while authorizing a new original-Task candidate input."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselineInputMode,
    BaselinePurpose,
)
from ai_software_engineer.git.baseline import GitExecutionBaselineAdapter
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.manager.baseline_models import (
    BaselineOperatorAuthorization,
    require_rejected_candidate_binding,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.execution_baseline import ExecutionBaselineService
from tests.git.test_worktree import _git
from tests.manager.test_execution_baseline import Collector
from tests.manager.test_rejected_candidate_baseline_production import (
    RejectedCandidateProductionFixture,
)
from tests.manager.test_rejected_candidate_baseline_production import (
    rejected_candidate_production as rejected_candidate_production,
)


def test_candidate_input_service_does_not_rebase_or_rewrite_old_success(
    tmp_path: Path,
    rejected_candidate_production: RejectedCandidateProductionFixture,
) -> None:
    f = rejected_candidate_production
    facts = f.facts()
    original_task = f.task.to_wire()
    original_outcome = f.outcome.to_wire()
    head = _git(f.native.worktree.path, "rev-parse", "HEAD")
    inventory = capture_mutation_inventory(f.native.worktree.path)
    store = FileExecutionBaselineStore(tmp_path / "service-baselines")
    service = ExecutionBaselineService(
        store=store,
        git=GitExecutionBaselineAdapter(f.native.git),
        facts=Collector(facts, f.native.worktree),
    )
    plan = service.propose(None, purpose=BaselinePurpose.REJECTED_CANDIDATE_RESCUE)
    assert plan.target_base_ref == f.task.base_ref
    assert plan.prepared_source_revision == head
    assert plan.dirty_capture.to_capture().changed_paths == ()
    assert facts.rejected_candidate_output is not None
    assert plan.complete_capture == facts.rejected_candidate_output.complete_capture
    assert service.propose(None, purpose=BaselinePurpose.REJECTED_CANDIDATE_RESCUE) == plan
    with pytest.raises(ValueError, match="暂停"):
        BaselineOperatorAuthorization.for_plan(
            plan,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="wrong auto-resume",
            submitted_at=datetime.now(UTC),
            continuation_mode=BaselineContinuationMode.RESUME,
        )
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact fixture engineering",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    assert binding.execution_base_ref == binding.prior_execution_base_ref == f.task.base_ref
    assert binding.prior_source_revision == f.native.request.source_revision
    assert binding.execution_source_revision == head
    assert binding.before_inventory_sha256 == binding.after_inventory_sha256 == inventory.sha256
    assert f.task.to_wire() == original_task and f.outcome.to_wire() == original_outcome
    assert _git(f.native.worktree.path, "rev-parse", "HEAD") == head
    assert _git(f.native.worktree.path, "status", "--porcelain") == ""
    assert capture_mutation_inventory(f.native.worktree.path) == inventory
    assert FileExecutionBaselineStore(store.root).bindings_for_task(f.task.id) == (binding,)
    assert service.execute(plan.plan_sha256, authority=authority) == binding
    assert len(store.bindings_for_task(f.task.id)) == 1
    assert "候选" in store.required_context(binding)


def test_changed_candidate_cannot_be_consumed_under_old_exact_plan(
    tmp_path: Path,
    rejected_candidate_production: RejectedCandidateProductionFixture,
) -> None:
    f = rejected_candidate_production
    service = ExecutionBaselineService(
        store=FileExecutionBaselineStore(tmp_path / "service-baselines"),
        git=GitExecutionBaselineAdapter(f.native.git),
        facts=Collector(f.facts(), f.native.worktree),
    )
    plan = service.propose(None, purpose=BaselinePurpose.REJECTED_CANDIDATE_RESCUE)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact fixture engineering",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    (f.native.worktree.path / "src/app.py").write_text("VALUE = 999\n")
    with pytest.raises((ValueError, RuntimeError)):
        service.execute(plan.plan_sha256, authority=authority)
    assert not service.store.bindings_for_task(f.task.id)
    assert (f.native.worktree.path / "src/app.py").read_text() == "VALUE = 999\n"


def test_rehashed_candidate_binding_cannot_graft_unapproved_fields(
    tmp_path: Path,
    rejected_candidate_production: RejectedCandidateProductionFixture,
) -> None:
    f = rejected_candidate_production
    service = ExecutionBaselineService(
        store=FileExecutionBaselineStore(tmp_path / "graft-baselines"),
        git=GitExecutionBaselineAdapter(f.native.git),
        facts=Collector(f.facts(), f.native.worktree),
    )
    plan = service.propose(None, purpose=BaselinePurpose.REJECTED_CANDIDATE_RESCUE)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact field regression",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    changes: tuple[dict[str, object], ...] = (
        {"scope": binding.scope.model_copy(update={"project_id": "project_foreign"})},
        {"task_id": "task_foreign_001"},
        {"task_intent_sha256": "f" * 64},
        {"source_artifact_ids": ("art_foreign_001",)},
        {"resolved_interruption_receipt_sha256s": ("f" * 64,)},
        {"prior_task_revision": binding.prior_task_revision + 1},
        {"worktree_path": "/foreign/worktree"},
        {"branch_name": "ai/feature/foreign"},
        {"approved_base_ref": "f" * 40},
        {"sequence": binding.sequence + 1, "previous_binding_sha256": "f" * 64},
        {"superseded_progress_artifact_id": "art_foreign_001"},
        {"input_mode": BaselineInputMode.CODER_REAPPLY},
    )
    for change in changes:
        grafted = binding.model_copy(update=change)
        grafted = grafted.model_copy(update={"binding_sha256": grafted.recompute_sha256()})
        with pytest.raises(ValueError):
            require_rejected_candidate_binding(plan, grafted)
