"""A source rebind cannot silently admit changed or newly added native policy."""

from pathlib import Path

import pytest

from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.manager.baseline_production import native_rules_at_revision
from ai_software_engineer.repository_profile import discover_repository_profile
from tests.git.test_worktree import _create_fixture_repository, _git


def test_native_rules_match_frozen_discovery_and_ignore_mutable_checkout(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    (repository / ".trellis/spec").mkdir(parents=True)
    (repository / ".trellis/spec/runtime.md").write_text("frozen execution policy\n")
    (repository / "AGENTS.md").write_text("frozen agent policy\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "freeze native rules")
    revision = _git(repository, "rev-parse", "HEAD")
    profile = discover_repository_profile(repository, repository_id="repository_baseline")
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    original = native_rules_at_revision(
        manager, repository_id="repository_baseline", revision=revision
    )
    assert original == profile.native_rules
    (repository / "AGENTS.md").write_text("unapproved checkout policy\n")
    assert (
        native_rules_at_revision(manager, repository_id="repository_baseline", revision=revision)
        == original
    )
    with pytest.raises(ValueError, match="完整"):
        native_rules_at_revision(manager, repository_id="repository_baseline", revision="main")


@pytest.mark.parametrize(
    "path", ["AGENTS.md", ".github/workflows/build.yml", ".trellis/spec/new.md"]
)
def test_native_rules_include_new_target_policy_files(tmp_path: Path, path: str) -> None:
    repository = _create_fixture_repository(tmp_path)
    base = _git(repository, "rev-parse", "HEAD")
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    original = native_rules_at_revision(manager, repository_id="repository_baseline", revision=base)
    added = repository / path
    added.parent.mkdir(parents=True, exist_ok=True)
    added.write_text("new instruction\n")
    _git(repository, "add", path)
    _git(repository, "commit", "-m", "target adds rules")
    target = _git(repository, "rev-parse", "HEAD")
    new = native_rules_at_revision(manager, repository_id="repository_baseline", revision=target)
    assert new != original and any(rule.relative_path == path for rule in new)


def test_native_rules_reject_target_policy_symlink(tmp_path: Path) -> None:
    repository = _create_fixture_repository(tmp_path)
    (repository / "AGENTS.md").symlink_to("README.md")
    _git(repository, "add", "AGENTS.md")
    _git(repository, "commit", "-m", "untrusted native symlink")
    manager = GitWorktreeManager(repository, tmp_path / "worktrees")
    with pytest.raises(ValueError, match="普通"):
        native_rules_at_revision(
            manager,
            repository_id="repository_baseline",
            revision=_git(repository, "rev-parse", "HEAD"),
        )
