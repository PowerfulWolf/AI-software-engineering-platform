"""Organization-owned Agent, scheduling, lease, and model-allocation contracts."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.domain import (
    AgentProfile,
    AgentRole,
    AgentRunAllocation,
    AssignmentConflict,
    BrainTier,
    ModelPolicy,
    ModelRoute,
    ModelRouteReason,
    ModelSelection,
    OrganizationRole,
    RiskModelFloor,
    RiskTier,
    RoleAssignment,
    RunDemand,
    TaskLease,
    WorkItem,
    WorkItemStatus,
    is_waiting,
    lease_is_active,
    validate_assignment_independence,
)
from ai_software_engineer.domain.model import DomainModel

NOW = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def make_agent_profile() -> AgentProfile:
    return AgentProfile(
        id="agent_engineer_alpha",
        version="v1",
        display_name="Alpha",
        capabilities=("python", "contract-testing", "architecture"),
        eligible_roles=(OrganizationRole.CODER, OrganizationRole.QA, OrganizationRole.REVIEWER),
        max_parallel_assignments=3,
        default_model_policy_id="model_policy_engineering_default",
        metadata={"team": "platform"},
    )


def make_model_policy() -> ModelPolicy:
    routes = tuple(
        ModelRoute(provider="provider-a", model=f"model-{tier.value}", tier=tier)
        for tier in BrainTier
    )
    return ModelPolicy(
        id="model_policy_engineering_default",
        version="v1",
        default_tier=BrainTier.STANDARD,
        routes=routes,
        risk_floors=(
            RiskModelFloor(risk=RiskTier.LOW, minimum_tier=BrainTier.ECONOMY),
            RiskModelFloor(risk=RiskTier.NORMAL, minimum_tier=BrainTier.STANDARD),
            RiskModelFloor(risk=RiskTier.HIGH, minimum_tier=BrainTier.REASONING),
            RiskModelFloor(risk=RiskTier.CRITICAL, minimum_tier=BrainTier.CRITICAL),
        ),
    )


def make_model_selection() -> ModelSelection:
    return ModelSelection(
        policy_id="model_policy_engineering_default",
        policy_version="v1",
        provider="provider-a",
        model="model-reasoning",
        tier=BrainTier.REASONING,
        reasons=(ModelRouteReason.RISK_FLOOR, ModelRouteReason.TASK_COMPLEXITY),
        selected_at=NOW,
    )


def make_work_item(*, status: WorkItemStatus = WorkItemStatus.READY) -> WorkItem:
    waiting = is_waiting(status)
    return WorkItem(
        task_id="task_workforce_001",
        project_id="project_platform_001",
        status=status,
        priority=900,
        risk=RiskTier.HIGH,
        required_capabilities=("python", "architecture"),
        wait_reason="Awaiting architecture decision" if waiting else None,
        available_at=NOW + timedelta(minutes=5)
        if status is WorkItemStatus.RETRY_SCHEDULED
        else None,
        created_at=NOW,
        updated_at=NOW,
    )


def make_assignment(
    *,
    role: AgentRole = AgentRole.CODER,
    agent_id: str = "agent_engineer_alpha",
    attempt: int = 1,
) -> RoleAssignment:
    return RoleAssignment(
        id=f"assignment_{role.value}_{attempt:03d}",
        project_id="project_platform_001",
        task_id="task_workforce_001",
        agent_id=agent_id,
        role=role,
        attempt=attempt,
        lease_id=f"lease_{role.value}_{attempt:03d}",
        assigned_at=NOW,
    )


def make_lease() -> TaskLease:
    return TaskLease(
        id="lease_coder_001",
        assignment_id="assignment_coder_001",
        task_id="task_workforce_001",
        agent_id="agent_engineer_alpha",
        acquired_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )


def make_run_allocation() -> AgentRunAllocation:
    return AgentRunAllocation(
        run_id="run_workforce_coder_001",
        assignment_id="assignment_coder_001",
        project_id="project_platform_001",
        task_id="task_workforce_001",
        agent_id="agent_engineer_alpha",
        role=AgentRole.CODER,
        attempt=1,
        model_selection=make_model_selection(),
        context_manifest_id="ctx_" + "c" * 64,
        prompt_version="prompt-v1",
        spec_version="spec-v1",
        tool_policy_ref="policy://project_platform_001/coder-v1",
        allocated_at=NOW,
    )


def test_agent_profile_is_organization_owned_and_not_a_concrete_model_config() -> None:
    profile = make_agent_profile()

    assert profile.eligible_roles == (
        OrganizationRole.CODER,
        OrganizationRole.QA,
        OrganizationRole.REVIEWER,
    )
    assert profile.max_parallel_assignments == 3
    payload = profile.to_wire()
    payload["model"] = "must-not-be-member-identity"
    with pytest.raises(ValidationError):
        AgentProfile.model_validate(payload)


def test_agent_profile_declares_product_as_an_organization_role_only() -> None:
    profile = make_agent_profile().model_copy(
        update={
            "eligible_roles": (
                OrganizationRole.PROJECT_MANAGER,
                OrganizationRole.PRODUCT,
                OrganizationRole.DESIGNER,
            )
        }
    )

    assert profile.eligible_roles == (
        OrganizationRole.PROJECT_MANAGER,
        OrganizationRole.PRODUCT,
        OrganizationRole.DESIGNER,
    )
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas" / "workforce.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert list(Draft202012Validator(schema).iter_errors(profile.to_wire())) == []


def test_model_policy_requires_every_risk_floor_and_an_available_route() -> None:
    payload = make_model_policy().to_wire()
    risk_floors = payload["risk_floors"]
    assert isinstance(risk_floors, list)
    payload["risk_floors"] = risk_floors[:-1]
    with pytest.raises(ValidationError, match="risk_floors"):
        ModelPolicy.model_validate(payload)

    payload = make_model_policy().to_wire()
    routes = payload["routes"]
    assert isinstance(routes, list)
    payload["routes"] = routes[:-1]
    with pytest.raises(ValidationError, match="no eligible route"):
        ModelPolicy.model_validate(payload)


@pytest.mark.parametrize(
    "status",
    (
        WorkItemStatus.WAITING_HUMAN,
        WorkItemStatus.WAITING_DEPENDENCY,
        WorkItemStatus.RETRY_SCHEDULED,
    ),
)
def test_waiting_work_item_requires_explicit_reason(status: WorkItemStatus) -> None:
    payload = make_work_item(status=status).to_wire()
    payload.pop("wait_reason")

    with pytest.raises(ValidationError, match="wait_reason"):
        WorkItem.model_validate(payload)

    schema = json.loads(
        (Path(__file__).parents[2] / "schemas" / "workforce.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_retry_schedule_requires_a_future_available_time() -> None:
    payload = make_work_item(status=WorkItemStatus.RETRY_SCHEDULED).to_wire()
    payload["available_at"] = NOW.isoformat()

    with pytest.raises(ValidationError, match="future available_at"):
        WorkItem.model_validate(payload)


def test_task_lease_has_explicit_time_window_and_pure_activity_check() -> None:
    lease = make_lease()

    assert lease_is_active(lease, at=NOW + timedelta(minutes=1)) is True
    assert lease_is_active(lease, at=lease.expires_at) is False
    with pytest.raises(ValueError, match="timezone-aware"):
        lease_is_active(lease, at=datetime(2026, 9, 1, 10, 1))

    payload = lease.to_wire()
    payload["expires_at"] = payload["acquired_at"]
    with pytest.raises(ValidationError, match="later"):
        TaskLease.model_validate(payload)


def test_delivery_roles_cannot_be_assigned_to_the_same_agent_for_one_task() -> None:
    coder = make_assignment(role=AgentRole.CODER)
    reviewer = make_assignment(role=AgentRole.REVIEWER)

    with pytest.raises(AssignmentConflict, match="cannot hold coder and reviewer"):
        validate_assignment_independence(reviewer, (coder,))

    independent_reviewer = make_assignment(role=AgentRole.REVIEWER, agent_id="agent_reviewer_beta")
    validate_assignment_independence(independent_reviewer, (coder,))

    # A retry is still part of the same delivery history; changing attempt must not
    # turn a self-review into an apparently independent assignment.
    retry_reviewer = make_assignment(role=AgentRole.REVIEWER, attempt=2)
    with pytest.raises(AssignmentConflict):
        validate_assignment_independence(retry_reviewer, (coder,))


def test_run_demand_contains_objective_model_routing_signals() -> None:
    demand = RunDemand(
        task_id="task_workforce_001",
        role=AgentRole.CODER,
        risk=RiskTier.HIGH,
        required_capabilities=("python",),
        context_tokens=12_000,
        planned_files=8,
        affected_layers=("domain", "orchestration"),
        failed_runs=1,
        qa_failures=1,
        review_rejections=0,
        touches_critical_paths=True,
    )
    assert demand.touches_critical_paths is True


def test_run_allocation_makes_agent_model_and_policy_attributable() -> None:
    allocation = make_run_allocation()

    assert allocation.agent_id == "agent_engineer_alpha"
    assert allocation.model_selection.tier is BrainTier.REASONING
    assert allocation.context_manifest_id == "ctx_" + "c" * 64


@pytest.mark.parametrize(
    "model",
    (
        make_agent_profile(),
        make_model_policy(),
        make_model_selection(),
        RunDemand(
            task_id="task_workforce_001",
            role=AgentRole.CODER,
            risk=RiskTier.NORMAL,
        ),
        make_work_item(),
        make_assignment(),
        make_lease(),
        make_run_allocation(),
    ),
)
def test_workforce_python_models_satisfy_canonical_json_schema(model: DomainModel) -> None:
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas" / "workforce.schema.json").read_text(
            encoding="utf-8"
        )
    )
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(model.to_wire())
    )

    assert errors == []
