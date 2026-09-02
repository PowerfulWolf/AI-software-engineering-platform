"""Pure reconstruction of Task/Run/Agent/Lease read models."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime
from itertools import pairwise
from typing import Final

from ai_software_engineer.domain.artifact import (
    Artifact,
    ImplementationReportArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.enums import OrganizationRole
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.task import Task, TaskId
from ai_software_engineer.domain.workforce import (
    AgentRunAllocation,
    RoleAssignment,
    TaskLease,
    WorkItem,
)
from ai_software_engineer.evaluation.handoff import HandoffBundle
from ai_software_engineer.evaluation.models import (
    AgentRunEvent,
    ArtifactOutputStatus,
    EvaluationEvent,
)
from ai_software_engineer.evidence.models import AgentUsageEvidenceRecord, EvidenceRecord

from .models import (
    AgentProjection,
    LeaseProjection,
    LeaseProjectionStatus,
    ProjectionEventKind,
    ProjectionFacts,
    ProjectionSnapshot,
    RunProjection,
    RunProjectionStatus,
    TaskProjection,
    TimelineEntry,
)


class ProjectionError(RuntimeError):
    """Base class for read-model failures."""


class ProjectionConflict(ProjectionError):
    """Raised when durable facts disagree and cannot be safely projected."""


class ProjectionNotFound(ProjectionError):
    """Raised by read APIs when a requested projection ID is absent."""


_RUN_STATUS_BY_OUTPUT: Final[dict[ArtifactOutputStatus, RunProjectionStatus]] = {
    ArtifactOutputStatus.VALID: RunProjectionStatus.SUCCEEDED,
    ArtifactOutputStatus.INVALID: RunProjectionStatus.INVALID,
    ArtifactOutputStatus.NOT_PRODUCED: RunProjectionStatus.FAILED,
}


class RunProjectionBuilder:
    """Recompute projections from a finite set of immutable facts.

    No wall clock, store, subprocess, or state transition is accessed here.  Supplying
    ``as_of`` is optional; when omitted lease status remains ``UNKNOWN`` rather than
    consulting the host clock.  This makes a projection reproducible in tests and on
    every dashboard refresh.
    """

    def build(self, facts: ProjectionFacts) -> ProjectionSnapshot:
        self._validate_facts(facts)
        state_by_task = _group(facts.state_events, lambda item: item.task_id)
        artifacts_by_task = _group(facts.artifacts, lambda item: item.task_id)
        evidence_by_task = _group(facts.evidence, lambda item: item.identity.task_id)
        eval_by_task = _group(facts.evaluation_events, lambda item: item.task_id)
        handoff_by_task = _group(facts.handoffs, lambda item: item.task_id)
        work_item_by_task: dict[str, WorkItem] = {item.task_id: item for item in facts.work_items}

        assignments_by_task = _group(facts.assignments, lambda item: item.task_id)
        assignments_by_id = {item.id: item for item in facts.assignments}
        leases_by_task = _group(facts.leases, lambda item: item.task_id)

        runs = self._build_runs(facts)
        runs_by_task = _group(runs, lambda item: item.task_id)
        tasks = tuple(
            self._build_task(
                task,
                state_events=state_by_task.get(task.id, ()),
                artifacts=artifacts_by_task.get(task.id, ()),
                evidence=evidence_by_task.get(task.id, ()),
                evaluation_events=eval_by_task.get(task.id, ()),
                handoffs=handoff_by_task.get(task.id, ()),
                work_item=work_item_by_task.get(task.id),
                assignments=assignments_by_task.get(task.id, ()),
                leases=leases_by_task.get(task.id, ()),
                runs=runs_by_task.get(task.id, ()),
            )
            for task in sorted(facts.tasks, key=lambda item: item.id)
        )
        leases = tuple(
            self._build_lease(lease, assignments_by_id.get(lease.assignment_id), as_of=facts.as_of)
            for lease in sorted(facts.leases, key=lambda item: item.id)
        )
        agents = self._build_agents(facts, runs, leases)
        return ProjectionSnapshot(
            tasks=tasks,
            runs=tuple(sorted(runs, key=lambda item: item.run_id)),
            agents=agents,
            leases=leases,
        )

    # ``project`` is a descriptive alias useful to callers that treat this as a
    # query rather than a stateful builder.
    project = build

    def _build_task(
        self,
        task: Task,
        *,
        state_events: tuple[StateEvent, ...],
        artifacts: tuple[Artifact, ...],
        evidence: tuple[EvidenceRecord, ...],
        evaluation_events: tuple[EvaluationEvent, ...],
        handoffs: tuple[HandoffBundle, ...],
        work_item: WorkItem | None,
        assignments: tuple[RoleAssignment, ...],
        leases: tuple[TaskLease, ...],
        runs: tuple[RunProjection, ...],
    ) -> TaskProjection:
        ordered_state = tuple(
            sorted(state_events, key=lambda item: (item.occurred_at, item.event_id))
        )
        timeline: list[TimelineEntry] = []
        for event in ordered_state:
            timeline.append(
                TimelineEntry(
                    id=event.event_id,
                    kind=ProjectionEventKind.STATE,
                    occurred_at=event.occurred_at,
                    task_id=task.id,
                    role=event.actor,
                    summary=f"Task state {event.from_status.value} → {event.to_status.value}",
                    source_uri=f"state://{task.id}/{event.event_id}",
                    details={
                        "from_status": event.from_status.value,
                        "to_status": event.to_status.value,
                        "reason": event.reason,
                        "attempt": event.attempt,
                    },
                )
            )
        for evaluation_event in sorted(
            evaluation_events, key=lambda item: (item.occurred_at, item.event_id)
        ):
            run_id = (
                evaluation_event.run_id if isinstance(evaluation_event, AgentRunEvent) else None
            )
            role = evaluation_event.role if isinstance(evaluation_event, AgentRunEvent) else None
            timeline.append(
                TimelineEntry(
                    id=evaluation_event.event_id,
                    kind=ProjectionEventKind.EVALUATION,
                    occurred_at=evaluation_event.occurred_at,
                    task_id=task.id,
                    run_id=run_id,
                    role=role,
                    summary=f"Evaluation event {evaluation_event.kind.value}",
                    source_uri=f"evaluation://{evaluation_event.case_id}/{evaluation_event.event_id}",
                    details={
                        "case_id": evaluation_event.case_id,
                        "kind": evaluation_event.kind.value,
                    },
                )
            )
        for artifact in sorted(artifacts, key=lambda item: (item.created_at, item.artifact_id)):
            timeline.append(_artifact_entry(artifact))
        for record in sorted(evidence, key=lambda item: (item.captured_at, item.evidence_id)):
            timeline.append(_evidence_entry(record))
        for assignment in sorted(assignments, key=lambda item: (item.assigned_at, item.id)):
            timeline.append(
                TimelineEntry(
                    id=assignment.id,
                    kind=ProjectionEventKind.ASSIGNMENT,
                    occurred_at=assignment.assigned_at,
                    task_id=task.id,
                    role=assignment.role,
                    summary=f"{assignment.role.value} assigned to {assignment.agent_id}",
                    source_uri=f"assignment://{assignment.id}",
                    details={
                        "agent_id": assignment.agent_id,
                        "attempt": assignment.attempt,
                        "lease_id": assignment.lease_id,
                    },
                )
            )
        for handoff in sorted(handoffs, key=lambda item: (item.generated_at, item.handoff_id)):
            timeline.append(
                TimelineEntry(
                    id=handoff.handoff_id,
                    kind=ProjectionEventKind.HANDOFF,
                    occurred_at=handoff.generated_at,
                    task_id=task.id,
                    summary=f"Handoff {handoff.outcome.value}",
                    source_uri=f"handoff://{handoff.handoff_id}",
                    source_sha256=handoff.handoff_id.removeprefix("handoff_"),
                    details={"outcome": handoff.outcome.value},
                )
            )
        for lease in sorted(leases, key=lambda item: item.id):
            timeline.append(_lease_entry(lease, task.id))

        candidate = _latest_candidate(artifacts)
        latest_qa = _latest_qa(artifacts)
        latest_review = _latest_review(artifacts)
        project_id = work_item.project_id if work_item is not None else _first_project(runs)
        return TaskProjection(
            task_id=task.id,
            project_id=project_id,
            title=task.title,
            status=task.status,
            attempts=task.attempts,
            state_revision=len(ordered_state),
            work_item_status=getattr(work_item, "status", None),
            candidate_revision=candidate,
            qa_status=latest_qa,
            review_verdict=latest_review,
            state_event_ids=tuple(item.event_id for item in ordered_state),
            run_ids=tuple(item.run_id for item in sorted(runs, key=lambda item: item.run_id)),
            artifact_ids=tuple(
                item.artifact_id for item in sorted(artifacts, key=lambda item: item.artifact_id)
            ),
            evidence_ids=tuple(
                item.evidence_id for item in sorted(evidence, key=lambda item: item.evidence_id)
            ),
            evaluation_event_ids=tuple(
                item.event_id for item in sorted(evaluation_events, key=lambda item: item.event_id)
            ),
            handoff_id=(
                sorted(handoffs, key=lambda item: (item.generated_at, item.handoff_id))[
                    -1
                ].handoff_id
                if handoffs
                else None
            ),
            timeline=tuple(
                sorted(timeline, key=lambda item: (item.occurred_at, item.kind.value, item.id))
            ),
        )

    def _build_runs(self, facts: ProjectionFacts) -> tuple[RunProjection, ...]:
        allocations = {item.run_id: item for item in facts.allocations}
        by_run_evidence = _group(facts.evidence, lambda item: item.identity.run_id)
        by_run_artifacts = _group(facts.artifacts, lambda item: item.producer.run_id)
        by_run_events = _group(
            (item for item in facts.evaluation_events if isinstance(item, AgentRunEvent)),
            lambda item: item.run_id,
        )
        run_ids = (
            set(allocations) | set(by_run_evidence) | set(by_run_artifacts) | set(by_run_events)
        )
        runs: list[RunProjection] = []
        for run_id in sorted(run_ids):
            allocation = allocations.get(run_id)
            evidence = tuple(
                sorted(
                    by_run_evidence.get(run_id, ()),
                    key=lambda item: (item.captured_at, item.evidence_id),
                )
            )
            artifacts = tuple(
                sorted(
                    by_run_artifacts.get(run_id, ()),
                    key=lambda item: (item.created_at, item.artifact_id),
                )
            )
            events = tuple(
                sorted(
                    by_run_events.get(run_id, ()),
                    key=lambda item: (item.occurred_at, item.event_id),
                )
            )
            task_id = _single_value(
                run_id,
                [
                    allocation.task_id if allocation is not None else None,
                    *(item.identity.task_id for item in evidence),
                    *(item.task_id for item in artifacts),
                    *(item.task_id for item in events),
                ],
                "task_id",
            )
            project_id = _optional_single_value(
                run_id,
                [
                    allocation.project_id if allocation else None,
                    *(item.identity.project_id for item in evidence),
                ],
                "project_id",
            )
            role = (
                allocation.role
                if allocation
                else (
                    events[-1].role
                    if events
                    else (
                        evidence[-1].identity.role
                        if evidence
                        else (artifacts[-1].producer.role if artifacts else None)
                    )
                )
            )
            agent_id = (
                allocation.agent_id
                if allocation
                else (
                    evidence[-1].identity.agent_id
                    if evidence
                    else (artifacts[-1].producer.agent_id if artifacts else None)
                )
            )
            attempt = (
                allocation.attempt
                if allocation
                else (
                    events[-1].attempt
                    if events
                    else (evidence[-1].identity.attempt if evidence else None)
                )
            )
            provider = allocation.model_selection.provider if allocation else None
            model = allocation.model_selection.model if allocation else None
            context_id = (
                allocation.context_manifest_id
                if allocation
                else (evidence[-1].identity.context_manifest_id if evidence else None)
            )
            source_revision = _allocation_revision(allocation) if allocation else None
            if source_revision is None:
                source_revision = evidence[-1].identity.source_revision if evidence else None
            status = RunProjectionStatus.UNKNOWN
            output_status: str | None = None
            if events:
                output_status = events[-1].output_status.value
                status = _RUN_STATUS_BY_OUTPUT[events[-1].output_status]
            usage_records = [
                item for item in evidence if isinstance(item, AgentUsageEvidenceRecord)
            ]
            if usage_records:
                usage = usage_records[-1].payload
                status = _usage_status(usage.status.value)
                provider = provider or usage.provider
                model = model or usage.model
                output_status = output_status or usage.status.value
            timeline = [_artifact_entry(item) for item in artifacts]
            timeline.extend(_evidence_entry(item) for item in evidence)
            timeline.extend(
                TimelineEntry(
                    id=item.event_id,
                    kind=ProjectionEventKind.EVALUATION,
                    occurred_at=item.occurred_at,
                    task_id=item.task_id,
                    run_id=item.run_id,
                    role=item.role,
                    summary=f"Agent run {item.output_status.value}",
                    source_uri=f"evaluation://{item.case_id}/{item.event_id}",
                    details={
                        "case_id": item.case_id,
                        "output_status": item.output_status.value,
                        "attempt": item.attempt,
                    },
                )
                for item in events
            )
            runs.append(
                RunProjection(
                    run_id=run_id,
                    task_id=task_id,
                    project_id=project_id,
                    agent_id=agent_id,
                    role=role,
                    attempt=attempt,
                    provider=provider,
                    model=model,
                    context_manifest_id=context_id,
                    source_revision=source_revision,
                    status=status,
                    output_status=output_status,
                    artifact_ids=tuple(item.artifact_id for item in artifacts),
                    evidence_ids=tuple(item.evidence_id for item in evidence),
                    evaluation_event_ids=tuple(item.event_id for item in events),
                    timeline=tuple(
                        sorted(
                            timeline, key=lambda item: (item.occurred_at, item.kind.value, item.id)
                        )
                    ),
                )
            )
        return tuple(runs)

    def _build_lease(
        self, lease: TaskLease, assignment: object, *, as_of: datetime | None
    ) -> LeaseProjection:
        project_id = getattr(assignment, "project_id", None)
        role = getattr(assignment, "role", None)
        status = LeaseProjectionStatus.UNKNOWN
        if as_of is not None:
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise ProjectionConflict("projection as_of must be timezone-aware")
            status = (
                LeaseProjectionStatus.ACTIVE
                if lease.acquired_at <= as_of < lease.expires_at
                else LeaseProjectionStatus.EXPIRED
            )
        return LeaseProjection(
            lease_id=lease.id,
            assignment_id=lease.assignment_id,
            task_id=lease.task_id,
            project_id=project_id,
            agent_id=lease.agent_id,
            role=role,
            capacity_units=lease.capacity_units,
            acquired_at=lease.acquired_at,
            expires_at=lease.expires_at,
            status=status,
        )

    @staticmethod
    def _build_agents(
        facts: ProjectionFacts, runs: tuple[RunProjection, ...], leases: tuple[LeaseProjection, ...]
    ) -> tuple[AgentProjection, ...]:
        profiles = {item.id: item for item in facts.agent_profiles}
        run_by_agent: dict[str, list[RunProjection]] = defaultdict(list)
        for run in runs:
            if run.agent_id is not None:
                run_by_agent[run.agent_id].append(run)
        lease_by_agent: dict[str, list[LeaseProjection]] = defaultdict(list)
        for lease in leases:
            lease_by_agent[lease.agent_id].append(lease)
        agent_ids = set(profiles) | set(run_by_agent) | set(lease_by_agent)
        result: list[AgentProjection] = []
        for agent_id in sorted(agent_ids):
            profile = profiles.get(agent_id)
            agent_runs = sorted(run_by_agent.get(agent_id, ()), key=lambda item: item.run_id)
            agent_leases = sorted(lease_by_agent.get(agent_id, ()), key=lambda item: item.lease_id)
            roles = set(profile.eligible_roles if profile else ())
            roles.update(
                OrganizationRole(item.role.value) for item in agent_runs if item.role is not None
            )
            roles.update(
                OrganizationRole(item.role.value) for item in agent_leases if item.role is not None
            )
            models = {item.model for item in agent_runs if item.model is not None}
            result.append(
                AgentProjection(
                    agent_id=agent_id,
                    display_name=profile.display_name if profile else None,
                    active=profile.active if profile else None,
                    eligible_roles=tuple(sorted(roles, key=lambda item: item.value)),
                    run_ids=tuple(item.run_id for item in agent_runs),
                    lease_ids=tuple(item.lease_id for item in agent_leases),
                    models=tuple(sorted(models)),
                )
            )
        return tuple(result)

    @staticmethod
    def _validate_facts(facts: ProjectionFacts) -> None:
        _ensure_unique(facts.tasks, lambda item: item.id, "Task")
        _ensure_unique(facts.state_events, lambda item: item.event_id, "StateEvent")
        _ensure_unique(facts.artifacts, lambda item: item.artifact_id, "Artifact")
        _ensure_unique(facts.evidence, lambda item: item.evidence_id, "Evidence")
        _ensure_unique(facts.evaluation_events, lambda item: item.event_id, "EvaluationEvent")
        _ensure_unique(facts.handoffs, lambda item: item.handoff_id, "Handoff")
        _ensure_unique(facts.work_items, lambda item: item.task_id, "WorkItem")
        _ensure_unique(facts.assignments, lambda item: item.id, "RoleAssignment")
        _ensure_unique(facts.leases, lambda item: item.id, "TaskLease")
        _ensure_unique(facts.allocations, lambda item: item.run_id, "AgentRunAllocation")
        _ensure_unique(facts.agent_profiles, lambda item: item.id, "AgentProfile")
        task_ids = {item.id for item in facts.tasks}
        if task_ids:
            for collection, label in (
                (facts.state_events, "StateEvent"),
                (facts.artifacts, "Artifact"),
                (facts.evidence, "Evidence"),
                (facts.evaluation_events, "EvaluationEvent"),
                (facts.handoffs, "Handoff"),
                (facts.work_items, "WorkItem"),
                (facts.assignments, "RoleAssignment"),
                (facts.leases, "TaskLease"),
                (facts.allocations, "AgentRunAllocation"),
            ):
                for item in collection:
                    item_task = item.task_id if hasattr(item, "task_id") else item.identity.task_id
                    if item_task not in task_ids:
                        raise ProjectionConflict(f"{label} references unknown Task {item_task}")
        if facts.as_of is not None and (
            facts.as_of.tzinfo is None or facts.as_of.utcoffset() is None
        ):
            raise ProjectionConflict("projection as_of must be timezone-aware")
        assignments = {item.id: item for item in facts.assignments}
        if assignments and facts.leases:
            for lease in facts.leases:
                assignment = assignments.get(lease.assignment_id)
                if assignment is None:
                    raise ProjectionConflict(
                        f"Lease {lease.id} references unknown Assignment {lease.assignment_id}"
                    )
                if (
                    assignment.task_id != lease.task_id
                    or assignment.agent_id != lease.agent_id
                    or assignment.lease_id != lease.id
                ):
                    raise ProjectionConflict(f"Lease {lease.id} identity differs from Assignment")
        if assignments and facts.allocations:
            for allocation in facts.allocations:
                assignment = assignments.get(allocation.assignment_id)
                if assignment is None:
                    raise ProjectionConflict(
                        f"Run allocation {allocation.run_id} references unknown Assignment "
                        f"{allocation.assignment_id}"
                    )
                if (
                    assignment.task_id != allocation.task_id
                    or assignment.agent_id != allocation.agent_id
                    or assignment.role is not allocation.role
                ):
                    raise ProjectionConflict(
                        f"Run allocation {allocation.run_id} identity differs from Assignment"
                    )
        # A state stream is append-only and must be contiguous.  The reducer is
        # not called: projection only verifies the durable facts it displays.
        for task in facts.tasks:
            events = sorted(
                (item for item in facts.state_events if item.task_id == task.id),
                key=lambda item: (item.occurred_at, item.event_id),
            )
            for previous, current in pairwise(events):
                if previous.to_status is not current.from_status:
                    raise ProjectionConflict(f"StateEvent stream is not contiguous for {task.id}")
            if events and events[-1].to_status is not task.status:
                raise ProjectionConflict(f"Task {task.id} status differs from final StateEvent")


def _group[T, K](items: Iterable[T], key: Callable[[T], K]) -> dict[K, tuple[T, ...]]:
    grouped: dict[K, list[T]] = defaultdict(list)
    for item in items:
        grouped[key(item)].append(item)
    return {group_key: tuple(values) for group_key, values in grouped.items()}


def _ensure_unique[T, K](items: Iterable[T], key: Callable[[T], K], label: str) -> None:
    seen: set[K] = set()
    for item in items:
        identifier = key(item)
        if identifier in seen:
            raise ProjectionConflict(f"duplicate {label} ID: {identifier}")
        seen.add(identifier)


def _single_value[T](run_id: str, values: Iterable[T | None], label: str) -> T:
    present = tuple(value for value in values if value is not None)
    if not present:
        raise ProjectionConflict(f"Run {run_id} has no {label}")
    first = present[0]
    if any(value != first for value in present[1:]):
        raise ProjectionConflict(f"Run {run_id} has conflicting {label}")
    return first


def _optional_single_value[T](run_id: str, values: Iterable[T | None], label: str) -> T | None:
    present = tuple(value for value in values if value is not None)
    if not present:
        return None
    first = present[0]
    if any(value != first for value in present[1:]):
        raise ProjectionConflict(f"Run {run_id} has conflicting {label}")
    return first


def _allocation_revision(allocation: AgentRunAllocation) -> str | None:
    # The allocation stores the exact context identity, while source revision is
    # carried by the Context/Evidence facts.  Returning None here avoids guessing.
    del allocation
    return None


def _first_project(runs: tuple[RunProjection, ...]) -> str | None:
    projects = tuple(run.project_id for run in runs if run.project_id is not None)
    return projects[0] if projects else None


def _latest_candidate(artifacts: tuple[Artifact, ...]) -> str | None:
    candidates = [item for item in artifacts if isinstance(item, ImplementationReportArtifact)]
    return (
        max(candidates, key=lambda item: (item.created_at, item.artifact_id)).content.commit_sha
        if candidates
        else None
    )


def _latest_qa(artifacts: tuple[Artifact, ...]) -> str | None:
    candidates = [item for item in artifacts if isinstance(item, QaReportArtifact)]
    return (
        max(candidates, key=lambda item: (item.created_at, item.artifact_id)).content.status.value
        if candidates
        else None
    )


def _latest_review(artifacts: tuple[Artifact, ...]) -> str | None:
    candidates = [item for item in artifacts if isinstance(item, ReviewReportArtifact)]
    return (
        max(candidates, key=lambda item: (item.created_at, item.artifact_id)).content.verdict.value
        if candidates
        else None
    )


def _artifact_entry(artifact: Artifact) -> TimelineEntry:
    return TimelineEntry(
        id=artifact.artifact_id,
        kind=ProjectionEventKind.ARTIFACT,
        occurred_at=artifact.created_at,
        task_id=artifact.task_id,
        run_id=artifact.producer.run_id,
        role=artifact.producer.role,
        summary=f"Artifact {artifact.kind.value}",
        source_uri=f"artifact://{artifact.artifact_id}",
        source_sha256=artifact.integrity.sha256,
        details={
            "kind": artifact.kind.value,
            "source_revision": artifact.source_revision,
            "context_manifest_id": artifact.context_manifest_id,
        },
    )


def _evidence_entry(record: EvidenceRecord) -> TimelineEntry:
    return TimelineEntry(
        id=record.evidence_id,
        kind=ProjectionEventKind.EVIDENCE,
        occurred_at=record.captured_at,
        task_id=record.identity.task_id,
        run_id=record.identity.run_id,
        role=record.identity.role,
        summary=f"Evidence {record.kind.value}",
        source_uri=record.uri,
        source_sha256=record.record_sha256,
        details={"kind": record.kind.value, "operation_id": record.operation_id},
    )


def _lease_entry(lease: TaskLease, task_id: TaskId) -> TimelineEntry:
    return TimelineEntry(
        id=lease.id,
        kind=ProjectionEventKind.LEASE,
        occurred_at=lease.acquired_at,
        task_id=task_id,
        summary=f"Lease acquired by {lease.agent_id}",
        source_uri=f"lease://{lease.id}",
        details={
            "assignment_id": lease.assignment_id,
            "agent_id": lease.agent_id,
            "expires_at": lease.expires_at.isoformat(),
        },
    )


def _usage_status(value: str) -> RunProjectionStatus:
    return {
        "SUCCEEDED": RunProjectionStatus.SUCCEEDED,
        "FAILED": RunProjectionStatus.FAILED,
        "TIMED_OUT": RunProjectionStatus.TIMED_OUT,
        "REJECTED": RunProjectionStatus.REJECTED,
    }.get(value, RunProjectionStatus.UNKNOWN)


__all__ = ["ProjectionConflict", "ProjectionError", "ProjectionNotFound", "RunProjectionBuilder"]
