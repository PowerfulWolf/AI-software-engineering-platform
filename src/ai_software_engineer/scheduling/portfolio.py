"""Pure, deterministic organization workforce scheduling.

The scheduler owns neither a queue store nor Task delivery state.  It receives immutable
snapshots, computes a decision, and returns newly constructed Assignment/Lease facts.  A caller
can persist those facts or discard them without changing the result of a replay.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from hashlib import sha256

from ai_software_engineer.domain.agent import AgentId
from ai_software_engineer.domain.enums import AgentRole, RiskTier, WorkItemStatus
from ai_software_engineer.domain.task import AttemptCount, TaskId
from ai_software_engineer.domain.workforce import (
    AgentProfile,
    RoleAssignment,
    TaskLease,
    WorkItem,
    is_waiting,
    lease_is_active,
    validate_assignment_independence,
)
from ai_software_engineer.scheduling.models import (
    AssignmentDecision,
    AssignmentDecisionStatus,
    AssignmentRejection,
    AssignmentRejectionCode,
)


class SchedulerInputError(ValueError):
    """Raised when a scheduler snapshot cannot be evaluated safely."""


_RISK_RANK: Mapping[RiskTier, int] = {
    RiskTier.LOW: 0,
    RiskTier.NORMAL: 1,
    RiskTier.HIGH: 2,
    RiskTier.CRITICAL: 3,
}


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchedulerInputError(f"{label} must be timezone-aware")


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _active_capacity(
    agents: Iterable[AgentProfile],
    leases: Iterable[TaskLease],
    work_items: Iterable[WorkItem],
    *,
    at: datetime,
) -> dict[AgentId, int]:
    """Aggregate active Lease units, excluding leases held by waiting WorkItems."""
    _require_aware(at, "capacity evaluation time")
    known_agents = {agent.id for agent in agents}
    waiting_tasks = {item.task_id for item in work_items if is_waiting(item.status)}
    totals = {agent_id: 0 for agent_id in known_agents}
    for lease in leases:
        if not lease_is_active(lease, at=at) or lease.task_id in waiting_tasks:
            continue
        # Unknown agents are retained so malformed snapshots never hide capacity consumption.
        totals[lease.agent_id] = totals.get(lease.agent_id, 0) + lease.capacity_units
    return totals


def active_capacity_by_agent(
    agents: Sequence[AgentProfile],
    leases: Sequence[TaskLease],
    work_items: Sequence[WorkItem] = (),
    *,
    at: datetime,
) -> dict[AgentId, int]:
    """Public pure helper used by queue projections and tests."""
    return _active_capacity(agents, leases, work_items, at=at)


def _work_item_sort_key(item: WorkItem, *, now: datetime) -> tuple[int, int, int, datetime, TaskId]:
    # Ready work wins; then priority, risk, and age (oldest first). Task ID is the stable tie-break.
    ready = int(
        item.status in {WorkItemStatus.READY, WorkItemStatus.RETRY_SCHEDULED}
        and (item.available_at is None or item.available_at <= now)
    )
    return (
        0 if ready else 1,
        -item.priority,
        -_RISK_RANK[item.risk],
        item.created_at,
        item.task_id,
    )


class PortfolioScheduler:
    """Single-process bounded scheduler for independent Task WorkItems."""

    def __init__(self, *, lease_duration: timedelta = timedelta(minutes=15)) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._lease_duration = lease_duration

    @property
    def lease_duration(self) -> timedelta:
        """Configured duration for newly emitted leases."""
        return self._lease_duration

    def match(
        self,
        work_item: WorkItem,
        role: AgentRole,
        agents: Sequence[AgentProfile],
        active_leases: Sequence[TaskLease],
        assignments: Sequence[RoleAssignment] = (),
        *,
        now: datetime,
        attempt: AttemptCount = 1,
        work_items: Sequence[WorkItem] = (),
    ) -> AssignmentDecision:
        """Match one WorkItem without mutating any input collection."""
        _require_aware(now, "scheduler time")
        if attempt < 1:
            raise SchedulerInputError("attempt must be at least 1")
        all_work_items = tuple(work_items) or (work_item,)
        if work_item not in all_work_items:
            all_work_items = (*all_work_items, work_item)

        early = self._readiness_rejection(work_item, now=now)
        if early is not None:
            return self._rejected(work_item, role, attempt, now, (early,))

        capacity = _active_capacity(agents, active_leases, all_work_items, at=now)
        ordered_agents = sorted(agents, key=lambda agent: self._agent_sort_key(agent, capacity))
        rejections: list[AssignmentRejection] = []
        for agent in ordered_agents:
            missing = tuple(sorted(set(work_item.required_capabilities) - set(agent.capabilities)))
            rejection_code: AssignmentRejectionCode | None = None
            message = ""
            if not agent.active:
                rejection_code = AssignmentRejectionCode.INACTIVE_AGENT
                message = f"Agent {agent.id} is inactive"
            elif role not in agent.eligible_roles:
                rejection_code = AssignmentRejectionCode.ROLE_NOT_ELIGIBLE
                message = f"Agent {agent.id} is not eligible for role {role.value}"
            elif missing:
                rejection_code = AssignmentRejectionCode.CAPABILITY_MISMATCH
                message = f"Agent {agent.id} lacks required capabilities: {', '.join(missing)}"
            elif capacity.get(agent.id, 0) + 1 > agent.max_parallel_assignments:
                rejection_code = AssignmentRejectionCode.CAPACITY_EXHAUSTED
                message = (
                    f"Agent {agent.id} has no capacity ({capacity.get(agent.id, 0)}"
                    f"/{agent.max_parallel_assignments})"
                )
            else:
                candidate = self._build_assignment(work_item, role, agent.id, attempt, now)
                try:
                    validate_assignment_independence(candidate, tuple(assignments))
                except ValueError as error:
                    rejection_code = AssignmentRejectionCode.SELF_REVIEW
                    message = str(error)
                else:
                    lease = self._build_lease(candidate, work_item.task_id, agent.id, now)
                    return AssignmentDecision(
                        status=AssignmentDecisionStatus.ASSIGNED,
                        task_id=work_item.task_id,
                        project_id=work_item.project_id,
                        role=role,
                        attempt=attempt,
                        agent_id=agent.id,
                        assignment=candidate,
                        lease=lease,
                        decided_at=now,
                    )
            assert rejection_code is not None
            rejections.append(
                AssignmentRejection(
                    code=rejection_code,
                    message=message,
                    agent_id=agent.id,
                    missing_capabilities=missing
                    if rejection_code is AssignmentRejectionCode.CAPABILITY_MISMATCH
                    else (),
                )
            )

        if not rejections:
            rejections.append(
                AssignmentRejection(
                    code=AssignmentRejectionCode.INVALID_INPUT,
                    message="No AgentProfile was supplied",
                )
            )
        return self._rejected(work_item, role, attempt, now, tuple(rejections))

    def schedule(
        self,
        work_items: Sequence[WorkItem],
        role: AgentRole,
        agents: Sequence[AgentProfile],
        active_leases: Sequence[TaskLease],
        assignments: Sequence[RoleAssignment] = (),
        *,
        now: datetime,
        attempt: AttemptCount = 1,
    ) -> tuple[AssignmentDecision, ...]:
        """Schedule a batch by stable priority/age/risk order.

        Newly emitted leases are included in subsequent capacity calculations, so a single Agent
        cannot be overbooked merely because several WorkItems were presented in one call.
        """
        _require_aware(now, "scheduler time")
        if len({item.task_id for item in work_items}) != len(work_items):
            raise SchedulerInputError("work_items must contain unique task IDs")
        pending_leases = tuple(active_leases)
        decisions: list[AssignmentDecision] = []
        for item in sorted(work_items, key=lambda item: _work_item_sort_key(item, now=now)):
            decision = self.match(
                item,
                role,
                agents,
                pending_leases,
                assignments,
                now=now,
                attempt=attempt,
                work_items=work_items,
            )
            decisions.append(decision)
            if decision.lease is not None:
                pending_leases += (decision.lease,)
        return tuple(decisions)

    @staticmethod
    def _agent_sort_key(
        agent: AgentProfile, capacity: Mapping[AgentId, int]
    ) -> tuple[int, int, AgentId]:
        available = agent.max_parallel_assignments - capacity.get(agent.id, 0)
        return (-available, -agent.max_parallel_assignments, agent.id)

    @staticmethod
    def _readiness_rejection(item: WorkItem, *, now: datetime) -> AssignmentRejection | None:
        if item.status is WorkItemStatus.CLOSED:
            return AssignmentRejection(
                code=AssignmentRejectionCode.CLOSED,
                message=f"WorkItem {item.task_id} is closed",
            )
        if item.status is WorkItemStatus.RETRY_SCHEDULED:
            if item.available_at is not None and item.available_at <= now:
                return None
            return AssignmentRejection(
                code=AssignmentRejectionCode.NOT_READY,
                message=f"WorkItem {item.task_id} is unavailable until {item.available_at}",
            )
        if is_waiting(item.status):
            return AssignmentRejection(
                code=AssignmentRejectionCode.WAITING,
                message=f"WorkItem {item.task_id} is waiting: {item.wait_reason}",
            )
        if item.status not in {WorkItemStatus.READY, WorkItemStatus.RETRY_SCHEDULED}:
            return AssignmentRejection(
                code=AssignmentRejectionCode.NOT_READY,
                message=f"WorkItem {item.task_id} status {item.status.value} is not schedulable",
            )
        if item.available_at is not None and item.available_at > now:
            available_at = item.available_at.isoformat()
            return AssignmentRejection(
                code=AssignmentRejectionCode.NOT_READY,
                message=f"WorkItem {item.task_id} is unavailable until {available_at}",
            )
        return None

    @staticmethod
    def _build_assignment(
        item: WorkItem, role: AgentRole, agent_id: AgentId, attempt: AttemptCount, now: datetime
    ) -> RoleAssignment:
        assignment_id = _stable_id("assignment", item.task_id, role.value, agent_id, str(attempt))
        lease_id = _stable_id("lease", assignment_id)
        return RoleAssignment(
            id=assignment_id,
            project_id=item.project_id,
            task_id=item.task_id,
            agent_id=agent_id,
            role=role,
            attempt=attempt,
            lease_id=lease_id,
            assigned_at=now,
        )

    def _build_lease(
        self, assignment: RoleAssignment, task_id: TaskId, agent_id: AgentId, now: datetime
    ) -> TaskLease:
        return TaskLease(
            id=assignment.lease_id,
            assignment_id=assignment.id,
            task_id=task_id,
            agent_id=agent_id,
            acquired_at=now,
            expires_at=now + self._lease_duration,
        )

    @staticmethod
    def _rejected(
        item: WorkItem,
        role: AgentRole,
        attempt: AttemptCount,
        now: datetime,
        reasons: tuple[AssignmentRejection, ...],
    ) -> AssignmentDecision:
        return AssignmentDecision(
            status=AssignmentDecisionStatus.REJECTED,
            task_id=item.task_id,
            project_id=item.project_id,
            role=role,
            attempt=attempt,
            reasons=reasons,
            decided_at=now,
        )


__all__ = ["PortfolioScheduler", "SchedulerInputError", "active_capacity_by_agent"]
