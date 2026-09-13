from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_software_engineer.config import ProductionConfig, ProductionConfigError
from ai_software_engineer.team_view.models import TeamSnapshot
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import (
    ConsoleIntent,
    ConsoleOperation,
    InMemoryConsoleOperationStore,
    LocalConsoleAdministration,
    create_console_app,
)
from ai_software_engineer.web_console.host import production_console_app


class _Console:
    def __init__(self) -> None:
        self.store = InMemoryConsoleOperationStore("team_test")
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def close(self, *, timeout: float = 5.0) -> None:
        assert timeout == 5.0
        self.closed = True

    def submit(self, intent: ConsoleIntent, *, idempotency_key: str) -> ConsoleOperation:
        return self.store.submit(
            intent=intent,
            idempotency_key=idempotency_key,
            requested_at=datetime(2026, 9, 12, tzinfo=UTC),
        )

    def get(self, operation_id: str) -> ConsoleOperation:
        return self.store.get(operation_id)

    def list_operations(self) -> tuple[ConsoleOperation, ...]:
        return self.store.list_current()


class _Reader:
    def __init__(self) -> None:
        self.project_ids: list[str | None] = []

    def snapshot(self, project_id: str | None = None) -> TeamSnapshot:
        self.project_ids.append(project_id)
        return TeamSnapshot(
            as_of=datetime(2026, 9, 12, tzinfo=UTC),
            team_id="team_test",
            team_name="Test team",
            selected_project_id=project_id,
        )


def _payload(tmp_path: Path, *, name: str = "Frontend delivery") -> dict[str, object]:
    return {
        "idempotency_key": "browser-action-0001",
        "intent": {
            "action": "CREATE_REQUIREMENT",
            "project_id": "project_web",
            "name": name,
            "repository_roots": [str(tmp_path)],
        },
    }


def test_web_transport_composes_assets_snapshot_and_durable_submission(tmp_path: Path) -> None:
    console = _Console()
    reader = _Reader()
    app = create_console_app(console, reader, team_id="team_test", port=8765)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/").status_code == 200
        console_info = client.get("/api/v1/console").json()
        assert console_info["team_id"] == "team_test"
        assert console_info["delivery_ready"] is True
        snapshot = client.get("/api/v1/team")
        submitted = client.post(
            "/api/v1/operations",
            json=_payload(tmp_path),
            headers={"Origin": "http://127.0.0.1:8765"},
        )
        operation_id = submitted.json()["operation_id"]
        fetched = client.get(f"/api/v1/operations/{operation_id}")

        assert snapshot.status_code == 200
        assert snapshot.json()["team_id"] == "team_test"
        assert submitted.status_code == 202
        assert submitted.json()["status"] == "QUEUED"
        assert fetched.json() == submitted.json()
        assert client.get("/api/v1/operations").json() == [submitted.json()]
        assert submitted.headers["cache-control"] == "no-store"
        assert "form-action 'none'" in submitted.headers["content-security-policy"]

    assert console.started and console.closed


