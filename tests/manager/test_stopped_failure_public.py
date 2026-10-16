"""A real failed native invocation retries only after exact human PAUSE/RESUME."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain.execution_baseline import BaselineInputMode, BaselinePurpose
from ai_software_engineer.manager.baseline_production import BaselineProposeCommand
from tests.manager import test_production_execution_baseline as public_baseline
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn


def test_stopped_failure_public_command_is_same_base_preserve_only() -> None:
    wire = {
        "purpose": "stopped_failure_retry",
        "delivery_id": "delivery_stopped_failure",
        "task_id": "task_stopped_failure",
        "expected_task_intent_sha256": "a" * 64,
        "expected_task_revision": 2,
        "expected_work_item_id": "work_stopped_failure",
        "expected_source_revision": "b" * 40,
    }
    command = BaselineProposeCommand.model_validate(wire)
    assert command.purpose is BaselinePurpose.STOPPED_FAILURE_RETRY
    assert command.input_mode is BaselineInputMode.PRESERVE_DRAFT
    assert command.target_base_ref is None and "target_base_ref" not in command.to_wire()
    for change in ({"target_base_ref": "c" * 40}, {"input_mode": "coder_reapply"}):
        with pytest.raises(ValidationError):
            BaselineProposeCommand.model_validate({**wire, **change})


@pytest.mark.mysql
def test_public_stopped_failure_pause_resume_preserves_history_and_completes(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    public_baseline.test_public_baseline_updates_original_workspace_then_completes_independent_delivery(
        tmp_path,
        mysql_dsn,
        monkeypatch,
        mode=BaselineInputMode.PRESERVE_DRAFT,
        reject_after_baseline=False,
        native_pause=False,
        capture_pending=True,
        completed_output=False,
        same_base=True,
        unknown_failure=True,
        stopped_failure_retry=True,
        work_limit=3,
    )
