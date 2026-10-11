"""Stopped permanent failures must not wait forever on unused transient allowance."""

import json
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from pymysql.cursors import DictCursor

from ai_software_engineer.domain import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryWaitHandling,
    HandleDeliveryWait,
    InspectDeliveryWait,
)
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.stopped_budget_settlement import StoppedFailureBudgetSettlement
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_wait import DeliveryWaitService
from ai_software_engineer.manager.stopped_budget_settlement import StoppedBudgetSettlementService
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from tests.manager.test_completed_output_checkpoint import CompletedFixture, CompletedQueue
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.orchestration.test_native_continuation import NOW

completed = completed_fixture


class FixtureQueue(CompletedQueue):
    fixture: CompletedFixture
    commits: int = 0
    fail_before: bool = False
    fail_after: bool = False

    def settle_stopped_budget(
        self, cursor: DictCursor, record: StoppedFailureBudgetSettlement
    ) -> None:
        assert self.entered
        record.validate_integrity()
        if self.fail_before:
            self.fail_before = False
            raise RuntimeError("test crash before SQL commit")
        repo = self.fixture.native.repository
        if repo.get(record.task.id).status is TaskStatus.IMPLEMENTING:
            repo.append_event(record.event)
            self.item = self.item.model_copy(
                update={
                    "status": WorkItemStatus.CLOSED,
                    "wait_disposition": None,
                    "wait_reason": None,
                    "updated_at": record.event.occurred_at,
                }
            )
            self.commits += 1
        if self.fail_after:
            self.fail_after = False
            raise RuntimeError("test crash after SQL commit")


def _service(f: CompletedFixture) -> DeliveryWaitService:
    queue = object.__new__(FixtureQueue)
    queue.__dict__.update(f.queue.__dict__)
    queue.fixture = f
    assert queue.item.wait_disposition is not None
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts.model_validate(
            {**queue.item.wait_disposition.facts.to_wire(), "classification": "TRANSIENT_INFRA"}
        )
    )
    queue.item = queue.item.model_copy(
        update={
            "wait_disposition": disposition,
            "wait_reason": disposition.reason,
            "status": WorkItemStatus.WAITING_DEPENDENCY,
        }
    )
    f.queue = queue
    collector = DeliveryWaitFactCollector(
        sidecar_state=f.root,
        route_root=f.root / "model-routes",
        scope=f.collector.scope,
        expected_continuation_scope=f.native.scope,
        git=f.native.git,
        queue=queue,
    )
    return DeliveryWaitService(
        repository=f.native.repository,
        scope=f.collector.scope,
        queue=f.queue,
        sidecar_state=f.root,
        git=f.native.git,
        principal=LocalOperatorPrincipal.trusted_local(),
        consume=f.queue.consume,
        clock=lambda: NOW + timedelta(seconds=2),
        stop_observer=collector.observe_stop,
        budget_settlement=StoppedBudgetSettlementService(
            repository=f.native.repository,
            queue=queue,
            records=KnowledgeRecordStore(f.root / "delivery-waits"),
            collector=collector,
            git=f.native.git,
            clock=lambda: NOW + timedelta(seconds=2),
            idle_scope=lambda: queue.idle_task_scope(f.task.id),
        ),
    )


@pytest.mark.parametrize("completed", ["stopped_provider_exhausted"], indirect=True)
def test_handle_settles_stopped_exhausted_task_without_refund(completed: CompletedFixture) -> None:
    f = completed
    before = f.task
    events = f.native.repository.list_events(before.id)
    assert before.work_budget_exhausted
    service = _service(f)
    command = HandleDeliveryWait.model_validate(f.queue.command().to_wire())
    result = service.handle(command)
    assert f.task.status is TaskStatus.BLOCKED
    assert f.task.attempts == before.attempts
    assert f.task.retry_failures == before.retry_failures
    assert f.native.repository.list_events(before.id)[:-1] == events
    assert result.status == "BUDGET_EXHAUSTED"
    assert result.budget_settlement_sha256 is not None
    assert service.handle(command) == result
    assert cast(FixtureQueue, f.queue).commits == 1
    schemas = Path(__file__).parents[2] / "schemas"
    validator = Draft202012Validator(
        json.loads((schemas / "engineering-wait-resolution.schema.json").read_text())
    )
    validator.validate(result.to_wire())
    for status in ("RESOLVED", "PLATFORM_ATTENTION", "WAITING_PREREQUISITES"):
        invalid = {**result.to_wire(), "status": status}
        assert not validator.is_valid(invalid)
        with pytest.raises(ValidationError):
            DeliveryWaitHandling.model_validate(invalid)
    record = service.records.get(
        "stopped-budget-settlements",
        result.budget_settlement_sha256,
        StoppedFailureBudgetSettlement,
    )
    Draft202012Validator(
        json.loads((schemas / "stopped-failure-budget-settlement.schema.json").read_text())
    ).validate(record.to_wire())
    original_wire = {**result.to_wire()}
    original_wire.pop("budget_settlement_sha256")
    legacy = DeliveryWaitHandling.model_validate(original_wire)
    assert "budget_settlement_sha256" not in legacy.to_wire()


@pytest.mark.parametrize("completed", ["stopped_provider_exhausted"], indirect=True)
@pytest.mark.parametrize("phase", ["before", "after"])
def test_crash_replays_exact_sealed_settlement(completed: CompletedFixture, phase: str) -> None:
    f = completed
    service = _service(f)
    queue = cast(FixtureQueue, f.queue)
    command = HandleDeliveryWait.model_validate(queue.command().to_wire())
    before = f.native.repository.list_events(f.task.id)
    queue.fail_before, queue.fail_after = phase == "before", phase == "after"
    with pytest.raises(RuntimeError, match="test crash"):
        service.handle(command)
    record = service.handle(command)
    assert service.handle(command) == record
    assert queue.commits == 1
    assert f.native.repository.list_events(f.task.id)[:-1] == before


@pytest.mark.parametrize("completed", ["stopped_provider_exhausted"], indirect=True)
def test_inspect_remains_read_only_even_when_budget_exhausted(completed: CompletedFixture) -> None:
    f = completed
    service = _service(f)
    before = f.task
    events = f.native.repository.list_events(before.id)
    service.inspect(InspectDeliveryWait.model_validate(f.queue.command().to_wire()))
    assert f.task == before
    assert f.native.repository.list_events(before.id) == events
    assert not tuple((f.root / "delivery-waits" / "stopped-budget-settlements").glob("*"))


@pytest.mark.parametrize("completed", ["stopped_provider_exhausted"], indirect=True)
def test_complete_inventory_drift_refuses_without_mutation(completed: CompletedFixture) -> None:
    f = completed
    service = _service(f)
    before = f.task
    events = f.native.repository.list_events(before.id)
    (f.native.worktree.path / "src/app.py").write_text("VALUE = 3\n")
    with pytest.raises(ContinuationRejected, match="完整工作现场已变化"):
        service.handle(HandleDeliveryWait.model_validate(f.queue.command().to_wire()))
    assert f.task == before
    assert f.native.repository.list_events(before.id) == events
    assert cast(FixtureQueue, f.queue).commits == 0


@pytest.mark.parametrize("completed", ["stopped_provider"], indirect=True)
def test_unexhausted_task_is_not_ended(completed: CompletedFixture) -> None:
    f = completed
    service = _service(f)
    before = f.task
    assert not before.work_budget_exhausted
    result = service.handle(HandleDeliveryWait.model_validate(f.queue.command().to_wire()))
    assert result.budget_settlement_sha256 is None
    assert f.task == before
    assert cast(FixtureQueue, f.queue).commits == 0
