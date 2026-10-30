"""A wrong retirement catalog scope needs an explicit, evidenced local decision."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import maintenance_completion as completion
from ai_software_engineer.web_console.fault_retirement import (
    FaultRetirementError,
    _archive_root,
    execute_fault_retirement,
    inspection_required,
    prepare_fault_retirement,
)
from ai_software_engineer.web_console.maintenance_scope_correction import (
    MaintenanceScopeCorrection,
    MaintenanceScopeCorrectionError,
    MaintenanceScopeCorrectionPlan,
    execute_scope_correction,
    prepare_scope_correction,
)
from ai_software_engineer.web_console.models import ContinueDeliveryIntent
from ai_software_engineer.web_console.service_lifecycle import (
    ServiceInstance,
    ServiceLifecycleStore,
)
from ai_software_engineer.web_console.store import FileConsoleOperationStore
from tests.web_console.test_fault_retirement import _execute, _host
from tests.web_console.test_maintenance_completion import _inventory, _stopped_successor

_PROJECT = "project_scope_abcdefgh1234"
_DELIVERY = "delivery_scope_abcdefgh1234"
_REFERENCE = "human-action-k1-scope-20261030"


def _target(tmp_path: Path, old_config: Path, operation_id: str | None = None) -> tuple[Path, str]:
    platform = tmp_path / "target-platform"
    team = TeamWorkspace.initialize(platform, team_id="team_ai", name="AI Team")
    project = ProjectWorkspaceRegistry(team).register(project_id=_PROJECT, name="Scope project")
    (project.requirements_root / _DELIVERY).mkdir()
    store = FileConsoleOperationStore(
        team.directory("work-items") / "console-operations", team_id=team.manifest.team_id
    )
    queued = store.submit(
        intent=ContinueDeliveryIntent(
            project_id=_PROJECT,
            delivery_id=_DELIVERY,
            expected_checkpoint_sha256="a" * 64,
        ),
        idempotency_key="scope-correction-test",
        requested_at=datetime.now(UTC),
    )
    claimed = store.claim_next(at=datetime.now(UTC))
    assert claimed is not None and claimed.operation_id == queued.operation_id
    store.fail(
        claimed.operation_id,
        expected=claimed.operation_sha256,
        error_code="MANAGER_FAILURE",
        error_summary="stored failure",
        at=datetime.now(UTC),
    )
    if operation_id is not None:
        assert queued.operation_id == operation_id
    data = json.loads(old_config.read_text())
    data["platform_root"] = str(platform)
    target_config = tmp_path / "target-config.json"
    target_config.write_text(json.dumps(data))
    return target_config, queued.operation_id


def _admit_previous_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    with _host(tmp_path) as (env, _):
        target_config, operation_id = _target(tmp_path, Path(env["ASE_CONFIG"]))
        env["ASE_CONFIG"] = str(target_config)
        retirement = prepare_fault_retirement(env)
        _execute(env, retirement.record_sha256)
        _stopped_successor(env)
        monkeypatch.setattr(completion, "observe_maintenance_queue", lambda *_: _inventory())
        plan = completion.prepare_maintenance_completion(env)
        completion.complete_maintenance(
            env, plan_sha256=plan.record_sha256, confirm_restore_normal=True
        )
        completion.admit_completed_maintenance(env)
    return target_config, operation_id


def test_wrong_catalog_scope_requires_exact_evidenced_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_config, operation_id = _admit_previous_target(tmp_path, monkeypatch)
    with _host(tmp_path) as (env, _):
        old_config = Path(env["ASE_CONFIG"])
        old_platform = json.loads(old_config.read_text())["platform_root"]
        TeamWorkspace.initialize(old_platform, team_id="team_ai", name="AI Team")
        root = Path(env["ASE_SERVICE_STATE_DIR"])
        (root / "ase-console.log").write_text(
            f"Console operation {operation_id} failed with OwnedProcessesUncertain\n"
        )
        retirement = prepare_fault_retirement(env)
        assert retirement.previous_maintenance is not None
        _execute(env, retirement.record_sha256)
        archive = _archive_root(root, retirement.record_sha256)
        original = {
            name: (archive / name).read_bytes()
            for name in ("plan.json", "receipt.json", "ase-console.log")
        }
        env["ASE_CONFIG"] = str(target_config)
        _stopped_successor(env)
        monkeypatch.setattr(completion, "observe_maintenance_queue", lambda *_: _inventory())
        with pytest.raises(completion.MaintenanceCompletionError):
            completion.prepare_maintenance_completion(env)
        proposal = prepare_scope_correction(
            env, operation_id=operation_id, authority_reference=_REFERENCE
        )
        assert (
            prepare_scope_correction(env, operation_id=operation_id, authority_reference=_REFERENCE)
            == proposal
        )
        assert proposal.assessment == "EVIDENCE_BASED_RUNTIME_SCOPE"
        assert proposal.target_platform_root != proposal.observed_catalog_root
        env["ASE_CONFIG"] = str(old_config)
        with pytest.raises(MaintenanceScopeCorrectionError):
            completion.prepare_maintenance_completion(env)
        env["ASE_CONFIG"] = str(target_config)
        with pytest.raises(MaintenanceScopeCorrectionError):
            execute_scope_correction(
                env, plan_sha256=proposal.record_sha256, confirm_scope_correction=False
            )
        decision = execute_scope_correction(
            env, plan_sha256=proposal.record_sha256, confirm_scope_correction=True
        )
        assert (
            execute_scope_correction(
                env, plan_sha256=proposal.record_sha256, confirm_scope_correction=True
            )
            == decision
        )
        log_path = archive / "ase-console.log"
        log_path.write_bytes(b"changed after correction")
        with pytest.raises(MaintenanceScopeCorrectionError):
            completion.prepare_maintenance_completion(env)
        log_path.write_bytes(original["ase-console.log"])
        plan = completion.prepare_maintenance_completion(env)
        assert plan.scope_correction_sha256 == decision.record_sha256
        completion.complete_maintenance(
            env, plan_sha256=plan.record_sha256, confirm_restore_normal=True
        )
        completion.admit_completed_maintenance(env)
        assert not inspection_required(env)
        env["ASE_CONFIG"] = str(old_config)
        with pytest.raises(completion.MaintenanceCompletionError):
            completion.admit_completed_maintenance(env)
        env["ASE_CONFIG"] = str(target_config)
        completion.admit_completed_maintenance(env)
        for name, body in original.items():
            assert (archive / name).read_bytes() == body
        assert (root / "console-inspection.json").exists()
        with pytest.raises(MaintenanceScopeCorrectionError):
            prepare_scope_correction(env, operation_id=operation_id, authority_reference=_REFERENCE)
    # A later retirement must validate the archived corrected predecessor,
    # including its moved completion records and still immutable decision.
    with _host(tmp_path) as (third_env, _):
        third_env["ASE_CONFIG"] = str(target_config)
        third = prepare_fault_retirement(third_env)
        assert third.previous_maintenance is not None
        _execute(third_env, third.record_sha256)
        assert inspection_required(third_env)


def test_correction_rejects_missing_log_witness_and_wrong_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_config, operation_id = _admit_previous_target(tmp_path, monkeypatch)
    with _host(tmp_path) as (env, _):
        old_config = Path(env["ASE_CONFIG"])
        TeamWorkspace.initialize(
            json.loads(old_config.read_text())["platform_root"],
            team_id="team_ai",
            name="AI Team",
        )
        retirement = prepare_fault_retirement(env)
        _execute(env, retirement.record_sha256)
        env["ASE_CONFIG"] = str(target_config)
        with pytest.raises(MaintenanceScopeCorrectionError):
            prepare_scope_correction(env, operation_id=operation_id, authority_reference=_REFERENCE)
        assert inspection_required(env)


def test_new_host_bound_config_refuses_foreign_retirement_before_plan(tmp_path: Path) -> None:
    with _host(tmp_path) as (env, _):
        config_path = Path(env["ASE_CONFIG"])
        body = config_path.read_bytes()
        platform_root = json.loads(body)["platform_root"]
        store = ServiceLifecycleStore.from_environment(env)
        original = store.read_instance()
        assert original is not None
        bound = ServiceInstance.model_validate(
            {
                **original.model_dump(),
                "config_path": str(config_path),
                "platform_root": platform_root,
                "config_sha256": hashlib.sha256(body).hexdigest(),
            }
        )
        store.publish_instance(bound)
        foreign = tmp_path / "foreign-config.json"
        foreign.write_text(
            json.dumps({**json.loads(body), "platform_root": str(tmp_path / "foreign")})
        )
        with pytest.raises(FaultRetirementError):
            prepare_fault_retirement({**env, "ASE_CONFIG": str(foreign)})
        assert not (Path(env["ASE_SERVICE_STATE_DIR"]) / "console-fault-retirements").exists()
        plan = prepare_fault_retirement(env)
        assert plan.instance.config_sha256 == hashlib.sha256(body).hexdigest()
        copied = tmp_path / "copied-config.json"
        copied.write_bytes(body)
        with pytest.raises(FaultRetirementError):
            execute_fault_retirement(
                {**env, "ASE_CONFIG": str(copied)},
                plan_sha256=plan.record_sha256,
                confirm_fault_retirement=True,
            )


@pytest.mark.parametrize(
    "name,model",
    (
        ("console-maintenance-scope-correction-plan", MaintenanceScopeCorrectionPlan),
        ("console-maintenance-scope-correction", MaintenanceScopeCorrection),
    ),
)
def test_scope_correction_schema_parity(name: str, model: type) -> None:
    schema = json.loads((Path(__file__).parents[2] / "schemas" / f"{name}.schema.json").read_text())
    assert schema.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert schema.pop("$id").endswith(f"/{name}.schema.json")
    assert schema == model.model_json_schema()
