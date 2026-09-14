"""Strict Specs are immutable, versioned, scoped and explicitly activated."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.manager.spec_rules import (
    ProductionProjectRuleProvider,
    team_spec_rules,
)
from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.spec_documents import (
    CreateSpecDocument,
    ProjectSpecDocumentStore,
    SpecDocumentError,
    TeamSpecDocumentStore,
)
from ai_software_engineer.team_workspace import TeamWorkspace

NOW = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)


def _command(body: str = "Never merge without QA evidence.") -> CreateSpecDocument:
    return CreateSpecDocument(
        spec_key="delivery.qa-gate",
        title="QA gate",
        body_markdown=body,
        roles=(TeamRole.CODER, TeamRole.QA, TeamRole.REVIEWER),
        stages=("implementing", "qa", "review"),
        path_globs=("src/**", "tests/**"),
        verification="QA report must contain passing test evidence.",
    )


def _team(tmp_path: Path) -> TeamWorkspace:
    return TeamWorkspace.initialize(tmp_path / "platform", team_id="team_specs", name="Specs")


def test_spec_versions_require_explicit_activation_and_are_immutable(tmp_path: Path) -> None:
    store = TeamSpecDocumentStore(_team(tmp_path))

    first = store.create(_command(), created_at=NOW)
    replay = store.create(_command(), created_at=NOW)
    second = store.create(_command("QA and Review evidence are mandatory."), created_at=NOW)

    assert replay == first
    assert (first.version, second.version) == (1, 2)
    assert store.active() == ()
    store.activate((first.spec_id,))
    assert store.active() == (first,)
    store.activate((second.spec_id,))
    assert store.active() == (second,)
    with pytest.raises(SpecDocumentError, match="active Spec keys"):
        store.activate((first.spec_id, second.spec_id))


def test_team_and_project_specs_compile_with_exact_provenance(tmp_path: Path) -> None:
    team = _team(tmp_path)
    project = team.project_registry().register(project_id="project_specs", name="Specs")
    repository = tmp_path / "repository"
    repository.mkdir()
    profile = RepositoryProfile.discover(
        repository,
        repository_id="repository_specs",
        observed_at=NOW,
    )
    team_store = TeamSpecDocumentStore(team)
    project_store = ProjectSpecDocumentStore(project)
    team_spec = team_store.create(_command(), created_at=NOW)
    project_spec = project_store.create(
        _command("The Project requires integration evidence."), created_at=NOW
    )
    team_store.activate((team_spec.spec_id,))
    project_store.activate((project_spec.spec_id,))

    team_rule = team_spec_rules(team_store.active())[0]
    provider = ProductionProjectRuleProvider(project_store.active())
    project_rule = provider.rules_for(profile)[0]
    source = provider.sources_for(profile)[0]

    assert team_rule.source_uri.startswith("platform://team/team_specs/specs/")
    assert project_rule.source_uri == source.uri
    assert project_rule.source_sha256 == source.sha256 == project_spec.spec_sha256
    assert isinstance(project_rule.value, dict)
    assert project_rule.value["verification"] == project_spec.verification


def test_project_spec_repository_scope_filters_rules(tmp_path: Path) -> None:
    team = _team(tmp_path)
    project = team.project_registry().register(project_id="project_specs", name="Specs")
    selected = tmp_path / "selected"
    other = tmp_path / "other"
    selected.mkdir()
    other.mkdir()
    registered = project.repository_registry().register(selected)
    command = _command().model_copy(update={"repository_ids": (registered.repository_id,)})
    store = ProjectSpecDocumentStore(project)
    spec = store.create(command, created_at=NOW)
    store.activate((spec.spec_id,))
    provider = ProductionProjectRuleProvider(store.active())

    assert provider.rules_for(
        RepositoryProfile.discover(
            selected, repository_id=registered.repository_id, observed_at=NOW
        )
    )
    assert not provider.rules_for(
        RepositoryProfile.discover(other, repository_id="repository_other", observed_at=NOW)
    )


def test_spec_rejects_repository_outside_its_owner_scope(tmp_path: Path) -> None:
    team = _team(tmp_path)
    project = team.project_registry().register(project_id="project_specs", name="Specs")
    command = _command().model_copy(update={"repository_ids": ("repository_unknown",)})

    with pytest.raises(SpecDocumentError, match="outside its owner scope"):
        ProjectSpecDocumentStore(project).create(command, created_at=NOW)
    with pytest.raises(SpecDocumentError, match="outside its owner scope"):
        TeamSpecDocumentStore(team).create(command, created_at=NOW)


def test_spec_allows_verification_to_be_defined_later(tmp_path: Path) -> None:
    store = TeamSpecDocumentStore(_team(tmp_path))

    document = store.create(_command().model_copy(update={"verification": ""}), created_at=NOW)

    assert document.verification == ""
    document.validate_integrity()

    with pytest.raises(ValueError):
        CreateSpecDocument(
            spec_key="delivery.qa-gate",
            title="QA gate",
            body_markdown="Never merge without QA evidence.",
            verification="x" * 8_001,
        )


def test_retired_spec_leaves_current_library_but_keeps_revision_history(
    tmp_path: Path,
) -> None:
    store = TeamSpecDocumentStore(_team(tmp_path))
    first = store.create(_command(), created_at=NOW)
    store.activate((first.spec_id,))

    with pytest.raises(SpecDocumentError, match="deactivated"):
        store.retire(first.spec_key)

    store.activate(())
    retirement = store.retire(first.spec_key)
    assert retirement.retired_spec_keys == (first.spec_key,)
    assert store.list() == ()
    assert (store.root / "documents" / first.spec_id / "spec.json").is_file()

    updated = store.create(_command("Updated QA rule."), created_at=NOW)
    assert updated.version == 2
    assert store.list() == (first, updated)
    assert store.retirement().retired_spec_keys == ()


def test_tampered_spec_retirement_fails_closed(tmp_path: Path) -> None:
    store = TeamSpecDocumentStore(_team(tmp_path))
    document = store.create(_command(), created_at=NOW)
    store.retire(document.spec_key)
    path = store.root / "retirement.json"
    payload = json.loads(path.read_text())
    payload["retirement_sha256"] = "0" * 64
    path.write_text(json.dumps(payload))

    with pytest.raises(SpecDocumentError, match="digest mismatch"):
        store.list()
