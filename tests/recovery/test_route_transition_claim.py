"""An expired, uninvoked generation is evidence only while its full queue is current."""

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.route_transition_claim import UninvokedRouteClaimReader
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
