"""Explicit reapplication is approved input, never an implicit dirty-worktree fallback."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from ai_software_engineer.context import ContextBudget, ContextBudgetExceeded, FileContextBuilder
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.recovery import RecoveryAuthorization, RecoveryPlan, RecoveryRejected
from ai_software_engineer.recovery.context import recovery_context_sources, validate_reapply_context
from ai_software_engineer.recovery.models import CapturedChanges, digest
from ai_software_engineer.recovery.records import RecoverySeedRecord
from ai_software_engineer.recovery.store import FileRecoveryStore
from tests.recovery.test_authorization import Human, approval, make_plan
from tests.recovery.test_task_record import record_for


def test_mode_is_explicit_hash_bound_and_legacy_digest_unchanged(tmp_path: Path) -> None:
    old = make_plan(tmp_path / "project")
    wire = old.to_wire()
    assert "input_mode" not in wire
    assert old.recompute_sha256() == digest({k: v for k, v in wire.items() if k != "plan_sha256"})
    new = RecoveryPlan.create(**{**wire, "input_mode": "coder_reapply"})
    assert new.new_task_id != old.new_task_id
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/delivery-recovery.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(new.to_wire())
    with pytest.raises(RecoveryRejected):
        old.model_copy(update={"input_mode": "coder_reapply"}).validate_integrity()
    with pytest.raises(ValidationError):
        RecoveryPlan.model_validate({**wire, "input_mode": "ignore_conflicts"})
    with pytest.raises(SchemaValidationError):
        Draft202012Validator(schema).validate({**wire, "input_mode": "ignore_conflicts"})
    assert RecoveryPlan.model_validate(wire).to_wire() == wire


def test_reapply_context_is_complete_required_coder_only_and_verified(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    old = make_plan(root)
    capture = replace(old.capture.to_capture(), patch=b"untrusted old edit\n")
    plan = RecoveryPlan.create(
        **{
            **old.to_wire(),
            "input_mode": "coder_reapply",
            "capture": CapturedChanges.from_capture(capture),
        }
    )
    auth = RecoveryAuthorization.create(approval(plan), Human().verify(approval(plan)))
    task = record_for(plan, auth).task
    sources = recovery_context_sources(plan)
    patch = next(s for s in sources if s.source_id == "recovery.patch")
    assert patch.required and patch.roles == (AgentRole.CODER,)
    assert patch.content == plan.capture.patch
    builder = FileContextBuilder(root, plan.permissions, sources=sources)
    context = builder.build(task, AgentRole.CODER, attempt=1)
    validate_reapply_context(plan, context)
    section = next(s for s in context.sections if s.name == "source:recovery.patch")
    assert section.sha256 == hashlib.sha256(plan.capture.patch.encode()).hexdigest()
    for update in ({"content": "different"}, {"uri": "recovery://wrong"}, {"truncated": True}):
        bad = context.model_copy(
            update={
                "sections": tuple(
                    s.model_copy(update=update) if s == section else s for s in context.sections
                )
            }
        )
        with pytest.raises(RecoveryRejected):
            validate_reapply_context(plan, bad)
    missing = context.model_copy(
        update={"sections": tuple(s for s in context.sections if s != section)}
    )
    with pytest.raises(RecoveryRejected):
        validate_reapply_context(plan, missing)
    for role in (AgentRole.QA, AgentRole.REVIEWER):
        assert all(s.name != section.name for s in builder.build(task, role, attempt=1).sections)
    budget = ContextBudget(
        max_input_tokens=context.budget.used_input_tokens - section.tokens,
        reserved_output_tokens=1,
    )
    FileContextBuilder(root, plan.permissions, sources=(sources[0],), budget=budget).build(
        task, AgentRole.CODER, attempt=1
    )
    with pytest.raises(ContextBudgetExceeded):
        FileContextBuilder(
            root,
            plan.permissions,
            sources=sources,
            budget=budget,
        ).build(task, AgentRole.CODER, attempt=1)
    assert not any(s.source_id == "recovery.patch" for s in recovery_context_sources(old))


def test_reapply_cannot_reuse_old_approval_or_claim_applied_seed(tmp_path: Path) -> None:
    old = make_plan(tmp_path / "project")
    plan = RecoveryPlan.create(**{**old.to_wire(), "input_mode": "coder_reapply"})
    store = FileRecoveryStore.initialize(tmp_path / "records", scope=plan.source.scope)
    store.put_plan(old)
    store.put_plan(plan)
    store.put_authorization(
        RecoveryAuthorization.create(approval(old), Human().verify(approval(old)))
    )
    with pytest.raises(RecoveryRejected):
        store.get_authorization(plan.plan_sha256)
    auth = RecoveryAuthorization.create(approval(plan), Human().verify(approval(plan)))
    store.put_authorization(auth)
    store.put_task_record(record_for(plan, auth))
    capture = old.capture.to_capture()
    dirty = replace(
        capture,
        worktree=replace(
            capture.worktree,
            task_id=plan.new_task_id,
            head_revision=plan.target_base_revision,
            branch=f"ai/{plan.new_task_id}/attempt-1",
        ),
        patch=b"unexpected applied change\n",
    )
    seed = RecoverySeedRecord.create(
        plan_sha256=plan.plan_sha256,
        dispatch_sha256="8" * 64,
        capture=CapturedChanges.from_capture(dirty),
    )
    with pytest.raises(RecoveryRejected, match="must be clean"):
        store.put_seed(seed)
    assert not tuple((tmp_path / "records").glob("seed-*.json"))
