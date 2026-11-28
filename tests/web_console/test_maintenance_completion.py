"""Maintenance release is independent of old outcomes and demand approval."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.web_console import maintenance_completion as module
from ai_software_engineer.web_console.fault_retirement import (
    _Record,
    prepare_fault_retirement,
)
from ai_software_engineer.web_console.maintenance_queue import MaintenanceQueueInventory
from ai_software_engineer.web_console.service_lifecycle import (
    ServiceInstance,
    ServiceLifecycleStore,
    ServiceShutdownRequest,
    ServiceShutdownResult,
    ServiceState,
)
from tests.web_console.test_fault_retirement import _execute, _host


def _stopped_successor(env: dict[str, str]) -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"], env={"PATH": os.defpath})
    now = datetime.now(UTC)
    instance = ServiceInstance.new(pid=child.pid, at=now)
    request = ServiceShutdownRequest.new(instance, at=now)
    at = datetime.now(UTC)
    store = ServiceLifecycleStore.from_environment(env)
    store.publish_instance(instance.with_state(ServiceState.READY, at=at))
    store.write_request(request)
    store.write_result(ServiceShutdownResult.for_request(request, state=ServiceState.READY, at=at))
    child.wait(timeout=5)


def _inventory(**values: object) -> MaintenanceQueueInventory:
    return MaintenanceQueueInventory.model_validate(
        {
            "inventory_sha256": "a" * 64,
            "team_manifest_sha256": "b" * 64,
            "operation_count": 287,
            "work_item_count": 97,
            "claim_count": 112,
            "waiting_work_item_count": 1,
            **values,
        }
    )


@pytest.fixture
def maintained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    with _host(tmp_path) as (env, _):
        plan = prepare_fault_retirement(env)
        _execute(env, plan.record_sha256)
        _stopped_successor(env)
        monkeypatch.setattr(
            module, "observe_maintenance_queue", lambda config, environment: _inventory()
        )
        yield env


def _complete(env: dict[str, str], digest: str) -> module.MaintenanceCompletionReceipt:
    return module.complete_maintenance(env, plan_sha256=digest, confirm_restore_normal=True)


@pytest.mark.parametrize(
    "name,model",
    [
        ("console-maintenance-completion-plan", module.MaintenanceCompletionPlan),
        ("console-maintenance-completion-receipt", module.MaintenanceCompletionReceipt),
        ("console-maintenance-admission", module.MaintenanceNormalAdmission),
    ],
)
def test_completion_schema_parity(name: str, model: type[_Record]) -> None:
    schema = json.loads((Path(__file__).parents[2] / "schemas" / f"{name}.schema.json").read_text())
    assert schema.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert schema.pop("$id").endswith(f"/{name}.schema.json")
    assert schema == model.model_json_schema()
