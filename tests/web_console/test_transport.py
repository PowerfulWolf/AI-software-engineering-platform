from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Message, Scope

from ai_software_engineer.agents.model_diagnostics import ModelCallDiagnostic
from ai_software_engineer.config import ProductionConfig, ProductionConfigError
from ai_software_engineer.multi_directory.attachments import RequirementScreenshot
from ai_software_engineer.team_view.models import TeamSnapshot
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import (
    ConfigurationApplyError,
    ConfigurationApplyState,
    ConfigurationApplyStatus,
    ConsoleIntent,
    ConsoleOperation,
    InMemoryConsoleOperationStore,
    LocalConsoleAdministration,
    create_console_app,
)
from ai_software_engineer.web_console.administration import SettingsSnapshot
from ai_software_engineer.web_console.host import production_console_app
from ai_software_engineer.web_console.transport import _screenshot_body


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

    def model_calls(self, operation_id: str) -> tuple[ModelCallDiagnostic, ...]:
        return self.store.model_calls(operation_id)


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


class _DirectoryChooser:
    def __init__(self, *values: Path) -> None:
        self.values = tuple(str(value) for value in values)

    def choose(self) -> tuple[str, ...]:
        return self.values


class _ScreenshotAdministration:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str, bytes]] = []

    def upload_requirement_screenshot(
        self,
        project_id: str,
        delivery_id: str,
        expected_checkpoint_sha256: str,
        *,
        filename: str,
        content: bytes,
    ) -> RequirementScreenshot:
        self.calls.append((project_id, delivery_id, expected_checkpoint_sha256, filename, content))
        provisional = RequirementScreenshot(
            id="requirement_attachment_" + "a" * 40,
            project_id=project_id,
            delivery_id=delivery_id,
            source_name=filename,
            media_type="image/png",
            source_bytes=len(content),
            source_sha256="b" * 64,
            source_relative_path="attachments/fixture/source.png",
            uploaded_at=datetime(2026, 9, 12, tzinfo=UTC),
            manifest_sha256="0" * 64,
        )
        return provisional.model_copy(update={"manifest_sha256": provisional.recompute_digest()})


class _ApplyAdministration:
    def __init__(self, *, restart_required: bool = True) -> None:
        self.restart_required = restart_required

    def settings(self) -> SettingsSnapshot:
        return SettingsSnapshot(
            config=ProductionConfig.default(),
            config_path="/safe/config.json",
            config_source="saved",
            restart_required=self.restart_required,
        )

    def configuration_apply_token(self) -> str:
        return "a" * 64


class _ConfigurationLifecycle:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.state: ConfigurationApplyState | None = None

    def request(self, token_sha256: str) -> ConfigurationApplyState:
        self.calls.append(token_sha256)
        if self.state is None:
            self.state = ConfigurationApplyState(
                request_id="configuration_apply_" + token_sha256[:32],
                status=ConfigurationApplyStatus.PENDING,
                safe_summary="Configuration apply is in progress.",
            )
        return self.state

    def current(self) -> ConfigurationApplyState | None:
        return self.state


class _FailingConfigurationLifecycle:
    def request(self, token_sha256: str) -> ConfigurationApplyState:
        raise ConfigurationApplyError("mysql+pymysql://user:secret@db/database")

    def current(self) -> ConfigurationApplyState | None:
        raise ConfigurationApplyError("mysql+pymysql://user:secret@db/database")


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
        assert "img-src 'self' blob: data:" in submitted.headers["content-security-policy"]

    assert console.started and console.closed


