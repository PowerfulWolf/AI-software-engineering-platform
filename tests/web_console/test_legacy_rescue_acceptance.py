"""Browser rescue intents cannot use a stale requirement or forge containment facts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from ai_software_engineer.manager.delivery import ProjectDeliveryResult, UnifiedProjectEntryService
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.web_console import (
    ConsoleOperationStatus,
    FileConsoleOperationStore,
    ManagerConsoleAdapter,
    ProjectConsole,
    create_console_app,
)
from ai_software_engineer.web_console.manager import TeamConsoleHost
from tests.web_console.test_transport import _Reader

DELIVERY = "delivery_" + "a" * 40
TASK = "task_legacy_console_fixture"


class _Entry:
    def __init__(self, checkpoint: ProjectDeliveryCheckpoint) -> None:
        self.checkpoint = checkpoint

    def status(self, delivery_id: str) -> ProjectDeliveryResult:
        assert delivery_id == self.checkpoint.delivery_id
        return ProjectDeliveryResult(checkpoint=self.checkpoint)


class _Host:
    def __init__(self, checkpoint: ProjectDeliveryCheckpoint) -> None:
        self.entry = _Entry(checkpoint)
        self.baseline_calls = 0

    def project_entry(self, project_id: str) -> UnifiedProjectEntryService:
        assert project_id == "project_test"
        return cast(UnifiedProjectEntryService, self.entry)

    def propose_execution_baseline(self, *args: object, **kwargs: object) -> None:
        self.baseline_calls += 1
        raise AssertionError("stale browser input must be rejected before Host proposal")

    def execute_execution_baseline(self, *args: object, **kwargs: object) -> None:
        self.baseline_calls += 1
        raise AssertionError("stale browser input must be rejected before Host execution")


def _fixture(tmp_path: Path) -> tuple[ProjectConsole, TestClient, _Host]:
    checkpoint = ProjectDeliveryCheckpoint.create(
        delivery_id=DELIVERY,
        sequence=2,
        previous_checkpoint_sha256="1" * 64,
        repository_id="repository_" + "b" * 40,
        repository_root=str(tmp_path),
        stage=DeliveryStage.WAITING_HUMAN,
        stage_attempts=DeliveryStageAttempts(delivering=2),
        next_action=DeliveryNextAction.RUN_DELIVERY,
        failure_code=DeliveryFailureCode.RESOURCE_UNAVAILABLE,
        failure_summary="原调用结果未知, 原需求与开发现场保留。",
        checkpointed_at=datetime(2026, 10, 8, tzinfo=UTC),
    )
    host = _Host(checkpoint)
    console = ProjectConsole(
        store=FileConsoleOperationStore(tmp_path / "operations", team_id="team_test"),
        executor=ManagerConsoleAdapter(cast(TeamConsoleHost, host)),
    )
    app = create_console_app(console, _Reader(), team_id="team_test")
    return console, TestClient(app, base_url="http://127.0.0.1:8765"), host


def _intent(action: str) -> dict[str, object]:
    identity: dict[str, object] = {
        "action": action,
        "project_id": "project_test",
        "delivery_id": DELIVERY,
        "task_id": TASK,
        "expected_checkpoint_sha256": "9" * 64,
    }
    if action == "PROPOSE_EXECUTION_BASELINE":
        return {
            **identity,
            "purpose": "legacy_workspace_rescue",
            "expected_task_intent_sha256": "2" * 64,
            "expected_task_revision": 2,
            "expected_work_item_id": "work_original_unknown",
            "expected_source_revision": "3" * 40,
            "target_base_ref": "3" * 40,
            "input_mode": "preserve_draft",
        }
    return {
        **identity,
        "expected_plan_sha256": "4" * 64,
        "reference": "web-console-legacy-approval",
        "confirm_legacy_containment": True,
    }


@pytest.mark.parametrize("action", ["PROPOSE_EXECUTION_BASELINE", "EXECUTE_EXECUTION_BASELINE"])
def test_real_http_console_rejects_stale_checkpoint_before_any_rescue_action(
    tmp_path: Path, action: str
) -> None:
    console, client, host = _fixture(tmp_path)
    response = client.post(
        "/api/v1/operations",
        json={"intent": _intent(action), "idempotency_key": "stale-legacy-" + action},
    )
    assert response.status_code == 202, response.json()
    operation_id = response.json()["operation_id"]
    completed = console.run_once()
    assert completed is not None and completed.status is ConsoleOperationStatus.FAILED
    assert completed.error_code == "STALE_CHECKPOINT"
    assert host.baseline_calls == 0
    read = client.get(f"/api/v1/operations/{operation_id}")
    assert read.status_code == 200 and read.json()["error_code"] == "STALE_CHECKPOINT"
    assert len(console.list_operations()) == 1


@pytest.mark.parametrize("extra", ["booted_at", "process_stopped", "containment_sha256"])
def test_browser_cannot_supply_trusted_os_or_stop_facts(tmp_path: Path, extra: str) -> None:
    console, client, host = _fixture(tmp_path)
    intent = {**_intent("PROPOSE_EXECUTION_BASELINE"), extra: "caller-asserted-stop"}
    response = client.post(
        "/api/v1/operations",
        json={"intent": intent, "idempotency_key": "forged-legacy-" + extra},
    )
    assert response.status_code == 422
    assert not console.list_operations() and host.baseline_calls == 0


def test_false_engineering_confirmation_is_rejected_before_operation_submission(
    tmp_path: Path,
) -> None:
    console, client, host = _fixture(tmp_path)
    intent = {**_intent("EXECUTE_EXECUTION_BASELINE"), "confirm_legacy_containment": False}
    response = client.post(
        "/api/v1/operations",
        json={"intent": intent, "idempotency_key": "false-legacy-confirmation"},
    )
    assert response.status_code == 422
    assert not console.list_operations() and host.baseline_calls == 0
