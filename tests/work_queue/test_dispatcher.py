"""Deterministic Planner-owned Dispatcher tests."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

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
from ai_software_engineer.domain.workforce import ModelSelection, RoleAssignment, TaskLease
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.work_queue import (
    DispatcherLoop,
    DispatcherTickStatus,
    QueueArtifactReceipt,
    QueueClaim,
    QueueCompletion,
    QueuedWorkItem,
)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def item(**updates: object) -> QueuedWorkItem:
    values: dict[str, object] = {
        "id": "work_delivery_coder_001",
        "task_id": "task_delivery_001",
        "project_id": "project_platform_001",
        "role": AgentRole.CODER,
        "attempt": 1,
        "checkpoint_sequence": 0,
        "dispatch_sequence": 0,
        "repository_scopes": ("/code/platform",),
        "status": WorkItemStatus.READY,
        "priority": 800,
        "risk": RiskTier.NORMAL,
        "required_capabilities": ("python",),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return QueuedWorkItem.model_validate(values)


def agent(name: str, *, capacity: int = 1) -> AgentProfile:
    return AgentProfile(
        id=f"agent_{name}_001",
        version="v1",
        display_name=name,
        capabilities=("python",),
        eligible_roles=(OrganizationRole.CODER,),
        max_parallel_assignments=capacity,
        default_model_policy_id="model_policy_default_001",
    )


def policy() -> ModelPolicy:
    return ModelPolicy(
        id="model_policy_default_001",
        version="v1",
        default_tier=BrainTier.STANDARD,
        routes=(
            ModelRoute(provider="codex", model="gpt-5.5", tier=BrainTier.STANDARD),
            ModelRoute(provider="codex", model="gpt-reasoning", tier=BrainTier.REASONING),
            ModelRoute(provider="codex", model="gpt-critical", tier=BrainTier.CRITICAL),
            ModelRoute(provider="qwen", model="qwen-economy", tier=BrainTier.ECONOMY),
        ),
        risk_floors=(
            RiskModelFloor(risk=RiskTier.LOW, minimum_tier=BrainTier.ECONOMY),
            RiskModelFloor(risk=RiskTier.NORMAL, minimum_tier=BrainTier.STANDARD),
            RiskModelFloor(risk=RiskTier.HIGH, minimum_tier=BrainTier.REASONING),
            RiskModelFloor(risk=RiskTier.CRITICAL, minimum_tier=BrainTier.CRITICAL),
        ),
    )


class MemoryQueue:
    """Small protocol fake; lifecycle behavior belongs to MySQL integration tests."""

    def __init__(self, items: tuple[QueuedWorkItem, ...]) -> None:
        self.items = items
        self.claims: list[QueueClaim] = []
        self.expired: tuple[QueuedWorkItem, ...] = ()
        self.last_reclaim_window: tuple[datetime, datetime] | None = None

    def enqueue(self, queued: QueuedWorkItem) -> QueuedWorkItem:
        self.items += (queued,)
        return queued

    def get(self, work_item_id: str) -> QueuedWorkItem:
        return next(queued for queued in self.items if queued.id == work_item_id)

    def list_schedulable(self, *, now: datetime, limit: int = 100) -> tuple[QueuedWorkItem, ...]:
        del now
        return tuple(x for x in self.items if x.status is WorkItemStatus.READY)[:limit]

    def list_active_leases(self, *, now: datetime) -> tuple[TaskLease, ...]:
        return tuple(claim.lease for claim in self.claims if claim.lease.expires_at > now)

    def list_assignments(self) -> tuple[RoleAssignment, ...]:
        return tuple(claim.assignment for claim in self.claims)

    def claim(
        self,
        queued: QueuedWorkItem,
        *,
        assignment: RoleAssignment,
        lease: TaskLease,
        model_selection: ModelSelection,
        worker_id: str,
        owner_token: str,
        agent_capacity: int,
        now: datetime,
    ) -> QueueClaim:
        del owner_token, agent_capacity
        leased = queued.model_copy(update={"status": WorkItemStatus.LEASED, "updated_at": now})
        claim = QueueClaim(
            work_item=leased,
            assignment=assignment,
            lease=lease,
            model_selection=model_selection,
            worker_id=worker_id,
            claimed_at=now,
        )
        self.items = tuple(leased if x.id == queued.id else x for x in self.items)
        self.claims.append(claim)
        return claim

    def start(
        self, work_item_id: str, *, lease_id: str, owner_token: str, now: datetime
    ) -> QueuedWorkItem:
        raise NotImplementedError

    def renew(
        self,
        work_item_id: str,
        *,
        lease_id: str,
        owner_token: str,
        now: datetime,
        expires_at: datetime,
    ) -> TaskLease:
        raise NotImplementedError

    def complete(
        self,
        work_item_id: str,
        *,
        lease_id: str,
        owner_token: str,
        artifacts: Sequence[QueueArtifactReceipt],
        next_work_item: QueuedWorkItem | None,
        now: datetime,
    ) -> QueueCompletion:
        raise NotImplementedError

    def wait(
        self,
        work_item_id: str,
        *,
        lease_id: str,
        owner_token: str,
        status: WorkItemStatus,
        reason: str,
        now: datetime,
    ) -> QueuedWorkItem:
        raise NotImplementedError

    def retry(
        self,
        work_item_id: str,
        *,
        lease_id: str,
        owner_token: str,
        reason: str,
        now: datetime,
        available_at: datetime,
    ) -> QueuedWorkItem:
        raise NotImplementedError

    def make_ready(self, work_item_id: str, *, now: datetime) -> QueuedWorkItem:
        raise NotImplementedError

    def reclaim_expired(self, *, now: datetime, retry_at: datetime) -> tuple[QueuedWorkItem, ...]:
        self.last_reclaim_window = (now, retry_at)
        reclaimed = tuple(
            queued.model_copy(
                update={
                    "status": WorkItemStatus.RETRY_SCHEDULED,
                    "dispatch_sequence": queued.dispatch_sequence + 1,
                    "wait_reason": "lease_expired:test",
                    "available_at": retry_at,
                    "updated_at": now,
                }
            )
            for queued in self.expired
        )
        self.items = tuple(
            next((new for new in reclaimed if new.id == queued.id), queued) for queued in self.items
        )
        self.expired = ()
        return reclaimed


def demand(queued: QueuedWorkItem) -> RunDemand:
    return RunDemand(
        task_id=queued.task_id,
        role=queued.role,
        risk=queued.risk,
        required_capabilities=queued.required_capabilities,
        context_tokens=1_000,
    )


def dispatcher(queue: MemoryQueue, *agents: AgentProfile) -> DispatcherLoop:
    return DispatcherLoop(
        queue=queue,
        scheduler=PortfolioScheduler(),
        model_router=ModelRouter(
            route_context_capacities={
                ("codex", "gpt-5.5"): 128_000,
                ("codex", "gpt-reasoning"): 128_000,
                ("codex", "gpt-critical"): 128_000,
                ("qwen", "qwen-economy"): 128_000,
            }
        ),
        agents=agents,
        policies=(policy(),),
        demand_builder=demand,
        worker_id="worker_team_host_001",
        owner_token_factory=lambda: "queue-owner-token-0001",
    )


def test_tick_claims_one_run_and_does_not_serialize_owner_authority() -> None:
    queue = MemoryQueue((item(),))

    result = dispatcher(queue, agent("coder")).tick(now=NOW)

    assert result.status is DispatcherTickStatus.DISPATCHED
    assert result.claim is not None
    assert result.claim.work_item.status is WorkItemStatus.LEASED
    assert result.claim.assignment.role is AgentRole.CODER
    assert result.claim.model_selection.model == "gpt-5.5"
    assert result.lease_owner_token == "queue-owner-token-0001"
    assert "lease_owner_token" not in result.to_wire()


def test_tick_prefers_continuation_agent_and_is_idle_without_ready_work() -> None:
    preferred = agent("preferred", capacity=1)
    queued = item(preferred_agent_id=preferred.id)
    queue = MemoryQueue((queued,))

    result = dispatcher(queue, agent("other", capacity=4), preferred).tick(now=NOW)

    assert result.claim is not None
    assert result.claim.assignment.agent_id == preferred.id
    assert dispatcher(MemoryQueue(()), preferred).tick(now=NOW).status is DispatcherTickStatus.IDLE


def test_tick_returns_typed_rejections_when_no_member_is_eligible() -> None:
    queue = MemoryQueue((item(required_capabilities=("java",)),))

    result = dispatcher(queue, agent("python"), agent("python_two")).tick(now=NOW)

    assert result.status is DispatcherTickStatus.REJECTED
    assert result.rejections == ("work_delivery_coder_001:CAPABILITY_MISMATCH",)


def test_dispatcher_rejects_invalid_worker_identity_and_naive_tick_clock() -> None:
    queue = MemoryQueue((item(),))

    with pytest.raises(ValidationError):
        DispatcherLoop(
            queue=queue,
            scheduler=PortfolioScheduler(),
            model_router=ModelRouter(route_context_capacities={}),
            agents=(agent("coder"),),
            policies=(policy(),),
            demand_builder=demand,
            worker_id="worker_",
        )

    with pytest.raises(ValidationError):
        dispatcher(MemoryQueue(()), agent("coder")).tick(now=datetime(2026, 9, 8, 12, 0))


def test_tick_reclaims_expired_lease_before_scanning_for_new_work() -> None:
    expired = item(status=WorkItemStatus.RUNNING)
    queue = MemoryQueue((expired,))
    queue.expired = (expired,)

    result = dispatcher(queue, agent("coder")).tick(now=NOW)

    assert result.status is DispatcherTickStatus.IDLE
    assert result.reclaimed_work_item_ids == (expired.id,)
    assert queue.last_reclaim_window == (NOW, NOW + timedelta(seconds=30))
    assert queue.items[0].status is WorkItemStatus.RETRY_SCHEDULED
    assert queue.items[0].dispatch_sequence == 1


def test_queued_work_item_rejects_non_delivery_role_and_duplicate_scopes() -> None:
    for updates in (
        {"role": AgentRole.ORCHESTRATOR},
        {"repository_scopes": ("/code/platform", "/code/platform")},
    ):
        with pytest.raises(ValidationError):
            item(**updates)
