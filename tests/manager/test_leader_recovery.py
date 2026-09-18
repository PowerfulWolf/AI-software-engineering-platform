from __future__ import annotations

from ai_software_engineer.manager.leader_recovery import (
    ManagerCapabilityKind,
    ManagerIncident,
    ManagerIncidentKind,
    ManagerLeaderRecovery,
    ManagerRepairCapability,
    ManagerRepairDisposition,
    ManagerRepairExecution,
    ManagerRepairMode,
    ManagerRepairSubmission,
)


class _Executor:
    def __init__(self, repaired: bool = True) -> None:
        self.repaired = repaired
        self.incidents: list[ManagerIncident] = []

    def execute(self, incident: ManagerIncident) -> ManagerRepairExecution:
        self.incidents.append(incident)
        return ManagerRepairExecution.create(
            repaired=self.repaired,
            summary=(
                "project test runner repaired" if self.repaired else "runner remains unavailable"
            ),
            evidence="resolved executable: /project/.venv/bin/pytest",
        )


class _Submitter:
    def __init__(self) -> None:
        self.submissions: list[tuple[ManagerIncident, ManagerRepairCapability]] = []

    def submit(
        self,
        incident: ManagerIncident,
        capability: ManagerRepairCapability,
    ) -> ManagerRepairSubmission:
        self.submissions.append((incident, capability))
        return ManagerRepairSubmission(
            task_id="task_manager_repair_001",
            summary="repair Task submitted through Coder, QA, and Reviewer",
        )


def _incident(
    kind: ManagerIncidentKind = ManagerIncidentKind.ENVIRONMENT,
    *,
    recovery_attempt: int = 0,
) -> ManagerIncident:
    return ManagerIncident(
        id="manager_incident_fixture",
        kind=kind,
        summary="QA runner is unavailable",
        delivery_id="delivery_fixture",
        repository_root="/workspace/project",
        recovery_attempt=recovery_attempt,
    )


def test_manager_executes_preapproved_environment_skill_and_retries_delivery() -> None:
    capability = ManagerRepairCapability(
        id="manager_capability_project_runner",
        kind=ManagerCapabilityKind.SKILL,
        incident_kinds=(ManagerIncidentKind.ENVIRONMENT,),
        mode=ManagerRepairMode.DIRECT,
        max_attempts=2,
    )
    executor = _Executor()
    leader = ManagerLeaderRecovery(
        capabilities=(capability,),
        executors={capability.id: executor},
        task_submitter=_Submitter(),
    )

    result = leader.recover(_incident())

    assert result.disposition is ManagerRepairDisposition.RETRY_DELIVERY
    assert result.capability_id == capability.id
    assert result.evidence_sha256 is not None
    assert len(executor.incidents) == 1


def test_manager_submits_repository_repair_through_normal_delivery_pipeline() -> None:
    capability = ManagerRepairCapability(
        id="manager_capability_workflow_repair",
        kind=ManagerCapabilityKind.MCP,
        incident_kinds=(ManagerIncidentKind.WORKFLOW,),
        mode=ManagerRepairMode.CANDIDATE_DELIVERY,
    )
    submitter = _Submitter()
    leader = ManagerLeaderRecovery(
        capabilities=(capability,),
        executors={},
        task_submitter=submitter,
    )

    result = leader.recover(_incident(ManagerIncidentKind.WORKFLOW))

    assert result.disposition is ManagerRepairDisposition.REPAIR_TASK_SUBMITTED
    assert result.repair_task_id == "task_manager_repair_001"
    assert submitter.submissions == [(_incident(ManagerIncidentKind.WORKFLOW), capability)]


def test_manager_never_auto_repairs_policy_permission_or_business_incidents() -> None:
    capability = ManagerRepairCapability(
        id="manager_capability_environment_only",
        kind=ManagerCapabilityKind.BUILTIN,
        incident_kinds=(ManagerIncidentKind.ENVIRONMENT,),
        mode=ManagerRepairMode.DIRECT,
    )
    leader = ManagerLeaderRecovery(
        capabilities=(capability,),
        executors={capability.id: _Executor()},
        task_submitter=_Submitter(),
    )

    for kind in (
        ManagerIncidentKind.POLICY,
        ManagerIncidentKind.PERMISSION,
        ManagerIncidentKind.BUSINESS,
    ):
        result = leader.recover(_incident(kind))
        assert result.disposition is ManagerRepairDisposition.WAITING_HUMAN
        assert result.capability_id is None


def test_manager_stops_after_capability_repair_budget() -> None:
    capability = ManagerRepairCapability(
        id="manager_capability_bounded_runner",
        kind=ManagerCapabilityKind.BUILTIN,
        incident_kinds=(ManagerIncidentKind.ENVIRONMENT,),
        mode=ManagerRepairMode.DIRECT,
        max_attempts=1,
    )
    executor = _Executor()
    leader = ManagerLeaderRecovery(
        capabilities=(capability,),
        executors={capability.id: executor},
        task_submitter=_Submitter(),
    )

    result = leader.recover(_incident(recovery_attempt=1))

    assert result.disposition is ManagerRepairDisposition.WAITING_HUMAN
    assert executor.incidents == []
