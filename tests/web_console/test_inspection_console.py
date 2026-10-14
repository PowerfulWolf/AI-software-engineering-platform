from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import host
from ai_software_engineer.web_console.inspection_console import InspectionConsole
from ai_software_engineer.web_console.preparation_store import FilePreparationProgressStore
from ai_software_engineer.web_console.store import (
    ConsoleOperationConflict,
    FileConsoleOperationStore,
)
from ai_software_engineer.web_console.summary_models import OperationSummaryQuery
from ai_software_engineer.web_console.transport import create_console_app
from tests.web_console.test_core import _create_intent, _Executor
from tests.web_console.test_model_calls import call
from tests.web_console.test_transport import _Reader


def _bytes(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_readonly_operation_store_preserves_all_history_and_rejects_writes(tmp_path: Path) -> None:
    root = tmp_path / "operations"
    writer = FileConsoleOperationStore(root, team_id="team_test")
    queued = writer.submit(
        intent=_create_intent(tmp_path),
        idempotency_key="inspection-one",
        requested_at=datetime.now(UTC),
    )
    running = writer.claim_next(at=datetime.now(UTC))
    assert running is not None
    diagnostic = call()
    writer.record_model_call(queued.operation_id, diagnostic)
    before = _bytes(tmp_path)
    reader = FileConsoleOperationStore(root, team_id="team_test", read_only=True)
    assert reader.get(queued.operation_id) == running
    assert reader.list_current() == (running,)
    assert reader.model_calls(queued.operation_id) == (diagnostic,)
    assert reader.summary_page(OperationSummaryQuery()).active_complete
    with pytest.raises(ConsoleOperationConflict, match="read only"):
        reader.claim_next(at=datetime.now(UTC))
    with pytest.raises(ConsoleOperationConflict, match="read only"):
        reader.interrupt_running(at=datetime.now(UTC))
    with pytest.raises(ConsoleOperationConflict, match="read only"):
        reader.submit(
            intent=_create_intent(tmp_path),
            idempotency_key="inspection-two",
            requested_at=datetime.now(UTC),
        )
    with pytest.raises(ConsoleOperationConflict, match="read only"):
        reader.record_model_call(queued.operation_id, call())
    with pytest.raises(ConsoleOperationConflict, match="read only"):
        reader.succeed(
            queued.operation_id,
            expected=running.operation_sha256,
            result=_Executor().execute(running.intent),
            at=datetime.now(UTC),
        )
    with pytest.raises(ConsoleOperationConflict, match="read only"):
        reader.fail(
            queued.operation_id,
            expected=running.operation_sha256,
            error_code="OFFLINE",
            error_summary="offline",
            at=datetime.now(UTC),
        )
    assert _bytes(tmp_path) == before


def test_readonly_absent_store_stays_absent_and_missing_existing_lock_refuses(
    tmp_path: Path,
) -> None:
    root = tmp_path / "absent"
    reader = FileConsoleOperationStore(root, team_id="team_test", read_only=True)
    assert reader.list_current() == ()
    assert not root.exists()
    root.mkdir()
    with pytest.raises(OSError):
        reader.list_current()
    assert not (root / "console.lock").exists()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "TRACE", "CUSTOM"])
