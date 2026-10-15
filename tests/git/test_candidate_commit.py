"""CandidateCommit Skill behavior at the public Git boundary."""

import secrets
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


RETAINED_PATH = "src/artifacts/accepted.py"


def _ignored_repository(tmp_path: Path) -> tuple[Path, str]:
    root, _ = _repository(tmp_path)
    (root / ".gitignore").write_text(
        "artifacts/\n.pytest_cache/\n.ruff_cache/\n__pycache__/\n", encoding="utf-8"
    )
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-m", "ignore generated artifacts")
    (root / "src/artifacts").mkdir()
    (root / RETAINED_PATH).write_text("ACCEPTED = True\n", encoding="utf-8")
    return root, _git(root, "rev-parse", "HEAD")


def _request(source: str, *paths: str) -> CandidateCommitRequest:
    return CandidateCommitRequest(
        task_id="task_retained_candidate",
        source_revision=source,
        reported_paths=tuple(sorted(paths)),
        permissions=_permissions(),
    )


def test_retained_ignored_source_is_committed_and_visible_in_fresh_qa_checkout(
    tmp_path: Path,
) -> None:
    root, source = _ignored_repository(tmp_path)
    (root / "src/app.py").write_text("from .artifacts.accepted import ACCEPTED\n", encoding="utf-8")
    skill = GitCandidateCommitSkill(root, retained_source_paths=(RETAINED_PATH,))

    assert GitCandidateCommitSkill(root).changed_paths() == ("src/app.py",)
    assert skill.changed_paths() == ("src/app.py", RETAINED_PATH)
    result = skill.finalize(_request(source, "src/app.py", RETAINED_PATH))

    qa = tmp_path / "qa-checkout"
    _git(root, "worktree", "add", "--detach", str(qa), result.candidate_revision)
    assert (qa / RETAINED_PATH).read_text(encoding="utf-8") == "ACCEPTED = True\n"
    assert _git(qa, "ls-files", "--", RETAINED_PATH) == RETAINED_PATH
    assert _git(qa, "status", "--porcelain") == ""
    assert result.changed_paths == ("src/app.py", RETAINED_PATH)


def test_retained_source_must_be_reported_before_any_staging(tmp_path: Path) -> None:
    root, source = _ignored_repository(tmp_path)
    (root / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(CandidateCommitRejected, match="reported paths"):
        GitCandidateCommitSkill(root, retained_source_paths=(RETAINED_PATH,)).finalize(
            _request(source, "src/app.py")
        )

    assert _git(root, "rev-parse", "HEAD") == source
    assert _git(root, "diff", "--cached") == ""


def test_retained_source_authority_does_not_replace_coder_write_policy(tmp_path: Path) -> None:
    root, source = _ignored_repository(tmp_path)
    request = _request(source, RETAINED_PATH).model_copy(
        update={"permissions": _permissions().model_copy(update={"write_paths": ("src/app.py",)})}
    )

    with pytest.raises(CandidateCommitRejected, match="not allowed"):
        GitCandidateCommitSkill(root, retained_source_paths=(RETAINED_PATH,)).finalize(request)

    assert _git(root, "rev-parse", "HEAD") == source
    assert _git(root, "diff", "--cached") == ""


@pytest.mark.parametrize("fault", ["secret", "binary", "link", "oversized"])
def test_unsafe_retained_source_is_rejected_without_staging(tmp_path: Path, fault: str) -> None:
    from ai_software_engineer.git.capture import MAX_CAPTURE_BYTES

    root, source = _ignored_repository(tmp_path)
    target = root / RETAINED_PATH
    if fault == "secret":
        target.write_text(f'password = "{secrets.token_hex(24)}"\n', encoding="utf-8")
    elif fault == "binary":
        target.write_bytes(b"binary\0body")
    elif fault == "link":
        target.unlink()
        target.symlink_to(root / "src/app.py")
    else:
        target.write_text("x" * (MAX_CAPTURE_BYTES + 1), encoding="utf-8")

    with pytest.raises(CandidateCommitRejected, match="safe bounded regular text"):
        GitCandidateCommitSkill(root, retained_source_paths=(RETAINED_PATH,)).finalize(
            _request(source, RETAINED_PATH)
        )

    assert _git(root, "rev-parse", "HEAD") == source
    assert _git(root, "diff", "--cached") == ""


@pytest.mark.parametrize(
    "cache", [".pytest_cache/state", ".ruff_cache/state", "src/__pycache__/app.pyc"]
)
def test_retained_source_does_not_force_add_execution_cache(tmp_path: Path, cache: str) -> None:
    root, source = _ignored_repository(tmp_path)
    (root / cache).parent.mkdir(parents=True, exist_ok=True)
    (root / cache).write_bytes(b"cache\0body")
    skill = GitCandidateCommitSkill(
        root, retained_source_paths=tuple(sorted((RETAINED_PATH, cache)))
    )

    assert skill.changed_paths() == (RETAINED_PATH,)
    result = skill.finalize(_request(source, RETAINED_PATH))

    assert result.changed_paths == (RETAINED_PATH,)
    assert _git(root, "ls-files", "--", cache) == ""
    assert (root / cache).read_bytes() == b"cache\0body"


def test_retained_source_force_add_uses_exact_literal_paths(tmp_path: Path) -> None:
    root, source = _ignored_repository(tmp_path)
    (root / RETAINED_PATH).unlink()
    literal = "src/artifacts/a file.py"
    sibling = "src/artifacts/a-file.py"
    (root / literal).write_text("LITERAL = True\n", encoding="utf-8")
    (root / sibling).write_text("UNAUTHORIZED = True\n", encoding="utf-8")

    result = GitCandidateCommitSkill(root, retained_source_paths=(literal,)).finalize(
        _request(source, literal)
    )

    assert result.changed_paths == (literal,)
    assert _git(root, "ls-files", "--", literal) == literal
    assert _git(root, "ls-files", "--", sibling) == ""
    assert (root / sibling).read_text(encoding="utf-8") == "UNAUTHORIZED = True\n"


@pytest.mark.parametrize(
    "paths",
    [
        ("../outside.py",),
        ("/absolute.py",),
        ("src/*.py",),
        ("src/first.py", "src/first.py"),
        ("src/second.py", "src/first.py"),
    ],
)
def test_retained_source_authority_requires_exact_sorted_paths(
    tmp_path: Path, paths: tuple[str, ...]
) -> None:
    root, _ = _repository(tmp_path)
    with pytest.raises(CandidateCommitRejected, match="exact sorted relative paths"):
        GitCandidateCommitSkill(root, retained_source_paths=paths)
