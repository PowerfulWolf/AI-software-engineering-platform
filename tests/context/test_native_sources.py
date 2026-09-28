"""Successor rules come from its sealed profile, never a parent's older bytes."""

from pathlib import Path

import pytest

from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.repository_profile import RepositoryProfile
from tests.manager.test_production_backend import _git


def test_successor_native_sources_use_frozen_revision_and_preserve_role_scope(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.context.native import rebind_native_rule_sources

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
    with pytest.raises(ValueError, match="native rule is not in the sealed profile"):
        rebind_native_rule_sources(
            root, approved, (source.model_copy(update={"uri": "project://repository_other/a"}),)
        )
    uncommitted = RepositoryProfile.discover(root, repository_id="repository_fixture")
    with pytest.raises(ValueError, match="native rule differs from the sealed profile"):
        rebind_native_rule_sources(root, uncommitted, (source,))
