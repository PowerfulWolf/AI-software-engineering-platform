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
    BaselinePurpose,
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
from tests.manager.test_completed_output_checkpoint import CompletedFixture
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.manager.test_completed_output_rescue import service_for
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


@pytest.fixture(params=("uninvoked", "reserved_successor", "same_base_service_pause"))
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
        invoked = request.param != "uninvoked"
        same_base = request.param == "same_base_service_pause"
        reservation = BaselineExecutionReservation(
            current_attempt=1,
            next_execution_attempt=2 if invoked else 1,
            retry_cause="service_pause"
            if same_base
            else ("local_execution_limit" if invoked else "uninvoked"),
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
                "target_native_rules_sha256": (
                    fixture.collector.facts.source_native_rules_sha256
                    if same_base
                    else fixture.collector.facts.target_native_rules_sha256
                ),
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
        plan = fixture.service.propose(task.base_ref if same_base else fixture.target)
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


def test_paused_baseline_claim_uses_fresh_execution_and_preserves_history(
    paused: PausedFixture,
) -> None:
    task = paused.repository.get(paused.binding.task_id)
    history = paused.repository.list_events(task.id)
    assert paused.queue.release_baseline_pause(paused.binding, paused.authorization())
    tick = dispatcher(paused.queue, "worker_baseline_fresh").tick(
        now=paused.now + timedelta(seconds=6), work_item_id=paused.work_item_id
    )
    assert tick.claim is not None and tick.lease_owner_token is not None
    step = paused.queue.step(paused.work_item_id)
    reservation = paused.plan.facts.continuation
    assert reservation is not None
    assert step.boundary.attempt == reservation.next_execution_attempt
    assert step.boundary.source_revision == paused.binding.execution_source_revision
    if reservation.retry_cause == "service_pause":
        assert paused.binding.execution_base_ref == paused.binding.prior_execution_base_ref
        assert paused.binding.service_pause_outcome_sha256 == (
            reservation.current_invocation_outcome_sha256
        )
        assert task.attempts == 2 and task.work_attempt == 2
        assert task.retry_failures is None
    assert paused.repository.list_events(task.id) == history
    assert consume_baseline(paused.queue, paused.plan, paused.binding).id == paused.work_item_id
    assert paused.repository.get(task.id) == task
    paused.queue.wait(
        paused.work_item_id,
        lease_id=tick.claim.lease.id,
        owner_token=tick.lease_owner_token,
        status=WorkItemStatus.WAITING_DEPENDENCY,
        reason="isolated test finishes after exact fresh claim",
        now=paused.now + timedelta(seconds=7),
    )


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


completed = completed_fixture


@pytest.mark.parametrize(
    "purpose", [BaselinePurpose.COMPLETED_OUTPUT_RESCUE, BaselinePurpose.SOURCE_REBIND]
)
@pytest.mark.parametrize("completed", ["invalid_named"], indirect=True)
def test_rejected_completed_output_consumes_once_pauses_and_claims_exact_successor(
    completed: CompletedFixture, purpose: BaselinePurpose
) -> None:
    """Actual SQL consume/release/claim; original completion uses the offline native fixture."""
    f = completed
    service = service_for(f)
    target = None
    if purpose is BaselinePurpose.SOURCE_REBIND:
        root = Path(f.task.repository)
        (root / "README.md").write_text("trusted SQL fixture baseline\n")
        _git(root, "add", "README.md")
        _git(root, "commit", "-m", "independent source baseline")
        target = _git(root, "rev-parse", "HEAD")
    plan = service.propose(target, purpose=purpose)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact rejected draft",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = service.execute(plan.plan_sha256, authority=authority)
    history, old_task = f.sealed_bytes(), f.task
    original_events = f.native.repository.list_events(old_task.id)
    dsn = os.environ["ASE_TEST_MYSQL_DSN"]
    now = datetime.now(UTC)
    with MySqlTaskRepository(dsn) as repository:
        repository.create(f.native.task)
        repository.record_attempt(old_task.id, old_task.attempts)
        for event in original_events:
            repository.append_event(event)
        assert repository.get(old_task.id) == old_task
        queue = MySqlRoleQueue(dsn, clock=lambda: now)
        queue.admit(
            RoleQueueAdmission(
                task_id=old_task.id,
                repository_id=f.queue.item.repository_id,
                allocation_sha256=f.queue.bound.allocation_sha256,
                legacy_artifacts=(),
            ),
            f.queue.bound.model_copy(update={"work_item": f.queue.item}),
        )
        checks: list[str] = []
        waiting = consume_baseline(
            queue, plan, binding, validate_new_consumption=lambda: checks.append("fresh")
        )
        assert waiting.id != f.queue.item.id and waiting.parent_work_item_id == f.queue.item.id
        assert (
            waiting.status is WorkItemStatus.WAITING_HUMAN
            and waiting.attempt == old_task.attempts + 1
        )
        assert queue.get(f.queue.item.id).status is WorkItemStatus.CLOSED
        assert queue.list_schedulable(now=now + timedelta(minutes=1)) == ()
        reserved = repository.get(old_task.id)
        assert reserved.work_attempt == old_task.work_attempt + 1
        assert reserved.retry_failures == old_task.retry_failures
        assert repository.list_events(old_task.id) == original_events
        assert (
            consume_baseline(
                queue, plan, binding, validate_new_consumption=lambda: checks.append("replay")
            )
            == waiting
        )
        assert checks == ["fresh"] and repository.get(old_task.id) == reserved
        assert waiting.wait_disposition is not None
        continuation = BaselineContinueAuthorization.create(
            scope=binding.scope,
            task_id=old_task.id,
            task_intent_sha256=task_intent_sha256(reserved),
            task_revision=repository.current_revision(old_task.id),
            work_item_id=waiting.id,
            execution_baseline_sha256=binding.binding_sha256,
            expected_source_revision=binding.execution_source_revision,
            checkpoint_sequence=waiting.checkpoint_sequence,
            expected_disposition_sha256=waiting.wait_disposition.disposition_sha256,
            inventory_sha256=binding.after_inventory_sha256,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="explicit independent resume",
            submitted_at=now,
        )
        assert queue.release_baseline_pause(binding, continuation)
        assert not queue.release_baseline_pause(binding, continuation)
        assert repository.get(old_task.id) == reserved
        step = queue.step(waiting.id)
        assert step.boundary.attempt == old_task.attempts + 1
        assert step.boundary.source_revision == binding.execution_source_revision
        tick = dispatcher(queue, "worker_rejected_completed").tick(
            now=now + timedelta(seconds=1), work_item_id=waiting.id
        )
        assert tick.claim is not None and tick.lease_owner_token is not None
        assert tick.claim.work_item.id == waiting.id
        assert tick.claim.lease.id != f.start.lease_id
        assert tick.claim.work_item.attempt == old_task.attempts + 1
        queue.wait(
            waiting.id,
            lease_id=tick.claim.lease.id,
            owner_token=tick.lease_owner_token,
            status=WorkItemStatus.WAITING_DEPENDENCY,
            reason="offline fixture ends after real claim",
            now=now + timedelta(seconds=2),
        )
    assert all(path.read_bytes() == body for path, body in history.items())
