"""No-start discovery verifies clean removal without recreating a code checkout."""

from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.execution_baseline import (
    BaselineInputMode,
    ExecutionBaselineBinding,
)
from ai_software_engineer.git import GitWorkspaceError, WorktreeSpec
from ai_software_engineer.recovery.context_capacity import _capacity_capture
from tests.git.test_worktree import _git
from tests.manager.test_execution_baseline import authorize, setup


@pytest.mark.parametrize(
    "fact",
    (
        "existing",
        "removed",
        "missing_marker",
        "unsafe_marker",
        "branch_drift",
        "path_drift",
        "dirty",
    ),
)
def test_capacity_discovery_keeps_exact_removed_checkout_and_refuses_drift(
    tmp_path: Path, fact: str
) -> None:
    fixture = setup(tmp_path)
    plan = fixture.service.propose(fixture.target, input_mode=BaselineInputMode.CODER_REAPPLY)
    binding = fixture.service.execute(plan.plan_sha256, authority=authorize(plan))
    task = fixture.collector.facts.task
    spec = WorktreeSpec(
        task_id=task.id,
        role=AgentRole.CODER,
        attempt=1,
        source_revision=binding.execution_source_revision,
    )
    if fact in {"removed", "missing_marker", "unsafe_marker", "branch_drift"}:
        fixture.manager.remove(fixture.manager.recover(spec))
        marker = next(fixture.worktree.path.parent.glob(".coder-attempt-01.removed-*"))
        if fact == "missing_marker":
            marker.unlink()
        elif fact == "unsafe_marker":
            marker.unlink()
            marker.symlink_to(fixture.repository / "README.md")
        elif fact == "branch_drift":
            _git(
                fixture.repository, "update-ref", f"refs/heads/{binding.branch_name}", task.base_ref
            )
    elif fact == "path_drift":
        binding = ExecutionBaselineBinding.create(
            **{**binding.to_wire(), "worktree_path": binding.worktree_path + "-unbound"}
        )
    elif fact == "dirty":
        (fixture.worktree.path / "src/app.py").write_text("VALUE = 99\n")
    exists_before = fixture.worktree.path.exists()
    branch_before = _git(fixture.repository, "rev-parse", f"refs/heads/{binding.branch_name}")
    if fact in {"existing", "removed"}:
        capture = _capacity_capture(
            fixture.manager,
            task,
            binding,
            fixture.collector.facts.permissions,
            fixture.collector.facts.denied_paths,
        )
        assert (capture is None) == (fact == "removed")
        if capture is not None:
            assert not capture.patch and not capture.changed_paths
    else:
        with pytest.raises((ValueError, GitWorkspaceError)):
            _capacity_capture(
                fixture.manager,
                task,
                binding,
                fixture.collector.facts.permissions,
                fixture.collector.facts.denied_paths,
            )
    assert fixture.worktree.path.exists() == exists_before
    assert (
        _git(fixture.repository, "rev-parse", f"refs/heads/{binding.branch_name}") == branch_before
    )
    assert fixture.service.store.plan(plan.plan_sha256).complete_capture == plan.complete_capture


def test_public_proposal_git_seam_restores_only_the_proven_clean_checkout(tmp_path: Path) -> None:
    fixture = setup(tmp_path)
    plan = fixture.service.propose(fixture.target, input_mode=BaselineInputMode.CODER_REAPPLY)
    binding = fixture.service.execute(plan.plan_sha256, authority=authorize(plan))
    task = fixture.collector.facts.task
    spec = WorktreeSpec(
        task_id=task.id,
        role=AgentRole.CODER,
        attempt=1,
        source_revision=binding.execution_source_revision,
    )
    fixture.manager.remove(fixture.manager.recover(spec))
    assert (
        _capacity_capture(
            fixture.manager,
            task,
            binding,
            fixture.collector.facts.permissions,
            fixture.collector.facts.denied_paths,
        )
        is None
    )
    assert not fixture.worktree.path.exists()
    restored = fixture.manager.restore_clean_coder(spec)
    capture = _capacity_capture(
        fixture.manager,
        task,
        binding,
        fixture.collector.facts.permissions,
        fixture.collector.facts.denied_paths,
    )
    assert capture is not None and capture.worktree == restored
    assert not capture.patch and not capture.changed_paths
    assert (
        fixture.service.store.plan(plan.plan_sha256).complete_capture.patch
        == plan.complete_capture.patch
    )
