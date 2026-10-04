"""Historical rule edits remain auditable without becoming new execution grants."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.domain import AgentPermissions, AgentRole
from ai_software_engineer.git import (
    GitWorktreeManager,
    PathPolicyViolation,
    WorktreeCaptureRejected,
    WorktreeRef,
    WorktreeSeedRejected,
    WorktreeSpec,
)
from ai_software_engineer.manager.production_backend import _delivery_role_permissions
from ai_software_engineer.recovery import CapturedChanges, RecoveryPlan, RecoveryRejected
from ai_software_engineer.recovery.context import recovery_context_sources
from tests.git.test_capture import git
from tests.git.test_capture import workspace as workspace
from tests.recovery.test_authorization import make_plan


def _quarantine_plan(tmp_path: Path) -> RecoveryPlan:
    old = make_plan(tmp_path / "project")
    path = ".trellis/spec/core/contracts.md"
    capture = replace(
        old.capture.to_capture(),
        patch=b"complete historical patch\n",
        file_sha256s=((path, hashlib.sha256(b"old rule edit").hexdigest()),),
    )
    source_permissions = old.permissions.model_copy(
        update={"read_paths": ("**",), "write_paths": ("src/**", path)}
    )
    return RecoveryPlan.create(
        **{
            **old.to_wire(),
            "capture": CapturedChanges.from_capture(capture),
            "input_mode": "coder_reapply",
            "quarantined_paths": (path,),
            "permissions": source_permissions,
            "target_permissions": source_permissions.model_copy(
                update={"write_paths": ("src/**",)}
            ),
        }
    )


def test_quarantine_is_hash_bound_complete_and_explicit(tmp_path: Path) -> None:
    plan = _quarantine_plan(tmp_path)
    plan.require_execution_supported()
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/delivery-recovery.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(plan.to_wire())
    assert plan.quarantined_paths == (".trellis/spec/core/contracts.md",)
    assert recovery_context_sources(plan)[1].content == plan.capture.patch
    assert "Do not reapply" in (recovery_context_sources(plan)[0].content or "")
    assert plan.quarantined_paths[0] in (recovery_context_sources(plan)[0].content or "")
    for changes in (
        {"input_mode": None},
        {"quarantined_paths": ()},
        {"quarantined_paths": ("src/other.py",)},
        {"target_permissions": plan.permissions},
    ):
        with pytest.raises(ValidationError):
            RecoveryPlan.create(**{**plan.to_wire(), **changes})
    # Historical unsafe plans stay readable/hash-verifiable, but are not runnable.
    historical = RecoveryPlan.create(**{**plan.to_wire(), "quarantined_paths": None})
    historical.validate_integrity()
    with pytest.raises(RecoveryRejected):
        historical.require_execution_supported()
    assert historical.plan_sha256 != plan.plan_sha256


def test_role_compiler_filters_explicit_trellis_paths_without_guessing_identity() -> None:
    intended = "src/learning_collection/audit.py"
    permissions = _delivery_role_permissions(
        AgentRole.CODER, (intended, ".trellis/spec/core/x.md", "docs/contracts.md"), ("pytest",)
    )
    assert permissions.write_paths == (intended, "docs/contracts.md")


def test_historical_capture_preserves_full_rules_patch_but_cannot_seed(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
) -> None:
    manager, ref, permissions = workspace
    path = ".trellis/spec/core/contracts.md"
    file = ref.path / path
    file.parent.mkdir(parents=True)
    file.write_text("historical rule edit\n")
    (ref.path / "src/app.py").write_text("VALUE = 2\n")
    permissions = permissions.model_copy(update={"read_paths": ("**",), "write_paths": ("**",)})
    before = git(ref.path, "status", "--porcelain")
    with pytest.raises(PathPolicyViolation):
        manager.capture_changes(ref, permissions)
    capture = manager.capture_legacy_changes(ref, permissions)
    assert capture.changed_paths == (path, "src/app.py")
    assert b"historical rule edit" in capture.patch
    manager.verify_legacy_capture(capture, permissions)
    assert git(ref.path, "status", "--porcelain") == before
    target = manager.create(
        WorktreeSpec(
            task_id="task_audit_target",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=ref.head_revision,
        )
    )
    with pytest.raises(WorktreeSeedRejected):
        manager.seed_changes(capture, target, permissions, permissions)
    assert git(target.path, "status", "--porcelain") == ""
    for restricted in (
        permissions.model_copy(update={"read_paths": ("src/**",)}),
        permissions.model_copy(update={"write_paths": ("src/**",)}),
    ):
        with pytest.raises(PathPolicyViolation):
            manager.capture_legacy_changes(ref, restricted)
    with pytest.raises(PathPolicyViolation):
        manager.capture_legacy_changes(ref, permissions, denied_paths=(".trellis/**",))
    file.write_text("changed after capture\n")
    with pytest.raises(WorktreeCaptureRejected, match="no longer matches"):
        manager.verify_legacy_capture(capture, permissions)
