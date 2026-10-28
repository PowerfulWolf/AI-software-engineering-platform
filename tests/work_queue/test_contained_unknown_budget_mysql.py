"""Real MySQL fence and replay for an exhausted start-only Coder declaration."""

import json
import os
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.domain import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.contained_unknown_budget import ContainedUnknownBudgetSettlement
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import HandleDeliveryWait
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.evaluation import FileEvaluationEventStore, HumanActionEvent
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.contained_unknown_budget import (
    ContainedUnknownBudgetSettlementService,
)
from ai_software_engineer.manager.delivery_wait import DeliveryWaitService
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.continuation_models import ExecutionCaptureStart
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.runtime import _default_case_id
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue.dispatcher import DispatcherLoop, DispatcherTickStatus
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, RoleQueueAdmission
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from ai_software_engineer.work_queue.models import QueueClaim
from tests.manager.test_completed_output_checkpoint import CompletedFixture
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.manager.test_contained_unknown_budget import FakeBootObserver, FakeLocalObserver
from tests.work_queue.test_mysql_queue import agents, demand, policy
from tests.work_queue.test_worker_mysql import TOKEN

completed = completed_fixture
pytestmark = [
    pytest.mark.mysql,
    pytest.mark.parametrize("completed", ["start_only_unknown_exhausted"], indirect=True),
]


@dataclass
class RealContainedWait:
    repository: MySqlTaskRepository
    queue: MySqlRoleQueue
    service: DeliveryWaitService
    command: HandleDeliveryWait
    state: Path
    dsn: str


def _claim_coder(queue: MySqlRoleQueue, work_item_id: str) -> QueueClaim:
    source_policy = policy()
    codex_policy = source_policy.model_copy(
        update={
            "routes": tuple(
                route.model_copy(update={"route_kind": "codex_cli"})
                for route in source_policy.routes
            )
        }
    )
    profiles = tuple(
        profile.model_copy(update={"id": f"agent_{profile.eligible_roles[0].value}_001"})
        for profile in agents()
    )
    dispatcher = DispatcherLoop(
        queue=queue,
        scheduler=PortfolioScheduler(lease_duration=timedelta(minutes=15)),
        model_router=ModelRouter(
            route_context_capacities={
                (route.provider, route.model): 128_000 for route in codex_policy.routes
            }
        ),
        agents=profiles,
        policies=(codex_policy,),
        demand_builder=demand,
        worker_id="worker_contained_unknown",
        owner_token_factory=lambda: TOKEN,
    )
    tick = dispatcher.tick(now=datetime.now(UTC), work_item_id=work_item_id)
    assert tick.status is DispatcherTickStatus.DISPATCHED and tick.claim is not None
    assert tick.claim.model_selection.route_kind == "codex_cli"
    return tick.claim


