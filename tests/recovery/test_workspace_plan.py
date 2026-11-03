"""Exact plan binding and legacy compatibility for terminal workspace audits."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.git.mutation import MutationFile, WorkspaceMutationInventory
from ai_software_engineer.recovery import RecoveryPlan
from ai_software_engineer.recovery.models import CapturedChanges, InheritedReapplyInput
from ai_software_engineer.recovery.workspace_records import (
    RecoveryExcludedPath,
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


def test_terminal_snapshot_static_schema_matches_generated_contract() -> None:
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/delivery-recovery.schema.json").read_text()
    )
    generated = RecoveryPlan.model_json_schema()
    assert (
        schema["$defs"]["RecoveryWorkspaceSnapshot"]
        == generated["$defs"]["RecoveryWorkspaceSnapshot"]
    )
    assert schema["$defs"]["RecoveryPlan"]["allOf"][-2:] == generated["allOf"][-2:]


def test_synchronous_refusal_snapshot_requires_its_own_exact_completion_proof(
    tmp_path: Path,
) -> None:
    old = make_plan(tmp_path / "project")
    native = snapshot_for(old)
    synchronous = RecoveryWorkspaceSnapshot.create(
        **{
            **native.to_wire(),
            "schema_version": "v2",
            "completion_kind": "responses_tool_refusal",
            "capture_stop_sha256": None,
            "synchronous_completion_sha256": "8" * 64,
        }
    )
    plan = RecoveryPlan.create(**{**old.to_wire(), "workspace_snapshot": synchronous})
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/delivery-recovery.schema.json").read_text()
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(plan.to_wire())
    assert RecoveryPlan.model_validate(plan.to_wire()) == plan
    for missing in ("completion_kind", "synchronous_completion_sha256"):
        changed = plan.to_wire()
        changed["workspace_snapshot"].pop(missing)
        assert list(validator.iter_errors(changed))
    with pytest.raises(ValidationError):
        RecoveryWorkspaceSnapshot.create(
            **{
                **native.to_wire(),
                "schema_version": "v2",
                "completion_kind": "responses_tool_refusal",
                "synchronous_completion_sha256": "8" * 64,
            }
        )


def test_synchronous_refusal_with_inherited_patch_requires_coder_reapply(
    tmp_path: Path,
) -> None:
    old = make_plan(tmp_path / "project")
    native = snapshot_for(old)
    snapshot = RecoveryWorkspaceSnapshot.create(
        **{
            **native.to_wire(),
            "schema_version": "v2",
            "completion_kind": "responses_tool_refusal",
            "capture_stop_sha256": None,
            "synchronous_completion_sha256": "8" * 64,
        }
    )
    origin_sha = "e" * 64
    patch_sha = hashlib.sha256(b"").hexdigest()
    inherited = InheritedReapplyInput(
        origin_plan_sha256=origin_sha,
        origin_task_id="task_recovery_" + origin_sha[:32],
        origin_context_manifest_id="ctx_" + "d" * 64,
        patch_uri=f"recovery://{origin_sha}/patch/{patch_sha}",
        patch_sha256=patch_sha,
        patch_bytes=0,
        patch="",
    )
    values = {
        **old.to_wire(),
        "workspace_snapshot": snapshot,
        "inherited_reapply_inputs": (inherited,),
    }
    with pytest.raises(ValidationError, match="coder_reapply"):
        RecoveryPlan.create(**values)
    plan = RecoveryPlan.create(**{**values, "input_mode": "coder_reapply"})
    assert plan.inherited_reapply_inputs == (inherited,)
    assert plan.input_mode == "coder_reapply"


def test_responses_workspace_failure_requires_reapply_even_without_inheritance(
    tmp_path: Path,
) -> None:
    old = make_plan(tmp_path / "project")
    capture = CapturedChanges.from_capture(
        replace(
            old.capture.to_capture(),
            patch=b"diff --git a/src/example.py b/src/example.py\n",
            file_sha256s=(("src/example.py", "b" * 64),),
        )
    )
    native = snapshot_for(old)
    inventory = WorkspaceMutationInventory(files=())
    excluded = RecoveryExcludedPath(
        path=".venv/pyvenv.cfg", kind="file", sha256="a" * 64, mode=0o644, size=8
    )
    with pytest.raises(ValidationError):
        RecoveryWorkspaceSnapshot.create(
            **{
                **native.to_wire(),
                "schema_version": "v3",
                "completion_kind": "responses_workspace_policy_failure",
                "capture_stop_sha256": None,
                "synchronous_completion_sha256": "8" * 64,
                "inventory_after": inventory,
                "excluded_paths": (excluded,),
            }
        )
    file = MutationFile(
        path=excluded.path,
        kind="file",
        sha256=excluded.sha256,
        mode=excluded.mode,
        size=excluded.size,
    )
    inventory = WorkspaceMutationInventory(files=(file,))
    snapshot = RecoveryWorkspaceSnapshot.create(
        **{
            **native.to_wire(),
            "schema_version": "v3",
            "completion_kind": "responses_workspace_policy_failure",
            "capture_stop_sha256": None,
            "synchronous_completion_sha256": "8" * 64,
            "capture_sha256": capture.capture_sha256,
            "inventory_after": inventory,
            "inventory_after_sha256": inventory.sha256,
            "excluded_paths": (excluded,),
        }
    )
    with pytest.raises(ValidationError, match="reapply"):
        RecoveryPlan.create(**{**old.to_wire(), "capture": capture, "workspace_snapshot": snapshot})
    plan = RecoveryPlan.create(
        **{
            **old.to_wire(),
            "capture": capture,
            "workspace_snapshot": snapshot,
            "input_mode": "coder_reapply",
        }
    )
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/delivery-recovery.schema.json").read_text()
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(plan.to_wire())
    assert RecoveryPlan.model_validate(plan.to_wire()) == plan
    missing_mode = plan.to_wire()
    missing_mode.pop("input_mode")
    assert list(validator.iter_errors(missing_mode))


def test_responses_path_refusal_with_prior_draft_requires_reapply_and_exact_schema(
    tmp_path: Path,
) -> None:
    old = make_plan(tmp_path / "project")
    capture = CapturedChanges.from_capture(
        replace(
            old.capture.to_capture(),
            patch=b"diff --git a/src/example.py b/src/example.py\n",
            file_sha256s=(("src/example.py", "b" * 64),),
        )
    )
    inventory = WorkspaceMutationInventory(
        files=(
            MutationFile(path="src/example.py", kind="file", sha256="b" * 64, mode=0o644, size=1),
        )
    )
    native = snapshot_for(old)
    snapshot = RecoveryWorkspaceSnapshot.create(
        **{
            **native.to_wire(),
            "schema_version": "v4",
            "completion_kind": "responses_write_path_refusal",
            "capture_stop_sha256": None,
            "synchronous_completion_sha256": "8" * 64,
            "capture_sha256": capture.capture_sha256,
            "inventory_before_sha256": inventory.sha256,
            "inventory_after": inventory,
            "inventory_after_sha256": inventory.sha256,
        }
    )
    with pytest.raises(ValidationError, match="reapply"):
        RecoveryPlan.create(**{**old.to_wire(), "capture": capture, "workspace_snapshot": snapshot})
    plan = RecoveryPlan.create(
        **{
            **old.to_wire(),
            "capture": capture,
            "workspace_snapshot": snapshot,
            "input_mode": "coder_reapply",
        }
    )
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/delivery-recovery.schema.json").read_text()
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert not list(validator.iter_errors(plan.to_wire()))
    missing_mode = plan.to_wire()
    missing_mode.pop("input_mode")
    assert list(validator.iter_errors(missing_mode))
    wrong_proof = plan.to_wire()
    wrong_proof["workspace_snapshot"]["excluded_paths"] = [
        {"path": ".venv/pyvenv.cfg", "kind": "file", "sha256": "a" * 64, "mode": 420, "size": 1}
    ]
    assert list(validator.iter_errors(wrong_proof))


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
