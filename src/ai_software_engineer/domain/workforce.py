"""Organization-owned Agent workforce and run-allocation contracts."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.agent import AgentId
from ai_software_engineer.domain.enums import (
    AgentRole,
    BrainTier,
    ModelRouteReason,
    OrganizationRole,
    RiskTier,
    WorkItemStatus,
)
from ai_software_engineer.domain.identity import ContextId, ProjectId, RunId
from ai_software_engineer.domain.model import DomainModel, JsonValue, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import AttemptCount, TaskId

AgentProfileVersion = NonEmptyStr
ModelPolicyId = Annotated[
    str, StringConstraints(pattern=r"^model_policy_[a-z0-9][a-z0-9_-]{2,63}$")
]
AssignmentId = Annotated[str, StringConstraints(pattern=r"^assignment_[a-z0-9][a-z0-9_-]{2,63}$")]
LeaseId = Annotated[str, StringConstraints(pattern=r"^lease_[a-z0-9][a-z0-9_-]{2,63}$")]
ParallelAssignmentLimit = Annotated[StrictInt, Field(ge=1, le=16)]
CapacityUnits = Annotated[StrictInt, Field(ge=1, le=16)]
Priority = Annotated[StrictInt, Field(ge=0, le=1000)]
NonNegativeCount = Annotated[StrictInt, Field(ge=0, le=10_000_000)]

_WAITING_STATUSES = frozenset(
    {
        WorkItemStatus.WAITING_HUMAN,
        WorkItemStatus.WAITING_DEPENDENCY,
        WorkItemStatus.RETRY_SCHEDULED,
    }
)
_INDEPENDENT_DELIVERY_ROLES = frozenset({AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER})


class AssignmentConflict(ValueError):
    """Raised when one Agent would cross delivery roles in the same Task."""


class AgentProfile(DomainModel):
    """Long-lived organization identity; concrete models and project grants are resolved per run."""

    kind: Literal["agent_profile"] = "agent_profile"
    id: AgentId
    version: AgentProfileVersion
    display_name: NonEmptyStr
    capabilities: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    eligible_roles: Annotated[tuple[OrganizationRole, ...], Field(min_length=1)]
    max_parallel_assignments: ParallelAssignmentLimit
    default_model_policy_id: ModelPolicyId
    active: StrictBool = True
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        ensure_unique(self.capabilities, "AgentProfile capabilities")
        ensure_unique(self.eligible_roles, "AgentProfile eligible_roles")
        return self


class ModelRoute(DomainModel):
    """One provider model approved for a Brain Tier."""

    provider: NonEmptyStr
    model: NonEmptyStr
    tier: BrainTier
    capabilities: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_capabilities(self) -> Self:
        ensure_unique(self.capabilities, "ModelRoute capabilities")
        return self


class RiskModelFloor(DomainModel):
    """Minimum Brain Tier allowed for one risk class."""

    risk: RiskTier
    minimum_tier: BrainTier


class ModelPolicy(DomainModel):
    """Organization rule set from which a ModelRouter can make an auditable selection."""

    kind: Literal["model_policy"] = "model_policy"
    id: ModelPolicyId
    version: NonEmptyStr
    default_tier: BrainTier
    routes: Annotated[tuple[ModelRoute, ...], Field(min_length=1)]
    risk_floors: Annotated[tuple[RiskModelFloor, ...], Field(min_length=4, max_length=4)]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        route_keys = tuple((route.provider, route.model) for route in self.routes)
        ensure_unique(route_keys, "ModelPolicy provider/model routes")
        route_tiers = {route.tier for route in self.routes}
        if self.default_tier not in route_tiers:
            raise ValueError("ModelPolicy default_tier requires an eligible route")
        ensure_unique((floor.risk for floor in self.risk_floors), "ModelPolicy risk floors")
        if {floor.risk for floor in self.risk_floors} != set(RiskTier):
            raise ValueError("ModelPolicy risk_floors must cover every RiskTier")
        unavailable = sorted(
            {floor.minimum_tier.value for floor in self.risk_floors}
            - {tier.value for tier in route_tiers}
        )
        if unavailable:
            raise ValueError(
                "ModelPolicy risk floor has no eligible route: " + ", ".join(unavailable)
            )
        return self


class ModelSelection(DomainModel):
    """Concrete, run-scoped model allocation with machine-readable reasons."""

    kind: Literal["model_selection"] = "model_selection"
    policy_id: ModelPolicyId
    policy_version: NonEmptyStr
    provider: NonEmptyStr
    model: NonEmptyStr
    tier: BrainTier
    reasons: Annotated[tuple[ModelRouteReason, ...], Field(min_length=1)]
    selected_at: AwareDatetime

    @model_validator(mode="after")
    def validate_reasons(self) -> Self:
        ensure_unique(self.reasons, "ModelSelection reasons")
        return self


class RunDemand(DomainModel):
    """Objective signals consumed by a future ModelRouter for one role run."""

    kind: Literal["run_demand"] = "run_demand"
    task_id: TaskId
    role: AgentRole
    risk: RiskTier
    required_capabilities: tuple[NonEmptyStr, ...] = ()
    context_tokens: NonNegativeCount = 0
    planned_files: NonNegativeCount = 0
    affected_layers: tuple[NonEmptyStr, ...] = ()
    failed_runs: NonNegativeCount = 0
    qa_failures: NonNegativeCount = 0
    review_rejections: NonNegativeCount = 0
    touches_critical_paths: bool = False

    @model_validator(mode="after")
    def validate_signals(self) -> Self:
        ensure_unique(self.required_capabilities, "RunDemand required_capabilities")
        ensure_unique(self.affected_layers, "RunDemand affected_layers")
        return self


class WorkItem(DomainModel):
    """Scheduling view of one Task, orthogonal to its delivery state."""

    kind: Literal["work_item"] = "work_item"
    task_id: TaskId
    project_id: ProjectId
    status: WorkItemStatus
    priority: Priority
    risk: RiskTier
    required_capabilities: tuple[NonEmptyStr, ...] = ()
    wait_reason: NonEmptyStr | None = None
    available_at: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_scheduling_state(self) -> Self:
        ensure_unique(self.required_capabilities, "WorkItem required_capabilities")
        if self.updated_at < self.created_at:
            raise ValueError("WorkItem updated_at cannot be earlier than created_at")
        if self.status in _WAITING_STATUSES and self.wait_reason is None:
            raise ValueError("waiting WorkItem requires wait_reason")
        if self.status not in _WAITING_STATUSES and self.wait_reason is not None:
            raise ValueError("non-waiting WorkItem cannot carry wait_reason")
        if self.status is WorkItemStatus.RETRY_SCHEDULED and (
            self.available_at is None or self.available_at <= self.updated_at
        ):
            raise ValueError("RETRY_SCHEDULED WorkItem requires future available_at")
        return self


class RoleAssignment(DomainModel):
    """Temporary binding of an organization Agent to one Task role and lease."""

    kind: Literal["role_assignment"] = "role_assignment"
    id: AssignmentId
    project_id: ProjectId
    task_id: TaskId
    agent_id: AgentId
    role: AgentRole
    attempt: AttemptCount
    lease_id: LeaseId
    capacity_units: CapacityUnits = 1
    assigned_at: AwareDatetime

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        if self.attempt < 1:
            raise ValueError("RoleAssignment attempt must be at least 1")
        return self


class TaskLease(DomainModel):
    """Expiring claim on Agent capacity for one RoleAssignment."""

    kind: Literal["task_lease"] = "task_lease"
    id: LeaseId
    assignment_id: AssignmentId
    task_id: TaskId
    agent_id: AgentId
    capacity_units: CapacityUnits = 1
    acquired_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.expires_at <= self.acquired_at:
            raise ValueError("TaskLease expires_at must be later than acquired_at")
        return self


class AgentRunAllocation(DomainModel):
    """Auditable identity, model, context, and policy binding for one isolated Agent Run."""

    kind: Literal["agent_run_allocation"] = "agent_run_allocation"
    run_id: RunId
    assignment_id: AssignmentId
    project_id: ProjectId
    task_id: TaskId
    agent_id: AgentId
    role: AgentRole
    attempt: AttemptCount
    model_selection: ModelSelection
    context_manifest_id: ContextId
    prompt_version: NonEmptyStr
    spec_version: NonEmptyStr
    tool_policy_ref: NonEmptyStr
    allocated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        if self.attempt < 1:
            raise ValueError("AgentRunAllocation attempt must be at least 1")
        return self


def is_waiting(status: WorkItemStatus) -> bool:
    """Return whether a WorkItem is waiting and must not retain active capacity."""
    return status in _WAITING_STATUSES


def lease_is_active(lease: TaskLease, *, at: datetime) -> bool:
    """Evaluate lease activity without hidden wall-clock access."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("lease evaluation time must be timezone-aware")
    return lease.acquired_at <= at < lease.expires_at


def validate_assignment_independence(
    candidate: RoleAssignment, existing: tuple[RoleAssignment, ...]
) -> None:
    """Reject same-Agent delivery roles anywhere within one Task history."""
    for assignment in existing:
        if (
            assignment.task_id == candidate.task_id
            and assignment.agent_id == candidate.agent_id
            and assignment.role is not candidate.role
            and assignment.role in _INDEPENDENT_DELIVERY_ROLES
            and candidate.role in _INDEPENDENT_DELIVERY_ROLES
        ):
            raise AssignmentConflict(
                f"Agent {candidate.agent_id} cannot hold {assignment.role.value} and "
                f"{candidate.role.value} for Task {candidate.task_id}"
            )


__all__ = [
    "AgentProfile",
    "AgentRunAllocation",
    "AssignmentConflict",
    "AssignmentId",
    "ContextId",
    "LeaseId",
    "ModelPolicy",
    "ModelPolicyId",
    "ModelRoute",
    "ModelSelection",
    "RiskModelFloor",
    "RoleAssignment",
    "RunDemand",
    "RunId",
    "TaskLease",
    "WorkItem",
    "is_waiting",
    "lease_is_active",
    "validate_assignment_independence",
]
