"""Real retired-child receipts force production composition to remain read-only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import host
from ai_software_engineer.web_console.fault_retirement import (
    MARKER_NAME,
    FaultRetirementError,
    prepare_fault_retirement,
)
from ai_software_engineer.web_console.inspection_console import InspectionConsole
from ai_software_engineer.web_console.store import FileConsoleOperationStore
from tests.web_console.test_core import _create_intent
from tests.web_console.test_fault_retirement import _execute, _host
from tests.web_console.test_inspection_console import _bytes


def _forbid_writers(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("maintenance marker reached writer composition")

    for name in (
        "TeamHost",
        "ProjectConsole",
        "ManagerConsoleAdapter",
        "LocalConsoleAdministration",
        "NativeDirectoryChooser",
    ):
        monkeypatch.setattr(host, name, forbidden)
    monkeypatch.setattr(
        "ai_software_engineer.web_console.transport.KnowledgeIndexWorker", forbidden
    )
    monkeypatch.setattr(InspectionConsole, "start", forbidden)


def _existing_team(env: dict[str, str]) -> tuple[ProductionConfig, FileConsoleOperationStore]:
    config = ProductionConfig.from_file(Path(env["ASE_CONFIG"]))
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    return config, FileConsoleOperationStore(
        team.directory("work-items") / "console-operations", team_id=config.team_id
    )


def test_actual_retirement_marker_forces_inspection_without_rewriting_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _host(tmp_path) as (env, child):
        config, store = _existing_team(env)
        queued = store.submit(
            intent=_create_intent(tmp_path),
            idempotency_key="real-marker-history",
            requested_at=datetime.now(UTC),
        )
        running = store.claim_next(at=datetime.now(UTC))
        assert running is not None
        original_records = _bytes(Path(config.platform_root))
        state_root = Path(env["ASE_SERVICE_STATE_DIR"])
        original_lifecycle = {
            path.name: path.read_bytes() for path in state_root.glob("console-service-*.json")
        }
        plan = prepare_fault_retirement(env)
        receipt = _execute(env, plan.record_sha256)
        assert child.poll() is not None
        assert receipt.historical_execution_outcome == "UNKNOWN"
        _forbid_writers(monkeypatch)
        # Actual sealed marker and archive, no mocked inspection_required seam.
        app = host.production_console_app({**env, "ASE_CONSOLE_MODE": "normal"})
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            info = client.get("/api/v1/console").json()
            assert info["mode"] == "inspection"
            assert info["delivery_ready"] is False and info["supported_actions"] == []
            operation = client.get(f"/api/v1/operations/{queued.operation_id}")
            assert operation.status_code == 200
            assert operation.json()["status"] == "RUNNING"
            assert client.get("/api/v1/operation-summaries").status_code == 200
            assert client.get(f"/api/v1/operations/{queued.operation_id}/model-calls").json() == []
            assert (
                client.get(
                    f"/api/v1/operations/{queued.operation_id}/preparation-progress"
                ).status_code
                == 200
            )
            response = client.post("/api/v1/operations", content=b"invalid payload")
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "SERVICE_MAINTENANCE"
        assert store.get(queued.operation_id) == running
        assert _bytes(Path(config.platform_root)) == original_records
        assert original_lifecycle == {
            path.name: path.read_bytes() for path in state_root.glob("console-service-*.json")
        }


@pytest.mark.parametrize("corrupt", ["marker", "archived_log", "archived_lifecycle"])
def test_actual_corrupt_retirement_chain_refuses_before_any_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corrupt: str
) -> None:
    with _host(tmp_path) as (env, child):
        config, _ = _existing_team(env)
        before = _bytes(Path(config.platform_root))
        plan = prepare_fault_retirement(env)
        _execute(env, plan.record_sha256)
        assert child.poll() is not None
        root = Path(env["ASE_SERVICE_STATE_DIR"])
        archive = root / "console-fault-retirements" / plan.record_sha256
        target = (
            root / MARKER_NAME
            if corrupt == "marker"
            else archive
            / (
                "ase-console.log"
                if corrupt == "archived_log"
                else "console-service-shutdown.result.json"
            )
        )
        target.write_bytes(target.read_bytes() + b"tampered")
        _forbid_writers(monkeypatch)
        with pytest.raises(FaultRetirementError, match="不启动替代服务"):
            host.production_console_app({**env, "ASE_CONSOLE_MODE": "normal"})
        assert _bytes(Path(config.platform_root)) == before
