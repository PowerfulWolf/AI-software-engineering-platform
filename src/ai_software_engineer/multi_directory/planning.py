"""Manager routing and mechanical graph compilation for joint planning."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ai_software_engineer.domain.enums import BrainTier, RiskTier
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import (
    DesignComplexityFacts,
    PlanTestItem,
    PlanTestMatrixIssue,
    PlanWorkGraph,
    PlanWorkPackage,
)
from ai_software_engineer.domain.task import AcceptanceCriterionId
from ai_software_engineer.manager.production_agents import (
    DeliveryCapability,
    ExecutionPlanDraft,
    PhaseDraft,
    TechnicalDesignDraft,
)
from ai_software_engineer.multi_directory.models import (
    ComplexPlanRequired,
    JointCheckpoint,
    JointExecutionPlan,
    JointPlanFeedback,
    JointTechnicalDesign,
    UnitPlan,
    digest,
)
from ai_software_engineer.multi_directory.scope import UnitId
from ai_software_engineer.planning.gate import (
    PlanningDecision,
    PlanningFacts,
    PlanningGate,
    PlanningMode,
    risk_rank,
)


def joint_planning_decision(checkpoint: JointCheckpoint) -> PlanningDecision:
    product, design = checkpoint.product_spec, checkpoint.design
    if product is None or design is None:
        raise ValueError("planning gate requires approved Product and Design")
    structured = tuple(
        unit.design.complexity_facts or DesignComplexityFacts() for unit in design.units
    )
    groups = {group for facts in structured for group in facts.integration_groups}
    facts = PlanningFacts(
        product_spec_sha256=digest(product),
        technical_design_sha256=digest(design),
        repository_count=len(checkpoint.scope.units),
        component_count=sum(len(unit.design.components) for unit in design.units),
        integration_group_count=len(groups),
        technical_risk=max(
            (risk.tier for unit in design.units for risk in unit.design.risks),
            key=risk_rank,
            default=RiskTier.LOW,
        ),
        design_facts=DesignComplexityFacts(
            **{
                name: any(getattr(item, name) for item in structured)
                for name in (
                    "database_migration",
                    "data_backfill",
                    "security",
                    "performance",
                    "concurrency",
                    "work_package_dependencies",
                )
            },
            interface_compatibility=bool(design.interfaces)
            or any(item.interface_compatibility for item in structured),
            integration_groups=tuple(sorted(groups)),
        ),
    )
    return PlanningGate().classify(facts, upgrade=checkpoint.planning_upgrade)


def fast_joint_plan(checkpoint: JointCheckpoint) -> JointExecutionPlan:
    if (
        checkpoint.planning_decision is None
        or checkpoint.planning_decision.mode is not PlanningMode.SIMPLE
    ):
        raise ValueError("fast planning requires Manager SIMPLE decision")
    assert checkpoint.design is not None
    roles: tuple[tuple[Literal["coder", "qa", "reviewer"], DeliveryCapability], ...] = (
        ("coder", "implementation"),
        ("qa", "testing"),
        ("reviewer", "review"),
    )
    phases = tuple(
        PhaseDraft(
            role=role,
            objective=f"Complete independent {role} acceptance",
            required_capabilities=(capability,),
            risk=RiskTier.LOW,
            minimum_brain_tier=BrainTier.STANDARD,
            checkpoints=("All exact approved acceptance IDs are evidenced",),
        )
        for role, capability in roles
    )
    return compile_joint_plan(
        checkpoint,
        JointExecutionPlan(
            design_sha256=digest(checkpoint.design),
            units=tuple(
                UnitPlan(unit_id=unit.unit_id, plan=ExecutionPlanDraft(phases=phases))
                for unit in checkpoint.design.units
            ),
        ),
    )


def compile_joint_plan(checkpoint: JointCheckpoint, plan: JointExecutionPlan) -> JointExecutionPlan:
    """Fill only mechanical references from the exact design, never invent acceptance."""
    assert checkpoint.design is not None
    if len(plan.units) > 16:
        raise ValueError("new execution plans support at most 16 bounded repository work packages")
    designs = {unit.unit_id: unit.design for unit in checkpoint.design.units}
    units = []
    for unit in plan.units:
        design = designs.get(unit.unit_id)
        if design is None:
            raise ValueError("plan references unknown write unit")
        graph = unit.plan.work_graph
        if graph is None:
            if (
                checkpoint.planning_decision is None
                or checkpoint.planning_decision.mode is not PlanningMode.SIMPLE
            ):
                raise ComplexPlanRequired()
            graph = design_work_graph(design, package_id="package_" + unit.unit_id)
        units.append(
            unit.model_copy(update={"plan": unit.plan.model_copy(update={"work_graph": graph})})
        )
    feedback = checkpoint.planning_feedback
    return JointExecutionPlan.model_validate(
        {
            **plan.to_wire(),
            "units": [unit.to_wire() for unit in units],
            "version": 1 if feedback is None else (feedback.previous_plan.version or 1) + 1,
            "previous_plan_sha256": None if feedback is None else digest(feedback.previous_plan),
            "feedback_sha256": None if feedback is None else digest(feedback),
        }
    )


def design_work_graph(design: TechnicalDesignDraft, *, package_id: str) -> PlanWorkGraph:
    """Mechanical SIMPLE/legacy expansion only; complex new output may not use fallback."""
    return PlanWorkGraph(
        packages=(
            PlanWorkPackage(
                id=package_id,
                component_ids=tuple("component_" + item.key for item in design.components),
                step_ids=tuple("design_step_" + item.key for item in design.implementation_steps),
                acceptance_criterion_ids=tuple(
                    item.acceptance_criterion_id for item in design.acceptance_mappings
                ),
                risk=max((risk.tier for risk in design.risks), key=risk_rank, default=RiskTier.LOW),
                checkpoints=tuple(step.verification for step in design.implementation_steps),
                tests=tuple(
                    PlanTestItem(
                        id=f"test_{index}_{level_index}",
                        acceptance_criterion_ids=(mapping.acceptance_criterion_id,),
                        level=level,
                        verification=mapping.verification_strategy,
                    )
                    for index, mapping in enumerate(design.acceptance_mappings, 1)
                    for level_index, level in enumerate(mapping.test_levels, 1)
                ),
            ),
        )
    )


class PlannerTestRequirement(DomainModel):
    unit_id: UnitId
    acceptance_criterion_id: AcceptanceCriterionId
    test_levels: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


def planner_test_requirements(design: JointTechnicalDesign) -> tuple[PlannerTestRequirement, ...]:
    return tuple(
        PlannerTestRequirement(
            unit_id=unit.unit_id,
            acceptance_criterion_id=mapping.acceptance_criterion_id,
            test_levels=mapping.test_levels,
        )
        for unit in design.units
        for mapping in unit.design.acceptance_mappings
    )


def rejection_feedback(
    plan: JointExecutionPlan,
    reason: str,
    *,
    test_matrix_issues: tuple[PlanTestMatrixIssue, ...] | None = None,
) -> JointPlanFeedback:
    return JointPlanFeedback(
        previous_plan=plan,
        reason_codes=("PLAN_TEST_MATRIX_MISSING_LEVELS",) if test_matrix_issues else (reason,),
        test_matrix_issues=test_matrix_issues,
        required_changes=tuple(
            f"For unit {issue.unit_id}, criterion {issue.acceptance_criterion_id}, add separate "
            f"test entries using each exact missing level: {', '.join(issue.missing_levels)}. "
            "Do not concatenate level names; preserve all other approved coverage."
            for issue in test_matrix_issues
        )
        if test_matrix_issues
        else ("Correct the recorded rejection; preserve exact approved acceptance and interfaces",),
    )