def test_directory_picker_and_requirement_screenshot_use_local_bounded_endpoints(
    tmp_path: Path,
) -> None:
    first = tmp_path / "backend"
    second = tmp_path / "frontend"
    first.mkdir()
    second.mkdir()
    administration = _ScreenshotAdministration()
    app = create_console_app(
        _Console(),
        _Reader(),
        team_id="team_test",
        port=8765,
        directory_chooser=_DirectoryChooser(first, second),
        administration=administration,  # type: ignore[arg-type]
    )
    screenshot = b"\x89PNG\r\n\x1a\nfixture"
    delivery_id = "delivery_multi_" + "a" * 40
    checkpoint = "c" * 64

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        selected = client.post("/api/v1/admin/directories/select")
        uploaded = client.post(
            "/api/v1/admin/projects/project_web/requirements/"
            + delivery_id
            + "/screenshots?filename=checkout.png&checkpoint="
            + checkpoint,
            content=screenshot,
            headers={"Content-Type": "application/octet-stream"},
        )

    assert selected.json() == {
        "directories": [str(first), str(second)],
        "cancelled": False,
    }
    assert uploaded.status_code == 201
    assert uploaded.json()["id"] == "requirement_attachment_" + "a" * 40
    assert administration.calls == [
        ("project_web", delivery_id, checkpoint, "checkout.png", screenshot)
    ]


def test_screenshot_stream_stops_at_limit_without_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_software_engineer.web_console.transport.MAX_REQUIREMENT_SCREENSHOT_BYTES", 4
    )
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/screenshots",
        "headers": [(b"content-type", b"application/octet-stream")],
        "query_string": b"",
        "scheme": "http",
        "server": ("127.0.0.1", 8765),
        "client": ("127.0.0.1", 1234),
        "http_version": "1.1",
    }
    events: list[Message] = [
        {"type": "http.request", "body": b"123", "more_body": True},
        {"type": "http.request", "body": b"45", "more_body": False},
    ]

    async def receive() -> Message:
        return events.pop(0)

    result = asyncio.run(_screenshot_body(Request(scope, receive)))

    assert isinstance(result, Response)
    assert result.status_code == 413


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


def test_configuration_apply_endpoint_is_empty_typed_and_idempotent() -> None:
    administration = _ApplyAdministration()
    lifecycle = _ConfigurationLifecycle()
    app = create_console_app(
        _Console(),
        _Reader(),
        team_id="team_test",
        port=8765,
        administration=administration,  # type: ignore[arg-type]
        configuration_lifecycle=lifecycle,
    )

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        first = client.post("/api/v1/admin/settings/apply", json={})
        replay = client.post("/api/v1/admin/settings/apply", json={})
        status = client.get("/api/v1/admin/settings/apply")
        rejected = client.post("/api/v1/admin/settings/apply", json={"command": "restart --force"})

    assert first.status_code == replay.status_code == 202
    assert status.json() == first.json() == replay.json()
    assert lifecycle.calls == ["a" * 64, "a" * 64]
    assert first.json()["effective_console_port"] == 8765
    assert rejected.status_code == 422
    assert "restart --force" not in rejected.text


def test_configuration_apply_uses_server_selected_override_port() -> None:
    app = create_console_app(
        _Console(),
        _Reader(),
        team_id="team_test",
        port=8765,
        administration=_ApplyAdministration(),  # type: ignore[arg-type]
        configuration_lifecycle=_ConfigurationLifecycle(),
        configuration_port_override=8877,
    )

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        submitted = client.post("/api/v1/admin/settings/apply", json={})
        status = client.get("/api/v1/admin/settings/apply")

    assert submitted.json()["effective_console_port"] == 8877
    assert status.json()["effective_console_port"] == 8877


def test_configuration_apply_requires_server_side_restart_eligibility() -> None:
    lifecycle = _ConfigurationLifecycle()
    app = create_console_app(
        _Console(),
        _Reader(),
        team_id="team_test",
        port=8765,
        administration=_ApplyAdministration(restart_required=False),  # type: ignore[arg-type]
        configuration_lifecycle=lifecycle,
    )

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.post("/api/v1/admin/settings/apply", json={})

    assert response.status_code == 409
    assert lifecycle.calls == []


