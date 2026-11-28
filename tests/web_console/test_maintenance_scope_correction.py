"""A wrong retirement catalog scope needs an explicit, evidenced local decision."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import maintenance_completion as completion
from ai_software_engineer.web_console.fault_retirement import (
    prepare_fault_retirement,
)
from ai_software_engineer.web_console.maintenance_scope_correction import (
    MaintenanceScopeCorrection,
    MaintenanceScopeCorrectionPlan,
)
from ai_software_engineer.web_console.models import ContinueDeliveryIntent
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
