"""Published rescue contracts keep observation, preparation and approval distinct."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.manager.legacy_containment import LegacyExecutionContainment
from ai_software_engineer.manager.legacy_local_execution import LegacyLocalExecutionSurvey
from ai_software_engineer.web_console.models import ConsoleCommandResult, LegacyRescuePreparation
from tests.manager.test_legacy_containment import STARTED, legacy_fixture
from tests.web_console.test_legacy_rescue_acceptance import DELIVERY, TASK, _intent

SCHEMAS = Path(__file__).parents[2] / "schemas"


def validator(name: str, model: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / name).read_text())
    return Draft202012Validator(
        {"$defs": schema["$defs"], "$ref": f"#/$defs/{model}"}, format_checker=FormatChecker()
    )


@pytest.mark.parametrize(
    "name",
    [
        "console-operation.schema.json",
        "execution-baseline-plan.schema.json",
        "execution-baseline-queue-consumption.schema.json",
    ],
)
def test_published_containment_matches_both_real_methods_and_refuses_missing_survey(
    tmp_path: Path, name: str
) -> None:
    _, _, _, old = legacy_fixture(tmp_path)
    boot = old.boot.model_copy(update={"booted_at": STARTED - timedelta(days=1)})
    survey = LegacyLocalExecutionSurvey.create(
        worktree_path=str(tmp_path.resolve()),
        machine_sha256=boot.machine_sha256,
        boot_session_sha256=boot.boot_session_sha256,
        account_sha256="c" * 64,
        observed_at=datetime.now(UTC),
        scanner_version="local-execution-v1",
        blockers=(),
    )
    local = LegacyExecutionContainment.create(
        **old.model_dump(
            mode="python",
            exclude={"containment_sha256", "boot", "method", "local_execution_survey"},
        ),
        method="operator_confirmed_local_stop",
        boot=boot,
        local_execution_survey=survey,
    )
    check = validator(name, "LegacyExecutionContainment")
    assert check.is_valid(old.to_wire())
    assert check.is_valid(local.to_wire())
    missing = local.to_wire()
    missing.pop("local_execution_survey")
    assert not check.is_valid(missing)
    null_survey = {**local.to_wire(), "local_execution_survey": None}
    assert not check.is_valid(null_survey)
    wrong_method = {**local.to_wire(), "method": "os_reboot"}
    assert not check.is_valid(wrong_method)
    active = local.to_wire()
    active_survey = cast(dict[str, object], active["local_execution_survey"])
    active_survey["blockers"] = ["CODEX_EXECUTION_ACTIVE"]
    assert not check.is_valid(active)


def test_static_console_confirmation_fields_are_exclusive_and_only_true() -> None:
    check = validator("console-operation.schema.json", "ExecuteExecutionBaselineIntent")
    reboot = _intent("EXECUTE_EXECUTION_BASELINE")
    local = {**reboot, "confirm_local_execution_stopped": True}
    local.pop("confirm_legacy_containment")
    assert check.is_valid(reboot)
    assert check.is_valid(local)
    assert not check.is_valid({**reboot, "confirm_local_execution_stopped": True})
    for invalid in (False, "true"):
        assert not check.is_valid({**local, "confirm_local_execution_stopped": invalid})


def test_waiting_preparation_cannot_be_an_approval_binding_or_unbound_result() -> None:
    result = ConsoleCommandResult(
        project_id="project_test",
        delivery_id=DELIVERY,
        checkpoint_sha256="a" * 64,
        stage="WAITING_HUMAN",
        next_action="重新检查恢复前提",
        legacy_rescue_preparation=LegacyRescuePreparation(
            status="WAITING",
            task_id=TASK,
            work_item_id="work_original_unknown",
            source_revision="3" * 40,
            code="LEGACY_LOCAL_EXECUTION_ACTIVE",
            summary="本机执行尚未结束。",
            next_action="等待原调用及派生工具结束后再检查。",
            responsible_party="平台执行服务",
        ),
    )
    check = validator("console-operation.schema.json", "ConsoleCommandResult")
    assert check.is_valid(result.to_wire())
    ready_without_plan = result.to_wire()
    ready_preparation = cast(dict[str, object], ready_without_plan["legacy_rescue_preparation"])
    ready_preparation["status"] = "READY"
    with pytest.raises(ValidationError):
        ConsoleCommandResult.model_validate(ready_without_plan)
    assert not check.is_valid(ready_without_plan)
    for field in ("delivery_id", "checkpoint_sha256"):
        assert not check.is_valid({**result.to_wire(), field: None})
    schema = json.loads((SCHEMAS / "console-operation.schema.json").read_text())
    gates = schema["$defs"]["ConsoleCommandResult"]["allOf"]
    assert (
        sum(gate.get("if", {}).get("required") == ["legacy_rescue_preparation"] for gate in gates)
        == 1
    )