def test_inspection_refuses_every_mutation_before_routing(tmp_path: Path, method: str) -> None:
    console = InspectionConsole(
        FileConsoleOperationStore(tmp_path / "absent", team_id="team_test", read_only=True),
        FilePreparationProgressStore(tmp_path / "progress", read_only=True),
    )
    app = create_console_app(console, _Reader(), team_id="team_test", inspection=True)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.request(method, "/not-even-a-route", content="{bad")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_MAINTENANCE"
        info = client.get("/api/v1/console").json()
        assert info["mode"] == "inspection"
        assert info["delivery_ready"] is False
        assert info["supported_actions"] == []
        assert "仅查看" in info["maintenance_summary"]
        assert client.get("/api/v1/team").status_code == 200
        assert client.get("/api/v1/operations").json() == []
        assert (
            client.get("/api/v1/admin/team/knowledge/index").json()["error"]["code"]
            == "SERVICE_MAINTENANCE"
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", ["", "readonly", "INSPECTION", " inspection"])
def test_invalid_console_mode_fails_closed(value: str) -> None:
    with pytest.raises(ValueError, match="模式"):
        host._console_mode({"ASE_CONSOLE_MODE": value})


@pytest.mark.parametrize("value", ["normal", "inspection"])
def test_durable_marker_cannot_be_overridden(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(host, "_inspection_required", lambda env: True)
    assert host._console_mode({"ASE_CONSOLE_MODE": value}) == "inspection"


def test_production_inspection_never_constructs_writer_or_reconciles_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "team_id": "team_test",
            "team_name": "Test",
            "model_routes": [{"provider": "codex", "model": "gpt-6.1-sol", "kind": "codex_cli"}],
        }
    )
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    operation_root = team.directory("work-items") / "console-operations"
    writer = FileConsoleOperationStore(operation_root, team_id=config.team_id)
    queued = writer.submit(
        intent=_create_intent(tmp_path),
        idempotency_key="production-inspect",
        requested_at=datetime.now(UTC),
    )
    running = writer.claim_next(at=datetime.now(UTC))
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json())
    before = _bytes(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("inspection attempted writer composition")

    for name in (
        "TeamHost",
        "ProjectConsole",
        "ManagerConsoleAdapter",
        "LocalConsoleAdministration",
        "NativeDirectoryChooser",
    ):
        monkeypatch.setattr(host, name, forbidden)
    monkeypatch.setattr(host, "_inspection_required", lambda env: True)
    monkeypatch.setattr(
        "ai_software_engineer.web_console.transport.KnowledgeIndexWorker", forbidden
    )
    monkeypatch.setattr(InspectionConsole, "start", forbidden)
    app = host.production_console_app(
        {
            "ASE_CONFIG": str(config_path),
            "ASE_CONSOLE_MODE": "normal",
            "ASE_SERVICE_STATE_DIR": str(tmp_path / "service-state"),
        }
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/v1/console").json()["mode"] == "inspection"
        detail = client.get(f"/api/v1/operations/{queued.operation_id}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "RUNNING"
        assert client.get(f"/api/v1/operations/{queued.operation_id}/model-calls").json() == []
        assert client.get("/api/v1/operation-summaries").status_code == 200
        assert (
            client.get(f"/api/v1/operations/{queued.operation_id}/preparation-progress").status_code
            == 200
        )
    assert writer.get(queued.operation_id) == running
    assert _bytes(tmp_path) == before


def test_damaged_marker_cannot_fall_back_to_normal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def damaged(env: object) -> bool:
        raise ValueError("维护记录损坏")

    monkeypatch.setattr(host, "_inspection_required", damaged)
    with pytest.raises(ValueError, match="维护记录损坏"):
        host.production_console_app(
            {"ASE_CONSOLE_MODE": "normal", "ASE_SERVICE_STATE_DIR": str(tmp_path / "state")}
        )


def test_maintenance_completion_guide_is_readonly_and_contains_exact_quoted_commands(
    tmp_path: Path,
) -> None:
    import shlex

    from ai_software_engineer.web_console.maintenance_guide import completion_guide

    config = tmp_path / "config with space.json"
    state = tmp_path / "service state"
    guide = completion_guide(config, state)
    tokens = shlex.split(guide.prepare_command)
    assert tokens[0] == f"ASE_CONFIG={config}"
    assert tokens[1] == f"ASE_SERVICE_STATE_DIR={state}"
    assert tokens[-1] == "prepare-maintenance-completion"
    assert shlex.split(guide.complete_command)[-3:] == [
        "complete-maintenance",
        "PLAN_SHA256",
        "--confirm-restore-normal",
    ]
    console = InspectionConsole(
        FileConsoleOperationStore(tmp_path / "absent", team_id="team_test", read_only=True),
        FilePreparationProgressStore(tmp_path / "progress", read_only=True),
    )
    app = create_console_app(
        console, _Reader(), team_id="team_test", inspection=True, maintenance_completion_guide=guide
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        info = client.get("/api/v1/console").json()
        assert info["maintenance_completion_guide"] == guide.to_wire()
        assert client.post("/api/v1/maintenance/complete").status_code == 503
        assert info["supported_actions"] == [] and not info["delivery_ready"]
    assert list(tmp_path.iterdir()) == []
