"""Exact, fail-closed recovery scope supplementation on a retained worktree."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
from ai_software_engineer.git import (
    GitWorktreeManager,
    PathPolicyViolation,
    WorktreeRef,
    WorktreeSpec,
)
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.native import NativeRecoverySource
from ai_software_engineer.recovery.scope import (
    expanded_recovery_permissions,
    inspect_recovery_scope_supplement,
)
from tests.git.test_capture import git
from tests.recovery.test_authorization import make_plan


def _retained_worktree(
    tmp_path: Path,
) -> tuple[GitWorktreeManager, WorktreeRef, NativeRecoverySource]:
    repository = tmp_path / "repo"
    repository.mkdir()
    git(repository, "init", "--initial-branch=main")
    git(repository, "config", "user.name", "Fixture")
    git(repository, "config", "user.email", "fixture@example.invalid")
    (repository / "src").mkdir()
    (repository / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(repository, "add", "src/app.py")
    git(repository, "commit", "-m", "base")
    manager = GitWorktreeManager(repository, tmp_path / "roles")
    revision = git(repository, "rev-parse", "HEAD")
    worktree = manager.create(
        WorktreeSpec(
            task_id="task_original",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=revision,
        )
    )
    source = make_plan(repository).source.model_copy(
        update={
            "scope": make_plan(repository).source.scope.model_copy(
                update={"repository_root": str(repository)}
            ),
            "base_revision": revision,
        }
    )
    permissions = AgentPermissions(
        read_paths=("src/**",),
        write_paths=("src/**",),
        commands=(),
        network=NetworkAccess.NONE,
    )
    original = cast(
        NativeRecoverySource,
        SimpleNamespace(source=source, permissions=permissions, denied_paths=()),
    )
    return manager, worktree, original


def test_scope_supplement_requires_exact_paths_before_content_capture(tmp_path: Path) -> None:
    manager, worktree, original = _retained_worktree(tmp_path)
    (worktree.path / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    (worktree.path / "omitted.txt").write_text("retained work\n", encoding="utf-8")

    supplement = inspect_recovery_scope_supplement(manager, worktree, original)

    assert supplement is not None
    assert supplement.paths == ("omitted.txt",)
    with pytest.raises(PathPolicyViolation, match=r"omitted\.txt"):
        manager.capture_changes(
            worktree,
            original.permissions,
            denied_paths=original.denied_paths,
        )
    expanded = expanded_recovery_permissions(original.permissions, supplement)
    capture = manager.capture_changes(worktree, expanded, denied_paths=original.denied_paths)
    assert capture.changed_paths == ("omitted.txt", "src/app.py")

    (worktree.path / "second.txt").write_text("more retained work\n", encoding="utf-8")
    changed = inspect_recovery_scope_supplement(manager, worktree, original)
    assert changed is not None
    assert changed.paths == ("omitted.txt", "second.txt")
    assert changed.supplement_sha256 != supplement.supplement_sha256


def test_explicitly_denied_path_cannot_be_scope_approved(tmp_path: Path) -> None:
    manager, worktree, original = _retained_worktree(tmp_path)
    (worktree.path / "secret.txt").write_text("not inspectable\n", encoding="utf-8")
    denied = cast(
        NativeRecoverySource,
        SimpleNamespace(
            source=original.source,
            permissions=original.permissions,
            denied_paths=("secret.txt",),
        ),
    )

    with pytest.raises(RecoveryRejected, match="explicitly denied"):
        inspect_recovery_scope_supplement(manager, worktree, denied)
