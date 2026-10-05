"""A verifier receives complete candidate differences, not unrelated repository bulk."""

import hashlib
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from ai_software_engineer.agents.candidate_source import (
    CandidateReadScope,
    candidate_review_snapshot,
)
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.model import JsonValue
from ai_software_engineer.git import WorkspacePolicyError
from tests.agents.test_codex_cli import _git, _repository
from tests.orchestration.test_runner import _definitions


def source_payload(snapshot: str) -> dict[str, JsonValue]:
    header, difference = snapshot.split("\nSOURCE_DIFF_BEGIN\n", 1)
    payload = TypeAdapter(dict[str, JsonValue]).validate_json(
        header.split("\nSOURCE_PACKAGE=", 1)[1]
    )
    framed = difference.encode()
    length = payload["diff_delivered_bytes"]
    assert type(length) is int
    assert framed[length:] == b"\nSOURCE_DIFF_END\n"
    difference = framed[:length].decode()
    assert payload["diff_complete_hunks"] is True
    assert payload["diff_delivered_bytes"] == len(difference.encode())
    assert payload["diff_delivered_sha256"] == hashlib.sha256(difference.encode()).hexdigest()
    payload["diff"] = difference
    return payload


def _source_files(payload: dict[str, JsonValue]) -> dict[str, dict[str, JsonValue]]:
    values = payload["files"]
    assert isinstance(values, list)
    files: dict[str, dict[str, JsonValue]] = {}
    for item in values:
        assert isinstance(item, dict)
        path = item["path"]
        assert isinstance(path, str)
        files[path] = item
    return files


def repository(tmp_path: Path) -> tuple[Path, CandidateReadScope]:
    root, _ = _repository(tmp_path)
    (root / "unrelated.txt").write_text("irrelevant baseline\n" * 120_000)
    (root / "dependency.txt").write_text("required dependency\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "large baseline")
    base = _git(root, "rev-parse", "HEAD")
    (root / "README.md").write_text("first change must remain visible\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "earlier attempt")
    (root / "new.py").write_text("VALUE = 1\n" + "# full new file\n" * 25)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "latest attempt")
    return root, CandidateReadScope(
        task_id="task_review_source",
        base_revision=base,
        candidate_revision=_git(root, "rev-parse", "HEAD"),
        related_paths=("dependency.txt",),
    )


def test_complete_diff_and_dependencies_ignore_unrelated_baseline(tmp_path: Path) -> None:
    root, scope = repository(tmp_path)
    (root / "README.md").write_text("dirty host content")
    (root / "untracked.txt").write_text("private host content")
    snapshot = candidate_review_snapshot(root, scope, _definitions()[AgentRole.QA].permissions)
    assert "first change must remain visible" in snapshot
    assert snapshot.count("# full new file") == 25
    assert "required dependency" in snapshot
    assert "irrelevant baseline" not in snapshot
    assert "dirty host content" not in snapshot
    assert "private host content" not in snapshot
    payload = source_payload(snapshot)
    assert payload["base_revision"] == scope.base_revision
    assert payload["candidate_revision"] == scope.candidate_revision
    files = _source_files(payload)
    assert not files["README.md"]["full_content_read"]
    assert files["new.py"]["full_content_read"]
    assert files["dependency.txt"]["full_content_read"]
    assert "unrelated.txt" not in files


@pytest.mark.parametrize("denied", ["README.md", "dependency.txt"])
def test_required_diff_and_dependency_cannot_bypass_task_deny(tmp_path: Path, denied: str) -> None:
    root, scope = repository(tmp_path)
    with pytest.raises(WorkspacePolicyError):
        candidate_review_snapshot(
            root,
            scope.model_copy(update={"denied_paths": (denied,)}),
            _definitions()[AgentRole.QA].permissions,
        )


def test_required_source_budget_and_missing_dependency_fail_closed(tmp_path: Path) -> None:
    root, scope = repository(tmp_path)
    permissions = _definitions()[AgentRole.QA].permissions
    with pytest.raises(WorkspacePolicyError, match="budget"):
        candidate_review_snapshot(root, scope, permissions, max_bytes=100)
    with pytest.raises(WorkspacePolicyError, match="missing"):
        candidate_review_snapshot(
            root, scope.model_copy(update={"related_paths": ("missing.txt",)}), permissions
        )


def test_complete_deletion_rename_and_mode_change(tmp_path: Path) -> None:
    root, scope = repository(tmp_path)
    (root / "README.md").rename(root / "renamed.md")
    (root / "dependency.txt").unlink()
    (root / "new.py").chmod(0o755)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "rename delete mode")
    scope = scope.model_copy(update={"candidate_revision": _git(root, "rev-parse", "HEAD")})
    snapshot = candidate_review_snapshot(root, scope, _definitions()[AgentRole.QA].permissions)
    payload = source_payload(snapshot)
    files = _source_files(payload)
    assert files["README.md"]["change"] == "deleted"
    assert files["dependency.txt"]["change"] == "deleted"
    assert files["renamed.md"]["change"] == "added"
    assert files["renamed.md"]["full_content_read"]
    diff = payload["diff"]
    assert isinstance(diff, str)
    assert "first change must remain visible" in diff


