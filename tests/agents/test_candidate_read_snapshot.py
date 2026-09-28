"""Verifier source access remains candidate-bound, bounded and policy-filtered."""

from pathlib import Path

import pytest

from ai_software_engineer.agents.codex_policy import candidate_read_snapshot
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.git import WorkspacePolicyError
from tests.agents.test_codex_cli import _git, _repository
from tests.orchestration.test_runner import _definitions


def test_snapshot_uses_candidate_blobs_not_current_checkout_or_host(tmp_path: Path) -> None:
    root, revision = _repository(tmp_path)
    (root / "README.md").write_text("changed checkout\n")
    (root / "untracked.txt").write_text("host-only text\n")
    snapshot = candidate_read_snapshot(root, revision, _definitions()[AgentRole.QA].permissions)
    assert "fixture" in snapshot
    assert "changed checkout" not in snapshot
    assert "host-only text" not in snapshot
    assert revision in snapshot
    with pytest.raises(WorkspacePolicyError, match="bounded context"):
        candidate_read_snapshot(
            root, revision, _definitions()[AgentRole.QA].permissions, max_bytes=1
        )


def test_snapshot_skips_links_denied_paths_and_redacts(tmp_path: Path) -> None:
    root, _ = _repository(tmp_path)
    secret = tmp_path / "outside.txt"
    secret.write_text("outside-secret")
    (root / "link.txt").symlink_to(secret)
    (root / "private.txt").write_text("never included")
    (root / "README.md").write_text("password=top-secret-value\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "snapshot fixture")
    permissions = _definitions()[AgentRole.QA].permissions.model_copy(
        update={"read_paths": ("README.md",)}
    )
    snapshot = candidate_read_snapshot(root, _git(root, "rev-parse", "HEAD"), permissions)
    assert "outside-secret" not in snapshot
    assert "never included" not in snapshot
    assert "top-secret-value" not in snapshot
    assert "REDACTED" in snapshot
