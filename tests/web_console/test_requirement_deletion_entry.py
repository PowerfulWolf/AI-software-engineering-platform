"""Public Console deletion removes Requirement data and refuses stale execution."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.multi_directory.models import JointStage
from ai_software_engineer.multi_directory.service import CreateRequirement, JointDeliveryService
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.web_console import ManagerConsoleAdapter, ProjectConsole
from ai_software_engineer.web_console.manager import TeamConsoleHost
from ai_software_engineer.web_console.models import ConsoleOperation, ConsoleOperationStatus
from ai_software_engineer.web_console.store import FileConsoleOperationStore
from ai_software_engineer.web_console.transport import create_console_app
from tests.manager.test_requirement_retirement import _product_spec, _service


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


@pytest.mark.parametrize(
    "product_ready", [False, True], ids=["idle-draft", "product-awaiting-approval"]
)
@pytest.mark.parametrize("close_first", [False, True], ids=["delete-directly", "close-then-delete"])
def test_http_delete_replay_hidden_snapshot_audit_and_execution_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    product_ready: bool,
    close_first: bool,
) -> None:
    service, root = _service(tmp_path, monkeypatch)
    original = service.create(
        CreateRequirement(name="K1", repository_roots=(str(root),))
    ).checkpoint
    if product_ready:
        original = service._save(
            original,
            stage=JointStage.WAITING_PRODUCT_APPROVAL,
            product_spec=_product_spec(original),
        )
    config = ProductionConfig(
        platform_root=service.team.manifest.platform_root,
        team_id=service.team.manifest.team_id,
        team_name=service.team.manifest.name,
        default_project_id=service.project.manifest.project_id,
        default_project_name=service.project.manifest.name,
        model_routes=ProductionConfig.default().model_routes,
    )
    reader = ProductionTeamReader(config, {})
    from ai_software_engineer.web_console.requirement_visibility import (
        ProductionRequirementOperationVisibility,
    )

    store = FileConsoleOperationStore(
        service.team.directory("work-items") / "console-operations",
        team_id=service.team.manifest.team_id,
        visibility=ProductionRequirementOperationVisibility(service.team),
    )
    console = ProjectConsole(
        store=store, executor=ManagerConsoleAdapter(cast(TeamConsoleHost, _Host(service)))
    )
    app = create_console_app(console, reader, team_id=service.team.manifest.team_id, port=8765)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        before = client.get("/api/v1/team", params={"project_id": original.project_id}).json()
        assert [item["id"] for item in before["requests"]] == [original.delivery_id]
        assert before["requests"][0]["stage"] == original.stage.value
        current = original
        close_id: str | None = None
        if close_first:
            close_response = client.post(
                "/api/v1/operations",
                json={
                    "intent": {
                        "action": "CLOSE_REQUIREMENT",
                        "project_id": current.project_id,
                        "delivery_id": current.delivery_id,
                        "expected_checkpoint_sha256": current.checkpoint_sha256,
                    },
                    "idempotency_key": "close-k1-001",
                },
            )
            assert close_response.status_code == 202
            close_id = close_response.json()["operation_id"]
            closed_operation = _finished(console, close_id)
            assert closed_operation.status is ConsoleOperationStatus.SUCCEEDED
            assert closed_operation.result is not None
            assert closed_operation.result.stage == "CLOSED"
            closed = service.journal.current(original.delivery_id)
            assert closed is not None and closed.stage is JointStage.CLOSED
            assert closed.product_spec == original.product_spec
            assert closed.approval is None
            assert closed.previous_checkpoint_sha256 == original.checkpoint_sha256
            assert closed.checkpoint_sha256 != original.checkpoint_sha256
            assert service.retirements.entry(original.delivery_id) is None
            current = closed
        intent = {
            "action": "DELETE_REQUIREMENT",
            "project_id": current.project_id,
            "delivery_id": current.delivery_id,
            "expected_checkpoint_sha256": current.checkpoint_sha256,
        }
        response = client.post(
            "/api/v1/operations", json={"intent": intent, "idempotency_key": "delete-k1-001"}
        )
        assert response.status_code == 202
        deletion = _finished(console, response.json()["operation_id"])
        assert deletion.status is ConsoleOperationStatus.SUCCEEDED
        assert deletion.result is not None and deletion.result.stage == "REQUIREMENT_DELETED"
        acknowledgement = client.get("/api/v1/operations/" + deletion.operation_id)
        assert acknowledgement.status_code == 200
        assert acknowledgement.json()["status"] == "SUCCEEDED"
        if close_id is not None:
            assert client.get("/api/v1/operations/" + close_id).status_code == 404
        tombstone_bytes = service.retirements.path.read_bytes()
        replay = client.post(
            "/api/v1/operations", json={"intent": intent, "idempotency_key": "delete-k1-001"}
        )
        assert replay.status_code == 202
        assert replay.json()["operation_id"] == deletion.operation_id
        assert _finished(console, deletion.operation_id).status is ConsoleOperationStatus.SUCCEEDED
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
            assert denied.status_code == 409
            assert denied.json()["error"]["code"] == "OPERATION_CONFLICT"
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
    assert service.journal.history(original.delivery_id) == ()
    assert not service.journal.directory(original.delivery_id).exists()
    assert service.retirements.path.read_bytes() == tombstone_bytes
    schema = json.loads(Path("schemas/requirement-retirement.schema.json").read_text())
    Draft202012Validator(schema).validate(service.retirements.retirement().to_wire())
