"""A truly stopped UNKNOWN invocation can end exhausted work, never become success."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, ModelRouteAttempt
from ai_software_engineer.artifacts import seal_artifact
from ai_software_engineer.domain import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import HandleDeliveryWait
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.stopped_unknown_budget import StoppedUnknownBudgetSettlement
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_wait import DeliveryWaitService
from ai_software_engineer.manager.stopped_unknown_budget import (
    StoppedUnknownBudgetSettlementService,
)
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from tests.domain.factories import make_coder_progress_artifact
from tests.manager.test_completed_output_checkpoint import CompletedFixture, CompletedQueue
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture

completed = completed_fixture


class UnknownQueue(CompletedQueue):
    fixture: CompletedFixture
    commits = 0
    fail_before = False
    fail_after = False
    before_validate: Callable[[], None] | None = None

    def settle_stopped_budget(
        self,
        cursor: DictCursor,
        record: StoppedUnknownBudgetSettlement,
        *,
        validate_current: Callable[[], None] | None = None,
    ) -> None:
        assert self.entered
        record.validate_integrity()
        assert validate_current is not None
        if self.before_validate is not None:
            self.before_validate()
        validate_current()
        if self.fail_before:
            self.fail_before = False
            raise RuntimeError("test crash before commit")
        if self.fixture.task.status is TaskStatus.IMPLEMENTING:
            self.fixture.native.repository.append_event(record.event)
            self.item = self.item.model_copy(
                update={
                    "status": WorkItemStatus.CLOSED,
                    "wait_reason": None,
                    "wait_disposition": None,
                    "available_at": None,
                    "updated_at": record.event.occurred_at,
                }
            )
            self.commits += 1
        if self.fail_after:
            self.fail_after = False
            raise RuntimeError("test crash after commit")


def service_for(f: CompletedFixture) -> DeliveryWaitService:
    queue = object.__new__(UnknownQueue)
    queue.__dict__.update(f.queue.__dict__)
    queue.fixture = f
    assert queue.item.wait_disposition is not None
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts.model_validate(
            {**queue.item.wait_disposition.facts.to_wire(), "classification": "EXECUTION_UNCERTAIN"}
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
        queue=queue,
        sidecar_state=f.root,
        git=f.native.git,
        principal=LocalOperatorPrincipal.trusted_local(),
        consume=queue.consume,
        artifacts=f.native.artifacts,
        clock=lambda: datetime.now(UTC),
        stop_observer=collector.observe_stop,
        unknown_budget_settlement=StoppedUnknownBudgetSettlementService(
            repository=f.native.repository,
            queue=cast(MySqlRoleQueue, queue),
            records=KnowledgeRecordStore(f.root / "delivery-preflight"),
            collector=collector,
            git=f.native.git,
            artifacts=f.native.artifacts,
            clock=lambda: datetime.now(UTC),
            idle_scope=lambda: queue.idle_task_scope(f.task.id),
        ),
    )


@pytest.mark.parametrize(
    "completed", ["stopped_unknown_exhausted", "stopped_unknown_completed_exhausted"], indirect=True
)
def test_public_handle_ends_exhausted_unknown_without_rewriting_result(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = service_for(f)
    command = HandleDeliveryWait.model_validate(f.queue.command().to_wire())
    before, events, sealed = f.task, f.native.repository.list_events(f.task.id), f.sealed_bytes()
    result = service.handle(command)
    assert result.status == "BUDGET_EXHAUSTED" and result.budget_settlement_sha256
    assert f.task.status is TaskStatus.BLOCKED
    assert f.task.attempts == before.attempts and f.task.retry_failures == before.retry_failures
    assert f.task.retry_policy == before.retry_policy
    assert f.native.repository.list_events(f.task.id)[:-1] == events
    assert "UNKNOWN" in f.native.repository.list_events(f.task.id)[-1].reason
    assert (
        KnowledgeRecordStore(f.root / "invocations", read_only=True).find(
            "invocation-outcomes", f.queue.item.id, DeliveryInvocationOutcome
        )
        is None
    )
    assert all(path.read_bytes() == data for path, data in sealed.items())
    record = KnowledgeRecordStore(f.root / "delivery-preflight", read_only=True).get(
        "stopped-unknown-budget-settlements",
        result.budget_settlement_sha256,
        StoppedUnknownBudgetSettlement,
    )
    record.validate_integrity()
    assert record.stopped_execution.schema_version == (
        "v2" if record.stopped_execution.capture_stop.process_stop.kind == "completed" else "v1"
    )
    assert service.handle(command) == result
    assert cast(UnknownQueue, f.queue).commits == 1


@pytest.mark.parametrize("completed", ["stopped_unknown_exhausted"], indirect=True)
@pytest.mark.parametrize("crash", ["fail_before", "fail_after"])
def test_unknown_settlement_sealed_before_commit_replays_once(
    completed: CompletedFixture, crash: str
) -> None:
    f = completed
    service = service_for(f)
    command = HandleDeliveryWait.model_validate(f.queue.command().to_wire())
    setattr(f.queue, crash, True)
    with pytest.raises(RuntimeError, match="test crash"):
        service.handle(command)
    result = service.handle(command)
    assert result.budget_settlement_sha256
    assert f.task.status is TaskStatus.BLOCKED
    assert cast(UnknownQueue, f.queue).commits == 1


@pytest.mark.parametrize("completed", ["stopped_unknown"], indirect=True)
def test_unknown_settlement_never_ends_task_with_work_remaining(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = service_for(f)
    before = f.task
    result = service.handle(HandleDeliveryWait.model_validate(f.queue.command().to_wire()))
    assert result.budget_settlement_sha256 is None
    assert f.task == before


@pytest.mark.parametrize("completed", ["stopped_unknown_completed_exhausted"], indirect=True)
@pytest.mark.parametrize("late_fact", ["outcome", "route", "raw_artifact", "inventory"])
def test_final_fence_refuses_late_original_facts_or_draft_changes(
    completed: CompletedFixture, late_fact: str
) -> None:
    f = completed
    service = service_for(f)
    command = HandleDeliveryWait.model_validate(f.queue.command().to_wire())
    before, events = f.task, f.native.repository.list_events(f.task.id)

    def inject() -> None:
        if late_fact == "outcome":
            KnowledgeRecordStore(f.root / "invocations").put(
                "invocation-outcomes", f.queue.item.id, f.outcome
            )
        elif late_fact == "route":
            FileModelRouteAttemptStore(f.root / "model-routes").append(
                ModelRouteAttempt.create(
                    request=f.native.request,
                    route_index=1,
                    provider="native_fixture",
                    model="native_fixture",
                    route_kind="codex_cli",
                    started_at=f.start.started_at,
                    completed_at=datetime.now(UTC),
                    result=f.outcome.result,
                    fallback=False,
                )
            )
        elif late_fact == "raw_artifact":
            artifact = make_coder_progress_artifact()
            artifact = artifact.model_copy(
                update={
                    "task_id": f.task.id,
                    "source_revision": f.native.request.source_revision,
                    "context_manifest_id": f.native.request.context_manifest_id,
                    "producer": artifact.producer.model_copy(
                        update={
                            "agent_id": f.native.claim.assignment.agent_id,
                            "run_id": f.native.request.run_id,
                        }
                    ),
                }
            )
            f.native.artifacts.put(seal_artifact(artifact, validated_at=datetime.now(UTC)))
        else:
            (f.native.worktree.path / "src/app.py").write_text("VALUE = 3\n")

    cast(UnknownQueue, f.queue).before_validate = inject
    with pytest.raises((ValueError, ContinuationRejected)):
        service.handle(command)
    assert f.task == before
    assert f.native.repository.list_events(f.task.id) == events
    assert cast(UnknownQueue, f.queue).commits == 0
    assert f.queue.item.status is WorkItemStatus.WAITING_DEPENDENCY