@pytest.fixture
def real_contained_wait(
    completed: CompletedFixture, tmp_path: Path
) -> Iterator[RealContainedWait]:
    dsn = os.environ["ASE_TEST_MYSQL_DSN"]
    f = completed
    state = tmp_path / "mysql-contained-state"
    with MySqlTaskRepository(dsn) as repository:
        repository.create(f.native.task)
        repository.record_attempt(f.task.id, 1)
        for event in f.native.repository.list_events(f.task.id):
            repository.append_event(event)
        task = repository.get(f.task.id)
        assert task.work_budget_exhausted
        queue = MySqlRoleQueue(dsn)
        ready = f.queue.bound.model_copy(
            update={
                "work_item": f.queue.bound.work_item.model_copy(
                    update={"status": WorkItemStatus.READY}
                )
            }
        )
        queue.admit(
            RoleQueueAdmission(
                task_id=task.id,
                repository_id=ready.work_item.repository_id,
                allocation_sha256=ready.allocation_sha256,
                legacy_artifacts=(),
            ),
            ready,
        )
        claim = _claim_coder(queue, ready.work_item.id)
        request = f.native.request
        now = datetime.now(UTC)
        start = DeliveryInvocationStart(
            work_item_id=ready.work_item.id,
            checkpoint_sequence=ready.boundary.checkpoint_sequence,
            request=request,
            lease_id=claim.lease.id,
            started_at=now,
            start_sha256="0" * 64,
        )
        start = start.model_copy(
            update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
        )
        assert task.interruption_continuation_policy is not None
        capture_start = ExecutionCaptureStart.create(
            **{
                **f.capture_start.model_dump(mode="python", exclude={"start_sha256"}),
                "claim": claim,
                "request": request,
                "task_intent_sha256": task_intent_sha256(task),
                "policy_sha256": task.interruption_continuation_policy.policy_sha256,
                "task_revision": repository.current_revision(task.id),
                "started_at": now,
            }
        )
        KnowledgeRecordStore(state / "invocations").put(
            "invocation-starts", ready.work_item.id, start
        )
        (state / "continuations").mkdir(mode=0o700)
        ledger = FileContinuationStore.initialize(
            state / "continuations" / task.id, task_id=task.id
        )
        ledger.put_capture_start(capture_start)
        assert f.queue.item.wait_disposition is not None
        disposition = decide_delivery_disposition(
            DeliveryFailureFacts.model_validate(
                {
                    **f.queue.item.wait_disposition.facts.to_wire(),
                    "work_item_id": ready.work_item.id,
                    "task_intent_sha256": task_intent_sha256(task),
                    "classification": "EXECUTION_UNCERTAIN",
                    "budget_available": False,
                }
            )
        )
        item = queue.wait(
            ready.work_item.id,
            lease_id=claim.lease.id,
            owner_token=TOKEN,
            status=WorkItemStatus.WAITING_DEPENDENCY,
            reason=disposition.reason,
            disposition=disposition,
            now=datetime.now(UTC),
        )
        collector = DeliveryWaitFactCollector(
            sidecar_state=state,
            route_root=state / "routes",
            scope=f.collector.scope,
            expected_continuation_scope=f.native.scope,
            git=f.native.git,
            queue=queue,
        )
        artifacts = FileArtifactStore(f.root / "accepted-artifacts", read_only=True)
        contained = ContainedUnknownBudgetSettlementService(
            repository=repository,
            queue=queue,
            records=KnowledgeRecordStore(state / "delivery-preflight"),
            collector=collector,
            git=f.native.git,
            artifacts=artifacts,
            principal=LocalOperatorPrincipal.trusted_local(),
            boot_observer=FakeBootObserver(f),
            local_execution_observer=FakeLocalObserver(),
            evaluation_root=state / "evaluations",
            clock=lambda: datetime.now(UTC),
            idle_scope=lambda: queue.idle_task_scope(task.id),
        )
        service = DeliveryWaitService(
            repository=repository,
            queue=queue,
            scope=f.collector.scope,
            sidecar_state=state,
            git=f.native.git,
            principal=LocalOperatorPrincipal.trusted_local(),
            consume=lambda resolution: None,
            artifacts=artifacts,
            contained_unknown_budget_settlement=contained,
        )
        command = HandleDeliveryWait(
            work_item_id=item.id,
            expected_disposition_sha256=disposition.disposition_sha256,
            expected_task_intent_sha256=disposition.facts.task_intent_sha256,
            expected_source_revision=disposition.facts.source_revision,
            expected_checkpoint_sequence=item.checkpoint_sequence,
            confirm_local_execution_stopped=True,
            local_stop_reference="call_a7e4ebe2aed34bad899f8cc3588da3b5",
        )
        yield RealContainedWait(repository, queue, service, command, state, dsn)


def test_contained_unknown_sql_commit_and_exact_replay(
    real_contained_wait: RealContainedWait,
) -> None:
    f = real_contained_wait
    before = f.repository.get(f.queue.get(f.command.work_item_id).task_id)

    result = f.service.handle(f.command)

    after = f.repository.get(before.id)
    assert result.status == "BUDGET_EXHAUSTED"
    assert after.status is TaskStatus.BLOCKED
    assert after.attempts == before.attempts
    assert after.retry_failures == before.retry_failures
    assert f.queue.get(f.command.work_item_id).status is WorkItemStatus.CLOSED
    with (
        closing(open_mysql_connection(f.dsn)) as connection,
        connection.cursor(DictCursor) as cursor,
    ):
        cursor.execute(
            "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s AND event_type=%s",
            (f.command.work_item_id, "CONTAINED_UNKNOWN_BUDGET_SETTLED"),
        )
        rows = cursor.fetchall()
    assert len(rows) == 1
    assert result.budget_settlement_sha256 is not None
    settlement = KnowledgeRecordStore(f.state / "delivery-preflight", read_only=True).get(
        "contained-unknown-budget-settlements",
        result.budget_settlement_sha256,
        ContainedUnknownBudgetSettlement,
    )
    assert json.loads(str(rows[0]["payload_json"]))["detail"] == {
        "settlement_sha256": result.budget_settlement_sha256,
        "previous_work_item_sha256": settlement.expected_item_sha256,
        "budget_refund": False,
    }
    actions = FileEvaluationEventStore(f.state / "evaluations").list_for_case(
        _default_case_id(before.id)
    )
    assert len(actions) == 1 and isinstance(actions[0], HumanActionEvent)
    assert f.service.handle(f.command) == result


def test_contained_unknown_sql_rollback_then_replay(
    real_contained_wait: RealContainedWait, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = real_contained_wait
    before = f.repository.get(f.queue.get(f.command.work_item_id).task_id)
    original = f.queue._append_event

    def crash_before_queue_event(*args: object, **kwargs: object) -> None:
        raise RuntimeError("test crash before SQL commit")

    monkeypatch.setattr(f.queue, "_append_event", crash_before_queue_event)
    with pytest.raises(RuntimeError, match="test crash before SQL commit"):
        f.service.handle(f.command)
    assert f.repository.get(before.id) == before
    assert f.queue.get(f.command.work_item_id).status is WorkItemStatus.WAITING_DEPENDENCY
    monkeypatch.setattr(f.queue, "_append_event", original)

    result = f.service.handle(f.command)

    assert result.status == "BUDGET_EXHAUSTED"
    assert f.repository.get(before.id).status is TaskStatus.BLOCKED
    assert f.service.handle(f.command) == result
