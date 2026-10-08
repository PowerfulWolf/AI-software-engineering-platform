"""Ignored legacy input must never silently enter the resumed Coder execution."""

from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.manager.legacy_snapshot import require_complete_legacy_inventory
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from tests.git.test_worktree import _create_fixture_repository, _git


@pytest.mark.parametrize("extra", ["private/AGENTS.md", "private/run.sh", "private/link"])
def test_uncaptured_legacy_input_is_refused_and_preserved(tmp_path: Path, extra: str) -> None:
    repository = _create_fixture_repository(tmp_path)
    (repository / ".gitignore").write_text("private/\n")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "fixture ignore")
    git = GitWorktreeManager(repository, tmp_path / "worktrees")
    tree = git.create(
        WorktreeSpec(
            task_id="task_legacy",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=_git(repository, "rev-parse", "HEAD"),
        )
    )
    unknown = tree.path / extra
    unknown.parent.mkdir()
    if extra.endswith("link"):
        unknown.symlink_to("../src/app.py")
    else:
        unknown.write_text("unknown ignored execution input\n")
    permissions = AgentPermissions(
        read_paths=("**",),
        write_paths=("src/**",),
        commands=("git diff",),
        network=NetworkAccess.NONE,
    )
    capture = CapturedMutations.from_capture(git.capture_mutations(tree, permissions))
    before = capture_mutation_inventory(tree.path)
    with pytest.raises(ValueError, match=r"忽略文件|链接"):
        require_complete_legacy_inventory(git, capture, before)
    assert capture_mutation_inventory(tree.path) == before
    assert unknown.is_symlink() or unknown.read_text() == "unknown ignored execution input\n"


def test_explicit_cache_and_complete_authorized_draft_are_retained(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    (repository / ".gitignore").write_text("__pycache__/\n")
    _git(repository, "add", ".gitignore")
    _git(repository, "commit", "-m", "fixture cache")
    git = GitWorktreeManager(repository, tmp_path / "worktrees")
    tree = git.create(
        WorktreeSpec(
            task_id="task_legacy",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=_git(repository, "rev-parse", "HEAD"),
        )
    )
    (tree.path / "src/app.py").write_text("VALUE = 2\n")
    (tree.path / "__pycache__").mkdir()
    (tree.path / "__pycache__/app.pyc").write_bytes(b"fixture cache")
    permissions = AgentPermissions(
        read_paths=("**",),
        write_paths=("src/**",),
        commands=("git diff",),
        network=NetworkAccess.NONE,
    )
    capture = CapturedMutations.from_capture(git.capture_mutations(tree, permissions))
    before = capture_mutation_inventory(tree.path)
    require_complete_legacy_inventory(git, capture, before)
    assert capture_mutation_inventory(tree.path) == before
