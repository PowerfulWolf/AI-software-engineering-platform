"""Local administration keeps Team, document and config facts explicit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.team_workspace import TeamWorkspace, discover_team_workspaces
from ai_software_engineer.web_console import (
    AdministrationError,
    CreateProjectRequest,
    LocalConsoleAdministration,
    UpdateSettingsRequest,
)


def _config(tmp_path: Path) -> ProductionConfig:
    return ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "team_id": "team_test",
            "team_name": "Test team",
            "database": {"dsn_env": "TEST_MYSQL_DSN"},
            "model_routes": [
                {"provider": "codex", "model": "gpt-5.6-terra", "kind": "codex_cli"},
                {
                    "provider": "deepseek",
                    "model": "deepseek-v4",
                    "kind": "responses",
                    "endpoint": "https://example.invalid/v1/responses",
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "enabled": False,
                },
            ],
        }
    )


def _administration(tmp_path: Path) -> LocalConsoleAdministration:
    config = _config(tmp_path)
    TeamWorkspace.initialize(config.platform_root, team_id=config.team_id, name=config.team_name)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json(indent=2))
    return LocalConsoleAdministration(
        runtime_config=config,
        config_path=config_path,
        environment={"TEST_MYSQL_DSN": "mysql://user:secret@example.invalid/db"},
    )


def test_project_creation_and_team_document_selection_round_trip(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    created = administration.create_project(
        CreateProjectRequest(project_id="project_web", name="Web Project")
    )
    imported = administration.import_document(filename="guide.md", content=b"# Guide\n")
    changed = administration.runtime_config.model_copy(
        update={
            "team_knowledge_paths": (imported.manifest.normalized_relative_path,),
            "console_port": 8877,
        }
    )

    snapshot = administration.update_settings(UpdateSettingsRequest(config=changed))

    assert created.project_id == "project_web"
    assert [project.project_id for project in administration.projects()] == ["project_web"]
    assert administration.knowledge()[0].selected is True
    assert snapshot.restart_required is True
    assert snapshot.config.console_port == 8877
    statuses = {item.environment_name: item.configured for item in snapshot.secret_status}
    assert statuses == {"DEEPSEEK_API_KEY": False, "TEST_MYSQL_DSN": True}
    persisted = json.loads(administration.config_path.read_text())
    assert persisted["team_knowledge_paths"] == [imported.manifest.normalized_relative_path]
    assert "secret@example" not in administration.config_path.read_text()


def test_settings_reject_team_identity_and_name_drift(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    unknown = administration.runtime_config.model_copy(
        update={"team_id": "team_missing", "team_name": "Missing"}
    )
    renamed = administration.runtime_config.model_copy(update={"team_name": "Renamed"})

    with pytest.raises(AdministrationError, match="not prepared"):
        administration.update_settings(UpdateSettingsRequest(config=unknown))
    with pytest.raises(AdministrationError, match="immutable"):
        administration.update_settings(UpdateSettingsRequest(config=renamed))

    assert administration.settings().restart_required is False


def test_settings_prepare_selected_team_in_a_new_platform_root(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    new_root = tmp_path / "new-platform"
    moved = administration.runtime_config.model_copy(update={"platform_root": str(new_root)})

    snapshot = administration.update_settings(UpdateSettingsRequest(config=moved))

    assert snapshot.restart_required is True
    teams = discover_team_workspaces(new_root)
    assert [(item.manifest.team_id, item.manifest.name) for item in teams] == [
        ("team_test", "Test team")
    ]


def test_team_catalog_uses_the_single_canonical_team_directory(tmp_path: Path) -> None:
    config = _config(tmp_path)
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    displaced = team.root.parent / "unrelated"
    displaced.mkdir()
    (displaced / "team.json").write_bytes((team.root / "team.json").read_bytes())

    assert discover_team_workspaces(config.platform_root) == (team,)
