"""Completed rejected output follows the existing exact ordinary-work flow."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import (
    EngineeringAdmission,
    EngineeringCapability,
    EngineeringPolicy,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode, BaselinePurpose
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionFacts,
    BaselineOperatorAuthorization,
)
from ai_software_engineer.manager.baseline_production import BaselineExecuteCommand
from ai_software_engineer.manager.completed_output_checkpoint import (
    CompletedCoderOutputUnavailableProof,
)
from ai_software_engineer.orchestration.capture_reconciliation import CaptureStopProcessUncertain
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRecordMissing,
    ContinuationRejected,
)
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption
from ai_software_engineer.work_queue.models import QueuedWorkItem
from tests.git.test_worktree import _git
from tests.manager.test_completed_output_checkpoint import CompletedFixture
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.manager.test_completed_output_rescue import service_for

completed = completed_fixture


@pytest.mark.parametrize("completed", ["invalid_named"], indirect=True)
def test_real_collector_retains_rejected_completed_output(completed: CompletedFixture) -> None:
    f = completed
    history, task = f.sealed_bytes(), f.task
    proof = f.collect()
    assert proof is not None, "sealed INVALID_OUTPUT with completed stop must remain preparable"
    assert proof == f.proof()
    assert proof.outcome.result.error is not None
    assert proof.outcome.result.error.code is AgentErrorCode.INVALID_OUTPUT
    reservation = f.collector._reservation(task, f.queue.item, (), completed_output=proof)
    assert reservation.retry_cause == "completed_output_rejected"
    assert reservation.retry_failure is None and not reservation.reservation_already_applied
    assert reservation.next_execution_attempt == task.attempts + 1
    assert f.task == task and f.sealed_bytes() == history and not f.queue.consumed


@pytest.mark.parametrize(
    "purpose", [BaselinePurpose.COMPLETED_OUTPUT_RESCUE, BaselinePurpose.SOURCE_REBIND]
)
@pytest.mark.parametrize("completed", ["invalid_named"], indirect=True)
def test_real_service_rejected_output_requires_pause_and_preserves_history(
    completed: CompletedFixture, purpose: BaselinePurpose
) -> None:
    f = completed
    service = service_for(f)
    target = None
    if purpose is BaselinePurpose.SOURCE_REBIND:
        repository = Path(f.task.repository)
        (repository / "README.md").write_text("updated baseline\n")
        _git(repository, "add", "README.md")
        _git(repository, "commit", "-m", "independent trusted baseline")
        target = _git(repository, "rev-parse", "HEAD")
    plan = service.propose(target, purpose=purpose)
    with pytest.raises(ValueError, match="暂停"):
        BaselineOperatorAuthorization.for_plan(
            plan,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="exact rejected output",
            submitted_at=datetime.now(UTC),
            continuation_mode=BaselineContinuationMode.RESUME,
        )
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact rejected output",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    history = f.sealed_bytes()
    binding = service.execute(plan.plan_sha256, authority=authority)
    assert binding.completed_output_sha256 == f.proof().proof_sha256
    assert binding.continuation_mode is BaselineContinuationMode.PAUSE
    assert (
        binding.after_inventory_sha256 == capture_mutation_inventory(f.native.worktree.path).sha256
    )
    consumption = BaselineQueueConsumption(
        task_id=f.task.id,
        work_item_id=f.queue.item.id,
        next_work_item_id="work_successor",
        prior_step_sha256="1" * 64,
        plan=plan,
        binding=binding,
    )
    assert consumption.plan.facts.continuation is not None
    assert consumption.plan.facts.continuation.retry_cause == "completed_output_rejected"
    for changed in (
        {"completed_output_sha256": None},
        {"completed_output_sha256": "f" * 64},
        {"authority_source": "organization_engineering_policy"},
        {"continuation_mode": "resume"},
    ):
        with pytest.raises(ValueError):
            BaselineQueueConsumption.model_validate(
                {**consumption.to_wire(), "binding": {**binding.to_wire(), **changed}}
            )
    command = BaselineExecuteCommand(
        delivery_id="delivery_fixture",
        task_id=f.task.id,
        expected_plan_sha256=plan.plan_sha256,
        reference="exact rejected output",
        continuation_mode=BaselineContinuationMode.RESUME,
    )
    with pytest.raises(ValueError, match="暂停"):
        command.require_plan(plan)
    assert service.execute(plan.plan_sha256, authority=authority) == binding
    assert all(path.read_bytes() == body for path, body in history.items())


@pytest.mark.parametrize("completed", ["invalid_named"], indirect=True)
def test_reason_is_derived_without_new_wire_or_hash_fields(completed: CompletedFixture) -> None:
    f = completed
    proof = f.proof()
    assert proof.reason.value == "completed_output_rejected"
    assert "reason" not in proof.to_wire()
    assert proof.recompute_sha256() == digest(
        proof.model_dump(mode="json", exclude={"proof_sha256"})
    )
    with pytest.raises(ValidationError):
        CompletedCoderOutputUnavailableProof.model_validate(
            {**proof.to_wire(), "reason": "completed_output_unavailable"}
        )
    service = service_for(f)
    plan = service.propose(None, purpose=BaselinePurpose.COMPLETED_OUTPUT_RESCUE)
    facts = plan.facts.to_wire()
    assert plan.facts.continuation is not None
    mismatched = plan.facts.continuation.model_copy(
        update={"retry_cause": "completed_output_unavailable"}
    )
    with pytest.raises(ValueError, match="普通工作预留"):
        BaselineExecutionFacts.model_validate({**facts, "continuation": mismatched.to_wire()})


@pytest.mark.parametrize("problem", [None, "missing_stop", "inventory", "staged"])
@pytest.mark.parametrize("completed", ["invalid_named"], indirect=True)
def test_source_publication_rechecks_real_stop_and_rebased_after_workspace(
    completed: CompletedFixture, problem: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = completed
    service = service_for(f)
    repository = Path(f.task.repository)
    (repository / "README.md").write_text("independent baseline change\n")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "-m", "trusted baseline update")
    target = _git(repository, "rev-parse", "HEAD")
    plan = service.propose(target)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="source update rejected draft",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    assert binding.before_inventory_sha256 != binding.after_inventory_sha256
    validations: list[str] = []

    def consume(
        queue: object,
        plan: object,
        binding: object,
        *,
        cursor: DictCursor | None = None,
        validate_new_consumption: Callable[[], None] | None = None,
    ) -> QueuedWorkItem:
        assert cursor is not None and validate_new_consumption is not None
        validate_new_consumption()
        validations.append("fresh original and actual after")
        return f.queue.item

    monkeypatch.setattr("ai_software_engineer.work_queue.baseline.consume_baseline", consume)
    history = f.sealed_bytes()
    if problem == "missing_stop":
        # Remove the actual sealed observation: a cached Plan cannot replace it.
        (f.ledger._root / f"capture-stop-{f.native.request.run_id}.json").unlink()
    elif problem == "inventory":
        (f.native.worktree.path / "src/app.py").write_text("VALUE = 99\n")
    elif problem == "staged":
        _git(f.native.worktree.path, "add", "src/app.py")
    with f.collector.execution_scope():
        if problem is None:
            f.collector.publish_completion(plan, binding)
            assert validations == ["fresh original and actual after"]
        else:
            with pytest.raises((ValueError, ContinuationRecordMissing)):
                f.collector.publish_completion(plan, binding)
            assert validations == []
    assert all(path.read_bytes() == body for path, body in history.items() if path.exists())


@pytest.mark.parametrize("completed", ["invalid_named"], indirect=True)
def test_policy_cannot_approve_rejected_source_even_with_capability(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = service_for(f)
    repository = Path(f.task.repository)
    (repository / "README.md").write_text("trusted target\n")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "-m", "trusted target")
    plan = service.propose(_git(repository, "rev-parse", "HEAD"))
    policy = EngineeringPolicy.bounded_local(
        scope=plan.facts.scope, principal=LocalOperatorPrincipal.trusted_local()
    )
    # The service must reject the otherwise valid organization admission before
    # any authority/start or Git update, rather than relying on the UI.
    admission = EngineeringAdmission.create(
        task_id=f.task.id,
        task_intent_sha256=task_intent_sha256(plan.facts.task),
        policy=policy,
        policy_sha256=policy.policy_sha256,
        capabilities=(EngineeringCapability.EXECUTION_BASELINE_REBIND,),
        admission_number=1,
        plan_sha256=plan.plan_sha256,
        facts_sha256=plan.facts.facts_sha256,
        admitted_at=datetime.now(UTC),
    )
    before = capture_mutation_inventory(f.native.worktree.path)
    with pytest.raises(ValueError, match="人工工程确认"):
        service.execute(plan.plan_sha256, authority=admission)
    assert capture_mutation_inventory(f.native.worktree.path) == before
    assert service.store.bindings_for_task(f.task.id) == ()


@pytest.mark.parametrize(
    "completed",
    ["invalid_missing_stop", "invalid_output_absent", "invalid_live_process"],
    indirect=True,
)
def test_rejected_completed_output_still_requires_original_observed_stop(
    completed: CompletedFixture,
) -> None:
    f = completed
    before, task = f.sealed_bytes(), f.task
    with pytest.raises((ContinuationRecordMissing, ValidationError, CaptureStopProcessUncertain)):
        f.collect()
    assert f.sealed_bytes() == before and f.task == task and not f.queue.consumed


@pytest.mark.parametrize("completed", ["invalid_exhausted"], indirect=True)
def test_rejected_completed_output_never_refunds_exhausted_work(
    completed: CompletedFixture,
) -> None:
    f = completed
    before, task = f.sealed_bytes(), f.task
    assert task.work_budget_exhausted
    with pytest.raises(ValueError, match="工作额度"):
        f.collector._reservation(task, f.queue.item, (), completed_output=f.proof())
    assert f.task == task and f.sealed_bytes() == before and not f.queue.consumed


@pytest.mark.parametrize("completed", ["named_policy"], indirect=True)
def test_old_unavailable_source_keeps_policy_resume_and_canonical_fields(
    completed: CompletedFixture,
) -> None:
    f = completed
    proof = f.proof()
    assert proof.reason.value == "completed_output_unavailable"
    assert "reason" not in proof.model_dump(mode="json")
    service = service_for(f)
    repository = Path(f.task.repository)
    (repository / "README.md").write_text("trusted historical source update\n")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "-m", "historical source update")
    plan = service.propose(_git(repository, "rev-parse", "HEAD"))
    policy = f.task.engineering_policy
    assert policy is not None
    admission = EngineeringAdmission.create(
        task_id=f.task.id,
        task_intent_sha256=task_intent_sha256(f.task),
        policy=policy,
        policy_sha256=policy.policy_sha256,
        capabilities=(EngineeringCapability.EXECUTION_BASELINE_REBIND,),
        admission_number=1,
        plan_sha256=plan.plan_sha256,
        facts_sha256=plan.facts.facts_sha256,
        admitted_at=datetime.now(UTC),
    )
    binding = service.execute(plan.plan_sha256, authority=admission)
    assert binding.completed_output_sha256 is None
    assert binding.authority_source == "organization_engineering_policy"
    assert binding.continuation_mode is BaselineContinuationMode.RESUME
    assert "completed_output_sha256" not in binding.model_dump(mode="json")
    assert "purpose" not in binding.model_dump(mode="json")
    assert "continuation_mode" not in binding.model_dump(mode="json")
    assert service.store.bindings_for_task(f.task.id) == (binding,)
    assert service.execute(plan.plan_sha256, authority=admission) == binding


@pytest.mark.parametrize("completed", ["invalid_named"], indirect=True)
def test_collector_cannot_override_later_adopted_state_event(completed: CompletedFixture) -> None:
    f = completed
    from ai_software_engineer.domain import TaskStatus

    f.native._event(TaskStatus.QA, "later implementation adopted", ("art_impl_adopted",))
    before = f.sealed_bytes()
    events = f.native.repository.list_events(f.task.id)
    with pytest.raises(ContinuationRejected):
        f.collect()
    assert f.sealed_bytes() == before and f.native.repository.list_events(f.task.id) == events
    assert not f.queue.consumed
