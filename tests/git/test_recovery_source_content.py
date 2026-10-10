"""Recovery captures use the same conservative source detector as progress."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain import AgentPermissions
from ai_software_engineer.git import GitWorktreeManager, WorktreeCaptureRejected
from ai_software_engineer.git.ports import WorktreeRef
from ai_software_engineer.recovery import CapturedChanges
from tests.git.test_capture import git
from tests.git.test_capture import workspace as workspace


def test_recovery_keeps_runtime_generated_token_expression_as_source(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
) -> None:
    manager, ref, permissions = workspace
    source = ref.path / "src/generated.py"
    source.write_text("import secrets\ntoken = secrets.token_hex(16)\n", encoding="utf-8")
    before = git(ref.path, "status", "--porcelain")
    capture = manager.capture_legacy_changes(ref, permissions)
    record = CapturedChanges.from_capture(capture)
    assert "token = secrets.token_hex(16)" in record.patch
    assert record.to_capture() == capture
    manager.verify_legacy_capture(capture, permissions)
    assert git(ref.path, "status", "--porcelain") == before
    assert git(ref.path, "rev-parse", "HEAD") == ref.head_revision


@pytest.mark.parametrize("content", ["token = 'sensitive-literal'\n", "token=my.jwt.secret\n"])
def test_recovery_still_rejects_credential_literals_and_unverified_references(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], content: str
) -> None:
    manager, ref, permissions = workspace
    (ref.path / "src/generated.py").write_text(content, encoding="utf-8")
    before = git(ref.path, "status", "--porcelain")
    with pytest.raises(WorktreeCaptureRejected, match="sensitive content"):
        manager.capture_legacy_changes(ref, permissions)
    assert git(ref.path, "status", "--porcelain") == before


def test_captured_source_wire_cannot_hide_secret_in_patch_metadata(tmp_path: Path) -> None:
    from ai_software_engineer.git.capture import WorktreeChangeCapture
    from tests.recovery.test_authorization import make_plan

    base = make_plan(tmp_path / "project").capture.to_capture()
    capture = WorktreeChangeCapture(
        worktree=base.worktree,
        patch=b"token='sensitive-literal'\n",
        index_diff_sha256=base.index_diff_sha256,
        file_sha256s=(),
    )
    with pytest.raises(ValidationError, match="sensitive content"):
        CapturedChanges.from_capture(capture)
