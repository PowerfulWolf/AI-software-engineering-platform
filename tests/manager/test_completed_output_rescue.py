"""Same-base recovery preserves unknown output and requires exact paused authority."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselineInputMode,
    BaselinePurpose,
    ExecutionBaselineBinding,
)
from ai_software_engineer.domain.execution_native_rules import NativeRuleEpoch
from ai_software_engineer.git.baseline import GitExecutionBaselineAdapter
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionFacts,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
)
from ai_software_engineer.manager.baseline_production import BaselineProposeCommand
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.execution_baseline import ExecutionBaselineService
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.web_console.models import ProposeExecutionBaselineIntent
from tests.git.test_worktree import _git
from tests.manager.test_completed_output_checkpoint import CompletedFixture
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.manager.test_execution_baseline import Collector, authorize, setup

completed = completed_fixture


def service_for(f: CompletedFixture) -> ExecutionBaselineService:
    facts = BaselineExecutionFacts(
        task=f.task,
        scope=f.collector.scope,
        task_revision=f.native.repository.current_revision(f.task.id),
        work_item_id=f.queue.item.id,
        checkpoint_sequence=f.queue.item.checkpoint_sequence,
        quiescence_proof_sha256="1" * 64,
        runtime_manifest_sha256="2" * 64,
        source_native_rules_sha256="3" * 64,
        target_native_rules_sha256="3" * 64,
        source_artifact_ids=f.native.request.input_artifact_ids,
        continuation=f.collector._reservation(f.task, f.queue.item, (), completed_output=f.proof()),
        completed_output=f.proof(),
        permissions=f.native.request.permissions,
        denied_paths=(),
        facts_sha256="0" * 64,
    )
    facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    return ExecutionBaselineService(
        store=FileExecutionBaselineStore(f.root / "same-base-records"),
        git=GitExecutionBaselineAdapter(f.native.git),
        facts=Collector(facts, f.native.worktree),
    )


def public_input() -> dict[str, object]:
    return {
        "action": "PROPOSE_EXECUTION_BASELINE",
        "project_id": "project_current",
        "delivery_id": "delivery_current",
        "expected_checkpoint_sha256": "a" * 64,
        "task_id": "task_current",
        "expected_task_intent_sha256": "b" * 64,
        "expected_task_revision": 2,
        "expected_work_item_id": "work_current",
        "expected_source_revision": "c" * 40,
        "purpose": "completed_output_rescue",
    }


def proposal_schema() -> Draft202012Validator:
    document = json.loads(
        (Path(__file__).parents[2] / "schemas/console-operation.schema.json").read_text()
    )
    return Draft202012Validator(
        {"$defs": document["$defs"], "$ref": "#/$defs/ProposeExecutionBaselineIntent"}
    )


def test_target_free_public_command_and_schema() -> None:
    wire = public_input()
    intent = ProposeExecutionBaselineIntent.model_validate(wire)
    assert intent.target_base_ref is None
    assert "target_base_ref" not in intent.to_wire()
    assert not list(proposal_schema().iter_errors(wire))
    for mutation in (
        {"target_base_ref": "d" * 40},
        {"input_mode": "coder_reapply"},
        {"purpose": "source_rebind"},
        {"purpose": "legacy_workspace_rescue"},
    ):
        changed = {**wire, **mutation}
        with pytest.raises(ValidationError):
            ProposeExecutionBaselineIntent.model_validate(changed)
        assert list(proposal_schema().iter_errors(changed))


@pytest.mark.parametrize("completed", ["named"], indirect=True)
def test_same_base_real_git_proposal_and_pause_replay_preserve_every_byte(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = service_for(f)
    inventory, history = capture_mutation_inventory(f.native.worktree.path), f.sealed_bytes()
    head = _git(f.native.worktree.path, "rev-parse", "HEAD")
    plan = service.propose(None, purpose=BaselinePurpose.COMPLETED_OUTPUT_RESCUE)
    assert plan.target_base_ref == f.task.base_ref
    assert plan.prepared_source_revision == head
    assert plan.prepared_dirty_patch == plan.dirty_capture.patch
    assert plan.facts.completed_output == f.proof()
    assert plan.facts.continuation is not None
    assert plan.facts.continuation.next_execution_attempt == f.task.attempts + 1
    plan.validate_integrity()
    command = BaselineProposeCommand(
        purpose=BaselinePurpose.COMPLETED_OUTPUT_RESCUE,
        delivery_id="delivery_current",
        task_id=f.task.id,
        expected_task_intent_sha256=task_intent_sha256(f.task),
        expected_task_revision=plan.facts.task_revision,
        expected_work_item_id=f.queue.item.id,
        expected_source_revision=head,
    )
    command.require_plan(plan)
    assert service.propose(None, purpose=BaselinePurpose.COMPLETED_OUTPUT_RESCUE) == plan
    with pytest.raises(ValueError, match="暂停"):
        BaselineOperatorAuthorization.for_plan(
            plan,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="exact fixture",
            submitted_at=datetime.now(UTC),
        )
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact fixture",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    assert binding.completed_output_sha256 == f.proof().proof_sha256
    assert binding.execution_base_ref == binding.prior_execution_base_ref
    assert binding.execution_source_revision == binding.prior_source_revision == head
    assert binding.continuation_mode is BaselineContinuationMode.PAUSE
    assert service.execute(plan.plan_sha256, authority=authority) == binding
    assert service.store.bindings_for_task(f.task.id)[-1] == binding
    assert capture_mutation_inventory(f.native.worktree.path) == inventory
    assert all(path.read_bytes() == body for path, body in history.items())


@pytest.mark.parametrize("completed", ["named"], indirect=True)
def test_source_rebind_still_rejects_same_base_and_rescue_rejects_wrong_input(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = service_for(f)
    before = capture_mutation_inventory(f.native.worktree.path)
    with pytest.raises(ValueError):
        service.propose(f.task.base_ref)
    with pytest.raises(ValueError):
        service.propose(None)
    with pytest.raises(ValueError):
        service.propose(
            None,
            purpose=BaselinePurpose.COMPLETED_OUTPUT_RESCUE,
            input_mode=BaselineInputMode.CODER_REAPPLY,
        )
    plan = service.propose(None, purpose=BaselinePurpose.COMPLETED_OUTPUT_RESCUE)
    for mutation in (
        {"purpose": BaselinePurpose.SOURCE_REBIND},
        {"target_base_ref": "f" * 40},
        {"prepared_source_revision": "f" * 40},
        {"conflicted": True},
    ):
        with pytest.raises(ValidationError):
            ExecutionBaselinePlan.model_validate({**plan.to_wire(), **mutation})
    assert capture_mutation_inventory(f.native.worktree.path) == before


@pytest.mark.parametrize("completed", ["named"], indirect=True)
def test_prevalidated_previous_binding_epoch_and_context_lineage_are_inherited(
    completed: CompletedFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = completed
    service = service_for(f)
    first = service.propose(None, purpose=BaselinePurpose.COMPLETED_OUTPUT_RESCUE)
    authority = BaselineOperatorAuthorization.for_plan(
        first,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="first fixture decision",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    original = service.execute(first.plan_sha256, authority=authority)
    epoch = NativeRuleEpoch.create(
        scope=original.scope,
        task_id=f.task.id,
        source_revision="a" * 40,
        target_base_ref=original.execution_base_ref,
        source_rules=(),
        before_bodies=(),
        bodies=(),
    )
    # Stub only the previously validated historical reader. New proposal,
    # authority, source preservation and binding validation use real services.
    previous = ExecutionBaselineBinding.create(
        **{
            **original.model_dump(mode="python", exclude={"binding_sha256"}),
            "native_rule_epoch_sha256": epoch.epoch_sha256,
        }
    )
    monkeypatch.setattr(service.store, "bindings_for_task", lambda task_id: (previous,))
    monkeypatch.setattr(service.store, "native_rule_epoch", lambda sha256: epoch)
    plan = service.propose(None, purpose=BaselinePurpose.COMPLETED_OUTPUT_RESCUE)
    assert plan.previous_binding == previous
    next_authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="next exact fixture decision",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = service.execute(plan.plan_sha256, authority=next_authority)
    assert binding.previous_binding_sha256 == previous.binding_sha256
    assert binding.native_rule_epoch_sha256 == previous.native_rule_epoch_sha256
    assert binding.source_artifact_ids == previous.source_artifact_ids
    assert binding.retained_patch.sha256 == previous.retained_patch.sha256
    assert "报告内容仍未知" in service.store.required_context(binding)
    for mutation, message in (
        ({"completed_output_sha256": "f" * 64}, "完整原执行证据"),
        ({"native_rule_epoch_sha256": None}, "完整项目规范版本"),
    ):
        changed = ExecutionBaselineBinding.create(
            **{**binding.model_dump(mode="python", exclude={"binding_sha256"}), **mutation}
        )
        with pytest.raises(ValueError, match=message):
            service.store._require_authorized_binding(changed, plan, previous)


def test_old_source_rebind_binding_retains_canonical_wire_without_new_optional_field(
    tmp_path: Path,
) -> None:
    f = setup(tmp_path)
    plan = f.service.propose(f.target)
    binding = f.service.execute(plan.plan_sha256, authority=authorize(plan))
    wire = binding.to_wire()
    assert "completed_output_sha256" not in wire and "purpose" not in wire
    assert binding.model_dump(mode="json", exclude={"completed_output_sha256", "purpose"}) == wire
    assert binding.binding_sha256 == digest(
        {key: value for key, value in wire.items() if key != "binding_sha256"}
    )
