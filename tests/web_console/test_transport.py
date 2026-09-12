from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_software_engineer.company_workspace import CompanyWorkspace
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.team_view.models import TeamSnapshot
from ai_software_engineer.web_console import (
    ConsoleIntent,
    ConsoleOperation,
    InMemoryConsoleOperationStore,
    LocalConsoleAdministration,
    create_console_app,
)
from ai_software_engineer.web_console.host import main


class _Console:
    def __init__(self) -> None:
        self.store = InMemoryConsoleOperationStore("company_test")
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
        self.company_ids: list[str | None] = []

    def snapshot(self, company_id: str | None = None) -> TeamSnapshot:
        self.company_ids.append(company_id)
        return TeamSnapshot(
            as_of=datetime(2026, 9, 12, tzinfo=UTC),
            company_id=company_id or "company_test",
            company_name="Test company",
        )


def _payload(tmp_path: Path, *, name: str = "Frontend delivery") -> dict[str, object]:
    return {
        "idempotency_key": "browser-action-0001",
        "intent": {
            "action": "CREATE_REQUIREMENT_PROJECT",
            "name": name,
            "project_roots": [str(tmp_path)],
        },
    }


def test_web_transport_composes_assets_snapshot_and_durable_submission(tmp_path: Path) -> None:
    console = _Console()
    reader = _Reader()
    app = create_console_app(console, reader, company_id="company_test", port=8765)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/v1/console").json()["company_id"] == "company_test"
        snapshot = client.get("/api/v1/team")
        submitted = client.post(
            "/api/v1/operations",
            json=_payload(tmp_path),
            headers={"Origin": "http://127.0.0.1:8765"},
        )
        operation_id = submitted.json()["operation_id"]
        fetched = client.get(f"/api/v1/operations/{operation_id}")

        assert snapshot.status_code == 200
        assert snapshot.json()["company_id"] == "company_test"
        assert submitted.status_code == 202
        assert submitted.json()["status"] == "QUEUED"
        assert fetched.json() == submitted.json()
        assert client.get("/api/v1/operations").json() == [submitted.json()]
        assert submitted.headers["cache-control"] == "no-store"
        assert "form-action 'none'" in submitted.headers["content-security-policy"]

    assert console.started and console.closed


def test_web_transport_rejects_cross_origin_non_json_and_invalid_payload(tmp_path: Path) -> None:
    app = create_console_app(_Console(), _Reader(), company_id="company_test", port=8765)

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
                    "action": "CREATE_REQUIREMENT_PROJECT",
                    "name": "Invalid relative directory",
                    "project_roots": ["relative/project"],
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
    app = create_console_app(_Console(), _Reader(), company_id="company_test", port=8765)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        first = client.post("/api/v1/operations", json=_payload(tmp_path))
        changed = client.post("/api/v1/operations", json=_payload(tmp_path, name="Changed intent"))
        missing = client.get("/api/v1/operations/operation_" + "f" * 32)

    assert first.status_code == 202
    assert changed.status_code == 409
    assert missing.status_code == 404


def test_console_host_missing_config_fails_without_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ASE_CONFIG", str(tmp_path / "missing.json"))

    with pytest.raises(SystemExit, match=r"^error: cannot load production configuration:"):
        main()


def test_administration_endpoints_create_company_import_document_and_save_settings(
    tmp_path: Path,
) -> None:
    config = ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "company_id": "company_test",
            "company_name": "Test company",
            "model_routes": [{"provider": "codex", "model": "gpt-5.6-terra", "kind": "codex_cli"}],
        }
    )
    CompanyWorkspace.initialize(
        config.platform_root, company_id=config.company_id, name=config.company_name
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    administration = LocalConsoleAdministration(
        runtime_config=config,
        config_path=config_path,
        environment={"ASE_MYSQL_DSN": "mysql://user:secret@example.invalid/db"},
    )
    app = create_console_app(
        _Console(),
        _Reader(),
        company_id="company_test",
        port=8765,
        administration=administration,
    )

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        created = client.post(
            "/api/v1/admin/companies",
            json={"company_id": "company_other", "name": "Other company"},
        )
        imported = client.post(
            "/api/v1/admin/companies/company_test/knowledge?filename=team-guide.md",
            content=b"# Team guide\n",
            headers={"Content-Type": "application/octet-stream"},
        )
        companies = client.get("/api/v1/admin/companies")
        knowledge = client.get("/api/v1/admin/companies/company_test/knowledge")
        settings = client.get("/api/v1/admin/settings")
        updated_config = settings.json()["config"]
        normalized_path = imported.json()["manifest"]["normalized_relative_path"]
        updated_config["company_knowledge_paths"] = [normalized_path]
        updated = client.put("/api/v1/admin/settings", json={"config": updated_config})
        rejected = client.post(
            "/api/v1/admin/companies/company_test/knowledge?filename=unsafe.exe",
            content=b"binary",
            headers={"Content-Type": "application/octet-stream"},
        )

    assert created.status_code == 201
    assert imported.status_code == 201
    assert companies.status_code == 200
    assert [item["company_id"] for item in companies.json()] == [
        "company_other",
        "company_test",
    ]
    assert knowledge.json()[0]["manifest"]["source_name"] == "team-guide.md"
    assert settings.json()["secret_status"] == [
        {"environment_name": "ASE_MYSQL_DSN", "configured": True}
    ]
    assert updated.status_code == 200
    assert updated.json()["restart_required"] is True
    assert rejected.status_code == 422
    assert "Team guide" not in imported.text