def test_configuration_apply_failure_returns_only_fixed_safe_summaries() -> None:
    app = create_console_app(
        _Console(),
        _Reader(),
        team_id="team_test",
        port=8765,
        administration=_ApplyAdministration(),  # type: ignore[arg-type]
        configuration_lifecycle=_FailingConfigurationLifecycle(),
    )

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        submitted = client.post("/api/v1/admin/settings/apply", json={})
        status = client.get("/api/v1/admin/settings/apply")

    assert submitted.status_code == status.status_code == 503
    assert "secret" not in submitted.text
    assert "secret" not in status.text
    assert submitted.json()["error"]["code"] == "APPLY_UNAVAILABLE"


def test_console_host_missing_config_starts_with_visible_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    config_path = tmp_path / "config" / "missing.json"
    monkeypatch.setattr("ai_software_engineer.config.production.Path.home", lambda: home)
    app = production_console_app({"ASE_CONFIG": str(config_path), "PATH": "/missing"}, port=8765)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        settings = client.get("/api/v1/admin/settings")
        assert settings.json()["settings_contract_version"] == 1
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_software_engineer.knowledge.index.KnowledgeIndexWorker.start", lambda _: None
    )
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
        assert imported.json()["status"] == "QUEUED"
        administration.tick_knowledge_indexes()
        team_content = client.get(
            "/api/v1/admin/team/knowledge/" + imported.json()["document_id"] + "/content"
        )
        project_content = client.get(
            "/api/v1/admin/projects/project_web/knowledge/"
            + project_imported.json()["document_id"]
            + "/content"
        )
        team_selection = client.put(
            "/api/v1/admin/team/knowledge/selection",
            json={"document_ids": [imported.json()["document_id"]]},
        )
        project_selection = client.put(
            "/api/v1/admin/projects/project_web/knowledge/selection",
            json={"document_ids": [project_imported.json()["document_id"]]},
        )
        spec_payload = {
            "spec_key": "python.testing",
            "title": "Python testing",
            "body_markdown": "# Testing\n\nRun focused tests.",
            "roles": ["coder", "qa", "reviewer"],
            "stages": ["implementing", "qa", "review"],
            "repository_ids": [],
            "path_globs": ["*"],
            "verification": "Record passing pytest evidence.",
        }
        team_spec = client.post("/api/v1/admin/team/specs", json=spec_payload)
        project_spec = client.post("/api/v1/admin/projects/project_web/specs", json=spec_payload)
        team_spec_activation = client.put(
            "/api/v1/admin/team/specs/activation",
            json={"spec_ids": [team_spec.json()["document"]["spec_id"]]},
        )
        project_spec_activation = client.put(
            "/api/v1/admin/projects/project_web/specs/activation",
            json={"spec_ids": [project_spec.json()["document"]["spec_id"]]},
        )
        learning = client.get("/api/v1/admin/projects/project_web/learnings")
        collected = client.post("/api/v1/admin/projects/project_web/learnings/collect")
        team = client.get("/api/v1/admin/team")
        projects = client.get("/api/v1/admin/projects")
        knowledge = client.get("/api/v1/admin/team/knowledge")
        team_replaced = client.put(
            "/api/v1/admin/team/knowledge/"
            + imported.json()["document_id"]
            + "?filename=team-guide.md",
            content=b"# Team guide v2\n",
            headers={"Content-Type": "application/octet-stream"},
        )
        project_replaced = client.put(
            "/api/v1/admin/projects/project_web/knowledge/"
            + project_imported.json()["document_id"]
            + "?filename=project-guide.md",
            content=b"# Project guide v2\n",
            headers={"Content-Type": "application/octet-stream"},
        )
        administration.tick_knowledge_indexes()
        assert administration.knowledge()[0].selected is True
        assert administration.project_knowledge("project_web")[0].selected is True
        team_deleted = client.delete(
            "/api/v1/admin/team/knowledge/" + team_replaced.json()["document_id"]
        )
        project_deleted = client.delete(
            "/api/v1/admin/projects/project_web/knowledge/" + project_replaced.json()["document_id"]
        )
        team_spec_deleted = client.delete("/api/v1/admin/team/specs/python.testing")
        project_spec_deleted = client.delete(
            "/api/v1/admin/projects/project_web/specs/python.testing"
        )
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
    assert imported.status_code == 202
    assert project_imported.status_code == 202
    assert project_imported.json()["project_id"] == "project_web"
    assert team_content.json()["content_markdown"] == "# Team guide\n"
    assert project_content.json()["content_markdown"] == "# Project guide\n"
    assert team_selection.status_code == 200
    assert team_selection.json()[0]["selected"] is True
    assert project_selection.status_code == 200
    assert project_selection.json()[0]["selected"] is True
    assert project_selection.json()[0]["scope"] == "project"
    assert team_spec.status_code == 201
    assert team_spec_activation.json()[0]["active"] is True
    assert project_spec.status_code == 201
    assert project_spec_activation.json()[0]["active"] is True
    assert learning.json() == []
    assert collected.json() == []
    assert team.status_code == 200
    assert team.json()["team_id"] == "team_test"
    assert projects.status_code == 200
    assert [item["project_id"] for item in projects.json()] == ["project_web"]
    assert knowledge.json()[0]["manifest"]["source_name"] == "team-guide.md"
    assert team_replaced.status_code == 202
    assert project_replaced.status_code == 202
    assert team_deleted.json() == []
    assert project_deleted.json() == []
    assert team_spec_deleted.json() == []
    assert project_spec_deleted.json() == []
    assert settings.json()["secret_status"] == [
        {"environment_name": "ASE_MYSQL_DSN", "configured": True}
    ]
    assert status.status_code == 200
    assert status.json()["database"]["connection"] == "CONNECTED"
    assert status.json()["runtime_environment_path"].endswith("/runtime.env")
    assert [item["role"] for item in status.json()["agent_model_routes"]] == [
        "manager",
        "product",
        "designer",
        "planner",
        "coder",
        "qa",
        "reviewer",
    ]
    assert status.json()["agent_model_routes"][0]["policy_source"] == "global_default"
    assert mysql.json() == {"connected": True, "message": "MySQL 连接成功。"}
    assert "password" not in status.text
    assert "password" not in mysql.text
    assert updated.status_code == 200
    assert updated.json()["restart_required"] is False
    assert rejected.status_code == 422
    assert "Team guide" not in imported.text


