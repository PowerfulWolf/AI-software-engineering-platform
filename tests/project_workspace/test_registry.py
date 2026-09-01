"""Contract tests for external per-project AI workspace registration."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.project_workspace import (
    WORKSPACE_DIRECTORIES,
    WORKSPACE_MANIFEST_NAME,
    ProjectRootNotFound,
    ProjectWorkspaceConflict,
    ProjectWorkspaceCorruption,
    ProjectWorkspaceError,
    ProjectWorkspaceManifest,
    ProjectWorkspaceRegistry,
    WorkspacePlacementError,
    WorkspaceRootError,
    project_id_for_root,
)


def test_register_creates_external_normalized_sidecar_without_touching_project(
    tmp_path: Path,
) -> None:
    project = tmp_path / "target-project"
    project.mkdir()
    source = project / "README.md"
    source.write_text("project-owned\n", encoding="utf-8")
    registry = ProjectWorkspaceRegistry(tmp_path / "ai-workspaces")

    workspace = registry.register(project)

    assert workspace.manifest.layout_version == "v0.2"
    assert workspace.project_root == project.resolve()
    assert workspace.root.parent == (tmp_path / "ai-workspaces").resolve()
    assert workspace.root != workspace.project_root
    assert source.read_text(encoding="utf-8") == "project-owned\n"
    assert workspace.manifest_path.is_file()
    assert workspace.directory("profile").is_dir()
    assert workspace.directory("assignments").is_dir()
    assert workspace.directory("spec-conflicts").is_dir()
    assert not (project / ".ase").exists()
    assert set(project.iterdir()) == {source}
    assert {path.name for path in workspace.root.iterdir()} == {
        *WORKSPACE_DIRECTORIES,
        WORKSPACE_MANIFEST_NAME,
    }
    payload = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas" / "project-workspace.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
        == []
    )


def test_manifest_rejects_legacy_project_owned_agents_layout(tmp_path: Path) -> None:
    project = tmp_path / "target-project"
    project.mkdir()
    workspace = ProjectWorkspaceRegistry(tmp_path / "sidecars").register(project)
    payload = workspace.manifest.to_wire()
    layout = payload["layout"]
    assert isinstance(layout, dict)
    layout["agents"] = layout.pop("assignments")
    payload["layout_version"] = "v0.1"

    with pytest.raises(ValidationError):
        ProjectWorkspaceManifest.model_validate(payload)


def test_register_is_idempotent_and_preserves_first_manifest_observation(tmp_path: Path) -> None:
    project = tmp_path / "service"
    project.mkdir()
    registry = ProjectWorkspaceRegistry(tmp_path / "sidecars")

    first = registry.register(project)
    replay = registry.register(project)

    assert replay == first
    assert replay.manifest.created_at == first.manifest.created_at
    assert tuple(sorted(path.name for path in replay.root.iterdir())) == tuple(
        sorted(path.name for path in first.root.iterdir())
    )


def test_project_id_is_stable_and_distinguishes_same_named_projects(tmp_path: Path) -> None:
    first = tmp_path / "one" / "service"
    second = tmp_path / "two" / "service"
    first.mkdir(parents=True)
    second.mkdir(parents=True)

    assert project_id_for_root(first) == project_id_for_root(first)
    assert project_id_for_root(first) != project_id_for_root(second)


def test_manifest_rejects_relative_persisted_paths() -> None:
    with pytest.raises(ValidationError, match="absolute"):
        ProjectWorkspaceManifest.model_validate(
            {
                "project_id": "project_relative_001",
                "project_root": "relative/project",
                "ai_workspace_root": "relative/sidecar",
                "created_at": "2026-09-01T00:00:00Z",
                "manifest_sha256": "0" * 64,
            }
        )


def test_registry_rejects_missing_project_and_in_project_sidecar(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ProjectRootNotFound):
        ProjectWorkspaceRegistry(tmp_path / "sidecars").register(missing)

    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(WorkspacePlacementError):
        ProjectWorkspaceRegistry(project / "ai").register(project)


def test_registry_rejects_symlink_registry_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    actual_registry = tmp_path / "actual-sidecars"
    actual_registry.mkdir()
    linked_registry = tmp_path / "linked-sidecars"
    linked_registry.symlink_to(actual_registry, target_is_directory=True)

    with pytest.raises(WorkspaceRootError, match="symlink"):
        ProjectWorkspaceRegistry(linked_registry).register(project)


def test_registry_rejects_project_id_collision(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    registry = ProjectWorkspaceRegistry(tmp_path / "sidecars")
    registry.register(first, project_id="project_shared_001")

    with pytest.raises(ProjectWorkspaceConflict):
        registry.register(second, project_id="project_shared_001")


def test_registry_fails_closed_on_missing_manifest_or_layout(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry = ProjectWorkspaceRegistry(tmp_path / "sidecars")
    workspace = registry.register(project)
    workspace.manifest_path.unlink()

    with pytest.raises(ProjectWorkspaceCorruption):
        registry.register(project)


def test_registry_fails_closed_on_missing_layout_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry = ProjectWorkspaceRegistry(tmp_path / "sidecars")
    workspace = registry.register(project)
    workspace.directory("logs").rmdir()

    with pytest.raises(ProjectWorkspaceCorruption):
        registry.register(project)


def test_registry_detects_schema_valid_manifest_tampering(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry = ProjectWorkspaceRegistry(tmp_path / "sidecars")
    workspace = registry.register(project)
    payload = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    payload["created_at"] = "2026-09-01T01:00:00Z"
    workspace.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProjectWorkspaceCorruption, match="digest"):
        registry.register(project)


def test_failed_initialization_cleans_staging_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry_root = tmp_path / "sidecars"
    registry = ProjectWorkspaceRegistry(registry_root)

    def fail_write(_path: Path, _manifest: object) -> None:
        raise OSError("simulated manifest failure")

    monkeypatch.setattr("ai_software_engineer.project_workspace._write_manifest", fail_write)

    with pytest.raises(ProjectWorkspaceError, match="cannot initialize sidecar workspace"):
        registry.register(project)
    assert tuple(registry_root.iterdir()) == ()
