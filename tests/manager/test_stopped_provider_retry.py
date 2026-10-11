"""Permanent provider prerequisites retain lawful progress under explicit human authority."""

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentResult,
)
from ai_software_engineer.domain.delivery_resolution import DeliveryProofMissing
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselinePurpose,
    ExecutionBaselineBinding,
)
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.git.baseline import GitExecutionBaselineAdapter
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionFacts,
    BaselineExecutionReservation,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
)
from ai_software_engineer.manager.baseline_production import BaselineProposeCommand
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.delivery_wait import DeliveryWaitService
from ai_software_engineer.manager.execution_baseline import ExecutionBaselineService
from ai_software_engineer.manager.stopped_provider_checkpoint import (
    StoppedProviderFailureProof,
    require_stopped_provider_workspace,
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
from tests.manager.test_execution_baseline import Collector, authorize, setup

completed = completed_fixture


def proof_for(f: CompletedFixture) -> StoppedProviderFailureProof:
    return StoppedProviderFailureProof.create(
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
        continuation=f.collector._reservation(
            f.task, f.queue.item, (), stopped_provider_failure=proof
        ),
        stopped_provider_failure=proof,
        permissions=f.native.request.permissions,
        denied_paths=(),
        facts_sha256="0" * 64,
    )
    facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    return ExecutionBaselineService(
        store=FileExecutionBaselineStore(f.root / "stopped-provider-records"),
        git=GitExecutionBaselineAdapter(f.native.git),
        facts=Collector(facts, f.native.worktree),
    )


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
def test_proof_preserves_failure_without_claiming_health(completed: CompletedFixture) -> None:
    f = completed
    proof = proof_for(f)
    proof.validate_integrity()
    assert StoppedProviderFailureProof.model_validate(proof.to_wire()) == proof
    assert proof.outcome.result.error is not None
    assert proof.outcome.result.error.code is AgentErrorCode.AUTHENTICATION_ERROR
    assert (
        not {"workspace_ready", "provider_repaired", "output_content_status"}
        & proof.to_wire().keys()
    )
    with f.collector.execution_scope():
        assert f.collector._stopped_provider_failure(f.task, f.queue.item, f.queue.bound) == proof


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
@pytest.mark.parametrize(
    "code",
    [
        AgentErrorCode.WORK_INTERRUPTED,
        AgentErrorCode.POLICY_VIOLATION,
        AgentErrorCode.INVALID_OUTPUT,
        AgentErrorCode.PROVIDER_UNAVAILABLE,
    ],
)
def test_proof_rejects_non_prerequisite_failures(
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
        StoppedProviderFailureProof.create(
            outcome=outcome, capture_start=f.capture_start, capture_stop=f.capture_stop
        )


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
def test_same_base_authorization_pause_and_replay_preserve_bytes(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = service_for(f)
    before, history = capture_mutation_inventory(f.native.worktree.path), f.sealed_bytes()
    plan = service.propose(None, purpose=BaselinePurpose.STOPPED_PROVIDER_RETRY)
    assert plan.facts.continuation is not None
    assert plan.facts.continuation.retry_cause == "provider_prerequisite_repaired"
    assert plan.target_base_ref == f.task.base_ref
    assert plan.prepared_dirty_patch == plan.dirty_capture.patch
    kwargs = {
        "principal": LocalOperatorPrincipal.trusted_local(),
        "reference": "原凭证前提已检查并修复",
        "submitted_at": datetime.now(UTC),
    }
    with pytest.raises(ValueError, match="前提"):
        BaselineOperatorAuthorization.for_plan(
            plan, **kwargs, continuation_mode=BaselineContinuationMode.PAUSE
        )
    with pytest.raises(ValueError, match="暂停"):
        BaselineOperatorAuthorization.for_plan(
            plan, **kwargs, confirm_provider_prerequisites_repaired=True
        )
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        **kwargs,
        confirm_provider_prerequisites_repaired=True,
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    assert binding.stopped_provider_failure_sha256 == proof_for(f).proof_sha256
    assert binding.execution_base_ref == binding.prior_execution_base_ref
    assert binding.before_inventory_sha256 == binding.after_inventory_sha256
    assert service.execute(plan.plan_sha256, authority=authority) == binding
    assert capture_mutation_inventory(f.native.worktree.path) == before
    assert all(path.read_bytes() == body for path, body in history.items())
    assert "原提供方前提失败" in service.store.required_context(binding)


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
def test_published_proof_schema_preserves_narrow_failure_boundary(
    completed: CompletedFixture,
) -> None:
    check = Draft202012Validator(
        json.loads(
            (Path(__file__).parents[2] / "schemas/stopped-provider-failure.schema.json").read_text()
        )
    )
    proof = proof_for(completed)
    check.validate(proof.to_wire())
    for problem in (
        "transient",
        "code",
        "artifact",
        "timeout",
        "receipt",
        "completed",
        "output_present",
        "original_error",
    ):
        wire = proof.to_wire()
        result = cast(WirePayload, cast(WirePayload, wire["outcome"])["result"])
        error = cast(WirePayload, result["error"])
        if problem == "transient":
            error["transient"] = True
        elif problem == "code":
            error["code"] = "INVALID_OUTPUT"
        elif problem == "artifact":
            result["artifact"] = completed.native.artifacts.list_for_task(completed.task.id)[
                0
            ].to_wire()
        elif problem == "timeout":
            cast(WirePayload, cast(WirePayload, wire["capture_stop"])["process_stop"])["kind"] = (
                "local_execution_limit"
            )
        elif problem == "completed":
            cast(WirePayload, cast(WirePayload, wire["capture_stop"])["process_stop"]).update(
                kind="completed", returncode=0
            )
        elif problem == "output_present":
            cast(WirePayload, wire["capture_stop"])["output_present"] = True
        elif problem == "original_error":
            cast(WirePayload, wire["capture_stop"])["original_error_code"] = "PROVIDER_UNAVAILABLE"
        else:
            cast(WirePayload, wire["capture_stop"])["cause"] = "provider_transient"
        assert list(check.iter_errors(wire)), problem
        with pytest.raises((ValidationError, ContinuationRejected)):
            StoppedProviderFailureProof.model_validate(wire)


@pytest.mark.parametrize(
    "completed", ["stopped_provider_missing_stop", "stopped_provider_live_process"], indirect=True
)
def test_production_collector_never_accepts_missing_or_live_stop(
    completed: CompletedFixture,
) -> None:
    f = completed
    before = f.sealed_bytes()
    with (
        f.collector.execution_scope(),
        pytest.raises((ContinuationRecordMissing, CaptureStopProcessUncertain)),
    ):
        f.collector._stopped_provider_failure(f.task, f.queue.item, f.queue.bound)
    assert f.sealed_bytes() == before and not f.queue.consumed


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
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
            f.collector._stopped_provider_failure(f.task, f.queue.item, f.queue.bound)
    else:
        with f.collector.execution_scope(), pytest.raises((ValueError, ContinuationRejected)):
            f.collector._stopped_provider_failure(f.task, f.queue.item, f.queue.bound)
    assert f.sealed_bytes() == before and not f.queue.consumed


@pytest.mark.parametrize("completed", ["stopped_provider_exhausted"], indirect=True)
def test_no_provider_refund_or_successor_reuse(completed: CompletedFixture) -> None:
    f = completed
    assert f.task.work_budget_exhausted
    with pytest.raises(ValueError, match="普通工作额度"):
        f.collector._reservation(f.task, f.queue.item, (), stopped_provider_failure=proof_for(f))
    assert f.task.retry_failures is None and not f.queue.consumed


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
def test_complete_draft_remains_required_for_stopped_provider(completed: CompletedFixture) -> None:
    f = completed
    capture = f.capture()
    (f.native.worktree.path / "src/extra.py").write_text("EXTRA = 3\n")
    before = capture_mutation_inventory(f.native.worktree.path)
    with pytest.raises(ValueError, match="全部非缓存变更"):
        require_stopped_provider_workspace(
            proof_for(f), capture, before, f.native.request.permissions, ()
        )
    assert capture_mutation_inventory(f.native.worktree.path) == before


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
def test_permanent_provider_failure_cannot_accept_new_source_mutations(
    completed: CompletedFixture,
) -> None:
    f = completed
    (f.native.worktree.path / "src/app.py").write_text("VALUE = 3\n")
    capture, before = f.capture(), capture_mutation_inventory(f.native.worktree.path)
    with pytest.raises(ValueError, match="新增的源码变更"):
        require_stopped_provider_workspace(
            proof_for(f), capture, before, f.native.request.permissions, ()
        )
    assert capture_mutation_inventory(f.native.worktree.path) == before


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
def test_source_rebind_carries_same_original_failure_and_requires_paused_confirmation(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = service_for(f)
    repository = Path(f.task.repository)
    (repository / "README.md").write_text("updated independent baseline\n")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "-m", "fixture baseline update")
    target = _git(repository, "rev-parse", "HEAD")
    plan = service.propose(target)
    assert plan.facts.stopped_provider_failure == proof_for(f)
    with pytest.raises(ValueError, match="前提"):
        BaselineOperatorAuthorization.for_plan(
            plan,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="source",
            submitted_at=datetime.now(UTC),
            continuation_mode=BaselineContinuationMode.PAUSE,
        )
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="source prerequisites",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_provider_prerequisites_repaired=True,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    assert binding.stopped_provider_failure_sha256 == proof_for(f).proof_sha256
    assert binding.execution_base_ref == target != binding.prior_execution_base_ref
    assert "VALUE = 2" in (f.native.worktree.path / "src/app.py").read_text()


def test_generic_target_free_public_command_does_not_grant_source_rebind() -> None:
    wire = {
        "purpose": "stopped_provider_retry",
        "delivery_id": "delivery_current",
        "task_id": "task_current",
        "expected_task_intent_sha256": "a" * 64,
        "expected_task_revision": 2,
        "expected_work_item_id": "work_current",
        "expected_source_revision": "b" * 40,
    }
    command = BaselineProposeCommand.model_validate(wire)
    assert "target_base_ref" not in command.to_wire()
    for changes in (
        {"target_base_ref": "c" * 40},
        {"input_mode": "coder_reapply"},
        {"purpose": "source_rebind"},
    ):
        with pytest.raises(ValidationError):
            BaselineProposeCommand.model_validate({**wire, **changes})


@pytest.mark.parametrize("completed", ["stopped_provider", "named"], indirect=True)
def test_inspection_hint_is_read_only_exact_failure_and_old_wire_remains_absent(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = DeliveryWaitService.__new__(DeliveryWaitService)
    service.repository, service.clock = f.native.repository, lambda: datetime.now(UTC)
    before = f.sealed_bytes()
    proof = service._proof(
        f.queue.item,
        f.queue.bound,
        f.task,
        start=f.start,
        outcome=f.outcome,
        observed_stop=f.capture_stop,
        missing=(DeliveryProofMissing.OUTCOME_REJECTED,),
    )
    proof.validate_integrity()
    assert not proof.permitted_resolutions and not f.queue.consumed
    if (
        f.outcome.result.error is not None
        and f.outcome.result.error.code is AgentErrorCode.AUTHENTICATION_ERROR
    ):
        assert proof.provider_failure_code == "AUTHENTICATION_ERROR"
        assert "凭证前提" in proof.next_action
    else:
        assert (
            proof.provider_failure_code is None and "provider_failure_code" not in proof.to_wire()
        )
    assert f.sealed_bytes() == before


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
@pytest.mark.parametrize("source_rebind", [False, True])
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
        plan = service.propose(None, purpose=BaselinePurpose.STOPPED_PROVIDER_RETRY)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact SQL proof fixture",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_provider_prerequisites_repaired=True,
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


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
def test_queue_consumption_requires_distinct_normal_work_identity(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = service_for(f)
    plan = service.propose(None, purpose=BaselinePurpose.STOPPED_PROVIDER_RETRY)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="queue fixture",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_provider_prerequisites_repaired=True,
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


def test_additive_provider_fields_preserve_old_canonical_wire_and_authority(tmp_path: Path) -> None:
    f = setup(tmp_path)
    plan = f.service.propose(f.target)
    authority = authorize(plan)
    binding = f.service.execute(plan.plan_sha256, authority=authority)
    assert "stopped_provider_failure" not in plan.facts.to_wire()
    assert "stopped_provider_failure_sha256" not in binding.to_wire()
    assert "confirm_provider_prerequisites_repaired" not in authority.to_wire()
    plan.validate_integrity()
    authority.validate_integrity()
    binding.validate_integrity()


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
def test_exact_original_auth_error_or_legacy_absent_code_are_allowed(
    completed: CompletedFixture,
) -> None:
    from tests.manager.test_completed_output_checkpoint import _capture_stop

    f = completed
    proof = proof_for(f)
    assert proof.capture_stop.original_error_code is AgentErrorCode.AUTHENTICATION_ERROR
    absent = StoppedProviderFailureProof.create(
        outcome=f.outcome,
        capture_start=f.capture_start,
        capture_stop=_capture_stop(f.capture_stop, original_error_code=None),
    )
    absent.validate_integrity()


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
def test_history_shows_prerequisite_declaration_and_pause_without_claiming_source_update(
    completed: CompletedFixture,
) -> None:
    from ai_software_engineer.team_view.engineering_history import engineering_history

    f = completed
    service = service_for(f)
    sidecar = f.root / "history-sidecar"
    service.store = FileExecutionBaselineStore(sidecar / "state/execution-baselines" / f.task.id)
    plan = service.propose(None, purpose=BaselinePurpose.STOPPED_PROVIDER_RETRY)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="history prerequisites",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_provider_prerequisites_repaired=True,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    before = f.sealed_bytes()
    history = engineering_history(sidecar, f.task, plan.facts.scope, f.collector.requirement_id)
    assert len(history) == 3
    assert "声明" in history[0].summary and "已检查并修复" in history[0].summary
    assert "尚未启动" in history[1].summary and "原代码基线保持" in history[2].summary
    assert all("基线更新" not in entry.summary for entry in history)
    assert history[2].details["execution_source_revision"] == binding.execution_source_revision
    assert f.sealed_bytes() == before
