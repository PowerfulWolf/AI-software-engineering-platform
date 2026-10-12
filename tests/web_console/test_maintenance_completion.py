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
    inspection_required,
    prepare_fault_retirement,
)
from ai_software_engineer.web_console.maintenance_names import (
    COMPLETION_RECEIPT_NAME as RECEIPT_NAME,
)
from ai_software_engineer.web_console.maintenance_names import (
    NORMAL_ADMISSION_NAME as ADMISSION_NAME,
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


def test_complete_preserves_archive_and_rechecks_before_first_normal_writer(
    maintained: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env = maintained
    root = Path(env["ASE_SERVICE_STATE_DIR"])
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    plan = module.prepare_maintenance_completion(env)
    assert inspection_required(env)
    assert plan.inventory.waiting_work_item_count == 1
    receipt = _complete(env, plan.record_sha256)
    assert _complete(env, plan.record_sha256) == receipt
    assert not inspection_required(env)
    monkeypatch.setattr(
        module,
        "observe_maintenance_queue",
        lambda *args: _inventory(blocked_work_item_ids=("work_aaa",)),
    )
    with pytest.raises(module.MaintenanceCompletionError, match="队列"):
        module.admit_completed_maintenance(env)
    assert not (root / ADMISSION_NAME).exists()
    monkeypatch.setattr(module, "observe_maintenance_queue", lambda *args: _inventory())
    module.admit_completed_maintenance(env)
    assert (root / ADMISSION_NAME).exists()
    # Ordinary restarts can now contain newly authorized work; maintenance is not
    # an eternal idle-queue requirement. Explicit inspection still stays readonly.
    monkeypatch.setattr(
        module, "observe_maintenance_queue", lambda *args: pytest.fail("rechecked retired plan")
    )
    module.admit_completed_maintenance(env)
    assert not inspection_required(env)
    for name, body in before.items():
        assert (root / name).read_bytes() == body


@pytest.mark.parametrize(
    "field,value",
    [
        ("blocked_operation_ids", ("operation_" + "1" * 32,)),
        ("blocked_work_item_ids", ("work_aaa",)),
        ("active_lease_ids", ("lease_aaa",)),
    ],
)
def test_pending_queue_refuses_without_release(
    maintained: dict[str, str], monkeypatch: pytest.MonkeyPatch, field: str, value: tuple[str, ...]
) -> None:
    monkeypatch.setattr(
        module, "observe_maintenance_queue", lambda *args: _inventory(**{field: value})
    )
    with pytest.raises(module.MaintenanceCompletionError, match="队列"):
        module.prepare_maintenance_completion(maintained)
    assert inspection_required(maintained)


@pytest.mark.parametrize("change", ["config", "queue", "instance", "archive"])
def test_exact_plan_drift_refuses(
    maintained: dict[str, str], monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    plan = module.prepare_maintenance_completion(maintained)
    root = Path(maintained["ASE_SERVICE_STATE_DIR"])
    if change == "config":
        config = Path(maintained["ASE_CONFIG"])
        config.write_bytes(config.read_bytes() + b"\n")
    elif change == "queue":
        monkeypatch.setattr(
            module, "observe_maintenance_queue", lambda *args: _inventory(inventory_sha256="c" * 64)
        )
    elif change == "instance":
        _stopped_successor(maintained)
    else:
        log = next((root / "console-fault-retirements").glob("*/ase-console.log"))
        log.write_bytes(b"tampered")
    with pytest.raises((module.MaintenanceCompletionError, RuntimeError, ValueError)):
        _complete(maintained, plan.record_sha256)
    assert not (root / RECEIPT_NAME).exists()


def test_confirmation_live_pid_and_old_refusal_cannot_release(maintained: dict[str, str]) -> None:
    plan = module.prepare_maintenance_completion(maintained)
    with pytest.raises(module.MaintenanceCompletionError, match="确认"):
        module.complete_maintenance(
            maintained, plan_sha256=plan.record_sha256, confirm_restore_normal=False
        )
    with pytest.raises(module.MaintenanceCompletionError):
        _complete(maintained, "../elsewhere")
    store = ServiceLifecycleStore.from_environment(maintained)
    instance = ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC))
    request = ServiceShutdownRequest.new(instance, at=datetime.now(UTC))
    at = datetime.now(UTC)
    store.publish_instance(instance.with_state(ServiceState.READY, at=at))
    store.write_request(request)
    store.write_result(ServiceShutdownResult.for_request(request, state=ServiceState.READY, at=at))
    with pytest.raises(module.MaintenanceCompletionError, match="退出"):
        module.prepare_maintenance_completion(maintained)
    assert inspection_required(maintained)


def test_completion_publication_retry_and_damaged_receipt_fail_closed(
    maintained: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = module.prepare_maintenance_completion(maintained)
    from ai_software_engineer.web_console.fault_retirement import _save

    save = _save

    def fail(root: Path, name: str, record: _Record) -> None:
        if name == RECEIPT_NAME:
            raise OSError("injected")
        save(root, name, record)

    monkeypatch.setattr(module, "_save", fail)
    with pytest.raises((OSError, module.MaintenanceCompletionError)):
        _complete(maintained, plan.record_sha256)
    assert inspection_required(maintained)
    monkeypatch.setattr(module, "_save", save)
    _complete(maintained, plan.record_sha256)
    root = Path(maintained["ASE_SERVICE_STATE_DIR"])
    (root / RECEIPT_NAME).write_text("{}")
    with pytest.raises((RuntimeError, ValueError)):
        inspection_required(maintained)


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
    assert schema == model.model_json_schema()


def test_completed_but_not_started_can_reprepare_without_erasing_history(
    maintained: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(maintained["ASE_SERVICE_STATE_DIR"])
    first = module.prepare_maintenance_completion(maintained)
    old_receipt = _complete(maintained, first.record_sha256)
    anchor = (root / RECEIPT_NAME).read_bytes()
    monkeypatch.setattr(
        module, "observe_maintenance_queue", lambda *args: _inventory(inventory_sha256="c" * 64)
    )
    with pytest.raises(module.MaintenanceCompletionError, match="过期"):
        module.admit_completed_maintenance(maintained)
    second = module.prepare_maintenance_completion(maintained)
    new_receipt = _complete(maintained, second.record_sha256)
    assert new_receipt.supersedes_receipt_sha256 == old_receipt.record_sha256
    assert (root / RECEIPT_NAME).read_bytes() == anchor
    assert module.verified_completion(root) == (second, new_receipt)
    module.admit_completed_maintenance(maintained)
    assert not inspection_required(maintained)


def test_production_gate_refuses_before_normal_writer_and_admits_after_fresh_check(
    maintained: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.web_console import host

    plan = module.prepare_maintenance_completion(maintained)
    _complete(maintained, plan.record_sha256)
    called = []

    def writer(**kwargs: object) -> None:
        called.append(True)
        raise AssertionError("normal composition reached")

    monkeypatch.setattr(host, "TeamHost", writer)
    environment = {**maintained, "ASE_MYSQL_DSN": "fixture"}
    monkeypatch.setattr(
        module,
        "observe_maintenance_queue",
        lambda *args: _inventory(blocked_work_item_ids=("work_aaa",)),
    )
    with pytest.raises(module.MaintenanceCompletionError, match="队列"):
        host.production_console_app(environment)
    assert called == []
    monkeypatch.setattr(module, "observe_maintenance_queue", lambda *args: _inventory())
    with pytest.raises(AssertionError, match="normal composition reached"):
        host.production_console_app(environment)
    assert called == [True]


@pytest.mark.parametrize("drift", [False, True])
def test_partial_anchor_then_reprepare_retains_one_complete_confirmation_chain(
    maintained: dict[str, str], monkeypatch: pytest.MonkeyPatch, drift: bool
) -> None:
    from ai_software_engineer.web_console.fault_retirement import _save

    first = module.prepare_maintenance_completion(maintained)

    def fail(root: Path, name: str, record: _Record) -> None:
        if name == RECEIPT_NAME:
            raise OSError("anchor publication interrupted")
        _save(root, name, record)

    monkeypatch.setattr(module, "_save", fail)
    with pytest.raises(OSError):
        _complete(maintained, first.record_sha256)
    assert inspection_required(maintained)
    monkeypatch.setattr(module, "_save", _save)
    if drift:
        monkeypatch.setattr(
            module, "observe_maintenance_queue", lambda *args: _inventory(inventory_sha256="c" * 64)
        )
    second = module.prepare_maintenance_completion(maintained)
    root = Path(maintained["ASE_SERVICE_STATE_DIR"])
    anchor = module.MaintenanceCompletionReceipt.model_validate_json(
        (root / RECEIPT_NAME).read_bytes()
    )
    assert anchor.plan_sha256 == first.record_sha256
    receipt = _complete(maintained, second.record_sha256)
    assert receipt.supersedes_receipt_sha256 == anchor.record_sha256
    module.admit_completed_maintenance(maintained)
    assert module.verified_completion(root) == (second, receipt)
