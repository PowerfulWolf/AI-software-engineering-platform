"""Public Console deletion leaves immutable audit and refuses execution afterward."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.multi_directory.service import CreateRequirement, JointDeliveryService
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.web_console import ManagerConsoleAdapter, ProjectConsole
from ai_software_engineer.web_console.manager import TeamConsoleHost
from ai_software_engineer.web_console.models import ConsoleOperation, ConsoleOperationStatus
from ai_software_engineer.web_console.store import FileConsoleOperationStore
from ai_software_engineer.web_console.transport import create_console_app
from tests.manager.test_requirement_retirement import _service


class _Host:
    def __init__(self, service: JointDeliveryService) -> None:
        self.service = service

    def requirement_entry(self, project_id: str | None = None) -> JointDeliveryService:
        if project_id != self.service.project.manifest.project_id:
            raise ValueError("Requirement belongs to another Team or Project")
        return self.service


def _finished(console: ProjectConsole, operation_id: str) -> ConsoleOperation:
    for _ in range(200):
        operation = console.get(operation_id)
        if operation.status not in {ConsoleOperationStatus.QUEUED, ConsoleOperationStatus.RUNNING}:
            return operation
        time.sleep(0.01)
    raise AssertionError("Console did not finish a local deletion command")


def test_http_delete_replay_hidden_snapshot_audit_and_execution_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, root = _service(tmp_path, monkeypatch)
    original = service.create(
        CreateRequirement(name="K1", repository_roots=(str(root),))
    ).checkpoint
    history = service.journal.history(original.delivery_id)
    config = ProductionConfig(
        platform_root=service.team.manifest.platform_root,
        team_id=service.team.manifest.team_id,
        team_name=service.team.manifest.name,
        default_project_id=service.project.manifest.project_id,
        default_project_name=service.project.manifest.name,
        model_routes=ProductionConfig.default().model_routes,
    )
    reader = ProductionTeamReader(config, {})
    store = FileConsoleOperationStore(
        service.team.directory("work-items") / "deletion-operations",
        team_id=service.team.manifest.team_id,
    )
    console = ProjectConsole(
        store=store, executor=ManagerConsoleAdapter(cast(TeamConsoleHost, _Host(service)))
    )
    app = create_console_app(console, reader, team_id=service.team.manifest.team_id, port=8765)
    intent = {
        "action": "DELETE_REQUIREMENT",
        "project_id": original.project_id,
        "delivery_id": original.delivery_id,
        "expected_checkpoint_sha256": original.checkpoint_sha256,
    }
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        before = client.get("/api/v1/team", params={"project_id": original.project_id}).json()
        assert [item["id"] for item in before["requests"]] == [original.delivery_id]
        response = client.post(
            "/api/v1/operations", json={"intent": intent, "idempotency_key": "delete-k1-001"}
        )
        assert response.status_code == 202
        deletion = _finished(console, response.json()["operation_id"])
        assert deletion.status is ConsoleOperationStatus.SUCCEEDED
        assert deletion.result is not None and deletion.result.stage == "REQUIREMENT_DELETED"
        tombstone_bytes = service.retirements.path.read_bytes()
        replay = client.post(
            "/api/v1/operations", json={"intent": intent, "idempotency_key": "delete-k1-001"}
        )
        assert replay.status_code == 202
        assert replay.json()["operation_id"] == deletion.operation_id
        second = client.post(
            "/api/v1/operations", json={"intent": intent, "idempotency_key": "delete-k1-002"}
        )
        assert (
            _finished(console, second.json()["operation_id"]).status
            is ConsoleOperationStatus.SUCCEEDED
        )
        assert service.retirements.path.read_bytes() == tombstone_bytes
        after = client.get("/api/v1/team", params={"project_id": original.project_id}).json()
        assert after["requests"] == after["tasks"] == []
        assert after["projects"][0]["requirement_count"] == 0
        for action in ("CONTINUE_DELIVERY", "PRODUCT_APPROVAL", "RESTART_REQUIREMENT"):
            denied = client.post(
                "/api/v1/operations",
                json={
                    "intent": {**intent, "action": action},
                    "idempotency_key": "deleted-k1-" + action,
                },
            )
            assert denied.status_code == 202
            operation = _finished(console, denied.json()["operation_id"])
            assert operation.status is ConsoleOperationStatus.FAILED
            assert operation.error_code == "COMMAND_REJECTED"
            assert operation.error_summary is not None and "需求已删除" in operation.error_summary
            assert console.model_calls(operation.operation_id) == ()
        wrong_project = client.post(
            "/api/v1/operations",
            json={
                "intent": {**intent, "project_id": "project_other"},
                "idempotency_key": "delete-other-project",
            },
        )
        assert (
            _finished(console, wrong_project.json()["operation_id"]).status
            is ConsoleOperationStatus.FAILED
        )
    assert service.journal.history(original.delivery_id) == history
    assert service.retirements.path.read_bytes() == tombstone_bytes
    schema = json.loads(Path("schemas/requirement-retirement.schema.json").read_text())
    Draft202012Validator(schema).validate(service.retirements.retirement().to_wire())
