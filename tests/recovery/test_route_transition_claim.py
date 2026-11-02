"""An expired, uninvoked generation is evidence only while its full queue is current."""

import json
import os
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.domain import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.models import RecoveryScope
from ai_software_engineer.recovery.route_transition_claim import (
    RouteTransitionSettlement,
    UninvokedRouteClaimReader,
)
from ai_software_engineer.recovery.route_transition_settlement import (
    RouteTransitionRetained,
    RouteTransitionSettlementService,
)
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.dispatcher import DispatcherLoop, DispatcherTickStatus
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, RoleQueueAdmission
from ai_software_engineer.work_queue.ports import QueueConflict
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.domain.factories import make_task
from tests.work_queue.test_worker_mysql import (
    ALLOCATION_SHA,
    REPOSITORY_ID,
    TOKEN,
    agents,
    demand,
    make_step,
    policy,
)

pytestmark = pytest.mark.mysql


def test_expired_uninvoked_claim_is_observed_then_current_queue_drift_refuses(
    tmp_path: Path,
) -> None:
    dsn = os.environ["ASE_TEST_MYSQL_DSN"]
    task = make_task()
    with MySqlTaskRepository(dsn) as repository:
        repository.create(task)
        now = datetime.now(UTC)
        repository.append_event(
            build_event(
                task,
                TaskStatus.PLANNING,
                event_id="evt_route_claim_planning",
                reason="task_validated",
                source_revision=task.base_ref,
                occurred_at=now,
            )
        )
        task = repository.get(task.id)
        repository.append_event(
            build_event(
                task,
                TaskStatus.IMPLEMENTING,
                event_id="evt_route_claim_implementing",
                reason="plan_validated",
                source_revision=task.base_ref,
                occurred_at=datetime.now(UTC),
            )
        )
        repository.record_attempt(task.id, 1)
        revision = repository.current_revision(task.id)
        queue = MySqlRoleQueue(dsn)
        step = make_step(
            RoleRunBoundary(task.id, AgentRole.CODER, 1, revision, task.base_ref),
            None,
            datetime.now(UTC),
        )
        queue.admit(
            RoleQueueAdmission(
                task_id=task.id,
                repository_id=REPOSITORY_ID,
                allocation_sha256=ALLOCATION_SHA,
                legacy_artifacts=(),
            ),
            step,
        )
        profiles = tuple(
            profile.model_copy(update={"id": f"agent_{profile.eligible_roles[0].value}_001"})
            for profile in agents()
        )
        tick = DispatcherLoop(
            queue=queue,
            scheduler=PortfolioScheduler(lease_duration=timedelta(seconds=1)),
            model_router=ModelRouter(
                route_context_capacities={
                    (route.provider, route.model): 128_000 for route in policy().routes
                }
            ),
            agents=profiles,
            policies=(policy(),),
            demand_builder=demand,
            worker_id="worker_route_transition_test",
            owner_token_factory=lambda: TOKEN,
        ).tick(now=datetime.now(UTC), work_item_id=step.work_item.id)
        assert tick.status is DispatcherTickStatus.DISPATCHED and tick.claim is not None
        claim = tick.claim
        queue.start(
            step.work_item.id,
            lease_id=claim.lease.id,
            owner_token=TOKEN,
            now=datetime.now(UTC),
        )
        time.sleep(max(0.0, (claim.lease.expires_at - datetime.now(UTC)).total_seconds()) + 0.05)
        observed_at = datetime.now(UTC)
        (expired,) = queue.reclaim_expired(
            now=observed_at,
            retry_at=observed_at + timedelta(minutes=1),
        )
        assert expired.status is WorkItemStatus.RETRY_SCHEDULED
        sidecar = tmp_path / "sidecar"
        (sidecar / "artifacts").mkdir(parents=True)
        reader = UninvokedRouteClaimReader(dsn, sidecar)
        guard = WorkerExecutionGuard()
        with pytest.raises(QueueConflict, match="exact held Task process lock"):
            reader.inspect(task.id, guard)
        with guard.task_scope(sidecar / "state/queue-worker-locks", task.id):
            observation = reader.inspect(task.id, guard)
            assert observation.task_revision == revision
            assert observation.original_claim == claim
            assert observation.work_item == expired
            assert observation.claimed_sequence < observation.expired_sequence
        queue.make_ready(step.work_item.id, now=datetime.now(UTC))
        with (
            guard.task_scope(sidecar / "state/queue-worker-locks", task.id),
            pytest.raises(ValueError, match="exact Coder retry"),
        ):
            reader.inspect(task.id, guard)


