"""Preserved baseline inputs stay idle until an exact durable continue decision."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
)
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    ExecutionBaselineBinding,
)
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.baseline_models import (
    BaselineContinueAuthorization,
    BaselineExecutionReservation,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
)
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.baseline import (
    BaselineQueueRelease,
    consume_baseline,
)
from ai_software_engineer.work_queue.dispatcher import DispatcherTickStatus
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
    record_digest,
)
from ai_software_engineer.work_queue.ports import QueueConflict
from tests.git.test_worktree import _git
from tests.manager.test_execution_baseline import Setup, setup
from tests.work_queue.test_mysql_queue import dispatcher, queued_item

pytestmark = pytest.mark.mysql


@dataclass
class PausedFixture:
    git: Setup
    repository: MySqlTaskRepository
    queue: MySqlRoleQueue
    plan: ExecutionBaselinePlan
    binding: ExecutionBaselineBinding
    work_item_id: str
    now: datetime

    def authorization(self, **changes: object) -> BaselineContinueAuthorization:
        item = self.queue.get(self.work_item_id)
        assert item.wait_disposition is not None
        return BaselineContinueAuthorization.create(
            **{
                "scope": self.binding.scope,
                "task_id": item.task_id,
                "task_intent_sha256": task_intent_sha256(self.repository.get(item.task_id)),
                "task_revision": self.repository.current_revision(item.task_id),
                "work_item_id": item.id,
                "execution_baseline_sha256": self.binding.binding_sha256,
                "expected_source_revision": self.binding.execution_source_revision,
                "checkpoint_sequence": item.checkpoint_sequence,
                "expected_disposition_sha256": item.wait_disposition.disposition_sha256,
                "inventory_sha256": self.binding.after_inventory_sha256,
                "principal": LocalOperatorPrincipal.trusted_local(),
                "reference": "isolated exact continue decision",
                "submitted_at": self.now,
                **changes,
            }
        )


@pytest.fixture(params=(False, True), ids=("uninvoked", "reserved_successor"))
def paused(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[PausedFixture]:
    dsn = os.environ["ASE_TEST_MYSQL_DSN"]
    fixture = setup(tmp_path)
    task = fixture.collector.facts.task
    now = datetime.now(UTC)
    with MySqlTaskRepository(dsn) as repository:
        repository.create(task.model_copy(update={"status": TaskStatus.NEW, "attempts": 0}))
        repository.record_attempt(task.id, 1)
        for index, status in enumerate((TaskStatus.PLANNING, TaskStatus.IMPLEMENTING)):
            repository.append_event(
                build_event(
                    repository.get(task.id),
                    status,
                    event_id=f"evt_baseline_pause_{index}",
                    reason="isolated baseline checkpoint",
                    source_revision=task.base_ref,
                    occurred_at=now + timedelta(microseconds=index),
                )
            )
        task = repository.get(task.id)
        revision = repository.current_revision(task.id)
        invoked = bool(request.param)
        reservation = BaselineExecutionReservation(
            current_attempt=1,
            next_execution_attempt=2 if invoked else 1,
            retry_cause="local_execution_limit" if invoked else "uninvoked",
            original_run_id="run_baseline_prior" if invoked else None,
            current_invocation_start_sha256="7" * 64 if invoked else None,
            current_invocation_outcome_sha256="8" * 64 if invoked else None,
            reservation_already_applied=not invoked,
        )
        facts = fixture.collector.facts.model_copy(
            update={
                "task": task,
                "task_revision": revision,
                "checkpoint_sequence": revision,
                "continuation": reservation,
                "scope": fixture.collector.facts.scope.model_copy(
                    update={"repository_id": "repository_baseline_pause"}
                ),
            }
        )
        facts = facts.model_copy(
            update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
        )
        fixture.collector.facts = facts
        queue = MySqlRoleQueue(dsn, clock=lambda: now + timedelta(seconds=5))
        item = queued_item(created_at=now).model_copy(
            update={
                "id": facts.work_item_id,
                "task_id": task.id,
                "repository_id": facts.scope.repository_id,
                "repository_scopes": (task.repository,),
                "checkpoint_sequence": revision,
            }
        )
        step = QueuedRoleStep(
            work_item=item,
            boundary=RoleRunBoundary(
                task.id, AgentRole.CODER, 1, revision, fixture.worktree.head_revision
            ),
            allocation_sha256="a" * 64,
        )
        queue.admit(
            RoleQueueAdmission(
                task_id=task.id,
                repository_id=item.repository_id,
                allocation_sha256=step.allocation_sha256,
                legacy_artifacts=(),
            ),
            step,
        )
        plan = fixture.service.propose(fixture.target)
        authority = BaselineOperatorAuthorization.for_plan(
            plan,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="preserve source then pause",
            submitted_at=now,
            continuation_mode=BaselineContinuationMode.PAUSE,
        )
        binding = fixture.service.execute(plan.plan_sha256, authority=authority)
        waiting = consume_baseline(queue, plan, binding)
        yield PausedFixture(fixture, repository, queue, plan, binding, waiting.id, now)


def test_consumption_is_durably_paused_and_unclaimable(paused: PausedFixture) -> None:
    item = paused.queue.get(paused.work_item_id)
    assert item.status is WorkItemStatus.WAITING_HUMAN
    assert item.wait_disposition is not None
    assert item.wait_disposition.facts.classification == "EXECUTION_BASELINE_PAUSED"
    assert item.wait_disposition.facts.execution_baseline_sha256 == paused.binding.binding_sha256
    assert paused.queue.list_schedulable(now=paused.now + timedelta(minutes=5)) == ()
    assert (
        dispatcher(paused.queue, "worker_baseline_pause")
        .tick(now=paused.now + timedelta(minutes=5), work_item_id=item.id)
        .status
        is DispatcherTickStatus.IDLE
    )
    with pytest.raises(QueueConflict, match="精确"):
        paused.queue.make_ready(
            item.id,
            now=paused.now + timedelta(seconds=6),
            expected_disposition_sha256=item.wait_disposition.disposition_sha256,
        )
    resolution = DeliveryResolution(
        task_id=item.task_id,
        work_item_id=item.id,
        expected_disposition_sha256=item.wait_disposition.disposition_sha256,
        expected_task_intent_sha256=paused.binding.task_intent_sha256,
        expected_source_revision=paused.binding.execution_source_revision,
        expected_checkpoint_sequence=item.checkpoint_sequence,
        task_revision=item.checkpoint_sequence,
        task_snapshot_sha256=digest(paused.repository.get(item.task_id).to_wire()),
        step_sha256=record_digest(paused.queue.step(item.id)),
        resolution_kind=DeliveryResolutionKind.RESUME_UNINVOKED,
        proof_sha256="d" * 64,
        authorization_source="engineering_operator_decision",
        operator_principal=LocalOperatorPrincipal.trusted_local(),
        submitted_at=paused.now,
        resolution_sha256="0" * 64,
    )
    resolution = resolution.model_copy(update={"resolution_sha256": resolution.recompute_sha256()})
    with pytest.raises(QueueConflict, match="普通等待"):
        paused.queue.resolve_wait(resolution)
    assert consume_baseline(paused.queue, paused.plan, paused.binding) == item
    assert paused.repository.get(item.task_id).attempts == item.attempt


def test_exact_continue_is_atomic_and_replay_preserves_counters(paused: PausedFixture) -> None:
    authority = paused.authorization()
    task = paused.repository.get(authority.task_id)
    before = paused.queue.get(paused.work_item_id)
    validations: list[str] = []
    with paused.queue.idle_task_scope(task.id) as cursor:
        assert paused.queue.release_baseline_pause(
            paused.binding,
            authority,
            cursor=cursor,
            validate_new_release=lambda: validations.append("fresh"),
        )
    ready = paused.queue.get(before.id)
    assert ready.status is WorkItemStatus.READY and ready.wait_disposition is None
    assert ready.dispatch_sequence == before.dispatch_sequence + 1
    assert not paused.queue.release_baseline_pause(
        paused.binding, authority, validate_new_release=lambda: validations.append("stale")
    )
    assert validations == ["fresh"]
    assert paused.queue.get(before.id) == ready
    assert paused.repository.get(task.id) == task
    stored = paused.queue._find(
        "work_queue_baseline_releases", authority.authorization_sha256, BaselineQueueRelease
    )
    assert stored is not None and stored.ready_work_item == ready
    assert paused.queue.pending_baseline_release(paused.binding, authority)


def test_pending_release_never_restarts_a_claimed_or_later_waiting_execution(
    paused: PausedFixture,
) -> None:
    authority = paused.authorization()
    assert not paused.queue.pending_baseline_release(paused.binding, authority)
    assert paused.queue.release_baseline_pause(paused.binding, authority)
    assert paused.queue.pending_baseline_release(paused.binding, authority)
    tick = dispatcher(paused.queue, "worker_baseline_pending").tick(
        now=paused.now + timedelta(seconds=6), work_item_id=authority.work_item_id
    )
    assert tick.claim is not None and tick.lease_owner_token is not None
    assert not paused.queue.pending_baseline_release(paused.binding, authority)
    paused.queue.wait(
        authority.work_item_id,
        lease_id=tick.claim.lease.id,
        owner_token=tick.lease_owner_token,
        status=WorkItemStatus.WAITING_DEPENDENCY,
        reason="new execution requires new prerequisite facts",
        now=paused.now + timedelta(seconds=7),
    )
    assert not paused.queue.pending_baseline_release(paused.binding, authority)


def test_failed_fresh_validation_retains_pause_and_publishes_no_release(
    paused: PausedFixture,
) -> None:
    authority = paused.authorization()
    before = paused.queue.get(authority.work_item_id)

    def changed_workspace() -> None:
        raise ValueError("fixture input changed")

    with pytest.raises(ValueError, match="input changed"):
        paused.queue.release_baseline_pause(
            paused.binding, authority, validate_new_release=changed_workspace
        )
    assert paused.queue.get(before.id) == before
    assert (
        paused.queue._find(
            "work_queue_baseline_releases", authority.authorization_sha256, BaselineQueueRelease
        )
        is None
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"execution_baseline_sha256": "0" * 64},
        {"expected_source_revision": "0" * 40},
        {"inventory_sha256": "0" * 64},
        {"expected_disposition_sha256": "0" * 64},
        {"task_intent_sha256": "0" * 64},
        {"task_revision": 3, "checkpoint_sequence": 3},
    ],
)
def test_foreign_or_stale_continue_keeps_every_fact(
    paused: PausedFixture, changes: dict[str, object]
) -> None:
    before = paused.queue.get(paused.work_item_id)
    task = paused.repository.get(before.task_id)
    with pytest.raises(QueueConflict):
        paused.queue.release_baseline_pause(paused.binding, paused.authorization(**changes))
    assert paused.queue.get(before.id) == before
    assert paused.repository.get(task.id) == task


def test_a_later_source_update_stays_paused_and_rejects_old_continue(paused: PausedFixture) -> None:
    old_authority = paused.authorization()
    repository = paused.git.repository
    (repository / "another.txt").write_text("second upstream change\n")
    _git(repository, "add", "another.txt")
    _git(repository, "commit", "-m", "second target")
    target = _git(repository, "rev-parse", "HEAD")
    item = paused.queue.get(paused.work_item_id)
    facts = paused.git.collector.facts.model_copy(
        update={
            "task": paused.repository.get(item.task_id),
            "work_item_id": item.id,
            "continuation": BaselineExecutionReservation(
                current_attempt=item.attempt,
                next_execution_attempt=item.attempt,
                retry_cause="uninvoked",
                reservation_already_applied=True,
            ),
        }
    )
    paused.git.collector.facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    paused.git.collector.worktree = replace(
        paused.git.collector.worktree, head_revision=paused.binding.execution_source_revision
    )
    plan = paused.git.service.propose(target)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="second exact source update remains paused",
        submitted_at=paused.now,
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = paused.git.service.execute(plan.plan_sha256, authority=authority)
    waiting = consume_baseline(paused.queue, plan, binding)
    assert waiting.id == item.id and waiting.attempt == item.attempt
    assert waiting.status is WorkItemStatus.WAITING_HUMAN
    with pytest.raises(QueueConflict, match="最新"):
        paused.queue.release_baseline_pause(paused.binding, old_authority)
    assert paused.queue.get(waiting.id) == waiting
    assert paused.repository.get(item.task_id).attempts == item.attempt
