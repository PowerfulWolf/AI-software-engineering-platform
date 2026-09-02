"""Read-only Planner feasibility preview tests."""

import inspect
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain import (
    AgentProfile,
    AgentRole,
    BrainTier,
    ExecutionPlan,
    ModelPolicy,
    ModelRoute,
    OrganizationRole,
    RiskModelFloor,
    RiskTier,
    Task,
    TaskConstraints,
    TaskLease,
    WorkItem,
    WorkItemStatus,
)
from ai_software_engineer.planning import (
    PlanningPreviewExpired,
    PlanningPreviewRejected,
    PlanningPreviewService,
)
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from tests.planning.conftest import (
    NOW,
    approval,
    delivery_task,
    execution_plan,
    planning_request,
    preparation,
    product_spec,
    technical_design,
)


def _policy() -> ModelPolicy:
    return ModelPolicy(
        id="model_policy_planning_001",
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


def _agents() -> tuple[AgentProfile, AgentProfile, AgentProfile]:
    profiles = tuple(
        AgentProfile(
            id=f"agent_{role.value}_001",
            version="v1",
            display_name=role.value,
            capabilities=("python",),
            eligible_roles=(OrganizationRole(role.value),),
            max_parallel_assignments=1,
            default_model_policy_id="model_policy_planning_001",
        )
        for role in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)
    )
    return profiles[0], profiles[1], profiles[2]


def _facts(
    tmp_path: Path,
) -> tuple[
    Task,
    WorkItem,
    ExecutionPlan,
]:
    prepared = preparation(tmp_path)
    request = planning_request(prepared)
    spec = product_spec(request)
    approved = approval(spec)
    design = technical_design(spec, approved)
    plan = execution_plan(spec, design)
    task = delivery_task(prepared, request, spec, approved, design, plan)
    item = WorkItem(
        task_id=task.id,
        project_id=prepared.project_id,
        status=WorkItemStatus.READY,
        priority=500,
        risk=RiskTier.NORMAL,
        required_capabilities=("python",),
        created_at=NOW,
        updated_at=NOW,
    )
    return task, item, plan


def _service(*, capacities: bool = True) -> PlanningPreviewService:
    route_capacities = (
        {("provider_a", f"model_{tier.value}"): 10_000 for tier in BrainTier} if capacities else {}
    )
    return PlanningPreviewService(
        scheduler=PortfolioScheduler(),
        model_router=ModelRouter(route_context_capacities=route_capacities),
    )


def test_preview_is_deterministic_read_only_and_binds_demands(tmp_path: Path) -> None:
    task, item, plan = _facts(tmp_path)
    agents = _agents()
    policy = _policy()
    parameters = inspect.signature(PlanningPreviewService.__init__).parameters
    assert not {"store", "repository", "assignments_store", "lease_store"} & set(parameters)

    first = _service().preview(
        task=task,
        work_item=item,
        execution_plan=plan,
        agents=agents,
        active_leases=(),
        assignments=(),
        policies=(policy,),
        previewed_at=NOW,
    )
    second = _service().preview(
        task=task,
        work_item=item,
        execution_plan=plan,
        agents=tuple(reversed(agents)),
        active_leases=(),
        assignments=(),
        policies=(policy,),
        previewed_at=NOW,
    )

    assert first == second
    assert [phase.agent_id for phase in first.phases] == [
        "agent_coder_001",
        "agent_qa_001",
        "agent_reviewer_001",
    ]
    first.validate_integrity()
    first.require_valid_at(NOW + timedelta(minutes=9))
    with pytest.raises(PlanningPreviewExpired):
        first.require_valid_at(first.valid_until)

    constrained_task = task.model_copy(
        update={"constraints": TaskConstraints(allowed_paths=("src/**",))}
    )
    changed = _service().preview(
        task=constrained_task,
        work_item=item,
        execution_plan=plan,
        agents=agents,
        active_leases=(),
        assignments=(),
        policies=(policy,),
        previewed_at=NOW,
    )
    assert changed.workforce_snapshot_sha256 != first.workforce_snapshot_sha256
    assert changed.id != first.id


def test_preview_fails_closed_on_capacity_and_model_refusal(tmp_path: Path) -> None:
    task, item, plan = _facts(tmp_path)
    coder_lease = TaskLease(
        id="lease_existing_coder_001",
        assignment_id="assignment_existing_coder_001",
        task_id="task_other_001",
        agent_id="agent_coder_001",
        acquired_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )
    with pytest.raises(PlanningPreviewRejected, match="CAPACITY_EXHAUSTED") as capacity:
        _service().preview(
            task=task,
            work_item=item,
            execution_plan=plan,
            agents=_agents(),
            active_leases=(coder_lease,),
            assignments=(),
            policies=(_policy(),),
            previewed_at=NOW,
        )
    assert capacity.value.model_routing_decision is None

    with pytest.raises(PlanningPreviewRejected, match="NO_CONTEXT_CAPACITY") as model:
        _service(capacities=False).preview(
            task=task,
            work_item=item,
            execution_plan=plan,
            agents=_agents(),
            active_leases=(),
            assignments=(),
            policies=(_policy(),),
            previewed_at=NOW,
        )
    assert model.value.model_routing_decision is not None
