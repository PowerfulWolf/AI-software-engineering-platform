"""Deterministic organization scheduling and model-routing behavior."""

from datetime import UTC, datetime, timedelta

import pytest

from ai_software_engineer.domain import (
    AgentProfile,
    AgentRole,
    BrainTier,
    ModelPolicy,
    ModelRoute,
    ModelRouteReason,
    RiskModelFloor,
    RiskTier,
    RoleAssignment,
    RunDemand,
    TaskLease,
    WorkItem,
    WorkItemStatus,
)
from ai_software_engineer.scheduling import (
    AssignmentDecisionStatus,
    AssignmentRejectionCode,
    ModelRejectionCode,
    ModelRouter,
    ModelRoutingDecisionStatus,
    ModelRoutingRejected,
    PortfolioScheduler,
    active_capacity_by_agent,
)

NOW = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def agent(
    name: str = "alpha",
    *,
    capabilities: tuple[str, ...] = ("python",),
    roles: tuple[AgentRole, ...] = (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER),
    max_parallel_assignments: int = 1,
    active: bool = True,
) -> AgentProfile:
    return AgentProfile(
        id=f"agent_{name}_001",
        version="v1",
        display_name=name,
        capabilities=capabilities,
        eligible_roles=roles,
        max_parallel_assignments=max_parallel_assignments,
        default_model_policy_id="model_policy_default_001",
        active=active,
    )


def work_item(
    name: str = "one",
    *,
    priority: int = 500,
    risk: RiskTier = RiskTier.NORMAL,
    capabilities: tuple[str, ...] = ("python",),
    status: WorkItemStatus = WorkItemStatus.READY,
    created_at: datetime = NOW,
    available_at: datetime | None = None,
) -> WorkItem:
    waiting = status in {
        WorkItemStatus.WAITING_HUMAN,
        WorkItemStatus.WAITING_DEPENDENCY,
        WorkItemStatus.RETRY_SCHEDULED,
    }
    return WorkItem(
        task_id=f"task_{name}_001",
        project_id="project_platform_001",
        status=status,
        priority=priority,
        risk=risk,
        required_capabilities=capabilities,
        wait_reason="waiting for input" if waiting else None,
        available_at=available_at,
        created_at=created_at,
        updated_at=NOW,
    )


def assignment(
    *,
    task_id: str = "task_one_001",
    role: AgentRole = AgentRole.CODER,
    agent_id: str = "agent_alpha_001",
    attempt: int = 1,
) -> RoleAssignment:
    return RoleAssignment(
        id=f"assignment_{role.value}_{attempt:03d}",
        project_id="project_platform_001",
        task_id=task_id,
        agent_id=agent_id,
        role=role,
        attempt=attempt,
        lease_id=f"lease_{role.value}_{attempt:03d}",
        assigned_at=NOW,
    )


def lease(
    *,
    task_id: str = "task_one_001",
    agent_id: str = "agent_alpha_001",
    capacity_units: int = 1,
    acquired_at: datetime = NOW,
    expires_at: datetime = NOW + timedelta(minutes=10),
) -> TaskLease:
    return TaskLease(
        id="lease_existing_001",
        assignment_id="assignment_existing_001",
        task_id=task_id,
        agent_id=agent_id,
        capacity_units=capacity_units,
        acquired_at=acquired_at,
        expires_at=expires_at,
    )


