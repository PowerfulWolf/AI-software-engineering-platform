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
    (repository / "tests").mkdir()
    (repository / "tests/test_contract.py").write_text("def test_contract(): pass\n")
    git(repository, "add", "src/app.py", "tests/test_contract.py")
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


def _scope_request(original: NativeRecoverySource) -> tuple[NativeRecoverySource, object]:
    from ai_software_engineer.recovery.models import RecoveryScopeRequest

    request = RecoveryScopeRequest(
        progress_artifact_id="art_coder_progress",
        progress_sha256="a" * 64,
        paths=("tests/test_contract.py",),
        reason="Update the accepted-source contract fixture required by the frozen criteria.",
    )
    original = cast(
        NativeRecoverySource,
        SimpleNamespace(
            source=original.source,
            permissions=original.permissions,
            denied_paths=original.denied_paths,
            accepted_progress=SimpleNamespace(
                artifact_id=request.progress_artifact_id,
                integrity=SimpleNamespace(sha256=request.progress_sha256),
            ),
        ),
    )
    return original, request


def test_requested_scope_binds_progress_and_unchanged_git_blob(tmp_path: Path) -> None:
    from ai_software_engineer.recovery.models import RecoveryScopeRequest, digest

    manager, worktree, original = _retained_worktree(tmp_path)
    original, raw = _scope_request(original)
    request = cast(RecoveryScopeRequest, raw)
    supplement = inspect_recovery_scope_supplement(manager, worktree, original, request=request)
    assert supplement is not None
    assert supplement.paths == request.paths
    assert supplement.request == request
    assert supplement.requested_files is not None
    assert supplement.requested_files[0].blob_id == git(
        worktree.path, "rev-parse", "HEAD:tests/test_contract.py"
    )
    assert manager.inspect(worktree).changed_paths == ()
    expanded = expanded_recovery_permissions(original.permissions, supplement)
    assert expanded.write_paths == ("src/**", "tests/test_contract.py")
    assert expanded.commands == original.permissions.commands
    assert expanded.network == original.permissions.network
    assert supplement.recompute_sha256() == digest(
        {k: v for k, v in supplement.to_wire().items() if k != "supplement_sha256"}
    )
    (worktree.path / "tests/test_contract.py").write_text("changed before approval\n")
    with pytest.raises(RecoveryRejected, match="unchanged"):
        inspect_recovery_scope_supplement(manager, worktree, original, request=request)


@pytest.mark.parametrize(
    "failure",
    ["wrong_progress", "missing_progress", "denied", "missing", "directory", "allowed", "symlink"],
)
def test_requested_scope_rejects_unsafe_or_unbound_paths(tmp_path: Path, failure: str) -> None:
    from ai_software_engineer.recovery.models import RecoveryScopeRequest

    manager, worktree, original = _retained_worktree(tmp_path)
    original, raw = _scope_request(original)
    request = cast(RecoveryScopeRequest, raw)
    if failure == "wrong_progress":
        request = request.model_copy(update={"progress_sha256": "b" * 64})
    elif failure == "missing_progress":
        original.accepted_progress = None  # type: ignore[misc]
    elif failure == "denied":
        original.denied_paths = request.paths  # type: ignore[misc]
    elif failure in {"missing", "directory", "allowed"}:
        request = request.model_copy(
            update={
                "paths": (
                    {"missing": "tests/missing.py", "directory": "tests", "allowed": "src/app.py"}[
                        failure
                    ],
                )
            }
        )
    elif failure == "symlink":
        (worktree.path / request.paths[0]).unlink()
        (worktree.path / request.paths[0]).symlink_to(worktree.path / "src/app.py")
    with pytest.raises(RecoveryRejected):
        inspect_recovery_scope_supplement(manager, worktree, original, request=request)
