"""Team, Project, Requirement and Repository ownership boundaries."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.service import JointBackend, JointDeliveryService
from ai_software_engineer.team_workspace import TeamWorkspace


def team(root: Path) -> TeamWorkspace:
    return TeamWorkspace.initialize(root, team_id="team_ai", name="AI Team")


def test_team_and_projects_are_sibling_aggregates_without_copying_code(
    tmp_path: Path,
) -> None:
    workspace = team(tmp_path / "platform")
    backend = workspace.project_registry().create(name="Backend")
    frontend = workspace.project_registry().create(name="Frontend")
    assert workspace.root == tmp_path / "platform" / "team"
    assert backend.root.parent == tmp_path / "platform" / "projects"
    assert frontend.root.parent == backend.root.parent
    assert backend.root != frontend.root

    repository_root = tmp_path / "backend-code"
    repository_root.mkdir()
    (repository_root / "source.txt").write_text("code", encoding="utf-8")
    repository = backend.repository_registry().register(repository_root)
    assert repository.root.parent == backend.root / "repositories"
    assert list(repository_root.iterdir()) == [repository_root / "source.txt"]
    assert not (repository.root / "source.txt").exists()


def test_project_namespace_isolates_same_repository(tmp_path: Path) -> None:
    workspace = team(tmp_path / "platform")
    first_project = workspace.project_registry().create(name="First")
    second_project = workspace.project_registry().create(name="Second")
    repository_root = tmp_path / "repo"
    repository_root.mkdir()

    first = first_project.repository_registry().register(repository_root)
    second = second_project.repository_registry().register(repository_root)

    assert first.repository_id != second.repository_id
    assert first.root != second.root


def test_manifest_changes_and_symlinks_are_rejected(tmp_path: Path) -> None:
    workspace = team(tmp_path / "platform")
    manifest = workspace.root / "team.json"
    data = json.loads(manifest.read_text())
    data["name"] = "tampered"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="digest"):
        team(tmp_path / "platform")

    other = team(tmp_path / "other")
    (other.root / "knowledge").rmdir()
    (other.root / "knowledge").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        team(tmp_path / "other")


def test_selected_knowledge_is_separate_at_team_and_project_levels(tmp_path: Path) -> None:
    workspace = team(tmp_path / "platform")
    project = workspace.project_registry().create(name="Platform")
    (workspace.root / "knowledge" / "rules.md").write_text(
        "Team review required. password=private-value"
    )
    (project.root / "knowledge" / "rules.md").write_text("Project uses Python.")

    team_sources = workspace.knowledge_sources(("rules.md",))
    project_sources = project.knowledge_sources(("rules.md",))

    assert "private-value" not in str(team_sources)
    assert "REDACTED" in str(team_sources)
    assert team_sources[0].uri.startswith("team://team_ai/")
    assert project_sources[0].uri.startswith(f"project://{project.manifest.project_id}/")
    assert "Project uses Python" in project_sources[0].content


@pytest.mark.parametrize(
    "path", ["../team.json", "/etc/passwd", ".env", "a//b", "./rules.md", "secret.pem"]
)
def test_knowledge_escape_and_secret_files_rejected(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        team(tmp_path / "platform").knowledge_sources((path,))


def test_team_storage_cannot_overlap_registered_code(tmp_path: Path) -> None:
    workspace = team(tmp_path / "platform")
    project = workspace.project_registry().create(name="Platform")
    with pytest.raises(ValueError, match="overlap"):
        project.repository_registry().register(tmp_path)
    with pytest.raises(ValueError, match="overlap"):
        project.repository_registry().register(workspace.root / "knowledge")


def test_requirement_journal_is_project_scoped(tmp_path: Path) -> None:
    workspace = team(tmp_path / "platform")
    first_project = workspace.project_registry().create(name="First")
    second_project = workspace.project_registry().create(name="Second")
    backend = Mock(spec=JointBackend)
    first = JointDeliveryService(backend=backend, team=workspace, project=first_project)
    second = JointDeliveryService(backend=backend, team=workspace, project=second_project)
    scope = DirectoryScope(
        units=(
            DirectoryUnit(
                id="unit_" + "a" * 16,
                root=str(tmp_path / "code"),
                selected_paths=(".",),
                base_revision=None,
            ),
        )
    )
    checkpoint = JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_example",
            "team_id": workspace.manifest.team_id,
            "team_manifest_sha256": workspace.manifest.manifest_sha256,
            "project_id": first_project.manifest.project_id,
            "project_manifest_sha256": first_project.manifest.manifest_sha256,
            "sequence": 1,
            "stage": JointStage.PREPARING,
            "scope": scope,
            "title": "Joint change",
            "submitted_at": datetime.now(UTC),
            "next_action": "Prepare code scope",
        }
    )
    first.journal.append(checkpoint, expected=None)
    assert first.journal.root == first_project.requirements_root
    assert first.status(checkpoint.delivery_id).checkpoint == checkpoint
    with pytest.raises(ValueError, match="not found"):
        second.status(checkpoint.delivery_id)


def test_team_has_all_long_lived_workforce_directories(tmp_path: Path) -> None:
    workspace = team(tmp_path / "platform")
    assert {
        "agents",
        "knowledge",
        "leases",
        "metrics",
        "model-policies",
        "skills",
        "specs",
        "work-items",
    } <= {path.name for path in workspace.root.iterdir() if path.is_dir()}
