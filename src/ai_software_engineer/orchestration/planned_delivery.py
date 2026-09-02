"""Bridge an approved organization ExecutionPlan into the Task delivery runtime."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.domain import (
    AgentProducer,
    AgentRole,
    ArtifactIntegrity,
    ExecutionPlan,
    PlanAcceptanceMapping,
    PlanArtifact,
    PlanContent,
    PlanRisk,
    PlanStep,
    ProductSpec,
    Task,
    TaskStatus,
    TechnicalDesign,
)
from ai_software_engineer.store import TaskNotFound, TaskRepository

if TYPE_CHECKING:
    from ai_software_engineer.project_manager.dispatch import DispatchCommitRecord


class PlannedDeliveryError(RuntimeError):
    """Base class for failures at the organization-plan/delivery seam."""


class DispatchTaskConflict(PlannedDeliveryError):
    """A durable Task identity exists with different immutable dispatch facts."""


class PlannedDeliveryLineageError(PlannedDeliveryError):
    """ExecutionPlan, design, ProductSpec, and Task do not form one exact chain."""


class DispatchTaskMaterializer:
    """Create a Dispatch Task exactly once or verify its progressed durable replay."""

    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    def materialize(self, dispatch: DispatchCommitRecord) -> Task:
        dispatch.validate_integrity()
        expected = dispatch.task
        try:
            current = self._repository.get(expected.id)
        except TaskNotFound:
            self._repository.create(expected)
            return self._repository.get(expected.id)
        if _immutable_task_wire(current, expected) != expected.to_wire():
            raise DispatchTaskConflict(
                f"Task {expected.id} already exists with different dispatch content"
            )
        revision = self._repository.current_revision(expected.id)
        if revision != len(self._repository.list_events(expected.id)):
            raise DispatchTaskConflict(f"Task {expected.id} event revision is inconsistent")
        return current


class ExecutionPlanAgentAdapter:
    """Mechanically materialize the approved plan; it performs no new planning."""

    def __init__(
        self,
        *,
        task: Task,
        product_spec: ProductSpec,
        technical_design: TechnicalDesign,
        execution_plan: ExecutionPlan,
        agent_id: str,
        agent_version: str,
        created_at: datetime,
    ) -> None:
        _validate_lineage(task, product_spec, technical_design, execution_plan)
        self._task = task
        self._product_spec = product_spec
        self._technical_design = technical_design
        self._execution_plan = execution_plan
        self._agent_id = agent_id
        self._agent_version = agent_version
        self._created_at = created_at

    def run(self, request: AgentRequest) -> AgentResult:
        if request.role is not AgentRole.ORCHESTRATOR or request.task_id != self._task.id:
            raise PlannedDeliveryLineageError(
                "ExecutionPlan adapter only accepts its exact Orchestrator Task"
            )
        if request.source_revision != self._task.base_ref or request.input_artifact_ids:
            raise PlannedDeliveryLineageError(
                "ExecutionPlan materialization requires the Task base revision and no inputs"
            )
        artifact = self.materialize(request)
        return AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=artifact,
            duration_ms=0,
        )

    def materialize(self, request: AgentRequest) -> PlanArtifact:
        components = {component.id: component for component in self._technical_design.components}
        steps = tuple(
            PlanStep(
                step_id=step.id,
                description=step.description,
                files=tuple(
                    path
                    for component_id in step.component_ids
                    for path in components[component_id].affected_paths
                ),
                verification=step.verification,
            )
            for step in self._technical_design.implementation_steps
        )
        step_ids = tuple(step.step_id for step in steps)
        strategies = {
            mapping.acceptance_criterion_id: mapping.verification_strategy
            for mapping in self._technical_design.acceptance_mappings
        }
        content = PlanContent(
            goal=self._product_spec.summary,
            assumptions=self._product_spec.assumptions,
            steps=steps,
            acceptance_mapping=tuple(
                PlanAcceptanceMapping(
                    criterion_id=criterion.id,
                    step_ids=step_ids,
                    test_strategy=strategies[criterion.id],
                )
                for criterion in self._task.acceptance_criteria
            ),
            risks=tuple(
                PlanRisk(risk=risk.description, mitigation=risk.mitigation)
                for risk in self._technical_design.risks
            ),
        )
        identity = _digest(
            {
                "task_id": self._task.id,
                "execution_plan_sha256": self._execution_plan.execution_plan_sha256,
                "run_id": request.run_id,
            }
        )[:24]
        return PlanArtifact(
            artifact_id=f"art_plan_{identity}",
            task_id=request.task_id,
            schema_version="v0.1",
            producer=AgentProducer(
                role=AgentRole.ORCHESTRATOR,
                agent_id=self._agent_id,
                agent_version=self._agent_version,
                run_id=request.run_id,
            ),
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            created_at=self._created_at,
            parent_artifact_ids=(),
            evidence=(),
            content=content,
            integrity=ArtifactIntegrity(sha256="0" * 64, validated=False),
        )


class PlannedRoleAgentAdapter:
    """Route only planning to deterministic materialization and all roles explicitly."""

    def __init__(
        self,
        planning: AgentAdapter,
        delivery: Mapping[AgentRole, AgentAdapter],
    ) -> None:
        self._adapters = {AgentRole.ORCHESTRATOR: planning, **delivery}
        missing = set(AgentRole) - set(self._adapters)
        if missing:
            rendered = ", ".join(sorted(role.value for role in missing))
            raise PlannedDeliveryError(f"missing role adapter(s): {rendered}")

    def run(self, request: AgentRequest) -> AgentResult:
        return self._adapters[request.role].run(request)


def _validate_lineage(
    task: Task,
    product_spec: ProductSpec,
    technical_design: TechnicalDesign,
    execution_plan: ExecutionPlan,
) -> None:
    product_spec.validate_integrity()
    technical_design.validate_integrity()
    execution_plan.validate_integrity()
    if (
        task.status is not TaskStatus.NEW
        or task.metadata.get("project_request_id") != product_spec.request_id
        or task.metadata.get("execution_plan_id") != execution_plan.id
        or task.metadata.get("execution_plan_sha256") != execution_plan.execution_plan_sha256
        or technical_design.product_spec_id != product_spec.id
        or technical_design.product_spec_sha256 != product_spec.product_spec_sha256
        or execution_plan.product_spec_id != product_spec.id
        or execution_plan.product_spec_sha256 != product_spec.product_spec_sha256
        or execution_plan.technical_design_id != technical_design.id
        or execution_plan.technical_design_sha256 != technical_design.technical_design_sha256
    ):
        raise PlannedDeliveryLineageError("approved planning lineage does not match the Task")
    if {criterion.id for criterion in task.acceptance_criteria} != {
        mapping.acceptance_criterion_id for mapping in technical_design.acceptance_mappings
    }:
        raise PlannedDeliveryLineageError("design does not cover the exact Task acceptance set")


def _immutable_task_wire(current: Task, expected: Task) -> Mapping[str, object]:
    normalized = current.model_copy(
        update={
            "status": TaskStatus.NEW,
            "attempts": 0,
            "updated_at": expected.updated_at,
        }
    )
    return normalized.to_wire()


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


__all__ = [
    "DispatchTaskConflict",
    "DispatchTaskMaterializer",
    "ExecutionPlanAgentAdapter",
    "PlannedDeliveryError",
    "PlannedDeliveryLineageError",
    "PlannedRoleAgentAdapter",
]
