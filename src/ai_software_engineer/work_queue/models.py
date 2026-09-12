"""Run-level organization WorkQueue contracts."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.enums import AgentRole, WorkItemStatus
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import AttemptCount
from ai_software_engineer.domain.workforce import (
    ModelSelection,
    RoleAssignment,
    TaskLease,
    WorkItem,
)

WorkItemId = Annotated[str, StringConstraints(pattern=r"^work_[a-z0-9][a-z0-9_-]{2,95}$")]
LeaseWorkerId = Annotated[str, StringConstraints(pattern=r"^worker_[a-z0-9][a-z0-9_-]{2,63}$")]
ArtifactSha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
CheckpointSequence = Annotated[StrictInt, Field(ge=0, le=10_000)]

_DELIVERY_ROLES = frozenset({AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER})


class QueuedWorkItem(WorkItem):
    """One executable delivery-role Run in the organization queue."""

    id: WorkItemId
    role: AgentRole
    attempt: AttemptCount
    checkpoint_sequence: CheckpointSequence = 0
    dispatch_sequence: CheckpointSequence = 0
    repository_scopes: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    parent_work_item_id: WorkItemId | None = None

    @model_validator(mode="after")
    def validate_queue_identity(self) -> Self:
        if self.role not in _DELIVERY_ROLES:
            raise ValueError("QueuedWorkItem role must be coder, qa, or reviewer")
        if self.attempt < 1:
            raise ValueError("QueuedWorkItem attempt must be at least 1")
        ensure_unique(self.repository_scopes, "QueuedWorkItem repository_scopes")
        if self.parent_work_item_id == self.id:
            raise ValueError("QueuedWorkItem cannot be its own parent")
        return self


class QueueArtifactReceipt(DomainModel):
    """Immutable Artifact evidence accepted before a queue transition."""

    artifact_id: NonEmptyStr
    sha256: ArtifactSha256


class QueueClaim(DomainModel):
    """Durable assignment/model/Lease bundle returned to one worker."""

    kind: Literal["queue_claim"] = "queue_claim"
    work_item: QueuedWorkItem
    assignment: RoleAssignment
    lease: TaskLease
    model_selection: ModelSelection
    worker_id: LeaseWorkerId
    claimed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_claim(self) -> Self:
        if self.work_item.status is not WorkItemStatus.LEASED:
            raise ValueError("QueueClaim requires a LEASED WorkItem")
        if (
            self.assignment.task_id != self.work_item.task_id
            or self.assignment.repository_id != self.work_item.repository_id
            or self.assignment.role is not self.work_item.role
            or self.assignment.attempt != self.work_item.attempt
            or self.lease.assignment_id != self.assignment.id
            or self.lease.id != self.assignment.lease_id
            or self.lease.task_id != self.work_item.task_id
            or self.lease.agent_id != self.assignment.agent_id
            or self.model_selection.selected_at > self.claimed_at
        ):
            raise ValueError("QueueClaim allocation facts do not match WorkItem")
        return self


class QueueCompletion(DomainModel):
    """Atomic close-current plus optional publish-next result."""

    kind: Literal["queue_completion"] = "queue_completion"
    work_item: QueuedWorkItem
    artifacts: tuple[QueueArtifactReceipt, ...] = ()
    next_work_item: QueuedWorkItem | None = None
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_completion(self) -> Self:
        if self.work_item.status is not WorkItemStatus.CLOSED:
            raise ValueError("QueueCompletion requires a CLOSED WorkItem")
        ensure_unique((item.artifact_id for item in self.artifacts), "completion Artifact IDs")
        if self.next_work_item is not None:
            if self.next_work_item.task_id != self.work_item.task_id:
                raise ValueError("next WorkItem must belong to the same Task")
            if self.next_work_item.parent_work_item_id != self.work_item.id:
                raise ValueError("next WorkItem must reference the completed parent")
            if self.next_work_item.status not in {
                WorkItemStatus.READY,
                WorkItemStatus.RETRY_SCHEDULED,
            }:
                raise ValueError("next WorkItem must be schedulable")
        return self


__all__ = [
    "LeaseWorkerId",
    "QueueArtifactReceipt",
    "QueueClaim",
    "QueueCompletion",
    "QueuedWorkItem",
    "WorkItemId",
]
