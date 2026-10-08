"""Browser rescue intents cannot use a stale requirement or forge containment facts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.manager.delivery import ProjectDeliveryResult, UnifiedProjectEntryService
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.legacy_local_execution import LegacyRescuePrerequisiteError
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
        self.error: Exception | None = None

    def project_entry(self, project_id: str) -> UnifiedProjectEntryService:
        assert project_id == "project_test"
        return cast(UnifiedProjectEntryService, self.entry)

    def propose_execution_baseline(self, *args: object, **kwargs: object) -> None:
        self.baseline_calls += 1
        if self.error is not None:
            raise self.error
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


@pytest.mark.parametrize(
    "extra", ["booted_at", "process_stopped", "containment_sha256", "local_execution_survey"]
)
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


def test_pydantic_failure_does_not_publish_raw_input_in_response_or_operation(
    tmp_path: Path,
) -> None:
    console, client, host = _fixture(tmp_path)
    with pytest.raises(ValidationError) as validation:
        TypeAdapter(int).validate_python("private-local-rescue-input")
    host.error = validation.value
    intent = {
        **_intent("PROPOSE_EXECUTION_BASELINE"),
        "expected_checkpoint_sha256": host.entry.checkpoint.checkpoint_sha256,
    }
    response = client.post(
        "/api/v1/operations",
        json={"intent": intent, "idempotency_key": "safe-legacy-validation"},
    )
    assert response.status_code == 202
    completed = console.run_once()
    assert completed is not None and completed.status is ConsoleOperationStatus.FAILED
    assert completed.error_summary == "平台无法核验本次操作所需的记录，请重新检查当前需求。"  # noqa: RUF001
    persisted = client.get(f"/api/v1/operations/{completed.operation_id}")
    assert persisted.status_code == 200
    assert "private-local-rescue-input" not in persisted.text
    assert "input_value" not in persisted.text
    assert host.baseline_calls == 1


@pytest.mark.parametrize(
    ("code", "summary", "next_action"),
    [
        (
            "LEGACY_LOCAL_EXECUTION_ACTIVE",
            "当前仍有本机执行占用保留的工作现场。",
            "等待原调用及派生工具结束后重新检查恢复前提。",
        ),
        (
            "LEGACY_LOCAL_OBSERVATION_UNAVAILABLE",
            "平台暂时无法读取可靠的本机身份和启动记录, 不能准备旧执行恢复。",
            "请让平台维护者检查当前系统的只读查询能力和权限, "
            "修复后重新检查恢复前提; 不要清空工作区。",
        ),
    ],
)
def test_unmet_local_prerequisite_is_persisted_as_a_bound_check_without_execution(
    tmp_path: Path, code: str, summary: str, next_action: str
) -> None:
    console, client, host = _fixture(tmp_path)
    host.error = LegacyRescuePrerequisiteError(
        code=code,
        safe_message=summary,
        next_action=next_action,
    )
    intent = {
        **_intent("PROPOSE_EXECUTION_BASELINE"),
        "expected_checkpoint_sha256": host.entry.checkpoint.checkpoint_sha256,
    }
    response = client.post(
        "/api/v1/operations",
        json={"intent": intent, "idempotency_key": "waiting-legacy-local-check"},
    )
    assert response.status_code == 202
    completed = console.run_once()
    assert completed is not None and completed.status is ConsoleOperationStatus.SUCCEEDED
    assert completed.result is not None
    assert completed.result.execution_baseline_plan is None
    assert completed.result.execution_baseline_binding is None
    assert completed.result.approval is None
    check = completed.result.legacy_rescue_preparation
    assert check is not None and check.status == "WAITING"
    assert check.task_id == TASK
    assert check.work_item_id == "work_original_unknown"
    assert check.source_revision == "3" * 40
    assert check.code == host.error.code
    assert check.summary == host.error.safe_message
    assert check.next_action == host.error.next_action
    assert check.responsible_party == "平台执行服务"
    persisted = client.get(f"/api/v1/operations/{completed.operation_id}")
    assert persisted.status_code == 200
    assert persisted.json()["result"]["legacy_rescue_preparation"] == check.to_wire()
    assert host.baseline_calls == 1
    assert len(console.list_operations()) == 1


@pytest.mark.parametrize("local", [False, "yes"])
def test_local_stop_confirmation_requires_true_and_cannot_reuse_reboot_confirmation(
    tmp_path: Path, local: object
) -> None:
    console, client, host = _fixture(tmp_path)
    intent = {
        **_intent("EXECUTE_EXECUTION_BASELINE"),
        "confirm_local_execution_stopped": local,
    }
    response = client.post(
        "/api/v1/operations",
        json={"intent": intent, "idempotency_key": "false-local-stop-confirmation"},
    )
    assert response.status_code == 422
    assert not console.list_operations() and host.baseline_calls == 0


def test_two_engineering_confirmation_methods_cannot_be_combined(tmp_path: Path) -> None:
    console, client, host = _fixture(tmp_path)
    intent = {**_intent("EXECUTE_EXECUTION_BASELINE"), "confirm_local_execution_stopped": True}
    response = client.post(
        "/api/v1/operations",
        json={"intent": intent, "idempotency_key": "double-local-stop-confirmation"},
    )
    assert response.status_code == 422
    assert not console.list_operations() and host.baseline_calls == 0
