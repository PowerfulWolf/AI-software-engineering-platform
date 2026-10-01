"""Current work needs new exact authority; sealed snapshots reject later drift."""

from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentPermissions
from ai_software_engineer.git import GitWorktreeManager, WorktreeRef
from ai_software_engineer.recovery.interruption import _stopped_workspace_capture
from ai_software_engineer.recovery.interruption_records import RecoveryInterruptionPlan
from ai_software_engineer.recovery.models import CapturedChanges, RecoveryRejected
from tests.git.test_capture import git
from tests.git.test_capture import workspace as workspace
from tests.recovery.test_interruption_records import plan_fixture


def _proposal(tmp_path: Path, capture: CapturedChanges) -> RecoveryInterruptionPlan:
    original = plan_fixture(tmp_path)
    value = original.model_copy(update={"task_id": capture.task_id, "stopped_capture": capture})
    value = value.model_copy(update={"plan_sha256": value.recompute_sha256()})
    value.validate_integrity()
    return value


def test_stopped_capture_preserves_full_new_files_content_and_index(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], tmp_path: Path
) -> None:
    manager, ref, permissions = workspace
    seed = CapturedChanges.from_capture(manager.capture_changes(ref, permissions))
    assert _stopped_workspace_capture(manager, seed, permissions, (), None) is None
    (ref.path / "src/app.py").write_text("VALUE = 2\n")
    git(ref.path, "add", "src/app.py")
    (ref.path / "src/app.py").write_text("VALUE = 3\n")
    (ref.path / "src/new.py").write_text("NEW = True\n")
    before = git(ref.path, "status", "--porcelain")
    capture = _stopped_workspace_capture(manager, seed, permissions, (), None)
    assert capture is not None
    assert tuple(file.path for file in capture.files) == ("src/app.py", "src/new.py")
    assert "+VALUE = 3" in capture.patch and "+NEW = True" in capture.patch
    assert capture.index_diff_sha256 != seed.index_diff_sha256
    assert (
        _stopped_workspace_capture(manager, seed, permissions, (), _proposal(tmp_path, capture))
        == capture
    )
    assert git(ref.path, "status", "--porcelain") == before
    legacy = plan_fixture(tmp_path / "legacy")
    with pytest.raises(RecoveryRejected, match="capture"):
        _stopped_workspace_capture(manager, seed, permissions, (), legacy)


@pytest.mark.parametrize("drift", ["content", "index", "head"])
def test_stopped_capture_rejects_post_proposal_drift(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], tmp_path: Path, drift: str
) -> None:
    manager, ref, permissions = workspace
    seed = CapturedChanges.from_capture(manager.capture_changes(ref, permissions))
    (ref.path / "src/app.py").write_text("VALUE = 2\n")
    capture = _stopped_workspace_capture(manager, seed, permissions, (), None)
    assert capture is not None
    proposal = _proposal(tmp_path, capture)
    if drift == "content":
        (ref.path / "src/app.py").write_text("VALUE = 9\n")
    else:
        git(ref.path, "add", "src/app.py")
        if drift == "head":
            git(ref.path, "commit", "-m", "unexpected commit")
    with pytest.raises(RecoveryRejected, match="capture"):
        _stopped_workspace_capture(manager, seed, permissions, (), proposal)


@pytest.mark.parametrize(
    "field", ["worktree_path", "branch_name", "source_revision", "base_revision"]
)
def test_stopped_capture_rejects_rehashed_foreign_workspace_identity(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], tmp_path: Path, field: str
) -> None:
    manager, ref, permissions = workspace
    seed = CapturedChanges.from_capture(manager.capture_changes(ref, permissions))
    values = {
        "worktree_path": str(tmp_path / "foreign"),
        "branch_name": "ai/bugfix/foreign-workspace",
        "source_revision": "b" * 40,
        "base_revision": "c" * 40,
    }
    changed = seed.model_copy(update={field: values[field]})
    capture = CapturedChanges.from_capture(changed.to_capture())
    proposal = _proposal(tmp_path, capture)
    with pytest.raises(RecoveryRejected, match="identity"):
        _stopped_workspace_capture(manager, seed, permissions, (), proposal)


@pytest.mark.parametrize("invalid", ["outside_scope", "denied", "symlink", "binary"])
def test_stopped_capture_never_expands_scope_or_accepts_unsafe_files(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
    tmp_path: Path,
    invalid: str,
) -> None:
    manager, ref, permissions = workspace
    seed = CapturedChanges.from_capture(manager.capture_changes(ref, permissions))
    denied: tuple[str, ...] = ()
    if invalid == "outside_scope":
        (ref.path / "unapproved.txt").write_text("outside approved paths\n")
    elif invalid == "symlink":
        outside = tmp_path / "outside.txt"
        outside.write_text("unapproved fixture\n")
        (ref.path / "src/alias.py").symlink_to(outside)
    elif invalid == "binary":
        (ref.path / "src/app.py").write_bytes(b"\x00\xff")
    else:
        (ref.path / "src/app.py").write_text("VALUE = 2\n")
        denied = ("src/app.py",)
    with pytest.raises(RecoveryRejected):
        _stopped_workspace_capture(manager, seed, permissions, denied, None)