def test_knowledge_upload_is_async_and_failed_job_has_safe_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "ai_software_engineer.knowledge.index.KnowledgeIndexWorker.start", lambda _: None
    )
    config = ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "team_id": "team_test",
            "team_name": "Test",
            "model_routes": [{"provider": "codex", "model": "gpt-5.6-terra", "kind": "codex_cli"}],
        }
    )
    TeamWorkspace.initialize(config.platform_root, team_id=config.team_id, name=config.team_name)
    administration = LocalConsoleAdministration(
        runtime_config=config,
        config_path=tmp_path / "config.json",
        environment={},
        mysql_probe=lambda _: None,
    )
    app = create_console_app(
        _Console(), _Reader(), team_id="team_test", administration=administration
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        uploaded = client.post(
            "/api/v1/admin/team/knowledge?filename=broken.pdf",
            content=b"sk-do-not-log-secret-document",
            headers={"Content-Type": "application/octet-stream"},
        )
        assert uploaded.status_code == 202
        job = uploaded.json()
        assert job["status"] == "QUEUED"
        assert client.get("/api/v1/admin/team/knowledge").json() == []
        assert client.get("/api/v1/admin/team/knowledge/index").json()["backlog"] == 1
        administration.tick_knowledge_indexes()
        failed = client.get("/api/v1/admin/team/knowledge/index").json()
        assert failed["failed"] == 1
        assert failed["jobs"][0]["error_code"] == "DOCUMENT_INVALID"
        retried = client.post("/api/v1/admin/team/knowledge/index/" + job["job_id"] + "/retry")
        assert retried.status_code == 202 and retried.json()["status"] == "QUEUED"
        assert (
            client.post("/api/v1/admin/team/knowledge/index/" + "a" * 64 + "/retry").status_code
            == 409
        )
        assert "sk-do-not-log" not in str(failed)
        assert "sk-do-not-log" not in caplog.text
