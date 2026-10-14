"""Baseline queue reservations keep work and provider accounting exact."""

from pathlib import Path

import pytest

from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.domain import AgentRole, Task, TaskStatus
from ai_software_engineer.domain.retry_policy import DeliveryRetryPolicy, TransientRetryPolicy
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import BaselineExecutionFacts
from ai_software_engineer.manager.baseline_production import ProductionBaselineFactCollector
from ai_software_engineer.orchestration.continuation_models import ExecutionInterruptionReceipt
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueuedWorkItem
from tests.domain.factories import NOW, make_task
from tests.manager.test_execution_baseline import authorize, setup
from tests.orchestration.test_continuation_records import make_receipt
from tests.work_queue.test_mysql_queue import queued_item


def reservation_fixture(
    tmp_path: Path, *, provider: bool = False, work_limit: int = 3, transient_limit: int = 5
) -> tuple[ProductionBaselineFactCollector, Task, QueuedWorkItem, ExecutionInterruptionReceipt]:
    policy = DeliveryRetryPolicy(
        max_work_attempts=work_limit,
        coder=TransientRetryPolicy(max_transient_failures=transient_limit),
    )
    original = make_task()
    assert original.constraints is not None
    task = original.model_copy(
        update={
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 1,
            "max_attempts": policy.execution_limit,
            "retry_policy": policy,
            "constraints": original.constraints.model_copy(
                update={"max_attempts": policy.execution_limit}
            ),
        }
    )
    receipt = make_receipt(tmp_path)
    if provider:
        values = receipt.model_dump(mode="python", exclude={"receipt_sha256"})
        values.update(
            cause="provider_transient", original_error_code=AgentErrorCode.PROVIDER_UNAVAILABLE
        )
        receipt = ExecutionInterruptionReceipt.create(**values)
    item = queued_item().model_copy(
        update={"id": receipt.original_work_item_id, "task_id": receipt.request.task_id}
    )
    records = KnowledgeRecordStore(tmp_path / "invocations")
    start = DeliveryInvocationStart(
        work_item_id=item.id,
        checkpoint_sequence=item.checkpoint_sequence,
        request=receipt.request,
        lease_id=receipt.claim_lease_id,
        started_at=NOW,
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    records.put("invocation-starts", item.id, start)
    # The collector's public collect() performs all independent scope/stop/claim
    # checks first. This focused regression exercises its distinct accounting.
    collector = ProductionBaselineFactCollector.__new__(ProductionBaselineFactCollector)
    collector.state = tmp_path
    return collector, task, item, receipt


def test_local_window_baseline_consumes_work_without_inventing_provider_failure(
    tmp_path: Path,
) -> None:
    collector, task, item, receipt = reservation_fixture(tmp_path)
    reservation = collector._reservation(task, item, (receipt,))
    assert reservation.retry_cause == "local_execution_limit"
    assert reservation.next_execution_attempt == 2
    assert reservation.retry_failure is None and not reservation.reservation_already_applied
    already = task.model_copy(update={"attempts": 2})
    replay = collector._reservation(already, item, (receipt,))
    assert replay.next_execution_attempt == 2 and replay.reservation_already_applied
    assert task.retry_failures is None


def test_provider_baseline_reserves_one_exact_debit_and_replay_never_duplicates(
    tmp_path: Path,
) -> None:
    collector, task, item, receipt = reservation_fixture(tmp_path, provider=True)
    reservation = collector._reservation(task, item, (receipt,))
    assert reservation.retry_cause == "provider_transient"
    assert reservation.retry_failure is not None
    assert reservation.retry_failure.role is AgentRole.CODER
    assert reservation.retry_failure.run_id == receipt.request.run_id
    reserved = task.with_retry_failure(reservation.retry_failure)
    assert reserved.attempts == 2 and reserved.work_attempt == task.work_attempt
    replay = collector._reservation(reserved, item, (receipt,))
    assert replay.reservation_already_applied
    assert replay.next_execution_attempt == 2
    assert replay.retry_failure is not None
    assert reserved.with_retry_failure(replay.retry_failure) == reserved


def _sealed_failure(
    root: Path, item: QueuedWorkItem, *, code: AgentErrorCode, transient: bool
) -> DeliveryInvocationOutcome:
    records = KnowledgeRecordStore(root / "invocations")
    start = records.get("invocation-starts", item.id, DeliveryInvocationStart)
    request = start.request
    result = AgentResult(
        run_id=request.run_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        status=AgentRunStatus.TIMED_OUT
        if code is AgentErrorCode.TIMEOUT
        else AgentRunStatus.FAILED,
        error=AgentFailure(code=code, transient=transient, message="sealed provider failure"),
    )
    outcome = DeliveryInvocationOutcome(start=start, result=result, outcome_sha256="0" * 64)
    outcome = outcome.model_copy(
        update={
            "outcome_sha256": digest(outcome.model_dump(mode="json", exclude={"outcome_sha256"}))
        }
    )
    records.put("invocation-outcomes", item.id, outcome)
    return outcome


@pytest.mark.parametrize(
    "code",
    [
        AgentErrorCode.TIMEOUT,
        AgentErrorCode.QUOTA_EXHAUSTED,
        AgentErrorCode.RATE_LIMITED,
        AgentErrorCode.PROVIDER_UNAVAILABLE,
    ],
)
@pytest.mark.parametrize("transient", [False, True])
@pytest.mark.parametrize("work_limit", [1, 3])
def test_sealed_failure_requires_code_and_transient_before_provider_accounting(
    tmp_path: Path, code: AgentErrorCode, transient: bool, work_limit: int
) -> None:
    collector, task, item, _ = reservation_fixture(tmp_path, work_limit=work_limit)
    outcome = _sealed_failure(tmp_path, item, code=code, transient=transient)
    original_task = task.to_wire()
    original_files = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    assert task.work_budget_exhausted is (work_limit == 1)
    if transient:
        reservation = collector._reservation(task, item, ())
        assert reservation.retry_cause == "provider_transient"
        assert reservation.retry_failure is not None
        assert reservation.retry_failure.code == code.value
        assert reservation.current_invocation_outcome_sha256 == outcome.outcome_sha256
        reserved = task.with_retry_failure(reservation.retry_failure)
        assert reserved.attempts == task.attempts + 1
        assert reserved.work_attempt == task.work_attempt
        replay = collector._reservation(reserved, item, ())
        assert replay.reservation_already_applied
        assert replay.next_execution_attempt == reserved.attempts
        assert replay.retry_failure == reservation.retry_failure
    else:
        with pytest.raises(ValueError, match="明确、可预算"):
            collector._reservation(task, item, ())
    assert task.to_wire() == original_task and task.retry_failures is None
    assert {path: path.read_bytes() for path in tmp_path.rglob("*.json")} == original_files
    assert (
        KnowledgeRecordStore(tmp_path / "invocations").get(
            "invocation-outcomes", item.id, DeliveryInvocationOutcome
        )
        == outcome
    )


def test_transient_flag_cannot_admit_a_nonallowlisted_error_code(tmp_path: Path) -> None:
    collector, task, item, _ = reservation_fixture(tmp_path)
    outcome = _sealed_failure(
        tmp_path, item, code=AgentErrorCode.AUTHENTICATION_ERROR, transient=True
    )
    with pytest.raises(ValueError, match="明确、可预算"):
        collector._reservation(task, item, ())
    assert task.retry_failures is None
    assert (
        KnowledgeRecordStore(tmp_path / "invocations").get(
            "invocation-outcomes", item.id, DeliveryInvocationOutcome
        )
        == outcome
    )


@pytest.mark.parametrize("provider", [False, True])
def test_baseline_refuses_exhausted_matching_budget(tmp_path: Path, provider: bool) -> None:
    collector, task, item, receipt = reservation_fixture(
        tmp_path,
        provider=provider,
        work_limit=1 if not provider else 3,
        transient_limit=1 if provider else 5,
    )
    with pytest.raises(ValueError, match="额度"):
        collector._reservation(task, item, (receipt,))


def test_uninvoked_item_keeps_its_exact_attempt_and_cannot_claim_old_receipt(
    tmp_path: Path,
) -> None:
    collector, task, item, receipt = reservation_fixture(tmp_path)
    item = item.model_copy(update={"id": "work_uninvoked_current"})
    reservation = collector._reservation(task, item, (receipt,))
    assert reservation.retry_cause == "uninvoked"
    assert reservation.current_attempt == reservation.next_execution_attempt == 1
    assert reservation.original_run_id is None and reservation.retry_failure is None
    assert reservation.reservation_already_applied


def test_completed_baseline_replay_uses_frozen_intent_after_queue_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = setup(tmp_path)
    plan = f.service.propose(f.target)
    authority = authorize(plan)
    binding = f.service.execute(plan.plan_sha256, authority=authority)
    f.collector.facts = f.collector.facts.model_copy(
        update={"task": f.collector.facts.task.model_copy(update={"attempts": 2})}
    )

    def no_old_facts(target: str) -> BaselineExecutionFacts:
        del target
        raise AssertionError(
            "completed Git operation must not recollect obsolete queue/source/counters"
        )

    monkeypatch.setattr(f.collector, "collect", no_old_facts)
    assert f.service.execute(plan.plan_sha256, authority=authority) == binding
    assert f.service.store.bindings_for_task(binding.task_id) == (binding,)


@pytest.mark.parametrize("returned_route", [False, True])
def test_service_pause_no_start_baseline_uses_new_work_without_provider_refund(
    tmp_path: Path,
    returned_route: bool,
) -> None:
    from ai_software_engineer.agents.execution import (
        PausedInvocationProof,
        SynchronousToolLoopStop,
    )

    collector, task, item, _ = reservation_fixture(tmp_path, work_limit=3)
    records = KnowledgeRecordStore(tmp_path / "invocations")
    start = records.get("invocation-starts", item.id, DeliveryInvocationStart)
    result = AgentResult(
        run_id=start.request.run_id,
        task_id=start.request.task_id,
        role=start.request.role,
        attempt=start.request.attempt,
        source_revision=start.request.source_revision,
        context_manifest_id=start.request.context_manifest_id,
        status=AgentRunStatus.FAILED,
        error=AgentFailure(
            code=AgentErrorCode.SERVICE_PAUSED,
            message="服务重启已暂停执行。",
            transient=False,
        ),
    )
    outcome = DeliveryInvocationOutcome(
        start=start,
        result=result,
        service_pause=PausedInvocationProof.create(
            request=start.request,
            admission_closed=not returned_route,
            process_stop=SynchronousToolLoopStop.create(
                task_id=start.request.task_id,
                run_id=start.request.run_id,
                request_sha256=digest(start.request.to_wire()),
                completed_operation_ids=("model-route.1",),
                kind="service_pause",
                stopped_at=NOW,
            )
            if returned_route
            else None,
        ),
        outcome_sha256="0" * 64,
    )
    outcome = outcome.model_copy(
        update={
            "outcome_sha256": digest(outcome.model_dump(mode="json", exclude={"outcome_sha256"}))
        }
    )
    records.put("invocation-outcomes", item.id, outcome)
    reservation = collector._reservation(task, item, ())
    assert reservation.retry_cause == "service_pause"
    assert reservation.next_execution_attempt == task.attempts + 1
    assert reservation.retry_failure is None
    assert reservation.current_invocation_outcome_sha256 == outcome.outcome_sha256
    assert not reservation.reservation_already_applied

    exhausted = task.model_copy(update={"attempts": task.max_attempts})
    with pytest.raises(ValueError, match="额度"):
        collector._reservation(exhausted, item, ())
