from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, get_ident

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import Message, Scope

from ai_software_engineer.agents.model_diagnostics import ModelCallDiagnostic
from ai_software_engineer.config import ProductionConfig, ProductionConfigError
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.multi_directory.attachments import RequirementScreenshot
from ai_software_engineer.team_view.models import TeamReadError, TeamSnapshot
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import (
    ConfigurationApplyError,
    ConfigurationApplyState,
    ConfigurationApplyStatus,
    ConsoleIntent,
    ConsoleOperation,
    FileConsoleOperationStore,
    InMemoryConsoleOperationStore,
    LocalConsoleAdministration,
    create_console_app,
    transport,
)
from ai_software_engineer.web_console.administration import SettingsSnapshot
from ai_software_engineer.web_console.host import production_console_app
from ai_software_engineer.web_console.models import CONSOLE_INTENT_ADAPTER, ConsoleAction
from ai_software_engineer.web_console.store import ConsoleOperationStore
from ai_software_engineer.web_console.transport import _screenshot_body


class _Console:
    def __init__(self, store: ConsoleOperationStore | None = None) -> None:
        self.store = store if store is not None else InMemoryConsoleOperationStore("team_test")
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


class _HeldSnapshotReader(_Reader):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()
        self.finished = Event()

    def snapshot(self, project_id: str | None = None) -> TeamSnapshot:
        if not self.project_ids:
            self.project_ids.append(project_id)
            self.entered.set()
            try:
                assert self.release.wait(5), "test did not release its first snapshot"
            finally:
                self.finished.set()
            return TeamSnapshot(
                as_of=datetime(2026, 9, 12, tzinfo=UTC),
                team_id="team_test",
                team_name="Test team",
                selected_project_id=project_id,
            )
        return super().snapshot(project_id)


@pytest.mark.parametrize("cancel_first", [False, True])
def test_team_snapshot_admission_tracks_actual_worker_lifetime(cancel_first: bool) -> None:
    async def exercise() -> None:
        reader = _HeldSnapshotReader()
        app = create_console_app(_Console(), reader, team_id="team_test")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8765"
        ) as client:
            first = asyncio.create_task(client.get("/api/v1/team?project_id=project_first"))
            try:
                assert await asyncio.to_thread(reader.entered.wait, 2)
                if cancel_first:
                    first.cancel()
                    # Middleware may shield cancellation until the synchronous
                    # worker returns; do not wait for that before probing overlap.
                    await asyncio.sleep(0)
                rejected = await asyncio.wait_for(
                    client.get("/api/v1/team?project_id=project_second"), 2
                )
                assert rejected.status_code == 503
                assert rejected.json()["error"]["code"] == "TEAM_READ_IN_PROGRESS"
                assert rejected.headers["cache-control"] == "no-store"
                assert reader.project_ids == ["project_first"]
                assert (await client.get("/api/v1/console")).status_code == 200
                assert (
                    await client.get("/api/v1/team", headers={"Origin": "https://untrusted.test"})
                ).status_code == 403
                assert reader.project_ids == ["project_first"]
            finally:
                reader.release.set()
                if not cancel_first:
                    response = await asyncio.wait_for(first, 2)
                    assert response.json()["selected_project_id"] == "project_first"
                else:
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(first, 2)
                assert await asyncio.to_thread(reader.finished.wait, 2)

            # A cancelled HTTP caller is not proof that its synchronous worker stopped.
            # Wait for the actual worker's gate to be released, without reusing old facts.
            for _ in range(100):
                response = await client.get("/api/v1/team?project_id=project_second")
                if response.status_code != 503:
                    break
                await asyncio.sleep(0.005)
            assert response.status_code == 200
            assert response.json()["selected_project_id"] == "project_second"
            assert reader.project_ids == ["project_first", "project_second"]

    asyncio.run(exercise())


@pytest.mark.parametrize("safe_failure", [True, False])
def test_team_snapshot_admission_releases_after_read_failure(safe_failure: bool) -> None:
    class FailingOnceReader(_Reader):
        def snapshot(self, project_id: str | None = None) -> TeamSnapshot:
            if not self.project_ids:
                self.project_ids.append(project_id)
                error = TeamReadError if safe_failure else RuntimeError
                raise error("private configuration must never reach the response")
            return super().snapshot(project_id)

    reader = FailingOnceReader()
    app = create_console_app(_Console(), reader, team_id="team_test")
    with TestClient(app, base_url="http://127.0.0.1:8765", raise_server_exceptions=False) as client:
        failed = client.get("/api/v1/team")
        assert failed.status_code == (503 if safe_failure else 500)
        if safe_failure:
            assert failed.json()["error"]["code"] == "TEAM_UNAVAILABLE"
        assert "private configuration" not in failed.text
        assert client.get("/api/v1/team?project_id=project_next").status_code == 200


@pytest.mark.parametrize("phase", ["wire", "render"])
def test_team_snapshot_admission_includes_worker_serialization(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    entered, release = Event(), Event()
    loop_thread = get_ident()
    original_wire = TeamSnapshot.to_wire
    original_render = JSONResponse.render

    def hold() -> None:
        assert get_ident() != loop_thread, "serialization blocked the HTTP event loop"
        entered.set()
        assert release.wait(5), "test did not release serialization"

    def wire(snapshot: TeamSnapshot) -> WirePayload:
        if not release.is_set():
            hold()
        return original_wire(snapshot)

    def render(response: JSONResponse, content: object) -> bytes:
        if isinstance(content, dict) and "team_id" in content and not release.is_set():
            hold()
        return original_render(response, content)

    if phase == "wire":
        monkeypatch.setattr(TeamSnapshot, "to_wire", wire)
    else:
        monkeypatch.setattr(JSONResponse, "render", render)

    async def exercise() -> None:
        reader = _Reader()
        app = create_console_app(_Console(), reader, team_id="team_test")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8765"
        ) as client:
            first = asyncio.create_task(client.get("/api/v1/team"))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                second = await asyncio.wait_for(client.get("/api/v1/team"), 2)
                assert second.status_code == 503
                assert reader.project_ids == [None]
            finally:
                release.set()
                assert (await asyncio.wait_for(first, 2)).status_code == 200
            assert (await client.get("/api/v1/team")).status_code == 200

    asyncio.run(exercise())


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


