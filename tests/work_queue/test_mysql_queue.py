"""MySQL integration tests for queue transactions and Lease fencing."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from ai_software_engineer.domain import (
    AgentProfile,
    AgentRole,
    BrainTier,
    ModelPolicy,
    ModelRoute,
    OrganizationRole,
    RiskModelFloor,
    RiskTier,
    RunDemand,
    WorkItemStatus,
)
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue import (
    DispatcherLoop,
    DispatcherTickStatus,
    MySqlPersistentWorkQueue,
    QueueArtifactReceipt,
    QueueConflict,
    QueuedWorkItem,
)

pytestmark = pytest.mark.mysql

NOW = datetime(2026, 9, 8, 13, 0, tzinfo=UTC)
OWNER_TOKEN = "persistent-owner-token-0001"


@pytest.fixture
def mysql_queue() -> Iterator[MySqlPersistentWorkQueue]:
    dsn = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    queue = MySqlPersistentWorkQueue(dsn)
    _clear_queue(dsn)
    yield queue
    _clear_queue(dsn)


def _clear_queue(dsn: str) -> None:
    with closing(open_mysql_connection(dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM work_queue_events")
            cursor.execute("DELETE FROM work_queue_claims")
            cursor.execute("DELETE FROM work_queue_items")
        connection.commit()


def queued_item(
    name: str = "coder",
    *,
    role: AgentRole = AgentRole.CODER,
    attempt: int = 1,
    checkpoint_sequence: int = 0,
    parent: str | None = None,
    created_at: datetime = NOW,
) -> QueuedWorkItem:
    return QueuedWorkItem(
        id=f"work_delivery_{name}_001",
        task_id="task_queue_delivery_001",
        project_id="project_platform_001",
        role=role,
        attempt=attempt,
        checkpoint_sequence=checkpoint_sequence,
        dispatch_sequence=0,
        repository_scopes=("/code/api", "/code/web"),
        parent_work_item_id=parent,
        status=WorkItemStatus.READY,
        priority=750,
        risk=RiskTier.NORMAL,
        required_capabilities=("delivery",),
        created_at=created_at,
        updated_at=created_at,
    )


def agents() -> tuple[AgentProfile, ...]:
    return tuple(
        AgentProfile(
            id=f"agent_{role.value}_queue",
            version="v1",
            display_name=role.value,
            capabilities=("delivery",),
            eligible_roles=(OrganizationRole(role.value),),
            max_parallel_assignments=1,
            default_model_policy_id="model_policy_queue_001",
        )
        for role in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)
    )


def policy() -> ModelPolicy:
    return ModelPolicy(
        id="model_policy_queue_001",
        version="v1",
        default_tier=BrainTier.STANDARD,
        routes=tuple(
            ModelRoute(provider="codex", model=f"model-{tier.value}", tier=tier)
            for tier in BrainTier
        ),
        risk_floors=tuple(
            RiskModelFloor(risk=risk, minimum_tier=tier)
            for risk, tier in (
                (RiskTier.LOW, BrainTier.ECONOMY),
                (RiskTier.NORMAL, BrainTier.STANDARD),
                (RiskTier.HIGH, BrainTier.REASONING),
                (RiskTier.CRITICAL, BrainTier.CRITICAL),
            )
        ),
    )


def demand(item: QueuedWorkItem) -> RunDemand:
    return RunDemand(
        task_id=item.task_id,
        role=item.role,
        risk=item.risk,
        required_capabilities=item.required_capabilities,
        context_tokens=1_000,
    )


def dispatcher(queue: MySqlPersistentWorkQueue, worker: str) -> DispatcherLoop:
    return DispatcherLoop(
        queue=queue,
        scheduler=PortfolioScheduler(lease_duration=timedelta(minutes=15)),
        model_router=ModelRouter(
            route_context_capacities={
                ("codex", f"model-{tier.value}"): 128_000 for tier in BrainTier
            }
        ),
        agents=agents(),
        policies=(policy(),),
        demand_builder=demand,
        worker_id=worker,
        owner_token_factory=lambda: OWNER_TOKEN,
    )


def test_queue_lifecycle_closes_current_and_atomically_publishes_next(
    mysql_queue: MySqlPersistentWorkQueue,
) -> None:
    coder = queued_item()
    assert mysql_queue.enqueue(coder) == coder
    assert mysql_queue.enqueue(coder) == coder

    tick = dispatcher(mysql_queue, "worker_host_one").tick(now=NOW)
    assert tick.status is DispatcherTickStatus.DISPATCHED
    assert tick.claim is not None
    claim = tick.claim

    with pytest.raises(QueueConflict, match="owner"):
        mysql_queue.start(
            coder.id,
            lease_id=claim.lease.id,
            owner_token="wrong-owner-token-0000",
            now=NOW + timedelta(seconds=1),
        )

    running = mysql_queue.start(
        coder.id,
        lease_id=claim.lease.id,
        owner_token=OWNER_TOKEN,
        now=NOW + timedelta(seconds=1),
    )
    assert running.status is WorkItemStatus.RUNNING
    renewed = mysql_queue.renew(
        coder.id,
        lease_id=claim.lease.id,
        owner_token=OWNER_TOKEN,
        now=NOW + timedelta(seconds=2),
        expires_at=NOW + timedelta(minutes=30),
    )
    assert renewed.expires_at == NOW + timedelta(minutes=30)

    qa = queued_item(
        "qa",
        role=AgentRole.QA,
        parent=coder.id,
        created_at=NOW + timedelta(seconds=3),
    )
    completion = mysql_queue.complete(
        coder.id,
        lease_id=claim.lease.id,
        owner_token=OWNER_TOKEN,
        artifacts=(QueueArtifactReceipt(artifact_id="artifact_impl", sha256="a" * 64),),
        next_work_item=qa,
        now=NOW + timedelta(seconds=3),
    )

    assert completion.work_item.status is WorkItemStatus.CLOSED
    assert completion.next_work_item == qa
    assert (
        mysql_queue.complete(
            coder.id,
            lease_id=claim.lease.id,
            owner_token=OWNER_TOKEN,
            artifacts=(QueueArtifactReceipt(artifact_id="artifact_impl", sha256="a" * 64),),
            next_work_item=qa,
            now=NOW + timedelta(seconds=10),
        )
        == completion
    )
    assert mysql_queue.get(qa.id) == qa
    assert mysql_queue.list_active_leases(now=NOW + timedelta(seconds=4)) == ()
    assert mysql_queue.list_assignments() == (claim.assignment,)


def test_wait_resume_and_expired_owner_recovery(
    mysql_queue: MySqlPersistentWorkQueue,
) -> None:
    coder = mysql_queue.enqueue(queued_item())
    first = dispatcher(mysql_queue, "worker_host_one").tick(now=NOW)
    assert first.claim is not None
    claim = first.claim
    waiting = mysql_queue.wait(
        coder.id,
        lease_id=claim.lease.id,
        owner_token=OWNER_TOKEN,
        status=WorkItemStatus.WAITING_DEPENDENCY,
        reason="integration service unavailable",
        now=NOW + timedelta(seconds=1),
    )
    assert waiting.status is WorkItemStatus.WAITING_DEPENDENCY
    assert mysql_queue.list_active_leases(now=NOW + timedelta(seconds=2)) == ()
    assert (
        mysql_queue.make_ready(coder.id, now=NOW + timedelta(seconds=3)).status
        is WorkItemStatus.READY
    )

    second = dispatcher(mysql_queue, "worker_host_two").tick(now=NOW + timedelta(seconds=4))
    assert second.claim is not None
    reap_tick = dispatcher(mysql_queue, "worker_host_reaper").tick(
        now=second.claim.lease.expires_at
    )
    assert reap_tick.status is DispatcherTickStatus.IDLE
    assert reap_tick.reclaimed_work_item_ids == (coder.id,)
    reclaimed = (mysql_queue.get(coder.id),)
    assert reclaimed[0].status is WorkItemStatus.RETRY_SCHEDULED
    with pytest.raises(QueueConflict, match="state changed"):
        mysql_queue.complete(
            coder.id,
            lease_id=second.claim.lease.id,
            owner_token=OWNER_TOKEN,
            artifacts=(),
            next_work_item=None,
            now=second.claim.lease.expires_at + timedelta(seconds=1),
        )
    assert mysql_queue.list_schedulable(now=second.claim.lease.expires_at) == ()
    assert (
        mysql_queue.list_schedulable(now=second.claim.lease.expires_at + timedelta(seconds=30))
        == reclaimed
    )


def test_two_dispatchers_cannot_claim_the_same_work_item(
    mysql_queue: MySqlPersistentWorkQueue,
) -> None:
    mysql_queue.enqueue(queued_item())
    loops = (
        dispatcher(mysql_queue, "worker_host_one"),
        dispatcher(mysql_queue, "worker_host_two"),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda loop: loop.tick(now=NOW), loops))

    assert sum(result.status is DispatcherTickStatus.DISPATCHED for result in results) == 1
    assert len(mysql_queue.list_active_leases(now=NOW + timedelta(seconds=1))) == 1
