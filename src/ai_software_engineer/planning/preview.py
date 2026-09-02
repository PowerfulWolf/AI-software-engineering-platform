"""Read-only Scheduler and ModelRouter preview skill for Planner."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta

from ai_software_engineer.domain.enums import BrainTier, TaskStatus
from ai_software_engineer.domain.project_delivery import ExecutionPlan, PlanPhaseDemand
from ai_software_engineer.domain.task import Task
from ai_software_engineer.domain.workforce import (
    AgentProfile,
    ModelPolicy,
    RoleAssignment,
    RunDemand,
    TaskLease,
    WorkItem,
)
from ai_software_engineer.planning.models import (
    PlanningPhasePreview,
    PlanningPreview,
    workforce_snapshot_digest,
)
from ai_software_engineer.scheduling import (
    AssignmentDecision,
    AssignmentDecisionStatus,
    ModelRejectionCode,
    ModelRouter,
    ModelRoutingDecision,
    ModelRoutingDecisionStatus,
    ModelRoutingRefusal,
    PortfolioScheduler,
)

_TIER_RANK = {
    BrainTier.ECONOMY: 0,
    BrainTier.STANDARD: 1,
    BrainTier.REASONING: 2,
    BrainTier.CRITICAL: 3,
}


class PlanningPreviewError(RuntimeError):
    """Base error for invalid or infeasible Planner previews."""


class PlanningPreviewInputError(PlanningPreviewError):
    """Raised before engine invocation when supplied facts do not align."""


class PlanningPreviewRejected(PlanningPreviewError):
    """Typed phase refusal carrying the exact pure-engine evidence."""

    def __init__(
        self,
        *,
        phase_id: str,
        assignment_decision: AssignmentDecision,
        model_routing_decision: ModelRoutingDecision | None = None,
    ) -> None:
        self.phase_id = phase_id
        self.assignment_decision = assignment_decision
        self.model_routing_decision = model_routing_decision
        if assignment_decision.status is AssignmentDecisionStatus.REJECTED:
            detail = ", ".join(reason.code.value for reason in assignment_decision.reasons)
        elif model_routing_decision is not None and model_routing_decision.refusal is not None:
            detail = model_routing_decision.refusal.code.value
        else:
            detail = "UNKNOWN_REFUSAL"
        super().__init__(f"Planning preview rejected at {phase_id}: {detail}")


class PlanningPreviewService:
    """Preview a serial delivery plan using only injected pure decision engines."""

    def __init__(
        self,
        *,
        scheduler: PortfolioScheduler,
        model_router: ModelRouter,
        preview_valid_for: timedelta = timedelta(minutes=10),
    ) -> None:
        if preview_valid_for <= timedelta(0):
            raise ValueError("preview_valid_for must be positive")
        self._scheduler = scheduler
        self._model_router = model_router
        self._preview_valid_for = preview_valid_for

    def preview(
        self,
        *,
        task: Task,
        work_item: WorkItem,
        execution_plan: ExecutionPlan,
        agents: Sequence[AgentProfile],
        active_leases: Sequence[TaskLease],
        assignments: Sequence[RoleAssignment],
        policies: Sequence[ModelPolicy],
        previewed_at: datetime,
    ) -> PlanningPreview:
        """Return replayable evidence and never persist any scheduling fact."""
        phase_demands = derive_phase_demands(task, execution_plan)
        self._validate_inputs(
            task=task,
            work_item=work_item,
            execution_plan=execution_plan,
            agents=agents,
            active_leases=active_leases,
            assignments=assignments,
            policies=policies,
            previewed_at=previewed_at,
        )
        profiles = {profile.id: profile for profile in agents}
        policy_by_id = {policy.id: policy for policy in policies}
        pending_leases = tuple(active_leases)
        pending_assignments = tuple(assignments)
        previews: list[PlanningPhasePreview] = []
        for phase, demand in zip(execution_plan.phases, phase_demands, strict=True):
            # Scheduler accepts WorkItem capabilities, so each immutable preview copy is narrowed
            # to the exact phase demand. The durable supplied WorkItem remains unchanged.
            phase_item = work_item.model_copy(
                update={"required_capabilities": phase.required_capabilities}
            )
            assignment = self._scheduler.match(
                phase_item,
                phase.role,
                agents,
                pending_leases,
                pending_assignments,
                now=previewed_at,
                attempt=1,
                work_items=(phase_item,),
            )
            if assignment.status is AssignmentDecisionStatus.REJECTED:
                raise PlanningPreviewRejected(
                    phase_id=phase.id,
                    assignment_decision=assignment,
                )
            assert assignment.agent_id is not None
            assert assignment.assignment is not None
            assert assignment.lease is not None
            profile = profiles[assignment.agent_id]
            policy = policy_by_id.get(profile.default_model_policy_id)
            if policy is None:
                raise PlanningPreviewInputError(
                    f"no ModelPolicy {profile.default_model_policy_id} for Agent {profile.id}"
                )
            routing = self._model_router.route(demand, profile, policy, now=previewed_at)
            routing = _enforce_minimum_brain_tier(phase, routing, previewed_at=previewed_at)
            if routing.status is ModelRoutingDecisionStatus.REJECTED:
                raise PlanningPreviewRejected(
                    phase_id=phase.id,
                    assignment_decision=assignment,
                    model_routing_decision=routing,
                )
            previews.append(
                PlanningPhasePreview(
                    phase_id=phase.id,
                    role=phase.role,
                    demand=demand,
                    assignment_decision=assignment,
                    model_routing_decision=routing,
                )
            )
            pending_assignments = (*pending_assignments, assignment.assignment)
            pending_leases = (*pending_leases, assignment.lease)

        phases = (previews[0], previews[1], previews[2])
        snapshot_sha256 = workforce_snapshot_digest(
            work_item=work_item,
            phase_demands=phase_demands,
            agents=agents,
            active_leases=active_leases,
            assignments=assignments,
            policies=policies,
        )
        return PlanningPreview.create(
            task=task,
            work_item=work_item,
            execution_plan=execution_plan,
            workforce_snapshot_sha256=snapshot_sha256,
            phases=phases,
            previewed_at=previewed_at,
            valid_until=previewed_at + self._preview_valid_for,
        )

    @staticmethod
    def _validate_inputs(
        *,
        task: Task,
        work_item: WorkItem,
        execution_plan: ExecutionPlan,
        agents: Sequence[AgentProfile],
        active_leases: Sequence[TaskLease],
        assignments: Sequence[RoleAssignment],
        policies: Sequence[ModelPolicy],
        previewed_at: datetime,
    ) -> None:
        if previewed_at.tzinfo is None or previewed_at.utcoffset() is None:
            raise PlanningPreviewInputError("previewed_at must be timezone-aware")
        execution_plan.validate_integrity()
        if task.status is not TaskStatus.NEW:
            raise PlanningPreviewInputError("Planner preview requires a NEW derived Task")
        if task.id != work_item.task_id:
            raise PlanningPreviewInputError("Task and WorkItem identity do not match")
        project_id = task.metadata.get("project_id")
        if project_id != work_item.project_id or project_id != execution_plan.project_id:
            raise PlanningPreviewInputError(
                "Task, WorkItem, and ExecutionPlan project do not match"
            )
        if (
            task.metadata.get("execution_plan_id") != execution_plan.id
            or task.metadata.get("execution_plan_sha256") != execution_plan.execution_plan_sha256
        ):
            raise PlanningPreviewInputError("Task does not bind the exact ExecutionPlan")
        _require_unique(tuple(profile.id for profile in agents), "AgentProfile IDs")
        _require_unique(tuple(lease.id for lease in active_leases), "TaskLease IDs")
        _require_unique(tuple(item.id for item in assignments), "RoleAssignment IDs")
        _require_unique(tuple(policy.id for policy in policies), "ModelPolicy IDs")


def derive_phase_demands(
    task: Task,
    execution_plan: ExecutionPlan,
) -> tuple[RunDemand, RunDemand, RunDemand]:
    """Derive every model-routing signal from immutable Task and plan facts.

    v0.1 deliberately does not accept caller-authored demand counters.  Approximate context size
    is a deterministic wire-size estimate; planned paths and affected layers come from the exact
    Task constraints.  Retry counters come from the Task aggregate.
    """
    encoded = json.dumps(
        {"task": task.to_wire(), "execution_plan": execution_plan.to_wire()},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    context_tokens = (len(encoded) + 3) // 4
    planned_paths = task.constraints.allowed_paths if task.constraints is not None else ()
    affected_layers = tuple(
        sorted(
            {
                path.split("/", 1)[0]
                for path in planned_paths
                if path and path.split("/", 1)[0] not in {"*", "**"}
            }
        )
    )
    demands = tuple(
        RunDemand(
            task_id=task.id,
            role=phase.role,
            risk=phase.risk,
            required_capabilities=phase.required_capabilities,
            context_tokens=context_tokens,
            planned_files=len(planned_paths),
            affected_layers=affected_layers,
            failed_runs=task.attempts,
            touches_critical_paths=phase.critical_path,
        )
        for phase in execution_plan.phases
    )
    return demands[0], demands[1], demands[2]


def _enforce_minimum_brain_tier(
    phase: PlanPhaseDemand,
    routing: ModelRoutingDecision,
    *,
    previewed_at: datetime,
) -> ModelRoutingDecision:
    selection = routing.selection
    if selection is None or _TIER_RANK[selection.tier] >= _TIER_RANK[phase.minimum_brain_tier]:
        return routing
    return ModelRoutingDecision(
        status=ModelRoutingDecisionStatus.REJECTED,
        task_id=routing.task_id,
        agent_id=routing.agent_id,
        role=routing.role,
        refusal=ModelRoutingRefusal(
            code=ModelRejectionCode.NO_ELIGIBLE_ROUTE,
            message=(
                f"selected tier {selection.tier.value} is below plan minimum "
                f"{phase.minimum_brain_tier.value}"
            ),
            required_tier=phase.minimum_brain_tier,
            considered_routes=(f"{selection.provider}/{selection.model}",),
        ),
        decided_at=previewed_at,
    )


def _require_unique(values: Sequence[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise PlanningPreviewInputError(f"{label} must be unique")


__all__ = [
    "PlanningPreviewError",
    "PlanningPreviewInputError",
    "PlanningPreviewRejected",
    "PlanningPreviewService",
    "derive_phase_demands",
]
