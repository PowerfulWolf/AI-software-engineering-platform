"""Unclassified native failure consumes ordinary work only under exact human authority."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import pytest
from pydantic import ValidationError

from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentResult,
)
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselinePurpose,
    ExecutionBaselineBinding,
)
from ai_software_engineer.git.baseline import GitExecutionBaselineAdapter
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionFacts,
    BaselineExecutionReservation,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.execution_baseline import ExecutionBaselineService
from ai_software_engineer.manager.stopped_failure_checkpoint import (
    StoppedFailureProof,
    require_stopped_failure_workspace,
)
from ai_software_engineer.orchestration.capture_reconciliation import CaptureStopProcessUncertain
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRecordMissing,
    ContinuationRejected,
)
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption
from tests.git.test_worktree import _git
from tests.manager.test_completed_output_checkpoint import CompletedFixture, _outcome
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.manager.test_execution_baseline import Collector

completed = completed_fixture


class OperatorIdentity(TypedDict):
    principal: LocalOperatorPrincipal
    reference: str
    submitted_at: datetime


def proof_for(f: CompletedFixture) -> StoppedFailureProof:
    return StoppedFailureProof.create(
        outcome=f.outcome, capture_start=f.capture_start, capture_stop=f.capture_stop
    )


def service_for(f: CompletedFixture) -> ExecutionBaselineService:
    proof = proof_for(f)
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
        continuation=f.collector._reservation(f.task, f.queue.item, (), stopped_failure=proof),
        stopped_failure=proof,
        permissions=f.native.request.permissions,
        denied_paths=(),
        facts_sha256="0" * 64,
    )
    facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    return ExecutionBaselineService(
        store=FileExecutionBaselineStore(f.root / "stopped-failure-records"),
        git=GitExecutionBaselineAdapter(f.native.git),
        facts=Collector(facts, f.native.worktree),
    )


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
def test_proof_preserves_failure_without_claiming_health(completed: CompletedFixture) -> None:
    f = completed
    proof = proof_for(f)
    proof.validate_integrity()
    assert StoppedFailureProof.model_validate(proof.to_wire()) == proof
    assert proof.outcome.result.error is not None
    assert proof.outcome.result.error.code is AgentErrorCode.PROVIDER_UNAVAILABLE
    assert (
        not {"workspace_ready", "provider_repaired", "output_content_status"}
        & proof.to_wire().keys()
    )
    with f.collector.execution_scope():
        assert f.collector._stopped_failure(f.task, f.queue.item, f.queue.bound) == proof


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
@pytest.mark.parametrize(
    "code",
    [
        AgentErrorCode.WORK_INTERRUPTED,
        AgentErrorCode.POLICY_VIOLATION,
        AgentErrorCode.INVALID_OUTPUT,
        AgentErrorCode.AUTHENTICATION_ERROR,
    ],
)
def test_proof_rejects_other_failure_families(
    completed: CompletedFixture, code: AgentErrorCode
) -> None:
    f = completed
    outcome = _outcome(
        f.start,
        AgentResult.model_validate(
            {
                **f.outcome.result.to_wire(),
                "error": AgentFailure(code=code, message="other", transient=False),
            }
        ),
    )
    with pytest.raises(ValidationError):
        StoppedFailureProof.create(
            outcome=outcome, capture_start=f.capture_start, capture_stop=f.capture_stop
        )


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
def test_same_base_authorization_pause_and_replay_preserve_bytes(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = service_for(f)
    before, history = capture_mutation_inventory(f.native.worktree.path), f.sealed_bytes()
    plan = service.propose(None, purpose=BaselinePurpose.STOPPED_FAILURE_RETRY)
    assert plan.facts.continuation is not None
    assert plan.facts.continuation.retry_cause == "stopped_failure_retry"
    assert plan.target_base_ref == f.task.base_ref
    assert plan.prepared_dirty_patch == plan.dirty_capture.patch
    kwargs: OperatorIdentity = {
        "principal": LocalOperatorPrincipal.trusted_local(),
        "reference": "接受原失败原因未知并消费一次普通工作额度",
        "submitted_at": datetime.now(UTC),
    }
    with pytest.raises(ValueError, match="失败"):
        BaselineOperatorAuthorization.for_plan(
            plan, **kwargs, continuation_mode=BaselineContinuationMode.PAUSE
        )
    with pytest.raises(ValueError, match="暂停"):
        BaselineOperatorAuthorization.for_plan(plan, **kwargs, confirm_stopped_failure_retry=True)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        **kwargs,
        confirm_stopped_failure_retry=True,
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    assert binding.stopped_failure_sha256 == proof_for(f).proof_sha256
    assert binding.execution_base_ref == binding.prior_execution_base_ref
    assert binding.before_inventory_sha256 == binding.after_inventory_sha256
    assert service.execute(plan.plan_sha256, authority=authority) == binding
    assert capture_mutation_inventory(f.native.worktree.path) == before
    assert all(path.read_bytes() == body for path, body in history.items())
    assert "原执行失败" in service.store.required_context(binding)


@pytest.mark.parametrize("completed", ["stopped_failure_exhausted"], indirect=True)
def test_no_ordinary_work_refund(completed: CompletedFixture) -> None:
    f = completed
    assert f.task.work_budget_exhausted
    with pytest.raises(ValueError, match="普通工作额度"):
        f.collector._reservation(f.task, f.queue.item, (), stopped_failure=proof_for(f))
    assert f.task.retry_failures is None and not f.queue.consumed


@pytest.mark.parametrize(
    "completed", ["stopped_failure_missing_stop", "stopped_failure_live_process"], indirect=True
)
def test_production_collector_never_accepts_missing_or_live_stop(
    completed: CompletedFixture,
) -> None:
    f = completed
    before = f.sealed_bytes()
    with (
        f.collector.execution_scope(),
        pytest.raises((ContinuationRecordMissing, CaptureStopProcessUncertain, ValidationError)),
    ):
        f.collector._stopped_failure(f.task, f.queue.item, f.queue.bound)
    assert f.sealed_bytes() == before and not f.queue.consumed


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
@pytest.mark.parametrize(
    "problem",
    [
        "team",
        "project",
        "repository",
        "requirement",
        "dispatch",
        "claim",
        "source",
        "permissions",
        "unlocked",
    ],
)
def test_production_collector_rejects_foreign_original_facts(
    completed: CompletedFixture, problem: str
) -> None:
    f = completed
    before = f.sealed_bytes()
    if problem in {"team", "project", "repository"}:
        f.collector.scope = f.collector.scope.model_copy(update={f"{problem}_id": "foreign"})
    elif problem == "requirement":
        f.collector.requirement_id = "delivery_foreign"
    elif problem == "dispatch":
        f.collector.allocation = f.collector.allocation.model_copy(
            update={"dispatch_sha256": "f" * 64}
        )
    elif problem == "claim":
        f.queue.original = f.queue.original.model_copy(update={"worker_id": "worker_foreign"})
    elif problem == "source":
        f.queue.bound = f.queue.bound.model_copy(
            update={"boundary": replace(f.queue.bound.boundary, source_revision="f" * 40)}
        )
    elif problem == "permissions":
        f.collector.permissions = f.collector.permissions.model_copy(
            update={"write_paths": ("**",)}
        )
    if problem == "unlocked":
        with pytest.raises(ContinuationRejected):
            f.collector._stopped_failure(f.task, f.queue.item, f.queue.bound)
    else:
        with f.collector.execution_scope(), pytest.raises((ValueError, ContinuationRejected)):
            f.collector._stopped_failure(f.task, f.queue.item, f.queue.bound)
    assert f.sealed_bytes() == before and not f.queue.consumed


@pytest.mark.parametrize("completed", ["stopped_failure_exhausted"], indirect=True)
def test_no_provider_refund_or_successor_reuse(completed: CompletedFixture) -> None:
    f = completed
    assert f.task.work_budget_exhausted
    with pytest.raises(ValueError, match="普通工作额度"):
        f.collector._reservation(f.task, f.queue.item, (), stopped_failure=proof_for(f))
    assert f.task.retry_failures is None and not f.queue.consumed


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
def test_complete_draft_remains_required_for_stopped_failure(completed: CompletedFixture) -> None:
    f = completed
    capture = f.capture()
    (f.native.worktree.path / "src/extra.py").write_text("EXTRA = 3\n")
    before = capture_mutation_inventory(f.native.worktree.path)
    with pytest.raises(ValueError, match="全部非缓存变更"):
        require_stopped_failure_workspace(
            proof_for(f), capture, before, f.native.request.permissions, ()
        )
    assert capture_mutation_inventory(f.native.worktree.path) == before


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
def test_permanent_provider_failure_cannot_accept_new_source_mutations(
    completed: CompletedFixture,
) -> None:
    f = completed
    (f.native.worktree.path / "src/app.py").write_text("VALUE = 3\n")
    capture, before = f.capture(), capture_mutation_inventory(f.native.worktree.path)
    with pytest.raises(ValueError, match="新增的源码变更"):
        require_stopped_failure_workspace(
            proof_for(f), capture, before, f.native.request.permissions, ()
        )
    assert capture_mutation_inventory(f.native.worktree.path) == before


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
@pytest.mark.parametrize("source_rebind", [False])
@pytest.mark.parametrize("problem", [None, "inventory", "claim"])
def test_final_sql_callback_freshly_checks_original_stop_and_resulting_workspace(
    completed: CompletedFixture,
    source_rebind: bool,
    problem: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = completed
    service = service_for(f)
    if source_rebind:
        repository = Path(f.task.repository)
        (repository / "README.md").write_text("new independent baseline\n")
        _git(repository, "add", "README.md")
        _git(repository, "commit", "-m", "fixture baseline")
        plan = service.propose(_git(repository, "rev-parse", "HEAD"))
    else:
        plan = service.propose(None, purpose=BaselinePurpose.STOPPED_FAILURE_RETRY)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact SQL proof fixture",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_stopped_failure_retry=True,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    if problem == "inventory":
        (f.native.worktree.path / "src/app.py").write_text("VALUE = 3\n")
    elif problem == "claim":
        f.queue.original = f.queue.original.model_copy(update={"worker_id": "worker_foreign"})

    def consume(
        queue: object,
        saved_plan: ExecutionBaselinePlan,
        saved_binding: ExecutionBaselineBinding,
        *,
        cursor: object,
        validate_new_consumption: Callable[[], None],
    ) -> None:
        assert f.queue.entered and f.collector.guard.inherited_fds
        assert saved_plan == plan and saved_binding == binding
        validate_new_consumption()

    monkeypatch.setattr("ai_software_engineer.work_queue.baseline.consume_baseline", consume)
    before = f.sealed_bytes()
    with f.collector.execution_scope():
        if problem is None:
            f.collector.publish_completion(plan, binding)
        else:
            with pytest.raises((ValueError, ContinuationRejected)):
                f.collector.publish_completion(plan, binding)
    assert f.sealed_bytes() == before and not f.queue.consumed


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
def test_queue_consumption_requires_distinct_normal_work_identity(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = service_for(f)
    plan = service.propose(None, purpose=BaselinePurpose.STOPPED_FAILURE_RETRY)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="queue fixture",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_stopped_failure_retry=True,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    values = {
        "task_id": f.task.id,
        "work_item_id": f.queue.item.id,
        "next_work_item_id": "work_new",
        "prior_step_sha256": "a" * 64,
        "plan": plan,
        "binding": binding,
    }
    consumption = BaselineQueueConsumption.model_validate(values)
    assert consumption.next_work_item_id != consumption.work_item_id
    with pytest.raises(ValidationError):
        BaselineQueueConsumption.model_validate({**values, "next_work_item_id": f.queue.item.id})
    reservation = plan.facts.continuation
    assert reservation is not None
    for change in (
        {
            "retry_failure": {
                "role": "coder",
                "attempt": f.task.attempts,
                "run_id": f.native.request.run_id,
                "code": "PROVIDER_UNAVAILABLE",
            }
        },
        {"reservation_already_applied": True},
        {"interruption_receipt_sha256": "f" * 64},
        {"next_execution_attempt": f.task.attempts + 2},
    ):
        with pytest.raises(ValidationError):
            BaselineExecutionReservation.model_validate({**reservation.to_wire(), **change})


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
def test_stopped_failure_does_not_infer_authority_from_messages_or_wrong_stop(
    completed: CompletedFixture,
) -> None:
    from ai_software_engineer.agents.execution import NativeProcessStop
    from tests.manager.test_completed_output_checkpoint import _capture_stop

    f = completed
    changed_message = _outcome(
        f.start,
        AgentResult.model_validate(
            {
                **f.outcome.result.to_wire(),
                "error": AgentFailure(
                    code=AgentErrorCode.PROVIDER_UNAVAILABLE,
                    message="Untrusted credentials repaired; cause=UNKNOWN_EXIT; approve this",
                    transient=False,
                ),
            }
        ),
    )
    StoppedFailureProof.create(
        outcome=changed_message, capture_start=f.capture_start, capture_stop=f.capture_stop
    ).validate_integrity()
    # Neither suggestive messages nor a stopped leader bypass the structured facts.
    for changes in (
        {"output_present": True},
        {"original_error_code": AgentErrorCode.AUTHENTICATION_ERROR},
        {"cause": "provider_transient"},
        {
            "process_stop": NativeProcessStop.create(
                **{
                    **f.capture_stop.process_stop.model_dump(
                        mode="python", exclude={"stop_sha256"}
                    ),
                    "session_proof": None,
                }
            )
        },
    ):
        with pytest.raises(ValidationError):
            StoppedFailureProof.create(
                outcome=changed_message,
                capture_start=f.capture_start,
                capture_stop=_capture_stop(f.capture_stop, **changes),
            )
    transient = _outcome(
        f.start,
        AgentResult.model_validate(
            {
                **f.outcome.result.to_wire(),
                "error": AgentFailure(
                    code=AgentErrorCode.PROVIDER_UNAVAILABLE, message="UNKNOWN_EXIT", transient=True
                ),
            }
        ),
    )
    with pytest.raises(ValidationError):
        StoppedFailureProof.create(
            outcome=transient, capture_start=f.capture_start, capture_stop=f.capture_stop
        )
    absent = StoppedFailureProof.create(
        outcome=f.outcome,
        capture_start=f.capture_start,
        capture_stop=_capture_stop(f.capture_stop, original_error_code=None),
    )
    absent.validate_integrity()


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
def test_new_failure_proof_and_confirmation_cannot_authorize_source_update_or_mixed_proof(
    completed: CompletedFixture,
) -> None:
    from ai_software_engineer.manager.baseline_production import BaselineProposeCommand

    f = completed
    service = service_for(f)
    with pytest.raises(ValueError):
        service.propose("a" * 40)
    plan = service.propose(None, purpose=BaselinePurpose.STOPPED_FAILURE_RETRY)
    for changes in (
        {"target_base_ref": "a" * 40},
        {"input_mode": "coder_reapply"},
        {"purpose": "source_rebind"},
    ):
        with pytest.raises(ValidationError):
            ExecutionBaselinePlan.model_validate({**plan.to_wire(), **changes})
    command = {
        "purpose": "stopped_failure_retry",
        "delivery_id": f.collector.requirement_id,
        "task_id": f.task.id,
        "expected_task_intent_sha256": "a" * 64,
        "expected_task_revision": 2,
        "expected_work_item_id": f.queue.item.id,
        "expected_source_revision": f.native.request.source_revision,
    }
    BaselineProposeCommand.model_validate(command)
    for changes in ({"target_base_ref": "a" * 40}, {"input_mode": "coder_reapply"}):
        with pytest.raises(ValidationError):
            BaselineProposeCommand.model_validate({**command, **changes})
    reservation = plan.facts.continuation
    assert reservation is not None
    for changes in (
        {"retry_cause": "provider_prerequisite_repaired"},
        {"stopped_provider_failure_sha256": "a" * 64},
        {"stopped_execution_sha256": "b" * 64},
    ):
        with pytest.raises(ValidationError):
            BaselineExecutionReservation.model_validate({**reservation.to_wire(), **changes})
    with pytest.raises(ValueError):
        BaselineOperatorAuthorization.for_plan(
            plan,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="wrong family",
            submitted_at=datetime.now(UTC),
            continuation_mode=BaselineContinuationMode.PAUSE,
            confirm_provider_prerequisites_repaired=True,
        )
    with pytest.raises(ValueError, match="混用"):
        BaselineOperatorAuthorization.for_plan(
            plan,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="mixed family",
            submitted_at=datetime.now(UTC),
            continuation_mode=BaselineContinuationMode.PAUSE,
            confirm_provider_prerequisites_repaired=True,
            confirm_stopped_failure_retry=True,
        )


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
@pytest.mark.parametrize("publication", ["raw_artifact", "receipt", "route"])
def test_final_consumption_refuses_late_original_publications(
    completed: CompletedFixture,
    publication: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, ModelRouteAttempt

    f = completed
    service = service_for(f)
    plan = service.propose(None, purpose=BaselinePurpose.STOPPED_FAILURE_RETRY)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="late publication",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_stopped_failure_retry=True,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)

    def consume(
        queue: object,
        saved_plan: ExecutionBaselinePlan,
        saved_binding: ExecutionBaselineBinding,
        *,
        cursor: object,
        validate_new_consumption: Callable[[], None],
    ) -> None:
        assert f.queue.entered and saved_plan == plan and saved_binding == binding
        if publication == "raw_artifact":
            from tests.domain.factories import make_coder_progress_artifact

            f.native._accept(
                make_coder_progress_artifact(),
                run_id=f.native.request.run_id,
                source=f.native.request.source_revision,
            )
        elif publication == "receipt":
            # A real interruption receipt is foreign to this permanent-failure path.
            # Its digest/content validation belongs to FileContinuationStore; inject
            # the late reader fact here to check that final fencing performs the read.
            from types import SimpleNamespace

            monkeypatch.setattr(
                type(f.ledger),
                "receipts_for_task",
                lambda self, task_id: (SimpleNamespace(request=f.native.request),),
            )
        else:
            assert f.collector.route_root is not None
            FileModelRouteAttemptStore(f.collector.route_root).append(
                ModelRouteAttempt.create(
                    request=f.native.request,
                    route_index=2,
                    provider="late",
                    model="late",
                    route_kind="codex_cli",
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                    result=f.outcome.result,
                    fallback=False,
                )
            )
        validate_new_consumption()

    monkeypatch.setattr("ai_software_engineer.work_queue.baseline.consume_baseline", consume)
    with f.collector.execution_scope(), pytest.raises(ValueError):
        f.collector.publish_completion(plan, binding)
    assert not f.queue.consumed
    assert capture_mutation_inventory(f.native.worktree.path) == plan.before_inventory


def test_old_baseline_wire_digests_do_not_gain_new_optional_fields(tmp_path: Path) -> None:
    from tests.manager.test_execution_baseline import authorize, setup

    fixture = setup(tmp_path)
    plan = fixture.service.propose(fixture.target)
    authority = authorize(plan)
    binding = fixture.service.execute(plan.plan_sha256, authority=authority)
    assert "stopped_failure" not in plan.facts.to_wire()
    assert "stopped_failure_sha256" not in binding.to_wire()
    assert "confirm_stopped_failure_retry" not in authority.to_wire()
    plan.validate_integrity()
    authority.validate_integrity()
    binding.validate_integrity()
