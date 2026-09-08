"""Planner-owned deterministic dispatch loop over the PersistentWorkQueue."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.workforce import AgentProfile, ModelPolicy, RunDemand
from ai_software_engineer.scheduling import (
    AssignmentDecisionStatus,
    ModelRouter,
    ModelRoutingDecisionStatus,
    PortfolioScheduler,
)
from ai_software_engineer.work_queue.models import (
    LeaseWorkerId,
    QueueClaim,
    QueuedWorkItem,
    WorkItemId,
)
from ai_software_engineer.work_queue.ports import PersistentWorkQueue, QueueConflict


class DispatcherTickStatus(StrEnum):
    """Outcome of one bounded Dispatcher iteration."""

    DISPATCHED = "DISPATCHED"
    IDLE = "IDLE"
    REJECTED = "REJECTED"


class DispatcherTickResult(DomainModel):
    """Auditable result; the owner token is intentionally absent from wire output."""

    kind: Literal["dispatcher_tick_result"] = "dispatcher_tick_result"
    status: DispatcherTickStatus
    claim: QueueClaim | None = None
    rejections: tuple[NonEmptyStr, ...] = ()
    reclaimed_work_item_ids: tuple[WorkItemId, ...] = ()
    ticked_at: AwareDatetime
    lease_owner_token: Annotated[str | None, Field(exclude=True, repr=False)] = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        ensure_unique(self.rejections, "Dispatcher rejection reasons")
        ensure_unique(self.reclaimed_work_item_ids, "Dispatcher reclaimed WorkItem IDs")
        if self.status is DispatcherTickStatus.DISPATCHED:
            if self.claim is None or self.lease_owner_token is None:
                raise ValueError("DISPATCHED tick requires claim and owner token")
            if self.rejections:
                raise ValueError("DISPATCHED tick cannot carry terminal rejections")
        elif self.claim is not None or self.lease_owner_token is not None:
            raise ValueError("non-dispatched tick cannot carry claim authority")
        if self.status is DispatcherTickStatus.REJECTED and not self.rejections:
            raise ValueError("REJECTED tick requires reasons")
        if self.status is DispatcherTickStatus.IDLE and self.rejections:
            raise ValueError("IDLE tick cannot carry rejections")
        return self


RunDemandBuilder = Callable[[QueuedWorkItem], RunDemand]
OwnerTokenFactory = Callable[[], str]
_WORKER_ID_ADAPTER = TypeAdapter(LeaseWorkerId)


class DispatcherLoop:
    """Execute one reliable dispatch tick; an external supervisor owns repetition."""

    def __init__(
        self,
        *,
        queue: PersistentWorkQueue,
        scheduler: PortfolioScheduler,
        model_router: ModelRouter,
        agents: Sequence[AgentProfile],
        policies: Sequence[ModelPolicy],
        demand_builder: RunDemandBuilder,
        worker_id: LeaseWorkerId | str,
        owner_token_factory: OwnerTokenFactory | None = None,
        scan_limit: int = 100,
        expired_lease_retry_delay: timedelta = timedelta(seconds=30),
    ) -> None:
        if scan_limit < 1 or scan_limit > 1000:
            raise ValueError("Dispatcher scan_limit must be between 1 and 1000")
        if len({agent.id for agent in agents}) != len(agents):
            raise ValueError("Dispatcher Agent IDs must be unique")
        if len({policy.id for policy in policies}) != len(policies):
            raise ValueError("Dispatcher ModelPolicy IDs must be unique")
        if expired_lease_retry_delay <= timedelta(0):
            raise ValueError("Dispatcher expired Lease retry delay must be positive")
        typed_worker_id = _WORKER_ID_ADAPTER.validate_python(worker_id)
        self._queue = queue
        self._scheduler = scheduler
        self._model_router = model_router
        self._agents = tuple(agents)
        self._policies: Mapping[str, ModelPolicy] = {policy.id: policy for policy in policies}
        self._demand_builder = demand_builder
        self._worker_id = typed_worker_id
        self._owner_token_factory = owner_token_factory or (lambda: secrets.token_urlsafe(32))
        self._scan_limit = scan_limit
        self._expired_lease_retry_delay = expired_lease_retry_delay

    def tick(self, *, now: datetime) -> DispatcherTickResult:
        """Claim at most one Run-level WorkItem using current durable capacity facts."""
        reclaimed = self._queue.reclaim_expired(
            now=now,
            retry_at=now + self._expired_lease_retry_delay,
        )
        reclaimed_ids = tuple(item.id for item in reclaimed)
        candidates = self._queue.list_schedulable(now=now, limit=self._scan_limit)
        if not candidates:
            return DispatcherTickResult(
                status=DispatcherTickStatus.IDLE,
                reclaimed_work_item_ids=reclaimed_ids,
                ticked_at=now,
            )

        active_leases = self._queue.list_active_leases(now=now)
        assignments = self._queue.list_assignments()
        rejection_messages: list[str] = []
        for item in candidates:
            decision = self._scheduler.match(
                item,
                item.role,
                self._agents,
                active_leases,
                assignments,
                now=now,
                attempt=item.attempt,
                work_items=candidates,
            )
            if decision.status is AssignmentDecisionStatus.REJECTED:
                rejection_messages.extend(
                    f"{item.id}:{reason.code.value}" for reason in decision.reasons
                )
                continue
            assert decision.agent_id is not None
            assert decision.assignment is not None
            assert decision.lease is not None
            agent = next(profile for profile in self._agents if profile.id == decision.agent_id)
            policy = self._policies.get(agent.default_model_policy_id)
            if policy is None:
                rejection_messages.append(f"{item.id}:MODEL_POLICY_MISSING")
                continue
            demand = self._demand_builder(item)
            if (
                demand.task_id != item.task_id
                or demand.role is not item.role
                or demand.risk is not item.risk
                or demand.required_capabilities != item.required_capabilities
            ):
                raise ValueError("Dispatcher RunDemand does not match queued WorkItem")
            routing = self._model_router.route(demand, agent, policy, now=now)
            if routing.status is ModelRoutingDecisionStatus.REJECTED:
                assert routing.refusal is not None
                rejection_messages.append(f"{item.id}:{routing.refusal.code.value}")
                continue
            assert routing.selection is not None
            owner_token = self._owner_token_factory()
            try:
                claim = self._queue.claim(
                    item,
                    assignment=decision.assignment,
                    lease=decision.lease,
                    model_selection=routing.selection,
                    worker_id=self._worker_id,
                    owner_token=owner_token,
                    agent_capacity=agent.max_parallel_assignments,
                    now=now,
                )
            except QueueConflict:
                # Another dispatcher won or capacity changed after the pure preview.
                continue
            return DispatcherTickResult(
                status=DispatcherTickStatus.DISPATCHED,
                claim=claim,
                reclaimed_work_item_ids=reclaimed_ids,
                lease_owner_token=owner_token,
                ticked_at=now,
            )

        if rejection_messages:
            return DispatcherTickResult(
                status=DispatcherTickStatus.REJECTED,
                rejections=tuple(dict.fromkeys(rejection_messages)),
                reclaimed_work_item_ids=reclaimed_ids,
                ticked_at=now,
            )
        return DispatcherTickResult(
            status=DispatcherTickStatus.IDLE,
            reclaimed_work_item_ids=reclaimed_ids,
            ticked_at=now,
        )


__all__ = ["DispatcherLoop", "DispatcherTickResult", "DispatcherTickStatus"]