def policy() -> ModelPolicy:
    return ModelPolicy(
        id="model_policy_default_001",
        version="v1",
        default_tier=BrainTier.STANDARD,
        routes=tuple(
            ModelRoute(provider="provider_a", model=f"model_{tier.value}", tier=tier)
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


def demand(**updates: object) -> RunDemand:
    values: dict[str, object] = {
        "task_id": "task_one_001",
        "role": AgentRole.CODER,
        "risk": RiskTier.LOW,
    }
    values.update(updates)
    return RunDemand.model_validate(values)


def test_match_is_deterministic_and_emits_independent_assignment_and_lease() -> None:
    scheduler = PortfolioScheduler(lease_duration=timedelta(minutes=20))
    first = scheduler.match(work_item(), AgentRole.CODER, [agent()], [], now=NOW)
    second = scheduler.match(work_item(), AgentRole.CODER, [agent()], [], now=NOW)

    assert first.status is AssignmentDecisionStatus.ASSIGNED
    assert first.to_wire() == second.to_wire()
    assert first.assignment is not None and first.lease is not None
    assert first.assignment.lease_id == first.lease.id
    assert first.lease.expires_at == NOW + timedelta(minutes=20)


def test_active_capacity_aggregates_units_and_releases_expired_or_waiting_leases() -> None:
    profile = agent(max_parallel_assignments=3)
    waiting = work_item("waiting", status=WorkItemStatus.WAITING_HUMAN)
    current = lease(capacity_units=2)
    expired = lease(
        task_id="task_expired_001",
        acquired_at=NOW - timedelta(minutes=20),
        expires_at=NOW - timedelta(minutes=1),
    )
    held_by_waiting = lease(task_id=waiting.task_id)

    assert active_capacity_by_agent(
        [profile], [current, expired, held_by_waiting], [waiting], at=NOW
    ) == {profile.id: 2}


def test_schedule_orders_ready_work_by_priority_risk_then_age_and_applies_new_leases() -> None:
    scheduler = PortfolioScheduler()
    items = (
        work_item("old", priority=500, created_at=NOW - timedelta(hours=1)),
        work_item("high", priority=800, risk=RiskTier.LOW),
        work_item("risk", priority=800, risk=RiskTier.HIGH),
    )
    decisions = scheduler.schedule(items, AgentRole.CODER, [agent()], [], now=NOW)

    assert [decision.task_id for decision in decisions] == [
        "task_risk_001",
        "task_high_001",
        "task_old_001",
    ]
    assert decisions[0].status is AssignmentDecisionStatus.ASSIGNED
    assert decisions[1].reasons[0].code is AssignmentRejectionCode.CAPACITY_EXHAUSTED
    assert decisions[2].reasons[0].code is AssignmentRejectionCode.CAPACITY_EXHAUSTED


def test_retry_scheduled_item_becomes_ready_at_its_available_time() -> None:
    item = work_item(
        "retry",
        status=WorkItemStatus.RETRY_SCHEDULED,
        available_at=NOW + timedelta(minutes=5),
    )
    scheduler = PortfolioScheduler()

    before = scheduler.match(item, AgentRole.CODER, [agent()], [], now=NOW)
    after = scheduler.match(item, AgentRole.CODER, [agent()], [], now=NOW + timedelta(minutes=5))

    assert before.reasons[0].code is AssignmentRejectionCode.NOT_READY
    assert after.status is AssignmentDecisionStatus.ASSIGNED


@pytest.mark.parametrize(
    ("role", "expected"),
    (
        (AgentRole.CODER, AssignmentRejectionCode.CAPABILITY_MISMATCH),
        (AgentRole.QA, AssignmentRejectionCode.ROLE_NOT_ELIGIBLE),
    ),
)
def test_agent_eligibility_failures_are_structured(
    role: AgentRole, expected: AssignmentRejectionCode
) -> None:
    profile = agent(capabilities=("java",), roles=(AgentRole.CODER,))
    requested = work_item(capabilities=("python",)) if role is AgentRole.CODER else work_item()

    decision = PortfolioScheduler().match(requested, role, [profile], [], now=NOW)

    assert decision.status is AssignmentDecisionStatus.REJECTED
    assert decision.reasons[0].code is expected


def test_inactive_agent_and_no_capacity_are_rejected() -> None:
    inactive = agent("inactive", active=False)
    assert (
        PortfolioScheduler()
        .match(work_item(), AgentRole.CODER, [inactive], [], now=NOW)
        .reasons[0]
        .code
        is AssignmentRejectionCode.INACTIVE_AGENT
    )

    busy = agent(max_parallel_assignments=1)
    decision = PortfolioScheduler().match(work_item(), AgentRole.CODER, [busy], [lease()], now=NOW)
    assert decision.reasons[0].code is AssignmentRejectionCode.CAPACITY_EXHAUSTED


def test_same_agent_cannot_cross_delivery_roles_even_across_attempts() -> None:
    existing = assignment(role=AgentRole.CODER, attempt=1)
    decision = PortfolioScheduler().match(
        work_item(),
        AgentRole.REVIEWER,
        [agent()],
        [],
        [existing],
        now=NOW,
        attempt=2,
    )

    assert decision.reasons[0].code is AssignmentRejectionCode.SELF_REVIEW


def test_one_agent_can_hold_independent_leases_for_multiple_tasks() -> None:
    profile = agent(max_parallel_assignments=2)
    decisions = PortfolioScheduler().schedule(
        (work_item("one"), work_item("two")),
        AgentRole.CODER,
        [profile],
        [],
        now=NOW,
    )

    assert all(decision.status is AssignmentDecisionStatus.ASSIGNED for decision in decisions)
    assert decisions[0].lease is not None and decisions[1].lease is not None
    assert decisions[0].lease.id != decisions[1].lease.id


def test_model_router_selects_default_and_risk_floor_deterministically() -> None:
    router = ModelRouter()
    low = router.route(demand(), agent(), policy(), now=NOW)
    high = router.route(demand(risk=RiskTier.HIGH), agent(), policy(), now=NOW)

    assert low.status is ModelRoutingDecisionStatus.SELECTED
    assert low.selection is not None
    assert low.selection.tier is BrainTier.STANDARD
    assert low.selection.reasons == (ModelRouteReason.DEFAULT,)
    assert high.selection is not None
    assert high.selection.tier is BrainTier.REASONING
    assert ModelRouteReason.RISK_FLOOR in high.selection.reasons
    assert low.to_wire() == router.route(demand(), agent(), policy(), now=NOW).to_wire()


def test_model_router_escalates_for_complexity_and_prior_failures() -> None:
    selected = ModelRouter().select(
        demand(planned_files=8, failed_runs=1), agent(), policy(), now=NOW
    )

    assert selected.tier is BrainTier.REASONING
    assert ModelRouteReason.TASK_COMPLEXITY in selected.reasons
    assert ModelRouteReason.OBJECTIVE_ESCALATION in selected.reasons


def test_model_router_enforces_context_capacity_and_reports_refusal() -> None:
    capacities = {
        ("provider_a", "model_economy"): 4,
        ("provider_a", "model_standard"): 100,
        ("provider_a", "model_reasoning"): 200,
        ("provider_a", "model_critical"): 300,
    }
    router = ModelRouter(route_context_capacities=capacities)
    selected = router.select(demand(context_tokens=20), agent(), policy(), now=NOW)
    assert selected.tier is BrainTier.STANDARD
    assert ModelRouteReason.CONTEXT_CAPACITY in selected.reasons

    no_capacity = ModelRouter(route_context_capacities={key: 10 for key in capacities}).route(
        demand(context_tokens=20), agent(), policy(), now=NOW
    )
    assert no_capacity.status is ModelRoutingDecisionStatus.REJECTED
    assert no_capacity.refusal is not None
    assert no_capacity.refusal.code is ModelRejectionCode.NO_CONTEXT_CAPACITY

    undeclared = ModelRouter().route(demand(context_tokens=1), agent(), policy(), now=NOW)
    assert undeclared.refusal is not None
    assert undeclared.refusal.code is ModelRejectionCode.NO_CONTEXT_CAPACITY


def test_model_router_rejects_agent_and_policy_mismatches() -> None:
    inactive = ModelRouter().route(demand(), agent(active=False), policy(), now=NOW)
    assert inactive.refusal is not None
    assert inactive.refusal.code is ModelRejectionCode.INACTIVE_AGENT

    mismatched = ModelRouter().route(
        demand(),
        agent().model_copy(update={"default_model_policy_id": "model_policy_other_001"}),
        policy(),
        now=NOW,
    )
    assert mismatched.refusal is not None
    assert mismatched.refusal.code is ModelRejectionCode.POLICY_MISMATCH

    with pytest.raises(ModelRoutingRejected) as error:
        ModelRouter().select(demand(required_capabilities=("rust",)), agent(), policy(), now=NOW)
    assert error.value.refusal.code is ModelRejectionCode.CAPABILITY_MISMATCH
