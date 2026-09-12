"""Contract tests for Project-owned, external Repository sidecars."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.repository_workspace import (
    WORKSPACE_DIRECTORIES,
    WORKSPACE_MANIFEST_NAME,
    RepositoryRootNotFound,
    RepositoryWorkspaceCorruption,
    RepositoryWorkspaceError,
    RepositoryWorkspaceManifest,
    WorkspacePlacementError,
    WorkspaceRootError,
)
from ai_software_engineer.team_workspace import TeamWorkspace


def registry(tmp_path: Path):
    team = TeamWorkspace.initialize(
        tmp_path / "platform",
        team_id="team_test",
        name="Test Team",
    )
    project = team.project_registry().register(
        project_id="project_test",
        name="Test Project",
    )
    return project.repository_registry()


def test_register_creates_external_sidecar_without_touching_repository(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "target-repository"
    repository.mkdir()
    source = repository / "README.md"
    source.write_text("repository-owned\n", encoding="utf-8")

    workspace = registry(tmp_path).register(repository)

    assert workspace.manifest.schema_version == "v0.2"
    assert workspace.manifest.layout_version == "v0.2"
    assert workspace.manifest.project_id == "project_test"
    assert workspace.repository_root == repository.resolve()
    assert workspace.root.parent.name == "repositories"
    assert workspace.root != workspace.repository_root
    assert source.read_text(encoding="utf-8") == "repository-owned\n"
    assert not (repository / ".ase").exists()
    assert set(repository.iterdir()) == {source}
    assert {path.name for path in workspace.root.iterdir()} == {
        *WORKSPACE_DIRECTORIES,
        WORKSPACE_MANIFEST_NAME,
    }
    payload = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/repository-workspace.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
        == []
    )


def test_manifest_rejects_repository_owned_agents_layout(tmp_path: Path) -> None:
    repository = tmp_path / "target-repository"
    repository.mkdir()
    workspace = registry(tmp_path).register(repository)
    payload = workspace.manifest.to_wire()
    layout = payload["layout"]
    assert isinstance(layout, dict)
    layout["agents"] = layout.pop("assignments")

    with pytest.raises(ValidationError):
        RepositoryWorkspaceManifest.model_validate(payload)


def test_register_is_idempotent_and_preserves_first_manifest_observation(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "service"
    repository.mkdir()
    catalog = registry(tmp_path)

    first = catalog.register(repository)
    replay = catalog.register(repository)

    assert replay == first
    assert replay.manifest.created_at == first.manifest.created_at


def test_project_namespace_makes_repository_identity_stable(tmp_path: Path) -> None:
    repository = tmp_path / "service"
    repository.mkdir()
    catalog = registry(tmp_path)

    first = catalog.register(repository)
    second = catalog.register(repository)

    assert first.repository_id == second.repository_id
    assert first.repository_id.startswith("repository_")


def test_manifest_rejects_relative_persisted_paths() -> None:
    with pytest.raises(ValidationError, match="absolute"):
        RepositoryWorkspaceManifest.model_validate(
            {
                "project_id": "project_test",
                "project_manifest_sha256": "1" * 64,
                "repository_id": "repository_relative_001",
                "repository_root": "relative/repository",
                "ai_workspace_root": "relative/sidecar",
                "created_at": "2026-09-01T00:00:00Z",
                "manifest_sha256": "0" * 64,
            }
        )


def test_registry_rejects_missing_repository_and_overlapping_sidecar(
    tmp_path: Path,
) -> None:
    with pytest.raises(RepositoryRootNotFound):
        registry(tmp_path).register(tmp_path / "missing")

    repository = tmp_path / "repository"
    repository.mkdir()
    team = TeamWorkspace.initialize(
        repository / "platform",
        team_id="team_overlap",
        name="Overlap",
    )
    project = team.project_registry().register(
        project_id="project_overlap",
        name="Overlap",
    )
    with pytest.raises((ValueError, WorkspacePlacementError), match=r"overlap|outside"):
        project.repository_registry().register(repository)


def test_registry_rejects_symlink_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    linked = tmp_path / "linked-repository"
    linked.symlink_to(repository, target_is_directory=True)

    with pytest.raises((WorkspaceRootError, ValueError), match="symlink"):
        registry(tmp_path).register(linked)


def test_registry_rejects_repository_id_not_bound_to_owner_and_root(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    catalog = registry(tmp_path)
    bound = catalog.register(first)

    with pytest.raises(ValueError, match="bound"):
        catalog.register(second, repository_id=bound.repository_id)


def test_registry_fails_closed_on_missing_manifest_or_layout(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    catalog = registry(tmp_path)
    workspace = catalog.register(repository)
    workspace.manifest_path.unlink()

    with pytest.raises(RepositoryWorkspaceCorruption):
        catalog.register(repository)


def test_registry_fails_closed_on_missing_layout_directory(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    catalog = registry(tmp_path)
    workspace = catalog.register(repository)
    workspace.directory("logs").rmdir()

    with pytest.raises(RepositoryWorkspaceCorruption):
        catalog.register(repository)


def test_registry_detects_schema_valid_manifest_tampering(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    catalog = registry(tmp_path)
    workspace = catalog.register(repository)
    payload = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    payload["created_at"] = "2026-09-01T01:00:00Z"
    workspace.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RepositoryWorkspaceCorruption, match="digest"):
        catalog.register(repository)


def test_failed_initialization_cleans_staging_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    catalog = registry(tmp_path)
    registry_root = catalog.registry_root

    def fail_write(_path: Path, _manifest: object) -> None:
        raise OSError("simulated manifest failure")

    monkeypatch.setattr("ai_software_engineer.repository_workspace._write_manifest", fail_write)

    with pytest.raises(RepositoryWorkspaceError, match="cannot initialize sidecar workspace"):
        catalog.register(repository)
    assert tuple(registry_root.iterdir()) == ()