def test_expired_uninvoked_route_settlement_closes_task_and_work_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second commit is an exact replay, never a new attempt or result."""
    dsn = os.environ["ASE_TEST_MYSQL_DSN"]
    task = make_task()
    with MySqlTaskRepository(dsn) as repository:
        repository.create(task)
        repository.append_event(
            build_event(
                task,
                TaskStatus.PLANNING,
                event_id="evt_route_settle_planning",
                reason="task_validated",
                source_revision=task.base_ref,
                occurred_at=datetime.now(UTC),
            )
        )
        task = repository.get(task.id)
        repository.append_event(
            build_event(
                task,
                TaskStatus.IMPLEMENTING,
                event_id="evt_route_settle_implementing",
                reason="plan_validated",
                source_revision=task.base_ref,
                occurred_at=datetime.now(UTC),
            )
        )
        repository.record_attempt(task.id, 1)
        revision = repository.current_revision(task.id)
        queue = MySqlRoleQueue(dsn)
        step = make_step(
            RoleRunBoundary(task.id, AgentRole.CODER, 1, revision, task.base_ref),
            None,
            datetime.now(UTC),
        )
        queue.admit(
            RoleQueueAdmission(
                task_id=task.id,
                repository_id=REPOSITORY_ID,
                allocation_sha256=ALLOCATION_SHA,
                legacy_artifacts=(),
            ),
            step,
        )
        profiles = tuple(
            profile.model_copy(update={"id": f"agent_{profile.eligible_roles[0].value}_002"})
            for profile in agents()
        )
        tick = DispatcherLoop(
            queue=queue,
            scheduler=PortfolioScheduler(lease_duration=timedelta(seconds=1)),
            model_router=ModelRouter(
                route_context_capacities={
                    (route.provider, route.model): 128_000 for route in policy().routes
                }
            ),
            agents=profiles,
            policies=(policy(),),
            demand_builder=demand,
            worker_id="worker_route_settle_test",
            owner_token_factory=lambda: TOKEN,
        ).tick(now=datetime.now(UTC), work_item_id=step.work_item.id)
        assert tick.status is DispatcherTickStatus.DISPATCHED and tick.claim is not None
        queue.start(
            step.work_item.id,
            lease_id=tick.claim.lease.id,
            owner_token=TOKEN,
            now=datetime.now(UTC),
        )
        time.sleep(
            max(0.0, (tick.claim.lease.expires_at - datetime.now(UTC)).total_seconds()) + 0.05
        )
        observed_at = datetime.now(UTC)
        queue.reclaim_expired(
            now=observed_at,
            retry_at=observed_at + timedelta(minutes=1),
        )
        sidecar = tmp_path / "sidecar"
        (sidecar / "artifacts").mkdir(parents=True)
        reader = UninvokedRouteClaimReader(dsn, sidecar)
        guard = WorkerExecutionGuard()
        with guard.task_scope(sidecar / "state/queue-worker-locks", task.id):
            observation = reader.inspect(task.id, guard)
            event = build_event(
                observation.task,
                TaskStatus.BLOCKED,
                event_id="evt_route_settle_terminal",
                reason="ROUTE_TRANSITION: frozen route is no longer configured",
                source_revision=observation.step.boundary.source_revision,
                attempt=observation.task.attempts,
                occurred_at=datetime.now(UTC),
            )
            settlement = RouteTransitionSettlement.create(
                observation,
                event,
                scope=RecoveryScope(
                    team_id="team_route_test",
                    repository_id=REPOSITORY_ID,
                    delivery_id="delivery_route_test",
                    repository_root=task.repository,
                ),
                checkpoint_sha256="e" * 64,
                execution_baseline_sha256="b" * 64,
                inventory_sha256="c" * 64,
                retained_capture_sha256="d" * 64,
            )
            schema = json.loads(
                (
                    Path(__file__).parents[2] / "schemas/route-transition-settlement.schema.json"
                ).read_text()
            )
            assert not tuple(Draft202012Validator(schema).iter_errors(settlement.to_wire()))
            with pytest.raises(ValueError, match="digest mismatch"):
                settlement.model_copy(update={"inventory_sha256": "0" * 64}).validate_integrity()
            with pytest.raises(QueueConflict, match="facts changed"):
                queue.settle_uninvoked_route_claim(
                    observation,
                    settlement,
                    task_lock=guard,
                    validate_current=lambda: replace(observation, expired_sequence=999),
                )
            assert repository.get(task.id).status is TaskStatus.IMPLEMENTING
            assert queue.get(step.work_item.id).status is WorkItemStatus.RETRY_SCHEDULED
        service = object.__new__(RouteTransitionSettlementService)
        service.sidecar = sidecar
        service.reader = reader
        service.queue = queue
        service.dsn = dsn
        service.scope = settlement.scope
        retained = RouteTransitionRetained(
            baseline_sha256="b" * 64,
            inventory_sha256="c" * 64,
            capture=SimpleNamespace(capture_sha256="d" * 64),
        )
        monkeypatch.setattr(service, "inspect_retained", lambda _task: retained)
        monkeypatch.setattr(service, "_require_route_changed", lambda _observed: None)
        monkeypatch.setattr(
            service,
            "_require_checkpoint",
            lambda _task_id, _revision, _sha=None: SimpleNamespace(checkpoint_sha256="e" * 64),
        )
        first, _ = service.settle(task.id)
        replay, _ = service.settle(task.id)
        assert replay == first
        assert repository.get(task.id).status is TaskStatus.BLOCKED
        assert repository.current_revision(task.id) == revision + 1
        assert queue.get(step.work_item.id).status is WorkItemStatus.CLOSED
