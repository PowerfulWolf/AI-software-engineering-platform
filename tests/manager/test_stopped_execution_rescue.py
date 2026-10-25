"""A real stopped session can preserve its draft without inventing an outcome."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, ModelRouteAttempt
from ai_software_engineer.domain.artifact import CoderProgressArtifact
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode, BaselinePurpose
from ai_software_engineer.git.baseline import GitExecutionBaselineAdapter
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionFacts,
    BaselineExecutionReservation,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.execution_baseline import ExecutionBaselineService
from ai_software_engineer.manager.stopped_execution_checkpoint import StoppedCoderExecutionProof
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.owned_sessions import OwnedProcessIdentity, OwnedSessionStopProof
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.web_console.models import ProposeExecutionBaselineIntent
from ai_software_engineer.work_queue.execution_store import RoleQueueAdmission
from ai_software_engineer.work_queue.models import QueueArtifactReceipt
from tests.domain.factories import make_coder_progress_artifact
from tests.manager.test_completed_output_checkpoint import CompletedFixture
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.manager.test_completed_output_rescue import public_input
from tests.manager.test_execution_baseline import Collector


def test_stopped_rescue_public_target_free_input() -> None:
    wire = {**public_input(), "purpose": "stopped_execution_rescue"}
    intent = ProposeExecutionBaselineIntent.model_validate(wire)
    assert intent.target_base_ref is None
    assert "target_base_ref" not in intent.to_wire()
    for change in ({"target_base_ref": "d" * 40}, {"input_mode": "coder_reapply"}):
        with pytest.raises(ValidationError):
            ProposeExecutionBaselineIntent.model_validate({**wire, **change})


completed = completed_fixture


def proof_for(f: CompletedFixture) -> StoppedCoderExecutionProof:
    return StoppedCoderExecutionProof.create(
        invocation_start=f.start, capture_start=f.capture_start, capture_stop=f.capture_stop
    )


@pytest.mark.parametrize("completed", ["named"], indirect=True)
def test_stopped_proof_v2_preserves_completed_output_without_outcome(
    completed: CompletedFixture,
) -> None:
    """A completed native process with no published outcome uses the additive v2 proof."""
    f = completed
    stop = f.capture_stop
    process = stop.process_stop
    leader = OwnedProcessIdentity(
        process_id=process.process_id,
        group_id=process.process_id,
        session_id=process.process_id,
        birth_identity="fixture:leader",
    )
    child = OwnedProcessIdentity(
        process_id=process.process_id + 1,
        group_id=process.process_id + 1,
        session_id=process.process_id,
        birth_identity="fixture:child",
    )
    session = OwnedSessionStopProof.create(
        boot_identity="fixture:boot",
        leader=leader,
        observed_processes=(leader, child),
        observation_count=2,
        observations_sha256="a" * 64,
        observed_at=process.stopped_at,
    )
    completed_process = process.create(
        process_id=process.process_id,
        group_id=process.group_id,
        returncode=0,
        kind="completed",
        stopped_at=process.stopped_at,
        session_proof=session,
    )
    capture_stop = stop.create(
        task_id=stop.task_id,
        run_id=stop.run_id,
        capture_start_sha256=stop.capture_start_sha256,
        process_stop=completed_process,
        output_present=True,
        cause=None,
        original_error_code=None,
    )
    proof = StoppedCoderExecutionProof.create(
        schema_version="v2",
        invocation_start=f.start,
        capture_start=f.capture_start,
        capture_stop=capture_stop,
    )
    proof.validate_integrity()
    Draft202012Validator(
        json.loads(
            (Path(__file__).parents[2] / "schemas/stopped-coder-execution.schema.json").read_text()
        )
    ).validate(proof.to_wire())
    assert proof.schema_version == "v2"
    assert proof.capture_stop.output_present is True
    with pytest.raises(ValueError):
        StoppedCoderExecutionProof.create(
            schema_version="v1",
            invocation_start=f.start,
            capture_start=f.capture_start,
            capture_stop=capture_stop,
        )


@pytest.mark.parametrize("completed", ["named"], indirect=True)
def test_stopped_schema_omitted_version_keeps_historical_v1_guard(
    completed: CompletedFixture,
) -> None:
    f = completed
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/stopped-coder-execution.schema.json").read_text()
    )
    validator = Draft202012Validator(schema)
    process = f.capture_stop.process_stop
    leader = OwnedProcessIdentity(
        process_id=process.process_id,
        group_id=process.process_id,
        session_id=process.process_id,
        birth_identity="fixture:legacy-v1-leader",
    )
    child = OwnedProcessIdentity(
        process_id=process.process_id + 1,
        group_id=process.process_id + 1,
        session_id=process.process_id,
        birth_identity="fixture:legacy-v1-child",
    )
    session = OwnedSessionStopProof.create(
        boot_identity="fixture:legacy-v1-boot",
        leader=leader,
        observed_processes=(leader, child),
        observation_count=2,
        observations_sha256="c" * 64,
        observed_at=process.stopped_at,
    )
    failed_process = process.create(
        process_id=process.process_id,
        group_id=process.group_id,
        returncode=-1,
        kind="failed",
        stopped_at=process.stopped_at,
        session_proof=session,
    )
    failed_stop = f.capture_stop.create(
        task_id=f.capture_stop.task_id,
        run_id=f.capture_stop.run_id,
        capture_start_sha256=f.capture_stop.capture_start_sha256,
        process_stop=failed_process,
        output_present=False,
        cause=None,
        original_error_code=None,
    )
    legacy = StoppedCoderExecutionProof.create(
        invocation_start=f.start, capture_start=f.capture_start, capture_stop=failed_stop
    ).to_wire()
    assert isinstance(legacy, dict)
    legacy.pop("schema_version", None)
    validator.validate(legacy)

    process = f.capture_stop.process_stop
    leader = OwnedProcessIdentity(
        process_id=process.process_id,
        group_id=process.process_id,
        session_id=process.process_id,
        birth_identity="fixture:legacy-v2-leader",
    )
    child = OwnedProcessIdentity(
        process_id=process.process_id + 1,
        group_id=process.process_id + 1,
        session_id=process.process_id,
        birth_identity="fixture:legacy-v2-child",
    )
    session = OwnedSessionStopProof.create(
        boot_identity="fixture:legacy-v2-boot",
        leader=leader,
        observed_processes=(leader, child),
        observation_count=2,
        observations_sha256="b" * 64,
        observed_at=process.stopped_at,
    )
    completed_process = process.create(
        process_id=process.process_id,
        group_id=process.group_id,
        returncode=0,
        kind="completed",
        stopped_at=process.stopped_at,
        session_proof=session,
    )
    completed_stop = f.capture_stop.create(
        task_id=f.capture_stop.task_id,
        run_id=f.capture_stop.run_id,
        capture_start_sha256=f.capture_stop.capture_start_sha256,
        process_stop=completed_process,
        output_present=True,
        cause=None,
        original_error_code=None,
    )
    unqualified = StoppedCoderExecutionProof.create(
        schema_version="v2",
        invocation_start=f.start,
        capture_start=f.capture_start,
        capture_stop=completed_stop,
    ).to_wire()
    assert isinstance(unqualified, dict)
    unqualified.pop("schema_version", None)
    assert not validator.is_valid(unqualified)


def service_for(
    f: CompletedFixture, *, progress: CoderProgressArtifact | None = None
) -> ExecutionBaselineService:
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
        progress_artifact_id=progress.artifact_id if progress is not None else None,
        continuation=f.collector._reservation(f.task, f.queue.item, (), stopped_execution=proof),
        stopped_execution=proof,
        permissions=f.native.request.permissions,
        denied_paths=(),
        facts_sha256="0" * 64,
    )
    facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    return ExecutionBaselineService(
        store=FileExecutionBaselineStore(f.root / "stopped-records"),
        git=GitExecutionBaselineAdapter(f.native.git),
        facts=Collector(facts, f.native.worktree),
    )


@pytest.mark.parametrize("completed", ["stopped_unknown_named"], indirect=True)
def test_stopped_proof_and_pause_preserve_original_unknown_history(
    completed: CompletedFixture,
) -> None:
    f = completed
    proof = proof_for(f)
    proof.validate_integrity()
    Draft202012Validator(
        json.loads(
            (Path(__file__).parents[2] / "schemas/stopped-coder-execution.schema.json").read_text()
        )
    ).validate(proof.to_wire())
    assert proof.capture_stop.original_error_code is not None
    assert proof.capture_stop.original_error_code.value == "PROVIDER_ERROR"
    with f.collector.execution_scope():
        assert f.collector._stopped_execution(f.task, f.queue.item, f.queue.bound) == proof
    history, inventory, task = (
        f.sealed_bytes(),
        capture_mutation_inventory(f.native.worktree.path),
        f.task,
    )
    service = service_for(f)
    plan = service.propose(None, purpose=BaselinePurpose.STOPPED_EXECUTION_RESCUE)
    with pytest.raises(ValueError, match="暂停"):
        BaselineOperatorAuthorization.for_plan(
            plan,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="exact unknown-stop decision",
            submitted_at=datetime.now(UTC),
        )
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact unknown-stop decision",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    assert service.execute(plan.plan_sha256, authority=authority) == binding
    assert binding.stopped_execution_sha256 == proof.proof_sha256
    assert binding.execution_base_ref == binding.prior_execution_base_ref
    assert binding.execution_source_revision == binding.prior_source_revision
    assert binding.before_inventory_sha256 == binding.after_inventory_sha256
    assert all(path.read_bytes() == body for path, body in history.items())
    assert capture_mutation_inventory(f.native.worktree.path) == inventory and f.task == task
    assert plan.facts.continuation is not None and plan.facts.continuation.retry_failure is None
    assert plan.facts.continuation.next_execution_attempt == f.task.attempts + 1
    assert "原结果及原因仍未知" in service.store.required_context(binding)


@pytest.mark.parametrize("completed", ["stopped_unknown_named"], indirect=True)
@pytest.mark.parametrize("change", ["no_session", "output", "cause", "foreign_start", "digest"])
def test_stopped_proof_refuses_weaker_or_foreign_stop(
    completed: CompletedFixture, change: str
) -> None:
    f = completed
    wire = proof_for(f).to_wire()
    stop = wire["capture_stop"]
    start = wire["invocation_start"]
    assert isinstance(stop, dict) and isinstance(start, dict)
    if change == "no_session":
        process = stop["process_stop"]
        assert isinstance(process, dict)
        process["session_proof"] = None
    elif change == "output":
        stop["output_present"] = True
    elif change == "cause":
        stop["cause"] = "local_execution_limit"
    elif change == "foreign_start":
        start["lease_id"] = "lease_foreign"
    else:
        stop["observation_sha256"] = "f" * 64
    with pytest.raises((ValueError, ContinuationRejected)):
        StoppedCoderExecutionProof.model_validate(wire)


@pytest.mark.parametrize("completed", ["stopped_unknown_named"], indirect=True)
@pytest.mark.parametrize(
    "change",
    [
        {"retry_failure": {}},
        {"current_invocation_outcome_sha256": "f" * 64},
        {"reservation_already_applied": True},
        {"next_execution_attempt": 1},
        {"interruption_receipt_sha256": "f" * 64},
    ],
)
def test_stopped_reservation_refuses_result_refund_and_duplicate_work(
    completed: CompletedFixture, change: dict[str, object]
) -> None:
    f = completed
    reservation = f.collector._reservation(f.task, f.queue.item, (), stopped_execution=proof_for(f))
    with pytest.raises(ValueError):
        BaselineExecutionReservation.model_validate({**reservation.to_wire(), **change})


@pytest.mark.parametrize("completed", ["stopped_unknown_named"], indirect=True)
def test_stopped_plan_cannot_change_purpose_or_source(completed: CompletedFixture) -> None:
    plan = service_for(completed).propose(None, purpose=BaselinePurpose.STOPPED_EXECUTION_RESCUE)
    for change in (
        {"purpose": "source_rebind"},
        {"target_base_ref": "f" * 40},
        {"input_mode": "coder_reapply"},
        {"conflicted": True},
    ):
        with pytest.raises(ValueError):
            ExecutionBaselinePlan.model_validate({**plan.to_wire(), **change})


@pytest.mark.parametrize("completed", ["stopped_unknown_named"], indirect=True)
@pytest.mark.parametrize("kind", ["outcome", "artifact", "final_route", "fallback_route"])
def test_stopped_collector_freshly_rejects_an_existing_result_or_unproved_route(
    completed: CompletedFixture, kind: str
) -> None:
    f = completed
    if kind == "outcome":
        KnowledgeRecordStore(f.root / "invocations").put(
            "invocation-outcomes", f.queue.item.id, f.outcome
        )
    elif kind == "artifact":
        f.queue.queue_admission = RoleQueueAdmission(
            task_id=f.task.id,
            repository_id=f.collector.scope.repository_id,
            allocation_sha256=f.queue.bound.allocation_sha256,
            legacy_artifacts=tuple(
                QueueArtifactReceipt(
                    artifact_id=artifact.artifact_id, sha256=artifact.integrity.sha256
                )
                for artifact in f.native.artifacts.list_for_task(f.task.id)
            ),
        )
        leaked = f.native._accept(
            make_coder_progress_artifact(),
            run_id=f.start.request.run_id,
            source=f.start.request.source_revision,
        )
        assert leaked in f.collector.capacity_artifacts.list_for_task(f.task.id)
        assert leaked not in f.collector.artifacts.list_for_task(f.task.id)
        assert f.queue.accepted(f.task.id) == ()
    else:
        route = ModelRouteAttempt.create(
            request=f.start.request,
            route_index=1,
            provider="codex",
            model="offline fixture",
            route_kind="codex_cli",
            started_at=f.start.started_at,
            completed_at=f.start.started_at + timedelta(seconds=1),
            result=f.outcome.result,
            fallback=kind == "fallback_route",
        )
        assert f.collector.route_root is not None
        FileModelRouteAttemptStore(f.collector.route_root).append(route)
    before = f.sealed_bytes()
    with f.collector.execution_scope(), pytest.raises(ValueError):
        f.collector._stopped_execution(f.task, f.queue.item, f.queue.bound)
    assert f.sealed_bytes() == before and not f.queue.consumed


@pytest.mark.parametrize("completed", ["stopped_unknown_exhausted"], indirect=True)
def test_stopped_rescue_never_refunds_exhausted_work(completed: CompletedFixture) -> None:
    f = completed
    before, task = f.sealed_bytes(), f.task
    assert task.work_budget_exhausted
    with pytest.raises(ValueError, match="工作额度"):
        f.collector._reservation(task, f.queue.item, (), stopped_execution=proof_for(f))
    assert f.task == task and f.sealed_bytes() == before and not f.queue.consumed
