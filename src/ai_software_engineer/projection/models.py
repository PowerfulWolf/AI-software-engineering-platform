"""Read-only, event-derived projection contracts.

The projection layer intentionally has no repository write methods.  It accepts
already validated durable facts and builds a deterministic read model that can be
recomputed after a process restart.  Projection values are summaries: callers can
follow the IDs and digests to the immutable source records when they need detail.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.artifact import Artifact, ArtifactId, EvidenceId
from ai_software_engineer.domain.enums import (
    AgentRole,
    OrganizationRole,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.identity import ContextId, ProjectId, RunId
from ai_software_engineer.domain.model import DomainModel, JsonValue, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import Task, TaskId
from ai_software_engineer.domain.workforce import (
    AgentProfile,
    AgentRunAllocation,
    RoleAssignment,
    TaskLease,
    WorkItem,
)
from ai_software_engineer.evaluation.handoff import HandoffBundle, HandoffId
from ai_software_engineer.evaluation.models import EvaluationEvent, EvaluationEventId
from ai_software_engineer.evidence.models import EvidenceRecord

ProjectionId = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class RunProjectionStatus(StrEnum):
    """Status reconstructed from evaluation/usage evidence, never inferred as a verdict."""

    UNKNOWN = "UNKNOWN"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    INVALID = "INVALID"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    REJECTED = "REJECTED"


class LeaseProjectionStatus(StrEnum):
    """Lease status at an explicitly supplied projection clock."""

    UNKNOWN = "UNKNOWN"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ProjectionEventKind(StrEnum):
    """Source fact types rendered in a timeline."""

    STATE = "state_event"
    EVALUATION = "evaluation_event"
    ARTIFACT = "artifact"
    EVIDENCE = "evidence"
    HANDOFF = "handoff"
    ASSIGNMENT = "assignment"
    LEASE = "lease"


class TimelineEntry(DomainModel):
    """A small, source-addressable timeline item."""

    id: ProjectionId
    kind: ProjectionEventKind
    occurred_at: AwareDatetime
    task_id: TaskId | None = None
    run_id: RunId | None = None
    role: AgentRole | None = None
    summary: NonEmptyStr
    source_uri: NonEmptyStr
    source_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")] | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)


class RunProjection(DomainModel):
    """One isolated Agent Run reconstructed from durable facts."""

    run_id: RunId
    task_id: TaskId
    project_id: ProjectId | None = None
    agent_id: NonEmptyStr | None = None
    role: AgentRole | None = None
    attempt: StrictInt | None = Field(default=None, ge=1, le=10)
    provider: NonEmptyStr | None = None
    model: NonEmptyStr | None = None
    context_manifest_id: ContextId | None = None
    source_revision: NonEmptyStr | None = None
    status: RunProjectionStatus = RunProjectionStatus.UNKNOWN
    output_status: NonEmptyStr | None = None
    artifact_ids: tuple[ArtifactId, ...] = ()
    evidence_ids: tuple[EvidenceId, ...] = ()
    evaluation_event_ids: tuple[EvaluationEventId, ...] = ()
    timeline: tuple[TimelineEntry, ...] = ()

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        ensure_unique(self.artifact_ids, "RunProjection artifact IDs")
        ensure_unique(self.evidence_ids, "RunProjection evidence IDs")
        ensure_unique(self.evaluation_event_ids, "RunProjection evaluation event IDs")
        return self


class LeaseProjection(DomainModel):
    """A TaskLease plus assignment identity and an optional as-of status."""

    lease_id: NonEmptyStr
    assignment_id: NonEmptyStr
    task_id: TaskId
    project_id: ProjectId | None = None
    agent_id: NonEmptyStr
    role: AgentRole | None = None
    capacity_units: StrictInt = Field(ge=1)
    acquired_at: AwareDatetime
    expires_at: AwareDatetime
    status: LeaseProjectionStatus = LeaseProjectionStatus.UNKNOWN


class AgentProjection(DomainModel):
    """Organization Agent summary with run/lease references, not a mutable Agent record."""

    agent_id: NonEmptyStr
    display_name: NonEmptyStr | None = None
    active: StrictBool | None = None
    eligible_roles: tuple[OrganizationRole, ...] = ()
    run_ids: tuple[RunId, ...] = ()
    lease_ids: tuple[NonEmptyStr, ...] = ()
    models: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        ensure_unique(self.run_ids, "AgentProjection run IDs")
        ensure_unique(self.lease_ids, "AgentProjection lease IDs")
        ensure_unique(self.models, "AgentProjection models")
        ensure_unique(self.eligible_roles, "AgentProjection eligible roles")
        return self


class TaskProjection(DomainModel):
    """Current Task delivery checkpoint plus all source IDs needed for drill-down."""

    task_id: TaskId
    project_id: ProjectId | None = None
    title: NonEmptyStr
    status: TaskStatus
    attempts: StrictInt = Field(ge=0)
    state_revision: StrictInt = Field(ge=0)
    work_item_status: WorkItemStatus | None = None
    candidate_revision: NonEmptyStr | None = None
    qa_status: NonEmptyStr | None = None
    review_verdict: NonEmptyStr | None = None
    state_event_ids: tuple[ProjectionId, ...] = ()
    run_ids: tuple[RunId, ...] = ()
    artifact_ids: tuple[ArtifactId, ...] = ()
    evidence_ids: tuple[EvidenceId, ...] = ()
    evaluation_event_ids: tuple[EvaluationEventId, ...] = ()
    handoff_id: HandoffId | None = None
    timeline: tuple[TimelineEntry, ...] = ()

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        ensure_unique(self.state_event_ids, "TaskProjection state event IDs")
        ensure_unique(self.run_ids, "TaskProjection run IDs")
        ensure_unique(self.artifact_ids, "TaskProjection artifact IDs")
        ensure_unique(self.evidence_ids, "TaskProjection evidence IDs")
        ensure_unique(self.evaluation_event_ids, "TaskProjection evaluation event IDs")
        return self


class ProjectionSnapshot(DomainModel):
    """Deterministic read model returned by :class:`RunProjectionBuilder`."""

    schema_version: Literal["v0.1"] = "v0.1"
    tasks: tuple[TaskProjection, ...] = ()
    runs: tuple[RunProjection, ...] = ()
    agents: tuple[AgentProjection, ...] = ()
    leases: tuple[LeaseProjection, ...] = ()

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        ensure_unique((item.task_id for item in self.tasks), "Projection task IDs")
        ensure_unique((item.run_id for item in self.runs), "Projection run IDs")
        ensure_unique((item.agent_id for item in self.agents), "Projection agent IDs")
        ensure_unique((item.lease_id for item in self.leases), "Projection lease IDs")
        return self


@dataclass(frozen=True, slots=True)
class ProjectionFacts:
    """Typed inputs read from durable stores before projection.

    Stores intentionally remain independent.  The adapter/application layer can
    enumerate each store and pass immutable tuples here without granting this
    read model any write access.
    """

    tasks: tuple[Task, ...] = ()
    state_events: tuple[StateEvent, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    evidence: tuple[EvidenceRecord, ...] = ()
    evaluation_events: tuple[EvaluationEvent, ...] = ()
    handoffs: tuple[HandoffBundle, ...] = ()
    work_items: tuple[WorkItem, ...] = ()
    assignments: tuple[RoleAssignment, ...] = ()
    leases: tuple[TaskLease, ...] = ()
    allocations: tuple[AgentRunAllocation, ...] = ()
    agent_profiles: tuple[AgentProfile, ...] = ()
    as_of: datetime | None = None

    @classmethod
    def from_iterables(
        cls,
        *,
        tasks: Iterable[Task] = (),
        state_events: Iterable[StateEvent] = (),
        artifacts: Iterable[Artifact] = (),
        evidence: Iterable[EvidenceRecord] = (),
        evaluation_events: Iterable[EvaluationEvent] = (),
        handoffs: Iterable[HandoffBundle] = (),
        work_items: Iterable[WorkItem] = (),
        assignments: Iterable[RoleAssignment] = (),
        leases: Iterable[TaskLease] = (),
        allocations: Iterable[AgentRunAllocation] = (),
        agent_profiles: Iterable[AgentProfile] = (),
        as_of: datetime | None = None,
    ) -> ProjectionFacts:
        return cls(
            tasks=tuple(tasks),
            state_events=tuple(state_events),
            artifacts=tuple(artifacts),
            evidence=tuple(evidence),
            evaluation_events=tuple(evaluation_events),
            handoffs=tuple(handoffs),
            work_items=tuple(work_items),
            assignments=tuple(assignments),
            leases=tuple(leases),
            allocations=tuple(allocations),
            agent_profiles=tuple(agent_profiles),
            as_of=as_of,
        )


__all__ = [
    "AgentProjection",
    "LeaseProjection",
    "LeaseProjectionStatus",
    "ProjectionEventKind",
    "ProjectionFacts",
    "ProjectionSnapshot",
    "RunProjection",
    "RunProjectionStatus",
    "TaskProjection",
    "TimelineEntry",
]
