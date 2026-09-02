"""Deterministic projection and fact-conflict tests."""

from datetime import UTC, datetime, timedelta

import pytest

from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.evidence import (
    CommandEvidencePayload,
    CommandEvidenceRecord,
    CommandOutcome,
    RunEvidenceIdentity,
    seal_evidence_record,
)
from ai_software_engineer.projection import (
    LeaseProjectionStatus,
    ProjectionConflict,
    ProjectionFacts,
    RunProjectionBuilder,
    RunProjectionStatus,
)
from tests.domain.factories import make_state_event, make_task

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _evidence(*, run_id: str = "run_projection_001") -> CommandEvidenceRecord:
    identity = RunEvidenceIdentity(
        project_id="project_projection_001",
        task_id="task_domain_001",
        run_id=run_id,
        agent_id="agent_projection_001",
        role=AgentRole.CODER,
        attempt=1,
        source_revision="a" * 40,
        context_manifest_id="ctx_" + "c" * 64,
    )
    return seal_evidence_record(
        CommandEvidenceRecord(
            evidence_id="ev_projection_001",
            operation_id="projection.command",
            identity=identity,
            description="projection command",
            captured_at=NOW,
            payload=CommandEvidencePayload(
                outcome=CommandOutcome.COMPLETED,
                argv=("pytest", "-q"),
                cwd="/tmp/worktree",
                returncode=0,
                duration_ms=2,
            ),
            record_sha256="0" * 64,
        )
    )


def test_projection_rebuilds_task_run_agent_and_timeline_deterministically() -> None:
    task = make_task().model_copy(update={"status": TaskStatus.PLANNING})
    state = make_state_event(to_status=TaskStatus.PLANNING)
    evidence = _evidence()
    facts = ProjectionFacts.from_iterables(
        tasks=(task,), state_events=(state,), evidence=(evidence,)
    )
    first = RunProjectionBuilder().build(facts)
    assert first == RunProjectionBuilder().build(facts)
    assert first.tasks[0].status is TaskStatus.PLANNING
    assert first.tasks[0].state_event_ids == (state.event_id,)
    assert first.tasks[0].evidence_ids == (evidence.evidence_id,)
    assert first.runs[0].status is RunProjectionStatus.UNKNOWN
    assert first.runs[0].agent_id == evidence.identity.agent_id
    assert first.agents[0].run_ids == (evidence.identity.run_id,)
    assert first.tasks[0].timeline[-1].source_sha256 == evidence.record_sha256


def test_projection_rejects_non_contiguous_or_unknown_task_facts() -> None:
    task = make_task()
    with pytest.raises(ProjectionConflict, match="unknown Task"):
        RunProjectionBuilder().build(
            ProjectionFacts.from_iterables(
                tasks=(task,), state_events=(make_state_event(task_id="task_unknown_001"),)
            )
        )
    with pytest.raises(ProjectionConflict, match="status differs"):
        RunProjectionBuilder().build(
            ProjectionFacts.from_iterables(
                tasks=(task,), state_events=(make_state_event(to_status=TaskStatus.PLANNING),)
            )
        )


def test_projection_as_of_is_explicit_and_lease_status_is_recomputed() -> None:
    from ai_software_engineer.domain import TaskLease

    lease = TaskLease(
        id="lease_projection_001",
        assignment_id="assignment_projection_001",
        task_id="task_domain_001",
        agent_id="agent_projection_001",
        capacity_units=1,
        acquired_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    task = make_task()
    unknown = RunProjectionBuilder().build(
        ProjectionFacts.from_iterables(tasks=(task,), leases=(lease,))
    )
    active = RunProjectionBuilder().build(
        ProjectionFacts.from_iterables(
            tasks=(task,), leases=(lease,), as_of=NOW + timedelta(minutes=5)
        )
    )
    assert unknown.leases[0].status is LeaseProjectionStatus.UNKNOWN
    assert active.leases[0].status is LeaseProjectionStatus.ACTIVE
    with pytest.raises(ProjectionConflict, match="timezone-aware"):
        RunProjectionBuilder().build(
            ProjectionFacts.from_iterables(
                tasks=(task,), leases=(lease,), as_of=datetime(2026, 9, 1)
            )
        )
