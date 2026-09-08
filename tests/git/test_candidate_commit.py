"""CandidateCommit Skill behavior at the public Git boundary."""

import subprocess
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentPermissions, NetworkAccess
from ai_software_engineer.git import (
    CandidateCommitRejected,
    CandidateCommitRequest,
    GitCandidateCommitSkill,
)


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments), cwd=root, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Fixture Author")
    _git(root, "config", "user.email", "fixture@example.invalid")
    source = root / "src"
    source.mkdir()
    (source / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "src/app.py")
    _git(root, "commit", "-m", "initial fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _permissions() -> AgentPermissions:
    return AgentPermissions(
        read_paths=("**",),
        write_paths=("src/**",),
        commands=("pytest",),
        network=NetworkAccess.NONE,
    )


def test_skill_creates_one_policy_checked_candidate_commit(tmp_path: Path) -> None:
    root, source = _repository(tmp_path)
    (root / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    skill = GitCandidateCommitSkill(root)

    result = skill.finalize(
        CandidateCommitRequest(
            task_id="task_candidate_001",
            source_revision=source,
            reported_paths=("src/app.py",),
            permissions=_permissions(),
        )
    )

    assert result.source_revision == source
    assert result.candidate_revision == _git(root, "rev-parse", "HEAD")
    assert result.changed_paths == ("src/app.py",)
    assert result.candidate_revision != source
    assert _git(root, "status", "--porcelain") == ""
    assert _git(root, "show", "-s", "--format=%s", "HEAD") == "ai: task_candidate_001"


def test_skill_rejects_inventory_mismatch_without_committing(tmp_path: Path) -> None:
    root, source = _repository(tmp_path)
    (root / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(CandidateCommitRejected, match="reported paths"):
        GitCandidateCommitSkill(root).finalize(
            CandidateCommitRequest(
                task_id="task_candidate_002",
                source_revision=source,
                reported_paths=("src/other.py",),
                permissions=_permissions(),
            )
        )

    assert _git(root, "rev-parse", "HEAD") == source
    assert _git(root, "status", "--porcelain") == "M src/app.py"


def test_skill_rejects_paths_outside_coder_authority(tmp_path: Path) -> None:
    root, source = _repository(tmp_path)
    (root / "README.md").write_text("unauthorized\n", encoding="utf-8")

    with pytest.raises(CandidateCommitRejected):
        GitCandidateCommitSkill(root).finalize(
            CandidateCommitRequest(
                task_id="task_candidate_003",
                source_revision=source,
                reported_paths=("README.md",),
                permissions=_permissions(),
            )
        )

    assert _git(root, "rev-parse", "HEAD") == source


def test_skill_rejects_source_drift_before_staging(tmp_path: Path) -> None:
    root, old_source = _repository(tmp_path)
    (root / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(root, "add", "src/app.py")
    _git(root, "commit", "-m", "external candidate")
    current = _git(root, "rev-parse", "HEAD")
    (root / "src" / "app.py").write_text("VALUE = 3\n", encoding="utf-8")

    with pytest.raises(CandidateCommitRejected, match="source revision drifted"):
        GitCandidateCommitSkill(root).finalize(
            CandidateCommitRequest(
                task_id="task_candidate_004",
                source_revision=old_source,
                reported_paths=("src/app.py",),
                permissions=_permissions(),
            )
        )

    assert _git(root, "rev-parse", "HEAD") == current
    assert _git(root, "status", "--porcelain") == "M src/app.py"


def test_candidate_request_rejects_an_empty_inventory() -> None:
    with pytest.raises(ValueError, match="at least one reported path"):
        CandidateCommitRequest(
            task_id="task_candidate_005",
            source_revision="a" * 40,
            reported_paths=(),
            permissions=_permissions(),
        )
