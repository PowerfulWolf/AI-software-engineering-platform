"""Offline real-Git tests for read-only interrupted-Coder capture."""

import hashlib
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
from ai_software_engineer.git import (
    GitWorktreeManager,
    PathPolicyViolation,
    UnmanagedWorktree,
    WorktreeCaptureRejected,
    WorktreeRevisionDrift,
    WorktreeSpec,
)
from ai_software_engineer.git.capture import (
    MAX_CAPTURE_BYTES,
    WorktreeChangeCapture,
    read_capture_file,
)
from ai_software_engineer.git.ports import WorktreeRef


def git(root: Path, *argv: str) -> str:
    return subprocess.run(
        ("git", *argv), cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[GitWorktreeManager, WorktreeRef, AgentPermissions]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "src").mkdir()
    (repo / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(repo, "add", "src/app.py")
    git(repo, "commit", "-m", "base")
    manager = GitWorktreeManager(repo, tmp_path / "roles")
    ref = manager.create(
        WorktreeSpec(
            task_id="task_capture_001",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=git(repo, "rev-parse", "HEAD"),
        )
    )
    permissions = AgentPermissions(
        read_paths=("src/**",),
        write_paths=("src/**",),
        commands=(),
        network=NetworkAccess.NONE,
    )
    return manager, ref, permissions


def test_capture_binds_staged_and_unstaged_content_without_writes(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
    tmp_path: Path,
) -> None:
    manager, ref, permissions = workspace
    source = ref.path / "src/app.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    git(ref.path, "add", "src/app.py")
    source.write_text("VALUE = 3\n", encoding="utf-8")
    index = Path(git(ref.path, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    before_status = git(ref.path, "status", "--porcelain")
    index_bytes = index.read_bytes()

    capture = manager.capture_changes(ref, permissions)

    assert isinstance(capture, WorktreeChangeCapture)
    assert capture.changed_paths == ("src/app.py",)
    assert capture.file_sha256s == (
        ("src/app.py", hashlib.sha256(source.read_bytes()).hexdigest()),
    )
    assert b"-VALUE = 1" in capture.patch and b"+VALUE = 3" in capture.patch
    assert b"+VALUE = 2" not in capture.patch
    assert len(capture.capture_sha256) == 64
    assert manager.capture_changes(ref, permissions) == capture
    manager.verify_capture(capture, permissions)
    assert index.read_bytes() == index_bytes
    assert git(ref.path, "status", "--porcelain") == before_status
    assert git(ref.path, "rev-parse", "HEAD") == ref.head_revision
    assert git(tmp_path / "repo", "status", "--porcelain") == ""
    assert git(tmp_path / "repo", "rev-parse", "HEAD") == ref.head_revision

    # Only a temporary test checkout consumes the patch. Production application is
    # intentionally absent; prove stripped context/labels did not corrupt edit bytes.
    target = manager.create(
        WorktreeSpec(
            task_id="task_capture_copy",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=ref.head_revision,
        )
    )
    subprocess.run(
        ("git", "-c", "core.hooksPath=/dev/null", "apply", "--unidiff-zero", "-"),
        cwd=target.path,
        input=capture.patch,
        check=True,
        capture_output=True,
    )
    assert (target.path / "src/app.py").read_bytes() == source.read_bytes()
    assert index.read_bytes() == index_bytes


@pytest.mark.parametrize("change", ["bytes", "staging", "payload", "head"])
def test_capture_rejects_drift(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
    change: str,
) -> None:
    manager, ref, permissions = workspace
    source = ref.path / "src/app.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    capture = manager.capture_changes(ref, permissions)
    if change == "bytes":
        source.write_text("VALUE = 3\n", encoding="utf-8")
    elif change == "staging":
        git(ref.path, "add", "src/app.py")
    elif change == "payload":
        capture = replace(capture, patch=capture.patch.replace(b"VALUE = 2", b"VALUE = 9"))
    else:
        git(ref.path, "add", "src/app.py")
        git(ref.path, "commit", "-m", "unexpected candidate")
    with pytest.raises((WorktreeCaptureRejected, WorktreeRevisionDrift)):
        manager.verify_capture(capture, permissions)
    assert source.exists()


@pytest.mark.parametrize(
    "change",
    [
        "untracked",
        "added",
        "deleted",
        "mode",
        "binary",
        "encoding",
        "symlink",
        "large",
        "assume_unchanged",
        "skip_worktree",
        "index_only",
        "fifo",
        "secret",
    ],
)
def test_capture_refuses_unsupported_or_unsafe_work_and_preserves_it(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
    change: str,
) -> None:
    manager, ref, permissions = workspace
    source = ref.path / "src/app.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    if change in ("untracked", "added"):
        (ref.path / "src/new.py").write_text("NEW = 1\n", encoding="utf-8")
        if change == "added":
            git(ref.path, "add", "src/new.py")
    elif change == "deleted":
        source.unlink()
    elif change == "mode":
        source.chmod(0o755)
    elif change == "binary":
        source.write_bytes(b"abc\0def")
    elif change == "encoding":
        source.write_bytes(b"\xff\xfe")
    elif change == "symlink":
        source.unlink()
        source.symlink_to("missing.py")
    elif change == "large":
        source.write_bytes(b"x" * (MAX_CAPTURE_BYTES + 1))
    elif change in ("assume_unchanged", "skip_worktree"):
        git(ref.path, "update-index", "--" + change.replace("_", "-"), "src/app.py")
    elif change == "index_only":
        git(ref.path, "add", "src/app.py")
        source.write_text("VALUE = 1\n", encoding="utf-8")
    elif change == "fifo":
        source.unlink()
        os.mkfifo(source)
    else:
        source.write_text('api_key = "sk-' + "x" * 24 + '"\n', encoding="utf-8")
    with pytest.raises(WorktreeCaptureRejected) as error:
        manager.capture_changes(ref, permissions)
    assert "sk-" not in str(error.value)
    assert ref.path.is_dir()
    assert git(ref.path, "rev-parse", "HEAD") == ref.head_revision


def test_capture_checks_permissions_and_exact_manager_ownership(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
    tmp_path: Path,
) -> None:
    manager, ref, permissions = workspace
    (ref.path / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(PathPolicyViolation):
        manager.capture_changes(ref, permissions, denied_paths=("src/**",))
    with pytest.raises(PathPolicyViolation):
        manager.capture_changes(ref, permissions.model_copy(update={"write_paths": ()}))
    with pytest.raises(UnmanagedWorktree):
        manager.capture_changes(replace(ref, path=tmp_path / "repo"), permissions)
    with pytest.raises(WorktreeCaptureRejected):
        manager.capture_changes(replace(ref, role=AgentRole.QA), permissions)


def test_clean_capture_does_not_mean_delivery_or_authorization(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
) -> None:
    manager, ref, permissions = workspace
    capture = manager.capture_changes(ref, permissions)
    assert capture.patch == b""
    assert capture.changed_paths == ()
    assert not hasattr(capture, "verdict")
    assert not hasattr(capture, "approval")
    assert (
        replace(capture, worktree=replace(ref, task_id="task_other_001")).capture_sha256
        != capture.capture_sha256
    )


def test_capture_rejects_a_writer_between_observations(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, ref, permissions = workspace
    source = ref.path / "src/app.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    first_read = True

    def racing_read(root: Path, path: str, *, executable: bool) -> bytes:
        nonlocal first_read
        content = read_capture_file(root, path, executable=executable)
        if first_read:
            first_read = False
            source.write_text("VALUE = 3\n", encoding="utf-8")
        return content

    monkeypatch.setattr("ai_software_engineer.git.worktree.read_capture_file", racing_read)
    with pytest.raises(WorktreeCaptureRejected, match="changed during capture"):
        manager.capture_changes(ref, permissions)
    assert source.read_text(encoding="utf-8") == "VALUE = 3\n"


def test_capture_blocks_filters_without_executing_them(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
    tmp_path: Path,
) -> None:
    from ai_software_engineer.git import UnsafeRepositoryConfiguration

    manager, ref, permissions = workspace
    marker = tmp_path / "filter_was_run"
    git(tmp_path / "repo", "config", "filter.unsafe.clean", f"touch {marker}")
    (ref.path / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(UnsafeRepositoryConfiguration):
        manager.capture_changes(ref, permissions)
    assert not marker.exists()


def test_capture_does_not_copy_unchanged_secret_shaped_context(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
) -> None:
    manager, ref, permissions = workspace
    source = ref.path / "src/app.py"
    secret_line = 'secret = "synthetic-fixture-value"\n'
    source.write_text(secret_line + "VALUE = 1\n", encoding="utf-8")
    git(ref.path, "add", "src/app.py")
    git(ref.path, "commit", "-m", "fixture with sensitive-shaped unchanged context")
    ref = replace(ref, head_revision=git(ref.path, "rev-parse", "HEAD"))
    source.write_text(secret_line + "VALUE = 2\n", encoding="utf-8")

    capture = manager.capture_changes(ref, permissions)

    assert b"synthetic-fixture-value" not in capture.patch
    assert b"+VALUE = 2" in capture.patch
    assert b"@@ -2 +2 @@" in capture.patch
    manager.verify_capture(capture, permissions)
    # Changed sensitive lines remain a refusal; this is not a scanner exemption.
    source.write_text('secret = "changed-synthetic-value"\nVALUE = 2\n', encoding="utf-8")
    with pytest.raises(WorktreeCaptureRejected, match="sensitive content"):
        manager.capture_changes(ref, permissions)