def test_console_operation_manifest_reports_the_running_action_contract() -> None:
    app = create_console_app(_Console(), _Reader(), team_id="team_test", port=8765)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        info = client.get("/api/v1/console")
    assert info.status_code == 200
    assert info.json()["operation_contract_version"] == 2
    assert set(info.json()["supported_actions"]) == {action.value for action in ConsoleAction}
    assert set(info.json()["supported_actions"]) == set(
        CONSOLE_INTENT_ADAPTER.json_schema()["discriminator"]["mapping"]
    )


def test_static_assets_remain_bound_to_the_started_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("index.html", "app.js", "style.css"):
        (tmp_path / name).write_bytes(b"startup " + name.encode())
    monkeypatch.setattr(transport, "files", lambda _: tmp_path)
    app = create_console_app(_Console(), _Reader(), team_id="team_test", port=8765)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/app.js").content == b"startup app.js"
        (tmp_path / "app.js").write_bytes(b"new UI expects new HANDLE schema")
        (tmp_path / "index.html").write_bytes(b"new markup")
        (tmp_path / "style.css").write_bytes(b"new stylesheet")
        assert client.get("/app.js").content == b"startup app.js"
        assert client.get("/").content == b"startup index.html"
        assert client.get("/style.css").content == b"startup style.css"


def _wait_payload() -> dict[str, object]:
    return {
        "idempotency_key": "browser-wait-0001",
        "intent": {
            "action": "HANDLE_DELIVERY_WAIT",
            "project_id": "project_web",
            "delivery_id": "delivery_multi_fixture",
            "expected_checkpoint_sha256": "a" * 64,
            "work_item_id": "work_original",
            "expected_disposition_sha256": "b" * 64,
            "expected_task_intent_sha256": "c" * 64,
            "expected_source_revision": "d" * 40,
            "expected_checkpoint_sequence": 6,
        },
    }


def test_http_handle_wait_validates_and_durably_accepts_the_exact_browser_envelope(
    tmp_path: Path,
) -> None:
    root = tmp_path / "console-operations"
    console = _Console(FileConsoleOperationStore(root, team_id="team_test"))
    app = create_console_app(console, _Reader(), team_id="team_test", port=8765)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        submitted = client.post("/api/v1/operations", json=_wait_payload())
        assert submitted.status_code == 202, submitted.text
        assert submitted.json()["intent"] == _wait_payload()["intent"]
        assert submitted.json()["status"] == "QUEUED"
        assert len(client.get("/api/v1/operations").json()) == 1
        replay = client.post("/api/v1/operations", json=_wait_payload())
        assert replay.json() == submitted.json()
    reopened = FileConsoleOperationStore(root, team_id="team_test")
    assert reopened.get(submitted.json()["operation_id"]).to_wire() == submitted.json()


def test_http_unknown_action_reports_service_mismatch_without_echo_or_submission() -> None:
    console = _Console()
    app = create_console_app(console, _Reader(), team_id="team_test", port=8765)
    payload = _wait_payload()
    payload["intent"] = {"action": "FUTURE_ACTION_PRIVATE_INPUT"}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        rejected = client.post("/api/v1/operations", json=payload)
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "OPERATION_NOT_SUPPORTED"
    assert "服务" in rejected.json()["error"]["message"]
    assert "FUTURE_ACTION_PRIVATE_INPUT" not in rejected.text
    assert console.list_operations() == ()


def test_http_internal_record_validation_is_not_reported_as_invalid_browser_input() -> None:
    class InvalidRecordConsole(_Console):
        def submit(self, intent: ConsoleIntent, *, idempotency_key: str) -> ConsoleOperation:
            TypeAdapter(int).validate_python("PRIVATE_INTERNAL_RECORD")
            raise AssertionError("validation unexpectedly succeeded")

    console = InvalidRecordConsole()
    app = create_console_app(console, _Reader(), team_id="team_test", port=8765)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        rejected = client.post("/api/v1/operations", json=_wait_payload())
    assert rejected.status_code == 503
    assert rejected.json()["error"]["code"] == "OPERATION_STATE_INVALID"
    assert "平台" in rejected.json()["error"]["message"]
    assert "PRIVATE_INTERNAL_RECORD" not in rejected.text
    assert console.list_operations() == ()


def test_http_handle_wait_still_rejects_input_authority_and_localizes_failure() -> None:
    console = _Console()
    app = create_console_app(console, _Reader(), team_id="team_test", port=8765)
    payload = _wait_payload()
    intent = payload["intent"]
    assert isinstance(intent, dict)
    intent["process_stopped"] = True
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        rejected = client.post("/api/v1/operations", json=payload)
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "INVALID_REQUEST"
    assert "未受理" in rejected.json()["error"]["message"]
    assert "process_stopped" not in rejected.text
    assert console.list_operations() == ()


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
        assert settings.json()["settings_contract_version"] == 2
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
