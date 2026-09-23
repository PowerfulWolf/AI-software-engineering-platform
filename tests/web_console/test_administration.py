"""Local administration keeps Team, document and config facts explicit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_software_engineer.config import LocalRuntimeEnvironmentStore, ProductionConfig
from ai_software_engineer.spec_documents import CreateSpecDocument
from ai_software_engineer.team_workspace import TeamWorkspace, discover_team_workspaces
from ai_software_engineer.web_console import (
    AdministrationError,
    CreateProjectRequest,
    LocalConsoleAdministration,
    MySqlConnectionRequest,
    UpdateKnowledgeSelectionRequest,
    UpdateSettingsRequest,
    UpdateSpecActivationRequest,
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

    assert administration.document_content(team_document.manifest.document_id).to_wire() == {
        "scope": "team",
        "document_id": team_document.manifest.document_id,
        "source_name": "team-guide.md",
        "content_markdown": "# Team\n",
    }
    assert (
        administration.project_document_content(
            "project_web", project_document.manifest.document_id
        ).content_markdown
        == "# Project\n"
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


def test_team_and_project_specs_are_versioned_and_activated_independently(
    tmp_path: Path,
) -> None:
    administration = _administration(tmp_path)
    administration.create_project(
        CreateProjectRequest(project_id="project_web", name="Web Project")
    )
    command = CreateSpecDocument(
        spec_key="python.testing",
        title="Python testing",
        body_markdown="# Testing\n\nRun focused tests.",
        verification="Record the pytest command and passing evidence.",
    )

    team = administration.create_team_spec(command)
    project = administration.create_project_spec(
        "project_web",
        command.model_copy(update={"body_markdown": "# Testing\n\nRun Project tests."}),
    )
    team_values = administration.update_team_spec_activation(
        UpdateSpecActivationRequest(spec_ids=(team.document.spec_id,))
    )
    project_values = administration.update_project_spec_activation(
        "project_web",
        UpdateSpecActivationRequest(spec_ids=(project.document.spec_id,)),
    )

    assert team_values[0].active is True
    assert team_values[0].project_id is None
    assert project_values[0].active is True
    assert project_values[0].project_id == "project_web"
    assert administration.settings().restart_required is False


def test_background_knowledge_can_be_replaced_and_retired_without_losing_history(
    tmp_path: Path,
) -> None:
    administration = _administration(tmp_path)
    administration.create_project(
        CreateProjectRequest(project_id="project_web", name="Web Project")
    )
    original = administration.import_project_document(
        "project_web", filename="architecture.md", content=b"# Architecture v1\n"
    )
    administration.update_project_knowledge_selection(
        "project_web",
        UpdateKnowledgeSelectionRequest(document_ids=(original.manifest.document_id,)),
    )

    replacement = administration.replace_project_document(
        "project_web",
        original.manifest.document_id,
        filename="architecture.md",
        content=b"# Architecture v2\n",
    )

    assert replacement.selected is True
    assert replacement.manifest.document_id != original.manifest.document_id
    assert [
        item.manifest.document_id for item in administration.project_knowledge("project_web")
    ] == [replacement.manifest.document_id]
    original_path = (
        Path(administration.runtime_config.platform_root)
        / "projects"
        / "project_web"
        / "knowledge"
        / original.manifest.normalized_relative_path
    )
    assert original_path.is_file()

    assert (
        administration.delete_project_document("project_web", replacement.manifest.document_id)
        == ()
    )
    assert original_path.is_file()


def test_spec_delete_retires_all_versions_and_deactivates_current_version(
    tmp_path: Path,
) -> None:
    administration = _administration(tmp_path)
    first = administration.create_team_spec(
        CreateSpecDocument(
            spec_key="python.testing",
            title="Python testing",
            body_markdown="# Testing v1\n",
            verification="",
        )
    )
    second = administration.create_team_spec(
        CreateSpecDocument.model_validate(
            first.document.model_copy(update={"body_markdown": "# Testing v2\n"}).model_dump(
                include={
                    "spec_key",
                    "title",
                    "body_markdown",
                    "roles",
                    "stages",
                    "repository_ids",
                    "path_globs",
                    "verification",
                }
            )
        )
    )
    administration.update_team_spec_activation(
        UpdateSpecActivationRequest(spec_ids=(second.document.spec_id,))
    )

    assert administration.delete_team_spec("python.testing") == ()

    spec_root = Path(administration.runtime_config.platform_root) / "team" / "specs"
    assert (spec_root / "documents" / first.document.spec_id / "spec.json").is_file()
    assert (spec_root / "documents" / second.document.spec_id / "spec.json").is_file()


def test_runtime_configuration_change_requires_restart(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    changed = administration.runtime_config.model_copy(update={"console_port": 8877})

    snapshot = administration.update_settings(UpdateSettingsRequest(config=changed))

    assert snapshot.restart_required is True
    assert snapshot.config.console_port == 8877


def test_local_codex_proxy_setting_is_saved_and_requires_restart(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    changed = ProductionConfig.model_validate(
        {
            **administration.runtime_config.to_wire(),
            "codex_cli_proxy_base_url": "http://127.0.0.1:8317/v1",
        }
    )

    saved = administration.update_settings(UpdateSettingsRequest(config=changed))

    assert saved.config.codex_cli_proxy_base_url == "http://127.0.0.1:8317/v1"
    assert saved.restart_required is True
    assert ProductionConfig.from_file(tmp_path / "config.json").codex_cli_proxy_base_url == (
        "http://127.0.0.1:8317/v1"
    )
    assert not (tmp_path / "runtime.env").exists()


def test_design_retry_settings_roundtrip_requires_restart(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    changed = ProductionConfig.model_validate(
        {
            **administration.runtime_config.to_wire(),
            "execution_retry_policy": {
                "designer": {"max_attempts": 8, "max_transient_failures": 20},
                "product": {"max_attempts": 30, "max_transient_failures": 10},
                "planner": {"max_attempts": 7},
                "coder": {"max_attempts": 9},
                "qa": {"max_transient_failures": 12},
                "reviewer": {"max_transient_failures": 13},
            },
        }
    )
    saved = administration.update_settings(UpdateSettingsRequest(config=changed))
    assert saved.restart_required
    assert saved.config.design_retry_policy == changed.design_retry_policy
    assert saved.config.execution_retry_policy == changed.execution_retry_policy
    assert administration.runtime_config.design_retry_policy.max_design_attempts == 3
    reopened = LocalConsoleAdministration(
        runtime_config=ProductionConfig.from_file(tmp_path / "config.json"),
        config_path=tmp_path / "config.json",
        environment=administration.environment,
    )
    assert reopened.settings().config.design_retry_policy == changed.design_retry_policy
    assert reopened.settings().config.execution_retry_policy == changed.execution_retry_policy
    assert not reopened.settings().restart_required


def test_configuration_apply_token_changes_without_exposing_runtime_secret(
    tmp_path: Path,
) -> None:
    administration = _administration(tmp_path)
    before = administration.configuration_apply_token()
    synthetic_dsn = "mysql+pymysql://user:changed@127.0.0.1:3307/database"

    administration.update_settings(
        UpdateSettingsRequest.model_validate(
            {
                "config": administration.runtime_config.to_wire(),
                "runtime_variables": [
                    {"environment_name": "TEST_MYSQL_DSN", "value": synthetic_dsn}
                ],
            }
        )
    )
    after = administration.configuration_apply_token()

    assert before != after
    assert len(after) == 64
    assert synthetic_dsn not in after


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
    assert status.model_routes[0].reasoning_effort == "medium"
    assert [item.role.value for item in status.agent_model_routes] == [
        "manager",
        "product",
        "designer",
        "planner",
        "coder",
        "qa",
        "reviewer",
    ]
    assert all(item.policy_source == "global_default" for item in status.agent_model_routes)
    assert dsn not in snapshot.model_dump_json()
    assert dsn not in status.model_dump_json()
    assert dsn in (tmp_path / "runtime.env").read_text(encoding="utf-8")


def test_status_reports_each_agent_exact_model_route_and_readiness(tmp_path: Path) -> None:
    roles = ("manager", "product", "designer", "planner", "coder", "qa", "reviewer")
    medium = {
        "provider": "codex",
        "model": "gpt-5.6-terra",
        "reasoning_effort": "medium",
    }
    high = {**medium, "reasoning_effort": "high"}
    deepseek = {
        "provider": "deepseek",
        "model": "deepseek-v4",
        "reasoning_effort": "high",
    }
    config = ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "team_id": "team_test",
            "team_name": "Test team",
            "database": {"dsn_env": "TEST_MYSQL_DSN"},
            "codex_executable": "/bin/sh",
            "model_routes": [
                {**medium, "kind": "codex_cli"},
                {**high, "kind": "codex_cli"},
                {
                    **deepseek,
                    "kind": "responses",
                    "endpoint": "https://example.invalid/v1/responses",
                    "api_key_env": "DEEPSEEK_API_KEY",
                },
            ],
            "agent_model_routes": [
                {
                    "role": role,
                    "routes": (
                        [deepseek, medium, high]
                        if role == "product"
                        else [high, medium, deepseek]
                        if role == "coder"
                        else [medium, high, deepseek]
                    ),
                }
                for role in roles
            ],
        }
    )
    TeamWorkspace.initialize(
        config.platform_root,
        team_id=config.team_id,
        name=config.team_name,
    )
    administration = LocalConsoleAdministration(
        runtime_config=config,
        config_path=tmp_path / "config.json",
        environment={
            "TEST_MYSQL_DSN": "mysql+pymysql://user:secret@example.invalid/database",
        },
        mysql_probe=lambda _: None,
    )

    status = administration.status()
    by_role = {item.role.value: item for item in status.agent_model_routes}

    assert all(item.policy_source == "agent_policy" for item in by_role.values())
    assert [route.reasoning_effort for route in by_role["coder"].routes[:2]] == [
        "high",
        "medium",
    ]
    assert by_role["coder"].routes[0].ready is True
    assert by_role["product"].routes[0].provider == "deepseek"
    assert by_role["product"].routes[0].ready is False
    assert by_role["product"].routes[0].credential_configured is False


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


def test_knowledge_tick_isolates_team_and_project_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.knowledge.index import KnowledgeIndexer
    from ai_software_engineer.knowledge.models import KnowledgeError

    administration = _administration(tmp_path)
    for project_id in ("project_broken", "project_healthy"):
        administration.create_project(CreateProjectRequest(project_id=project_id, name=project_id))
    healthy = administration.enqueue_document(
        project_id="project_healthy", filename="guide.md", content=b"# Healthy"
    )
    tick = KnowledgeIndexer.tick

    def isolated_tick(self: KnowledgeIndexer, *, limit: int = 4) -> tuple[object, ...]:
        if self.documents.project_id != "project_healthy":
            raise KnowledgeError("INDEX_CACHE_INTEGRITY")
        return tick(self, limit=limit)

    monkeypatch.setattr(KnowledgeIndexer, "tick", isolated_tick)
    administration.tick_knowledge_indexes()
    jobs = administration.knowledge_index("project_healthy").jobs
    assert next(job for job in jobs if job.job_id == healthy.job_id).status == "READY"
