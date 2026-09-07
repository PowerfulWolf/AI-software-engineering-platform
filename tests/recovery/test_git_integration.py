"""Capture -> durable plan -> human receipt -> restart with actual Git verification."""

from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.git import GitWorktreeManager, WorktreeCaptureRejected, WorktreeSpec
from ai_software_engineer.recovery import (
    CapturedChanges,
    FileRecoveryStore,
    RecoveryAuthorizationService,
    RecoveryPlan,
)
from tests.git.test_worktree import _create_fixture_repository, _git
from tests.recovery.test_authorization import Facts, Human, approval, make_plan


def test_real_git_capture_survives_store_restart_and_rejects_later_change(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    base = _git(repository, "rev-parse", "HEAD")
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    coder = manager.create(
        WorktreeSpec(task_id="task_original", role=AgentRole.CODER, attempt=1, source_revision=base)
    )
    (coder.path / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    prototype = make_plan(repository)
    capture = manager.capture_changes(coder, prototype.permissions)
    plan = RecoveryPlan.create(
        **{
            **prototype.to_wire(),
            "source": prototype.source.model_copy(update={"base_revision": base}),
            "capture": CapturedChanges.from_capture(capture),
            "target_base_revision": base,
        }
    )
    root = tmp_path / "records"
    store = FileRecoveryStore.initialize(root, scope=plan.source.scope)
    facts, human = Facts(), Human()
    service = RecoveryAuthorizationService(store, facts=facts, captures=manager, human=human)
    service.propose(plan)
    receipt = service.authorize(approval(plan))
    reopened = FileRecoveryStore(root, scope=plan.source.scope)
    resumed = RecoveryAuthorizationService(reopened, facts=facts, captures=manager, human=human)
    assert reopened.get_plan(plan.plan_sha256).capture.to_capture() == capture
    assert resumed.require_current_authorization(plan.plan_sha256) == plan
    assert _git(repository, "status", "--porcelain") == ""
    assert _git(coder.path, "rev-parse", "HEAD") == base
    assert _git(coder.path, "status", "--porcelain") == "M src/app.py"
    assert human.calls == 1
    (coder.path / "src/app.py").write_text("VALUE = 3\n", encoding="utf-8")
    # Historical authorization replays, but does not authorize the new contents.
    assert resumed.authorize(approval(plan)) == receipt
    with pytest.raises(WorktreeCaptureRejected):
        resumed.require_current_authorization(plan.plan_sha256)
    assert human.calls == 1
