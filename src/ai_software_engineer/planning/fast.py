"""The zero-model plan for a Manager-classified simple change."""

from __future__ import annotations

import hashlib

from ai_software_engineer.domain.enums import AgentRole, BrainTier, RiskTier
from ai_software_engineer.domain.project_delivery import ExecutionPlan, PlanPhaseDemand
from ai_software_engineer.planning.agents import (
    PlannerAgentRequest,
    PlannerAgentResult,
    PlannerAgentRunStatus,
)
from ai_software_engineer.planning.gate import PlanningMode


def fast_plan(request: PlannerAgentRequest) -> PlannerAgentResult:
    decision = request.context.planning_decision
    if decision is None or decision.mode is not PlanningMode.SIMPLE:
        raise ValueError("fast plan requires the Manager SIMPLE gate decision")
    decision.validate_integrity()
    criteria = request.context.product_spec.acceptance_criteria
    plan = ExecutionPlan.create(
        request.context.product_spec,
        request.context.technical_design,
        plan_id="execution_plan_" + hashlib.sha256(request.run_id.encode()).hexdigest()[:24],
        version=request.context.expected_execution_plan_version,
        phases=tuple(
            PlanPhaseDemand(
                id=f"phase_{role.value}_001",
                role=role,
                objective=f"Complete {role.value} for all exact approved acceptance criteria",
                required_capabilities=(capability,),
                risk=RiskTier.LOW,
                minimum_brain_tier=BrainTier.STANDARD,
                checkpoints=tuple(
                    f"{criterion.id}: {criterion.verification}" for criterion in criteria
                ),
            )
            for role, capability in (
                (AgentRole.CODER, "implementation"),
                (AgentRole.QA, "testing"),
                (AgentRole.REVIEWER, "review"),
            )
        ),
        created_at=request.context.built_at,
    )
    return PlannerAgentResult(
        run_id=request.run_id,
        repository_id=request.repository_id,
        request_id=request.request_id,
        context_id=request.context.context_id,
        status=PlannerAgentRunStatus.SUCCEEDED,
        execution_plan=plan,
    )
