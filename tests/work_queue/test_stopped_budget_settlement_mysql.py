"""Real SQL authority, idle fence and atomic exhausted stopped Task settlement."""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.artifacts.store import seal_artifact
from ai_software_engineer.domain import Task, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.continuation import (
    InterruptionContinuationPolicy,
    task_intent_sha256,
)
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryWaitHandling,
    HandleDeliveryWait,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringPolicy,
    LocalOperatorPrincipal,
)
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_wait import DeliveryWaitService
from ai_software_engineer.manager.stopped_budget_settlement import StoppedBudgetSettlementService
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.store.mysql_repository import _encode, open_mysql_connection
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    RoleQueueAdmission,
    record_digest,
)
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from ai_software_engineer.work_queue.ports import QueueConflict, QueueCorruption
from tests.domain.factories import make_coder_progress_artifact, make_plan_artifact
from tests.manager.test_completed_output_checkpoint import CompletedFixture, _outcome
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.work_queue.test_rejected_output_mysql import rejected_resolution
from tests.work_queue.test_wait_resolution_mysql import WaitingFixture, reseal
from tests.work_queue.test_worker_mysql import TOKEN, claim_step

completed = completed_fixture
pytestmark = [
    pytest.mark.mysql,
    pytest.mark.parametrize("completed", ["stopped_provider_exhausted"], indirect=True),
]


@dataclass
class RealWait:
    repository: MySqlTaskRepository
    queue: MySqlRoleQueue
    entry: DeliveryWaitService
    command: HandleDeliveryWait


