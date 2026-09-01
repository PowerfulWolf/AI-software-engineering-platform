"""Typed decisions emitted by the organization scheduler and model router.

These models deliberately describe decisions and refusals as durable facts.  A caller can
persist the wire representation or replay the same input without depending on an in-memory
queue implementation.
"""

from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, model_validator

from ai_software_engineer.domain.agent import AgentId
from ai_software_engineer.domain.enums import AgentRole, BrainTier
from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.domain.workforce import ModelSelection, RoleAssignment, TaskLease


class AssignmentDecisionStatus(StrEnum):
    """Whether one WorkItem obtained a role assignment."""

    ASSIGNED = "ASSIGNED"
    REJECTED = "REJECTED"


class AssignmentRejectionCode(StrEnum):
    """Stable scheduler refusal categories."""

    NOT_READY = "NOT_READY"
    WAITING = "WAITING"
    CLOSED = "CLOSED"
    INACTIVE_AGENT = "INACTIVE_AGENT"
    ROLE_NOT_ELIGIBLE = "ROLE_NOT_ELIGIBLE"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    CAPACITY_EXHAUSTED = "CAPACITY_EXHAUSTED"
    SELF_REVIEW = "SELF_REVIEW"
    INVALID_INPUT = "INVALID_INPUT"


class AssignmentRejection(DomainModel):
    """One machine-readable reason why an Agent was not selected."""

    code: AssignmentRejectionCode
    message: NonEmptyStr
    agent_id: AgentId | None = None
    missing_capabilities: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_capabilities(self) -> Self:
        ensure_unique(self.missing_capabilities, "AssignmentRejection missing_capabilities")
        if self.code is AssignmentRejectionCode.CAPABILITY_MISMATCH:
            if self.agent_id is None or not self.missing_capabilities:
                raise ValueError("CAPABILITY_MISMATCH requires agent_id and missing_capabilities")
        elif self.missing_capabilities:
            raise ValueError("missing_capabilities is only valid for CAPABILITY_MISMATCH")
        return self


class AssignmentDecision(DomainModel):
    """Pure result of matching one WorkItem to one Agent and Lease."""

    kind: Literal["assignment_decision"] = "assignment_decision"
    status: AssignmentDecisionStatus
    task_id: TaskId
    project_id: ProjectId
    role: AgentRole
    attempt: StrictInt = Field(ge=1, le=10)
    agent_id: AgentId | None = None
    assignment: RoleAssignment | None = None
    lease: TaskLease | None = None
    reasons: tuple[AssignmentRejection, ...] = ()
    decided_at: AwareDatetime

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.status is AssignmentDecisionStatus.ASSIGNED:
            if self.agent_id is None or self.assignment is None or self.lease is None:
                raise ValueError("ASSIGNED decision requires agent_id, assignment, and lease")
            if self.reasons:
                raise ValueError("ASSIGNED decision cannot carry rejection reasons")
            if (
                self.assignment.task_id != self.task_id
                or self.assignment.project_id != self.project_id
            ):
                raise ValueError("assignment does not match decision task/project")
            if self.assignment.agent_id != self.agent_id or self.assignment.role is not self.role:
                raise ValueError("assignment does not match decision Agent/role")
            if self.assignment.attempt != self.attempt:
                raise ValueError("assignment does not match decision attempt")
            if self.lease.assignment_id != self.assignment.id:
                raise ValueError("lease does not match decision assignment")
            if self.lease.task_id != self.task_id or self.lease.agent_id != self.agent_id:
                raise ValueError("lease does not match decision task/Agent")
        else:
            if self.agent_id is not None or self.assignment is not None or self.lease is not None:
                raise ValueError("REJECTED decision cannot carry an assignment or lease")
            if not self.reasons:
                raise ValueError("REJECTED decision requires structured reasons")
        ensure_unique(self.reasons, "AssignmentDecision reasons")
        return self


class ModelRoutingDecisionStatus(StrEnum):
    """Whether a ModelSelection was resolved for a run demand."""

    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


class ModelRejectionCode(StrEnum):
    """Stable model routing refusal categories."""

    INACTIVE_AGENT = "INACTIVE_AGENT"
    ROLE_NOT_ELIGIBLE = "ROLE_NOT_ELIGIBLE"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    POLICY_MISMATCH = "POLICY_MISMATCH"
    NO_CONTEXT_CAPACITY = "NO_CONTEXT_CAPACITY"
    NO_ELIGIBLE_ROUTE = "NO_ELIGIBLE_ROUTE"


class ModelRoutingRefusal(DomainModel):
    """Auditable explanation returned when no policy route can satisfy a demand."""

    code: ModelRejectionCode
    message: NonEmptyStr
    required_tier: BrainTier | None = None
    missing_capabilities: tuple[NonEmptyStr, ...] = ()
    considered_routes: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_details(self) -> Self:
        ensure_unique(self.missing_capabilities, "ModelRoutingRefusal missing_capabilities")
        ensure_unique(self.considered_routes, "ModelRoutingRefusal considered_routes")
        if self.code is ModelRejectionCode.CAPABILITY_MISMATCH:
            if not self.missing_capabilities:
                raise ValueError("CAPABILITY_MISMATCH requires missing_capabilities")
        elif self.missing_capabilities:
            raise ValueError("missing_capabilities is only valid for CAPABILITY_MISMATCH")
        return self


class ModelRoutingDecision(DomainModel):
    """Pure ModelRouter result; selection and refusal are mutually exclusive."""

    kind: Literal["model_routing_decision"] = "model_routing_decision"
    status: ModelRoutingDecisionStatus
    task_id: TaskId
    agent_id: AgentId
    role: AgentRole
    selection: ModelSelection | None = None
    refusal: ModelRoutingRefusal | None = None
    decided_at: AwareDatetime

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.status is ModelRoutingDecisionStatus.SELECTED:
            if self.selection is None or self.refusal is not None:
                raise ValueError("SELECTED decision requires selection and no refusal")
        elif self.selection is not None or self.refusal is None:
            raise ValueError("REJECTED decision requires refusal and no selection")
        return self


__all__ = [
    "AssignmentDecision",
    "AssignmentDecisionStatus",
    "AssignmentRejection",
    "AssignmentRejectionCode",
    "ModelRejectionCode",
    "ModelRoutingDecision",
    "ModelRoutingDecisionStatus",
    "ModelRoutingRefusal",
]