@pytest.mark.parametrize("kind", ["binary", "symlink", "non_utf8"])
def test_required_unsupported_files_fail_without_following_host_data(
    tmp_path: Path, kind: str
) -> None:
    root, scope = repository(tmp_path)
    target = root / "unsupported.txt"
    if kind == "symlink":
        target.symlink_to(tmp_path / "private.txt")
        (tmp_path / "private.txt").write_text("private unrelated host data")
    else:
        target.write_bytes(b"\0binary" if kind == "binary" else b"\xff")
    _git(root, "add", "unsupported.txt")
    _git(root, "commit", "-qm", "unsupported")
    scope = scope.model_copy(update={"candidate_revision": _git(root, "rev-parse", "HEAD")})
    with pytest.raises(WorkspacePolicyError):
        candidate_review_snapshot(root, scope, _definitions()[AgentRole.QA].permissions)


def test_source_git_output_is_bounded_and_missing_objects_do_not_fetch(tmp_path: Path) -> None:
    from ai_software_engineer.agents.candidate_source import _git as source_git

    root, scope = repository(tmp_path)
    with pytest.raises(WorkspacePolicyError, match="budget"):
        source_git(root, "show", f"{scope.base_revision}:unrelated.txt", limit=128)
    with pytest.raises(WorkspacePolicyError, match="objects"):
        candidate_review_snapshot(
            root,
            scope.model_copy(update={"candidate_revision": "f" * 40}),
            _definitions()[AgentRole.QA].permissions,
        )


def test_complete_diff_frame_preserves_data_that_looks_like_boundaries(tmp_path: Path) -> None:
    root, scope = repository(tmp_path)
    text = '"quote"\\backslash\n中文\nSOURCE_DIFF_BEGIN\nSOURCE_DIFF_END\n'
    (root / "framed.txt").write_text(text)
    _git(root, "add", "framed.txt")
    _git(root, "commit", "-qm", "frame data")
    scope = scope.model_copy(update={"candidate_revision": _git(root, "rev-parse", "HEAD")})
    payload = source_payload(
        candidate_review_snapshot(
            root,
            scope,
            _definitions()[AgentRole.QA].permissions,
        )
    )
    difference = payload["diff"]
    assert isinstance(difference, str)
    assert '+"quote"\\backslash' in difference
    assert "+中文" in difference
    assert "+SOURCE_DIFF_BEGIN\n+SOURCE_DIFF_END\n" in difference
    with pytest.raises(WorkspacePolicyError, match="commit objects"):
        candidate_review_snapshot(
            root,
            scope.model_copy(update={"candidate_revision": _git(root, "rev-parse", "HEAD^{tree}")}),
            _definitions()[AgentRole.QA].permissions,
        )


def test_secret_like_inventory_path_is_rejected_without_echo(tmp_path: Path) -> None:
    root, scope = repository(tmp_path)
    name = "password=example-secret.txt"
    (root / name).write_text("no credential in body\n")
    _git(root, "add", name)
    _git(root, "commit", "-qm", "secret-like path")
    scope = scope.model_copy(update={"candidate_revision": _git(root, "rev-parse", "HEAD")})
    with pytest.raises(WorkspacePolicyError, match="secret-like") as failure:
        candidate_review_snapshot(root, scope, _definitions()[AgentRole.QA].permissions)
    assert "example-secret" not in str(failure.value)