def test_web_transport_rejects_cross_origin_non_json_and_invalid_payload(tmp_path: Path) -> None:
    app = create_console_app(_Console(), _Reader(), team_id="team_test", port=8765)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        cross_origin = client.post(
            "/api/v1/operations",
            json=_payload(tmp_path),
            headers={"Origin": "https://malicious.example"},
        )
        form = client.post(
            "/api/v1/operations",
            content="action=create",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        invalid = client.post(
            "/api/v1/operations",
            json={
                **_payload(tmp_path),
                "intent": {
                    "action": "CREATE_REQUIREMENT",
                    "project_id": "project_web",
                    "name": "Invalid relative directory",
                    "repository_roots": ["relative/project"],
                },
            },
        )
        oversized = client.post(
            "/api/v1/operations",
            content=b"x" * 64_001,
            headers={"Content-Type": "application/json"},
        )

    assert cross_origin.status_code == 403
    assert form.status_code == 415
    assert invalid.status_code == 422
    assert oversized.status_code == 413
    assert "relative/project" not in invalid.text


def test_web_transport_rejects_changed_idempotency_key_and_unknown_operation(
    tmp_path: Path,
) -> None:
    app = create_console_app(_Console(), _Reader(), team_id="team_test", port=8765)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        first = client.post("/api/v1/operations", json=_payload(tmp_path))
        changed = client.post("/api/v1/operations", json=_payload(tmp_path, name="Changed intent"))
        missing = client.get("/api/v1/operations/operation_" + "f" * 32)

    assert first.status_code == 202
    assert changed.status_code == 409
    assert missing.status_code == 404


def test_console_host_missing_config_starts_with_visible_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    config_path = tmp_path / "config" / "missing.json"
    monkeypatch.setattr("ai_software_engineer.config.production.Path.home", lambda: home)
    app = production_console_app({"ASE_CONFIG": str(config_path), "PATH": "/missing"}, port=8765)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        settings = client.get("/api/v1/admin/settings")
        status = client.get("/api/v1/admin/status")
        team = client.get("/api/v1/team")
        delivery = client.post("/api/v1/operations", json=_payload(tmp_path))
        assert not config_path.exists()
        assert not home.exists()
        saved = client.put(
            "/api/v1/admin/settings",
            json={
                "config": settings.json()["config"],
                "runtime_variables": [
                    {
                        "environment_name": "ASE_MYSQL_DSN",
                        "value": ("mysql+pymysql://user:password@127.0.0.1:3307/database"),
                    }
                ],
            },
        )
        prepared_team = client.get("/api/v1/admin/team")

    assert settings.status_code == 200
    assert settings.json()["config_source"] == "default"
    assert settings.json()["config"]["console_port"] == 8765
    assert status.json()["delivery_runtime"] == "SETUP_REQUIRED"
    assert status.json()["live_model_execution"] is False
    assert status.json()["database"]["connection"] == "NOT_CONFIGURED"
    assert status.json()["team_prepared"] is False
    assert team.status_code == 200
    assert team.json()["team_id"] == "team_ai"
    assert delivery.status_code == 503
    assert delivery.json()["error"]["code"] == "SETUP_REQUIRED"
    assert saved.status_code == 200
    assert saved.json()["config_source"] == "saved"
    assert saved.json()["restart_required"] is True
    assert prepared_team.status_code == 200
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/v1/console").json()["delivery_ready"] is False
    assert config_path.is_file()
    assert (home / ".ase" / "team" / "team.json").is_file()


def test_console_host_rejects_existing_invalid_config(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.json"
    config_path.write_text("{", encoding="utf-8")

    with pytest.raises(ProductionConfigError, match="cannot load production configuration"):
        production_console_app({"ASE_CONFIG": str(config_path)}, port=8765)


def test_administration_endpoints_create_project_import_document_and_save_settings(
    tmp_path: Path,
) -> None:
    config = ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "team_id": "team_test",
            "team_name": "Test team",
            "model_routes": [{"provider": "codex", "model": "gpt-5.6-terra", "kind": "codex_cli"}],
        }
    )
    TeamWorkspace.initialize(config.platform_root, team_id=config.team_id, name=config.team_name)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    administration = LocalConsoleAdministration(
        runtime_config=config,
        config_path=config_path,
        environment={"ASE_MYSQL_DSN": "mysql://user:secret@example.invalid/db"},
        mysql_probe=lambda _: None,
    )
    app = create_console_app(
        _Console(),
        _Reader(),
        team_id="team_test",
        port=8765,
        administration=administration,
    )

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        created = client.post(
            "/api/v1/admin/projects",
            json={"project_id": "project_web", "name": "Web Project"},
        )
        imported = client.post(
            "/api/v1/admin/team/knowledge?filename=team-guide.md",
            content=b"# Team guide\n",
            headers={"Content-Type": "application/octet-stream"},
        )
        project_imported = client.post(
            "/api/v1/admin/projects/project_web/knowledge?filename=project-guide.md",
            content=b"# Project guide\n",
            headers={"Content-Type": "application/octet-stream"},
        )
        team_selection = client.put(
            "/api/v1/admin/team/knowledge/selection",
            json={"document_ids": [imported.json()["manifest"]["document_id"]]},
        )
        project_selection = client.put(
            "/api/v1/admin/projects/project_web/knowledge/selection",
            json={"document_ids": [project_imported.json()["manifest"]["document_id"]]},
        )
        team = client.get("/api/v1/admin/team")
        projects = client.get("/api/v1/admin/projects")
        knowledge = client.get("/api/v1/admin/team/knowledge")
        settings = client.get("/api/v1/admin/settings")
        status = client.get("/api/v1/admin/status")
        mysql = client.post(
            "/api/v1/admin/settings/test-mysql",
            json={"dsn": "mysql+pymysql://user:password@127.0.0.1:3307/database"},
        )
        updated_config = settings.json()["config"]
        updated = client.put("/api/v1/admin/settings", json={"config": updated_config})
        rejected = client.post(
            "/api/v1/admin/team/knowledge?filename=unsafe.exe",
            content=b"binary",
            headers={"Content-Type": "application/octet-stream"},
        )

    assert created.status_code == 201
    assert created.json()["project_id"] == "project_web"
    assert imported.status_code == 201
    assert project_imported.status_code == 201
    assert project_imported.json()["project_id"] == "project_web"
    assert team_selection.status_code == 200
    assert team_selection.json()[0]["selected"] is True
    assert project_selection.status_code == 200
    assert project_selection.json()[0]["selected"] is True
    assert project_selection.json()[0]["scope"] == "project"
    assert team.status_code == 200
    assert team.json()["team_id"] == "team_test"
    assert projects.status_code == 200
    assert [item["project_id"] for item in projects.json()] == ["project_web"]
    assert knowledge.json()[0]["manifest"]["source_name"] == "team-guide.md"
    assert settings.json()["secret_status"] == [
        {"environment_name": "ASE_MYSQL_DSN", "configured": True}
    ]
    assert status.status_code == 200
    assert status.json()["database"]["connection"] == "CONNECTED"
    assert status.json()["runtime_environment_path"].endswith("/runtime.env")
    assert mysql.json() == {"connected": True, "message": "MySQL 连接成功。"}
    assert "password" not in status.text
    assert "password" not in mysql.text
    assert updated.status_code == 200
    assert updated.json()["restart_required"] is False
    assert rejected.status_code == 422
    assert "Team guide" not in imported.text
