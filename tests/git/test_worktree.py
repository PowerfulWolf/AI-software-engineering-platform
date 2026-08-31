"""Behavior tests for isolated role worktrees using real Git repositories."""

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.git import (
    DirtyWorktree,
    GitWorktreeManager,
    InvalidRepository,
    InvalidWorktreeRoot,
    RevisionNotFound,
    UnmanagedWorktree,
    UnsafeRepositoryConfiguration,
    WorktreeAlreadyExists,
    WorktreeSpec,
)


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _create_fixture_repository(root: Path) -> Path:
    repository = root / "repository"
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.name", "Fixture Author")
    _git(repository, "config", "user.email", "fixture@example.invalid")
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")
    source_directory = repository / "src"
    source_directory.mkdir()
    (source_directory / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repository, "add", "README.md", "src/app.py")
    _git(repository, "commit", "-m", "initial fixture")
    return repository


def test_coder_worktree_is_isolated_from_main_checkout(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    main_revision = _git(repository, "rev-parse", "HEAD")
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")

    reference = manager.create(
        WorktreeSpec(
            task_id="task_fixture_001",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=main_revision,
        )
    )

    assert reference.path == tmp_path / "worktrees/task_fixture_001/coder-attempt-01"
    assert reference.branch == "ai/task_fixture_001/attempt-1"
    assert reference.head_revision == main_revision
    assert reference.detached is False
    assert _git(reference.path, "branch", "--show-current") == reference.branch
    assert _git(reference.path, "rev-parse", "HEAD") == main_revision
    assert _git(repository, "branch", "--show-current") == "main"
    assert _git(repository, "rev-parse", "HEAD") == main_revision
    assert _git(repository, "status", "--porcelain") == ""


def test_qa_and_reviewer_are_detached_at_the_same_clean_candidate(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    coder = manager.create(
        WorktreeSpec(
            task_id="task_fixture_002",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=_git(repository, "rev-parse", "HEAD"),
        )
    )
    (coder.path / "README.md").write_text("fixture candidate\n", encoding="utf-8")
    _git(coder.path, "add", "README.md")
    _git(coder.path, "commit", "-m", "candidate")
    candidate_revision = _git(coder.path, "rev-parse", "HEAD")

    qa = manager.create(
        WorktreeSpec(
            task_id="task_fixture_002",
            role=AgentRole.QA,
            attempt=1,
            source_revision=candidate_revision,
        )
    )
    reviewer = manager.create(
        WorktreeSpec(
            task_id="task_fixture_002",
            role=AgentRole.REVIEWER,
            attempt=1,
            source_revision=candidate_revision,
        )
    )

    assert qa.path != reviewer.path != coder.path
    assert qa.branch is reviewer.branch is None
    assert qa.detached is reviewer.detached is True
    assert _git(qa.path, "branch", "--show-current") == ""
    assert _git(reviewer.path, "branch", "--show-current") == ""
    assert manager.inspect(qa).head_revision == candidate_revision
    assert manager.inspect(qa).changed_paths == ()
    assert manager.inspect(reviewer).head_revision == candidate_revision
    assert manager.inspect(reviewer).changed_paths == ()


def test_dirty_worktree_is_preserved_until_changes_are_cleared(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    candidate_revision = _git(repository, "rev-parse", "HEAD")
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    qa = manager.create(
        WorktreeSpec(
            task_id="task_fixture_003",
            role=AgentRole.QA,
            attempt=1,
            source_revision=candidate_revision,
        )
    )
    (qa.path / "README.md").write_text("qa changed this\n", encoding="utf-8")
    (qa.path / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(qa.path, "add", "src/app.py")
    tests_directory = qa.path / "tests"
    tests_directory.mkdir()
    untracked_test = tests_directory / "qa_regression.py"
    untracked_test.write_text("assert True\n", encoding="utf-8")

    snapshot = manager.inspect(qa)

    assert snapshot.dirty is True
    assert snapshot.changed_paths == (
        "README.md",
        "src/app.py",
        "tests/qa_regression.py",
    )
    with pytest.raises(DirtyWorktree) as error:
        manager.remove(qa)
    assert error.value.changed_paths == snapshot.changed_paths
    assert qa.path.is_dir()

    _git(qa.path, "restore", "--staged", "--worktree", "README.md", "src/app.py")
    untracked_test.unlink()
    tests_directory.rmdir()
    manager.remove(qa)

    assert not qa.path.exists()


def test_worktree_root_inside_main_checkout_is_rejected(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    manager = GitWorktreeManager(repository, repository / "worktrees")

    with pytest.raises(InvalidWorktreeRoot):
        manager.create(
            WorktreeSpec(
                task_id="task_fixture_004",
                role=AgentRole.CODER,
                attempt=1,
                source_revision=_git(repository, "rev-parse", "HEAD"),
            )
        )

    assert _git(repository, "status", "--porcelain") == ""


def test_symlinked_task_directory_cannot_escape_worktree_root(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (worktree_root / "task_fixture_escape").symlink_to(outside, target_is_directory=True)
    manager = GitWorktreeManager(repository, worktree_root)

    with pytest.raises(InvalidWorktreeRoot):
        manager.create(
            WorktreeSpec(
                task_id="task_fixture_escape",
                role=AgentRole.CODER,
                attempt=1,
                source_revision=_git(repository, "rev-parse", "HEAD"),
            )
        )

    assert not (outside / "coder-attempt-01").exists()


def test_invalid_role_and_unknown_repository_or_revision_are_rejected(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)

    with pytest.raises(ValidationError):
        WorktreeSpec.model_validate(
            {
                "task_id": "task_fixture_005",
                "role": "orchestrator",
                "attempt": 1,
                "source_revision": "HEAD",
            }
        )

    not_a_repository = tmp_path / "not-a-repository"
    not_a_repository.mkdir()
    with pytest.raises(InvalidRepository):
        GitWorktreeManager(not_a_repository, tmp_path / "invalid-worktrees").create(
            WorktreeSpec(
                task_id="task_fixture_005",
                role=AgentRole.CODER,
                attempt=1,
                source_revision="HEAD",
            )
        )

    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    with pytest.raises(RevisionNotFound):
        manager.create(
            WorktreeSpec(
                task_id="task_fixture_005",
                role=AgentRole.CODER,
                attempt=1,
                source_revision="missing-candidate",
            )
        )


def test_worktree_path_and_coder_branch_are_never_reused(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    spec = WorktreeSpec(
        task_id="task_fixture_006",
        role=AgentRole.CODER,
        attempt=1,
        source_revision=_git(repository, "rev-parse", "HEAD"),
    )
    coder = manager.create(spec)

    with pytest.raises(WorktreeAlreadyExists):
        manager.create(spec)

    manager.remove(coder)
    assert _git(repository, "show-ref", "--verify", f"refs/heads/{coder.branch}")
    with pytest.raises(WorktreeAlreadyExists):
        manager.create(spec)


def test_inspection_rejects_a_reference_outside_the_managed_layout(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    qa = manager.create(
        WorktreeSpec(
            task_id="task_fixture_007",
            role=AgentRole.QA,
            attempt=1,
            source_revision=_git(repository, "rev-parse", "HEAD"),
        )
    )

    with pytest.raises(UnmanagedWorktree):
        manager.inspect(replace(qa, path=repository))


def test_repository_hook_cannot_execute_during_worktree_creation(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    hook_sentinel = tmp_path / "hook-executed"
    hook = repository / ".git/hooks/post-checkout"
    hook.write_text(
        f"#!/bin/sh\nprintf executed > {hook_sentinel}\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")

    manager.create(
        WorktreeSpec(
            task_id="task_fixture_008",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=_git(repository, "rev-parse", "HEAD"),
        )
    )

    assert not hook_sentinel.exists()


def test_external_checkout_filter_is_rejected_before_it_can_execute(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    filter_sentinel = tmp_path / "filter-executed"
    filter_program = tmp_path / "unsafe-filter"
    filter_program.write_text(
        f"#!/bin/sh\ncat\nprintf executed > {filter_sentinel}\n",
        encoding="utf-8",
    )
    filter_program.chmod(0o755)
    _git(repository, "config", "filter.unsafe.smudge", str(filter_program))
    (repository / ".gitattributes").write_text("README.md filter=unsafe\n", encoding="utf-8")
    _git(repository, "add", ".gitattributes")
    _git(repository, "commit", "-m", "configure unsafe checkout filter")
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")

    with pytest.raises(UnsafeRepositoryConfiguration):
        manager.create(
            WorktreeSpec(
                task_id="task_fixture_009",
                role=AgentRole.CODER,
                attempt=1,
                source_revision=_git(repository, "rev-parse", "HEAD"),
            )
        )

    assert not filter_sentinel.exists()
