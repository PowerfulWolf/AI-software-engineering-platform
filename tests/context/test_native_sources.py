"""Successor rules come from its sealed profile, never a parent's older bytes."""

import hashlib
from pathlib import Path

import pytest

from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.repository_profile import RepositoryProfile
from tests.manager.test_production_backend import _git, _git_output


def test_successor_native_sources_use_frozen_revision_and_preserve_role_scope(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.context.native import (
        native_rule_prompt_sources,
        rebind_native_rule_sources,
    )

    root = tmp_path / "repository"
    root.mkdir()
    _git("init", "-b", "main", cwd=root)
    rules = root / "README.md"
    rules.write_text("Original rules.\n")
    _git("add", ".", cwd=root)
    _git("commit", "-m", "original", cwd=root)
    old = RepositoryProfile.discover(root, repository_id="repository_fixture")
    source = ContextSource(
        source_id="native.rule.0",
        uri=old.native_rules[0].uri,
        content=rules.read_text(),
        required=True,
        roles=(AgentRole.QA,),
    )
    rules.write_text("Approved successor rules.\n")
    _git("add", ".", cwd=root)
    _git("commit", "-m", "successor", cwd=root)
    approved = RepositoryProfile.discover(root, repository_id="repository_fixture")
    rules.write_text("Unapproved current checkout.\n")
    result = rebind_native_rule_sources(root, approved, (source,))
    assert result == (source.model_copy(update={"content": "Approved successor rules.\n"}),)
    assert rules.read_text() == "Unapproved current checkout.\n"
    assert rebind_native_rule_sources(root, approved, ()) == ()
    rebound = native_rule_prompt_sources(result)[0]
    assert rebound.source_id == "native.reference.0"
    assert rebound.roles == (AgentRole.QA,)
    assert rebound.required
    assert "Approved successor rules." not in (rebound.content or "")
    assert approved.native_rules[0].uri in (rebound.content or "")
    assert hashlib.sha256(b"Approved successor rules.\n").hexdigest() in (rebound.content or "")
    with pytest.raises(ValueError, match="native rule is not in the sealed profile"):
        rebind_native_rule_sources(
            root, approved, (source.model_copy(update={"uri": "project://repository_other/a"}),)
        )
    uncommitted = RepositoryProfile.discover(root, repository_id="repository_fixture")
    with pytest.raises(ValueError, match="native rule differs from the sealed profile"):
        rebind_native_rule_sources(root, uncommitted, (source,))


def test_linked_worktree_legacy_profile_rebinds_from_explicit_task_revision(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.context.native import rebind_native_rule_sources

    source_root = tmp_path / "source"
    source_root.mkdir()
    _git("init", "-b", "main", cwd=source_root)
    rules = source_root / "README.md"
    rules.write_text("Rules from the sealed base.\n")
    _git("add", ".", cwd=source_root)
    _git("commit", "-m", "base", cwd=source_root)
    revision = _git_output("rev-parse", "HEAD", cwd=source_root)
    linked_root = tmp_path / "linked"
    _git("worktree", "add", str(linked_root), revision, cwd=source_root)

    legacy = RepositoryProfile.discover(linked_root, repository_id="repository_fixture")
    assert legacy.source_revision == "unknown"
    source = ContextSource(
        source_id="native.rule.0",
        uri=legacy.native_rules[0].uri,
        content=rules.read_text(),
        required=True,
        roles=(AgentRole.QA,),
    )

    result = rebind_native_rule_sources(
        linked_root,
        legacy,
        (source,),
        source_revision=revision,
    )

    assert result[0].content == "Rules from the sealed base.\n"
