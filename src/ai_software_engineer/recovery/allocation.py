"""Fresh recovery allocation in the ordinary organization reservation domain."""

from datetime import UTC, datetime

from ai_software_engineer.domain import AgentProfile, ModelPolicy, WorkItem, WorkItemStatus
from ai_software_engineer.planning import PlanningPreviewService
from ai_software_engineer.project_manager.dispatch import (
    DispatchPhaseCommit,
    DispatchWorkforceSnapshot,
    RecoveryDispatchRecord,
    _record_digest,
)
from ai_software_engineer.project_manager.mysql_dispatch_authority import MySqlDispatchAuthority
from ai_software_engineer.project_manager.production_backend import _maximum_risk
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.sealing import RecoveryTaskSealingService
from ai_software_engineer.recovery.task import AuthorizedRecoveryTaskBuilder
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler


class RecoveryAllocator:
    def __init__(
        self,
        *,
        sealing: RecoveryTaskSealingService,
        builder: AuthorizedRecoveryTaskBuilder,
        authority: MySqlDispatchAuthority,
        agents: tuple[AgentProfile, ...],
        policies: tuple[ModelPolicy, ...],
    ) -> None:
        self._sealing, self._builder, self._authority = sealing, builder, authority
        self._agents, self._policies = agents, policies

    def allocate(self, plan_sha256: str) -> RecoveryDispatchRecord:
        sealed = self._sealing.require_current(plan_sha256)
        draft = self._builder.build(plan_sha256)
        task, plan = sealed.task, draft.facts.original.plan
        snapshot = DispatchWorkforceSnapshot.create(
            project_id=plan.project_id,
            task_id=task.id,
            work_item=WorkItem(
                project_id=plan.project_id,
                task_id=task.id,
                status=WorkItemStatus.READY,
                priority=500,
                risk=_maximum_risk(p.risk for p in plan.phases),
                required_capabilities=tuple(
                    sorted({c for p in plan.phases for c in p.required_capabilities})
                ),
                created_at=task.created_at,
                updated_at=task.created_at,
            ),
            agents=self._agents,
            model_policies=self._policies,
        )
        self._authority.seed_snapshot(snapshot)

        def validate(record: RecoveryDispatchRecord | None) -> None:
            current = self._sealing.require_current(plan_sha256)
            if current != sealed or (
                record is not None
                and (
                    record.task != sealed.task
                    or record.recovery_task_record_sha256 != sealed.record_sha256
                    or record.recovery_plan_sha256 != plan_sha256
                )
            ):
                raise RecoveryRejected("recovery dispatch no longer matches sealed Task")

        def build(current: DispatchWorkforceSnapshot) -> RecoveryDispatchRecord:
            now = datetime.now(UTC)
            preview = PlanningPreviewService(
                scheduler=PortfolioScheduler(),
                model_router=ModelRouter(
                    route_context_capacities={
                        (route.provider, route.model): 2_000_000
                        for policy in current.model_policies
                        for route in policy.routes
                    }
                ),
            ).preview(
                task=task,
                work_item=current.work_item,
                execution_plan=plan,
                agents=current.agents,
                active_leases=current.active_leases,
                assignments=current.assignments,
                policies=current.model_policies,
                previewed_at=now,
            )
            phases = []
            for phase in preview.phases:
                assignment, routing = phase.assignment_decision, phase.model_routing_decision
                assert assignment.agent_id is not None and assignment.assignment is not None
                assert assignment.lease is not None and routing is not None
                assert routing.selection is not None
                phases.append(
                    DispatchPhaseCommit(
                        phase_id=phase.phase_id,
                        role=phase.role,
                        agent_id=assignment.agent_id,
                        assignment=assignment.assignment,
                        lease=assignment.lease,
                        model_selection=routing.selection,
                    )
                )
            result = RecoveryDispatchRecord(
                id=f"dispatch_commit_{plan_sha256}",
                project_id=plan.project_id,
                task_id=task.id,
                project_request_id=sealed.rebound_request.id,
                execution_plan_id=plan.id,
                execution_plan_sha256=plan.execution_plan_sha256,
                execution_plan_phase_ids=(plan.phases[0].id, plan.phases[1].id, plan.phases[2].id),
                recovery_plan_sha256=plan_sha256,
                recovery_task_record_sha256=sealed.record_sha256,
                workforce_snapshot_sha256=current.snapshot_sha256,
                task=task,
                phases=tuple(phases),
                committed_at=now,
                dispatch_sha256="0" * 64,
            )
            return result.model_copy(update={"dispatch_sha256": _record_digest(result)})

        return self._authority.commit_recovery(
            project_id=plan.project_id,
            task_id=task.id,
            plan_sha256=plan_sha256,
            validate_current=validate,
            build=build,
        )
