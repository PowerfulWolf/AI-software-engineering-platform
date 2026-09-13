"""Local administration keeps Team, document and config facts explicit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_software_engineer.config import LocalRuntimeEnvironmentStore, ProductionConfig
from ai_software_engineer.team_workspace import TeamWorkspace, discover_team_workspaces
from ai_software_engineer.web_console import (
    AdministrationError,
    CreateProjectRequest,
    LocalConsoleAdministration,
    MySqlConnectionRequest,
    UpdateKnowledgeSelectionRequest,
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


def test_team_and_project_document_selections_are_live_and_independent(
    tmp_path: Path,
) -> None:
    administration = _administration(tmp_path)
    created = administration.create_project(
        CreateProjectRequest(project_id="project_web", name="Web Project")
    )
    team_document = administration.import_document(filename="team-guide.md", content=b"# Team\n")
    project_document = administration.import_project_document(
        "project_web", filename="project-guide.md", content=b"# Project\n"
    )

    team_values = administration.update_team_knowledge_selection(
        UpdateKnowledgeSelectionRequest(document_ids=(team_document.manifest.document_id,))
    )
    project_values = administration.update_project_knowledge_selection(
        "project_web",
        UpdateKnowledgeSelectionRequest(document_ids=(project_document.manifest.document_id,)),
    )

    assert created.project_id == "project_web"
    assert [project.project_id for project in administration.projects()] == ["project_web"]
    assert team_values[0].scope == "team"
    assert team_values[0].selected is True
    assert team_values[0].project_id is None
    assert project_values[0].scope == "project"
    assert project_values[0].project_id == "project_web"
    assert project_values[0].selected is True
    assert administration.settings().restart_required is False
    statuses = {
        item.environment_name: item.configured for item in administration.settings().secret_status
    }
    assert statuses == {"DEEPSEEK_API_KEY": False, "TEST_MYSQL_DSN": True}
    persisted = json.loads(administration.config_path.read_text())
    assert persisted["team_knowledge_paths"] == []
    assert "secret@example" not in administration.config_path.read_text()


def test_runtime_configuration_change_requires_restart(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    changed = administration.runtime_config.model_copy(update={"console_port": 8877})

    snapshot = administration.update_settings(UpdateSettingsRequest(config=changed))

    assert snapshot.restart_required is True
    assert snapshot.config.console_port == 8877


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


def test_runtime_values_are_write_only_and_feed_status(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    probed: list[str] = []
    administration.mysql_probe = probed.append
    dsn = "mysql+pymysql://user:changed@127.0.0.1:3307/database"

    snapshot = administration.update_settings(
        UpdateSettingsRequest.model_validate(
            {
                "config": administration.runtime_config.to_wire(),
                "runtime_variables": [{"environment_name": "TEST_MYSQL_DSN", "value": dsn}],
            }
        )
    )
    connection = administration.test_mysql_connection(MySqlConnectionRequest())
    status = administration.status()

    assert snapshot.restart_required is True
    assert snapshot.secret_status[1].environment_name == "TEST_MYSQL_DSN"
    assert connection.connected is True
    assert probed == [dsn, dsn]
    assert status.database.connection == "CONNECTED"
    assert status.database.source == "runtime.env"
    assert status.live_model_execution is False
    assert status.team_knowledge_imported == 0
    assert status.team_knowledge_selected == 0
    assert dsn not in snapshot.model_dump_json()
    assert dsn not in status.model_dump_json()
    assert dsn in (tmp_path / "runtime.env").read_text(encoding="utf-8")


def test_runtime_update_rejects_unknown_variable_and_invalid_dsn(tmp_path: Path) -> None:
    administration = _administration(tmp_path)

    with pytest.raises(AdministrationError, match="not referenced"):
        administration.update_settings(
            UpdateSettingsRequest.model_validate(
                {
                    "config": administration.runtime_config.to_wire(),
                    "runtime_variables": [
                        {"environment_name": "UNRELATED_VALUE", "value": "unsafe"}
                    ],
                }
            )
        )
    with pytest.raises(AdministrationError, match="DSN is invalid"):
        administration.update_settings(
            UpdateSettingsRequest.model_validate(
                {
                    "config": administration.runtime_config.to_wire(),
                    "runtime_variables": [
                        {"environment_name": "TEST_MYSQL_DSN", "value": "not-a-dsn"}
                    ],
                }
            )
        )

    assert not (tmp_path / "runtime.env").exists()


def test_mysql_connection_returns_safe_failure(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    administration.mysql_probe = lambda _: (_ for _ in ()).throw(OSError("secret"))

    result = administration.test_mysql_connection(
        MySqlConnectionRequest(dsn="mysql+pymysql://user:password@127.0.0.1:3307/database")
    )

    assert result.connected is False
    assert "secret" not in result.message


def test_preexisting_runtime_file_not_loaded_by_process_requires_restart(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    LocalRuntimeEnvironmentStore(tmp_path / "runtime.env").save(
        {"TEST_MYSQL_DSN": "mysql+pymysql://user:password@127.0.0.1:3307/database"}
    )

    snapshot = administration.settings()

    assert snapshot.restart_required is True