@pytest.fixture
def real_wait(
    completed: CompletedFixture, tmp_path: Path, request: pytest.FixtureRequest
) -> Iterator[RealWait]:
    f = completed
    dsn = os.environ["ASE_TEST_MYSQL_DSN"]
    root = tmp_path / "mysql-state"
    with MySqlTaskRepository(dsn) as repository:
        initial = f.native.task
        retired = getattr(request, "param", False)
        if retired:
            assert initial.retry_policy is not None and initial.constraints is not None
            retry = initial.retry_policy.model_copy(update={"max_work_attempts": 2})
            initial = Task.model_validate(
                {
                    **initial.to_wire(),
                    "retry_policy": retry.to_wire(),
                    "engineering_policy": EngineeringPolicy.bounded_local(
                        scope=f.collector.scope,
                        principal=LocalOperatorPrincipal.trusted_local(),
                    ).to_wire(),
                    "max_attempts": retry.execution_limit,
                    "constraints": initial.constraints.model_copy(
                        update={"max_attempts": retry.execution_limit}
                    ).to_wire(),
                    "interruption_continuation_policy": (
                        InterruptionContinuationPolicy.for_retry_budget(
                            max_work_attempts=2,
                            max_coder_transient_failures=retry.coder.max_transient_failures,
                        ).to_wire()
                    ),
                }
            )
        repository.create(initial)
        repository.record_attempt(f.task.id, 1)
        for event in f.native.repository.list_events(f.task.id):
            repository.append_event(event)
        task = repository.get(f.task.id)
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
        claim = claim_step(queue, ready)
        invocation_request = f.native.request
        if retired:
            # A real owner-fenced publication and committed WAIT_RESOLVED decision,
            # not a fake retired-ID set. Retry shares its input checkpoint.
            store = FileArtifactStore(root / "artifacts")
            store.put(
                seal_artifact(
                    make_plan_artifact().model_copy(update={"task_id": task.id}),
                    validated_at=datetime.now(UTC),
                )
            )
            progress = make_coder_progress_artifact()
            progress = progress.model_copy(
                update={
                    "task_id": task.id,
                    "source_revision": ready.boundary.source_revision,
                    "context_manifest_id": invocation_request.context_manifest_id,
                    "producer": progress.producer.model_copy(
                        update={
                            "agent_id": claim.assignment.agent_id,
                            "run_id": invocation_request.run_id,
                        }
                    ),
                    "content": progress.content.model_copy(update={"checkpoint_sequence": 9}),
                }
            )
            queue.accept_artifact(
                claim, TOKEN, store, seal_artifact(progress, validated_at=datetime.now(UTC))
            )
            assert f.queue.item.wait_disposition is not None
            rejected_disposition = decide_delivery_disposition(
                DeliveryFailureFacts.model_validate(
                    {
                        **f.queue.item.wait_disposition.facts.to_wire(),
                        "task_intent_sha256": task_intent_sha256(task),
                        "classification": "PLATFORM_BUG",
                    }
                )
            )
            queue.wait(
                ready.work_item.id,
                lease_id=claim.lease.id,
                owner_token=TOKEN,
                status=WorkItemStatus.WAITING_HUMAN,
                reason=rejected_disposition.reason,
                disposition=rejected_disposition,
                now=datetime.now(UTC),
            )
            waiting = WaitingFixture(
                dsn, repository, queue, ready, claim, rejected_disposition, datetime.now(UTC)
            )
            resolution = rejected_resolution(waiting)
            assert resolution.rejected_output is not None
            resolution = reseal(
                resolution,
                expected_source_revision=ready.boundary.source_revision,
                rejected_output={
                    **resolution.rejected_output.to_wire(),
                    "source_revision": ready.boundary.source_revision,
                },
            )
            successor = queue.resolve_wait(resolution)
            ready = queue.step(successor.id)
            claim = claim_step(queue, ready)
            task = repository.get(task.id)
            invocation_request = invocation_request.model_copy(
                update={
                    "attempt": successor.attempt,
                    "run_id": "run_stopped_successor",
                    "context_manifest_id": "ctx_" + "e" * 64,
                }
            )
            assert task.work_budget_exhausted
            assert (
                queue.accepted(task.id)[0].checkpoint_sequence == ready.boundary.checkpoint_sequence
            )
        now = datetime.now(UTC)
        start = DeliveryInvocationStart(
            work_item_id=ready.work_item.id,
            checkpoint_sequence=ready.boundary.checkpoint_sequence,
            request=invocation_request,
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
                "request": invocation_request,
                "task_intent_sha256": task_intent_sha256(task),
                "policy_sha256": digest(task.interruption_continuation_policy.to_wire()),
                "started_at": now,
            }
        )
        process = subprocess.Popen(
            (sys.executable, "-c", "raise SystemExit(1)"), start_new_session=True
        )
        rc = process.wait(timeout=5)
        stop = ExecutionCaptureStop.create(
            task_id=task.id,
            run_id=start.request.run_id,
            capture_start_sha256=capture_start.start_sha256,
            output_present=False,
            original_error_code=f.outcome.result.error.code if f.outcome.result.error else None,
            process_stop=NativeProcessStop.create(
                process_id=process.pid,
                group_id=process.pid,
                returncode=rc,
                kind="failed",
                stopped_at=datetime.now(UTC),
            ),
        )
        invocation_records = KnowledgeRecordStore(root / "invocations")
        invocation_records.put("invocation-starts", ready.work_item.id, start)
        invocation_records.put(
            "invocation-outcomes",
            ready.work_item.id,
            _outcome(
                start,
                f.outcome.result.model_copy(
                    update={
                        "run_id": invocation_request.run_id,
                        "context_manifest_id": invocation_request.context_manifest_id,
                        "attempt": invocation_request.attempt,
                    }
                ),
            ),
        )
        (root / "continuations").mkdir(mode=0o700)
        ledger = FileContinuationStore.initialize(root / "continuations" / task.id, task_id=task.id)
        ledger.put_capture_start(capture_start)
        ledger.put_capture_stop(stop)
        assert f.queue.item.wait_disposition is not None
        disposition = decide_delivery_disposition(
            DeliveryFailureFacts.model_validate(
                {
                    **f.queue.item.wait_disposition.facts.to_wire(),
                    "classification": "TRANSIENT_INFRA",
                    "work_item_id": ready.work_item.id,
                    "task_intent_sha256": task_intent_sha256(task),
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
            sidecar_state=root,
            route_root=root / "routes",
            scope=f.collector.scope,
            expected_continuation_scope=f.native.scope,
            git=f.native.git,
            queue=queue,
        )
        entry = DeliveryWaitService(
            repository=repository,
            queue=queue,
            scope=f.collector.scope,
            sidecar_state=root,
            git=f.native.git,
            principal=LocalOperatorPrincipal.trusted_local(),
            consume=lambda resolution: None,
            stop_observer=collector.observe_stop,
            budget_settlement=StoppedBudgetSettlementService(
                repository=repository,
                queue=queue,
                records=KnowledgeRecordStore(root / "delivery-waits"),
                collector=collector,
                git=f.native.git,
                clock=lambda: datetime.now(UTC),
                idle_scope=lambda: queue.idle_task_scope(task.id),
            ),
        )
        command = HandleDeliveryWait(
            work_item_id=item.id,
            expected_disposition_sha256=disposition.disposition_sha256,
            expected_task_intent_sha256=disposition.facts.task_intent_sha256,
            expected_source_revision=disposition.facts.source_revision,
            expected_checkpoint_sequence=item.checkpoint_sequence,
        )
        yield RealWait(repository, queue, entry, command)


def test_atomic_sql_settlement_and_exact_replay(real_wait: RealWait) -> None:
    f = real_wait
    item = f.queue.get(f.command.work_item_id)
    before = f.repository.get(item.task_id)
    events = f.repository.list_events(before.id)
    claims = f.queue.claims_for_work_item(item.id)
    result = f.entry.handle(f.command)
    assert result.budget_settlement_sha256 is not None
    assert f.repository.get(before.id).status is TaskStatus.BLOCKED
    assert f.repository.list_events(before.id)[:-1] == events
    assert f.repository.get(before.id).retry_failures == before.retry_failures
    assert f.queue.get(item.id).status is WorkItemStatus.CLOSED
    assert f.queue.claims_for_work_item(item.id) == claims
    assert f.entry.handle(f.command) == result
    assert len(f.repository.list_events(before.id)) == len(events) + 1


@pytest.mark.parametrize("real_wait", [True], indirect=True)
def test_consumed_rejected_progress_at_same_input_checkpoint_does_not_block_settlement(
    real_wait: RealWait,
) -> None:
    f = real_wait
    item = f.queue.get(f.command.work_item_id)
    publications = f.queue.accepted(item.task_id)
    assert len(publications) == 1
    assert publications[0].work_item_id != item.id
    assert publications[0].checkpoint_sequence == item.checkpoint_sequence
    assert publications[0].receipt.artifact_id in f.queue.rejected_output_artifact_ids(item.task_id)
    before = f.repository.get(item.task_id)
    events = f.repository.list_events(item.task_id)
    claims = f.queue.claims_for_work_item(item.id)
    result = f.entry.handle(f.command)
    assert result.budget_settlement_sha256 is not None
    assert f.repository.get(item.task_id).status is TaskStatus.BLOCKED
    assert f.repository.get(item.task_id).attempts == before.attempts
    assert f.repository.get(item.task_id).retry_failures == before.retry_failures
    assert f.repository.list_events(item.task_id)[:-1] == events
    assert f.queue.accepted(item.task_id) == publications
    assert f.queue.claims_for_work_item(item.id) == claims
    assert f.entry.handle(f.command) == result
    assert len(f.repository.list_events(item.task_id)) == len(events) + 1


@pytest.mark.parametrize("real_wait", [True], indirect=True)
@pytest.mark.parametrize("drift", ["unconsumed", "sha", "lease", "current", "future", "digest"])
def test_only_exact_consumed_historical_publication_can_be_excluded(
    real_wait: RealWait, drift: str
) -> None:
    f = real_wait
    item = f.queue.get(f.command.work_item_id)
    publication = f.queue.accepted(item.task_id)[0]
    # Deliberately damaged isolated SQL facts exercise the production reader and
    # transaction fence. A valid row checksum cannot substitute for retirement.
    with closing(open_mysql_connection(os.environ["ASE_TEST_MYSQL_DSN"])) as connection:
        with connection.cursor(DictCursor) as cursor:
            if drift == "unconsumed":
                cursor.execute(
                    "DELETE FROM work_queue_events WHERE work_item_id=%s "
                    "AND event_type='WAIT_RESOLVED'",
                    (publication.work_item_id,),
                )
            elif drift == "digest":
                cursor.execute(
                    "SELECT sequence,payload_json FROM work_queue_events "
                    "WHERE work_item_id=%s AND event_type='WAIT_RESOLVED'",
                    (publication.work_item_id,),
                )
                row = cursor.fetchone()
                assert row is not None
                payload = json.loads(str(row["payload_json"]))
                payload["detail"]["resolution"]["resolution_sha256"] = "0" * 64
                cursor.execute(
                    "UPDATE work_queue_events SET payload_json=%s WHERE sequence=%s",
                    (_encode(payload), row["sequence"]),
                )
            else:
                damaged = publication.model_copy(
                    update=(
                        {"receipt": publication.receipt.model_copy(update={"sha256": "f" * 64})}
                        if drift == "sha"
                        else {"lease_id": "lease_foreign"}
                        if drift == "lease"
                        else {"work_item_id": item.id}
                        if drift == "current"
                        else {"checkpoint_sequence": item.checkpoint_sequence + 1}
                    )
                )
                cursor.execute(
                    "UPDATE work_queue_accepted_artifacts SET payload_json=%s,sha256=%s "
                    "WHERE id=%s",
                    (
                        _encode(damaged.to_wire()),
                        record_digest(damaged),
                        publication.receipt.artifact_id,
                    ),
                )
        connection.commit()
    before = f.repository.get(item.task_id)
    events = f.repository.list_events(item.task_id)
    publications = f.queue.accepted(item.task_id)
    claims = f.queue.claims_for_work_item(item.id)
    with pytest.raises((QueueConflict, QueueCorruption, ContinuationRejected)):
        f.entry.handle(f.command)
    assert f.repository.get(item.task_id) == before
    assert f.repository.list_events(item.task_id) == events
    assert f.queue.get(item.id) == item
    assert f.queue.accepted(item.task_id) == publications
    assert f.queue.claims_for_work_item(item.id) == claims
    assert not f.entry.records.list("wait-handlings", DeliveryWaitHandling)


def test_sql_failure_rolls_back_all_three_publications(
    real_wait: RealWait, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = real_wait
    item = f.queue.get(f.command.work_item_id)
    before = f.repository.get(item.task_id)
    events = f.repository.list_events(before.id)
    append = f.queue._append_event

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("test queue append failure")

    monkeypatch.setattr(f.queue, "_append_event", fail)
    with pytest.raises(RuntimeError, match="queue append failure"):
        f.entry.handle(f.command)
    assert f.repository.get(before.id) == before
    assert f.repository.list_events(before.id) == events
    assert f.queue.get(item.id) == item
    monkeypatch.setattr(f.queue, "_append_event", append)
    result = f.entry.handle(f.command)
    assert result.budget_settlement_sha256 is not None
    assert f.repository.get(before.id).status is TaskStatus.BLOCKED


def test_no_public_success_before_transaction_commits(real_wait: RealWait) -> None:
    f = real_wait
    settlement = f.entry.budget_settlement
    assert settlement is not None
    original = settlement.idle_scope

    @contextmanager
    def interrupted_commit() -> Iterator[DictCursor]:
        with original() as cursor:
            yield cursor
            raise RuntimeError("test failure immediately before commit")

    before = f.repository.get(f.queue.get(f.command.work_item_id).task_id)
    events = f.repository.list_events(before.id)
    settlement.idle_scope = interrupted_commit
    with pytest.raises(RuntimeError, match="before commit"):
        f.entry.handle(f.command)
    assert f.repository.get(before.id) == before
    assert f.repository.list_events(before.id) == events
    assert not f.entry.records.list("wait-handlings", DeliveryWaitHandling)
    settlement.idle_scope = original
    result = f.entry.handle(f.command)
    assert result.budget_settlement_sha256 is not None
    assert f.entry.records.list("wait-handlings", DeliveryWaitHandling) == (result,)
