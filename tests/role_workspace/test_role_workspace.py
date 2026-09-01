"""T016 tests for role worktree and command executor composition."""

import subprocess
import sys
from pathlib import Path

import pytest

from ai_software_engineer.domain import (
    AgentDefinition,
    AgentPermissions,
    AgentRole,
    ArtifactKind,
    NetworkAccess,
)
from ai_software_engineer.git import DirtyWorktree, GitWorktreeManager, WorktreeSpec
from ai_software_engineer.role_workspace import (
    RoleWorktreeAgentMismatch,
    RoleWorktreeSession,
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


def _fixture_repository(root: Path) -> Path:
    repository = root / "repository"
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.name", "Fixture Author")
    _git(repository, "config", "user.email", "fixture@example.invalid")
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")
    source = repository / "src"
    source.mkdir()
    (source / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repository, "add", "README.md", "src/app.py")
    _git(repository, "commit", "-m", "initial fixture")
    return repository


def _agent(role: AgentRole) -> AgentDefinition:
    inputs = {
        AgentRole.CODER: (
            ArtifactKind.PLAN,
            ArtifactKind.QA_REPORT,
            ArtifactKind.REVIEW_REPORT,
        ),
        AgentRole.QA: (ArtifactKind.PLAN, ArtifactKind.IMPLEMENTATION_REPORT),
        AgentRole.REVIEWER: (
            ArtifactKind.PLAN,
            ArtifactKind.IMPLEMENTATION_REPORT,
            ArtifactKind.QA_REPORT,
        ),
    }[role]
    output = {
        AgentRole.CODER: ArtifactKind.IMPLEMENTATION_REPORT,
        AgentRole.QA: ArtifactKind.QA_REPORT,
        AgentRole.REVIEWER: ArtifactKind.REVIEW_REPORT,
    }[role]
    return AgentDefinition(
        id=f"agent_{role.value}_016",
        role=role,
        version="v0.1",
        model=f"fixture-{role.value}",
        provider="local",
        permissions=AgentPermissions(
            read_paths=("**",),
            write_paths=("src/**", "tests/**") if role is AgentRole.CODER else (),
            commands=(sys.executable,),
            network=NetworkAccess.NONE,
        ),
        input_artifacts=inputs,
        output_artifacts=(output,),
        max_retries=0,
        timeout_seconds=60,
        token_budget=1_000,
    )


def _spec(repository: Path, role: AgentRole, task_id: str = "task_workspace_016") -> WorktreeSpec:
    return WorktreeSpec(
        task_id=task_id,
        role=role,
        attempt=1,
        source_revision=_git(repository, "rev-parse", "HEAD"),
    )


def test_coder_binding_runs_in_manager_worktree_and_closes_cleanly(tmp_path: Path) -> None:
    repository = _fixture_repository(tmp_path)
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    session = RoleWorktreeSession(manager)

    binding = session.open(_spec(repository, AgentRole.CODER), _agent(AgentRole.CODER))
    result = binding.executor.run((sys.executable, "-c", "import os; print(os.getcwd())"))

    assert result.returncode == 0
    assert result.stdout.strip() == str(binding.worktree.path)
    assert binding.worktree.branch == "ai/task_workspace_016/attempt-1"
    assert session.inspect(binding).dirty is False

    session.close(binding)
    assert not binding.worktree.path.exists()
    assert _git(repository, "show-ref", "--verify", f"refs/heads/{binding.worktree.branch}")


def test_qa_binding_preserves_detached_candidate_identity(tmp_path: Path) -> None:
    repository = _fixture_repository(tmp_path)
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    coder = manager.create(_spec(repository, AgentRole.CODER, "task_workspace_qa"))
    (coder.path / "README.md").write_text("candidate\n", encoding="utf-8")
    _git(coder.path, "add", "README.md")
    _git(coder.path, "commit", "-m", "candidate")
    candidate = _git(coder.path, "rev-parse", "HEAD")

    session = RoleWorktreeSession(manager)
    qa = session.open(
        WorktreeSpec(
            task_id="task_workspace_qa",
            role=AgentRole.QA,
            attempt=1,
            source_revision=candidate,
        ),
        _agent(AgentRole.QA),
    )
    result = qa.executor.run((sys.executable, "-c", "import os; print(os.getcwd())"))

    assert result.stdout.strip() == str(qa.worktree.path)
    assert qa.worktree.detached is True
    assert qa.worktree.branch is None
    assert session.inspect(qa).head_revision == candidate

    session.close(qa)
    manager.remove(coder)


def test_role_mismatch_is_rejected_before_worktree_creation(tmp_path: Path) -> None:
    repository = _fixture_repository(tmp_path)
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    session = RoleWorktreeSession(manager)

    with pytest.raises(RoleWorktreeAgentMismatch, match="does not match"):
        session.open(_spec(repository, AgentRole.CODER), _agent(AgentRole.QA))

    assert not (tmp_path / "worktrees/task_workspace_016/coder-attempt-01").exists()


def test_dirty_binding_cannot_be_closed_and_is_retained_for_evidence(tmp_path: Path) -> None:
    repository = _fixture_repository(tmp_path)
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    session = RoleWorktreeSession(manager)
    binding = session.open(_spec(repository, AgentRole.REVIEWER), _agent(AgentRole.REVIEWER))
    evidence = binding.worktree.path / "review-output.txt"
    # Simulate unexpected external dirtiness; Reviewer permissions do not authorize this write.
    evidence.write_text("review evidence\n", encoding="utf-8")

    with pytest.raises(DirtyWorktree) as error:
        session.close(binding)

    assert error.value.changed_paths == ("review-output.txt",)
    assert binding.worktree.path.exists()
    evidence.unlink()
    session.close(binding)


def test_executor_configuration_failure_does_not_leave_new_worktree(tmp_path: Path) -> None:
    repository = _fixture_repository(tmp_path)
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")

    with pytest.raises(ValueError, match="environment variable name"):
        RoleWorktreeSession(manager, environment_allowlist=("not-safe",))

    assert not (tmp_path / "worktrees/task_workspace_016/coder-attempt-01").exists()
    assert _git(repository, "branch", "--list", "ai/task_workspace_016/attempt-1") == ""
