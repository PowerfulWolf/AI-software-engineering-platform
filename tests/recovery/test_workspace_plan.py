"""Exact plan binding and legacy compatibility for terminal workspace audits."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.git.mutation import WorkspaceMutationInventory
from ai_software_engineer.recovery import RecoveryPlan
from ai_software_engineer.recovery.workspace_records import (
    RecoveryWorkspaceScope,
    RecoveryWorkspaceSnapshot,
)
from tests.recovery.test_authorization import NOW, make_plan


def snapshot_for(plan: RecoveryPlan) -> RecoveryWorkspaceSnapshot:
    source = plan.source
    inventory = WorkspaceMutationInventory(files=())
    return RecoveryWorkspaceSnapshot.create(
        scope=RecoveryWorkspaceScope(
            team_id=source.scope.team_id,
            project_id="project_test",
            repository_id=source.scope.repository_id,
            requirement_id=source.scope.delivery_id,
            dispatch_sha256=source.dispatch_sha256,
        ),
        task_id=source.task_id,
        task_revision=source.task_revision,
        task_sha256=source.task_sha256,
        task_intent_sha256="d" * 64,
        run_id=source.failed_run_id,
        context_manifest_id=source.failed_context_id,
        worktree_path=plan.capture.worktree_path,
        source_revision=plan.capture.source_revision,
        effective_capture_base=source.effective_base_revision,
        execution_baseline_sha256=source.execution_baseline_sha256,
        capture_sha256=plan.capture.capture_sha256,
        capture_start_sha256="1" * 64,
        capture_stop_sha256="2" * 64,
        invocation_start_sha256="3" * 64,
        invocation_outcome_sha256="4" * 64,
        claim_sha256="5" * 64,
        step_sha256="6" * 64,
        routes_sha256="7" * 64,
        inventory_before_sha256=inventory.sha256,
        inventory_after=inventory,
        inventory_after_sha256=inventory.sha256,
        excluded_paths=(),
        stopped_at=NOW,
        blocked_at=NOW,
        created_at=NOW,
    )


def test_terminal_snapshot_binds_exact_plan_and_schema(tmp_path: Path) -> None:
    old = make_plan(tmp_path / "project")
    snapshot = snapshot_for(old)
    plan = RecoveryPlan.create(**{**old.to_wire(), "workspace_snapshot": snapshot})
    plan.validate_integrity()
    assert plan.workspace_snapshot == snapshot
    assert plan.plan_sha256 != old.plan_sha256
    assert plan.new_task_id != old.new_task_id
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/delivery-recovery.schema.json").read_text()
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(plan.to_wire())
    assert RecoveryPlan.model_validate(plan.to_wire()) == plan


def test_absent_snapshot_preserves_historical_plan_bytes_and_digest(tmp_path: Path) -> None:
    old = make_plan(tmp_path / "project")
    wire = old.to_wire()
    assert "workspace_snapshot" not in wire
    restored = RecoveryPlan.model_validate({**wire, "workspace_snapshot": None})
    assert restored.to_wire() == wire
    assert restored.recompute_sha256() == old.plan_sha256


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "task_other"),
        ("task_revision", 4),
        ("task_sha256", "f" * 64),
        ("run_id", "run_other"),
        ("context_manifest_id", "ctx_" + "f" * 64),
        ("worktree_path", "/other/coder"),
        ("source_revision", "d" * 40),
        ("effective_capture_base", "e" * 40),
        ("execution_baseline_sha256", "f" * 64),
        ("capture_sha256", "f" * 64),
    ],
)
def test_snapshot_from_other_execution_cannot_authorize_plan(
    tmp_path: Path, field: str, value: object
) -> None:
    old = make_plan(tmp_path / "project")
    snapshot = snapshot_for(old)
    changed = RecoveryWorkspaceSnapshot.create(**{**snapshot.to_wire(), field: value})
    with pytest.raises(ValidationError, match="workspace snapshot"):
        RecoveryPlan.create(**{**old.to_wire(), "workspace_snapshot": changed})


@pytest.mark.parametrize(
    "field,value",
    [
        ("team_id", "team_other"),
        ("repository_id", "repository_other"),
        ("requirement_id", "delivery_other"),
        ("dispatch_sha256", "f" * 64),
    ],
)
def test_snapshot_scope_must_match_original_delivery(
    tmp_path: Path, field: str, value: str
) -> None:
    old = make_plan(tmp_path / "project")
    snapshot = snapshot_for(old)
    scope = RecoveryWorkspaceScope.model_validate({**snapshot.scope.to_wire(), field: value})
    changed = RecoveryWorkspaceSnapshot.create(**{**snapshot.to_wire(), "scope": scope})
    with pytest.raises(ValidationError, match="workspace snapshot"):
        RecoveryPlan.create(**{**old.to_wire(), "workspace_snapshot": changed})


def test_tampered_snapshot_digest_is_rejected_before_plan_approval(tmp_path: Path) -> None:
    old = make_plan(tmp_path / "project")
    snapshot = snapshot_for(old).model_copy(update={"snapshot_sha256": "f" * 64})
    with pytest.raises(ValidationError, match="workspace snapshot"):
        RecoveryPlan.create(**{**old.to_wire(), "workspace_snapshot": snapshot})
