"""Local administration keeps Company, document and config facts explicit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_software_engineer.company_workspace import CompanyWorkspace, discover_company_workspaces
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.web_console import (
    AdministrationError,
    CreateCompanyRequest,
    LocalConsoleAdministration,
    UpdateSettingsRequest,
)


def _config(tmp_path: Path) -> ProductionConfig:
    return ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "company_id": "company_test",
            "company_name": "Test company",
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
    CompanyWorkspace.initialize(
        config.platform_root, company_id=config.company_id, name=config.company_name
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json(indent=2))
    return LocalConsoleAdministration(
        runtime_config=config,
        config_path=config_path,
        environment={"TEST_MYSQL_DSN": "mysql://user:secret@example.invalid/db"},
    )


def test_company_creation_and_document_selection_round_trip(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    created = administration.create_company(
        CreateCompanyRequest(company_id="company_other", name="Other company")
    )
    imported = administration.import_document(
        company_id="company_test", filename="guide.md", content=b"# Guide\n"
    )
    changed = administration.runtime_config.model_copy(
        update={
            "company_knowledge_paths": (imported.manifest.normalized_relative_path,),
            "console_port": 8877,
        }
    )

    snapshot = administration.update_settings(UpdateSettingsRequest(config=changed))

    assert created.company_id == "company_other"
    assert [company.company_id for company in administration.companies()] == [
        "company_other",
        "company_test",
    ]
    assert administration.knowledge("company_test")[0].selected is True
    assert snapshot.restart_required is True
    assert snapshot.config.console_port == 8877
    statuses = {item.environment_name: item.configured for item in snapshot.secret_status}
    assert statuses == {"DEEPSEEK_API_KEY": False, "TEST_MYSQL_DSN": True}
    persisted = json.loads(administration.config_path.read_text())
    assert persisted["company_knowledge_paths"] == [imported.manifest.normalized_relative_path]
    assert "secret@example" not in administration.config_path.read_text()


def test_settings_reject_unknown_company_and_name_drift(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    unknown = administration.runtime_config.model_copy(
        update={"company_id": "company_missing", "company_name": "Missing"}
    )
    renamed = administration.runtime_config.model_copy(update={"company_name": "Renamed"})

    with pytest.raises(AdministrationError, match="not prepared"):
        administration.update_settings(UpdateSettingsRequest(config=unknown))
    with pytest.raises(AdministrationError, match="immutable"):
        administration.update_settings(UpdateSettingsRequest(config=renamed))

    assert administration.settings().restart_required is False


def test_settings_prepare_selected_company_in_a_new_platform_root(tmp_path: Path) -> None:
    administration = _administration(tmp_path)
    new_root = tmp_path / "new-platform"
    moved = administration.runtime_config.model_copy(update={"platform_root": str(new_root)})

    snapshot = administration.update_settings(UpdateSettingsRequest(config=moved))

    assert snapshot.restart_required is True
    companies = discover_company_workspaces(new_root)
    assert [(item.manifest.company_id, item.manifest.name) for item in companies] == [
        ("company_test", "Test company")
    ]


def test_company_catalog_rejects_directory_manifest_identity_drift(tmp_path: Path) -> None:
    config = _config(tmp_path)
    company = CompanyWorkspace.initialize(
        config.platform_root, company_id=config.company_id, name=config.company_name
    )
    displaced = company.root.parent / "company_displaced"
    displaced.mkdir()
    (displaced / "company.json").write_bytes((company.root / "company.json").read_bytes())

    with pytest.raises(ValueError, match="does not match"):
        discover_company_workspaces(config.platform_root)
