"""Immutable Planner preview evidence and canonical snapshot identities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, StringConstraints, model_validator

from ai_software_engineer.domain.agent import AgentId
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.identity import ContextId, ProjectId, RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import (
    ExecutionPlan,
    ExecutionPlanId,
    PlanPhaseId,
    ProjectRequestId,
    StageIntegrityError,
    StageSha256,
)
from ai_software_engineer.domain.task import Task, TaskId
from ai_software_engineer.domain.workforce import (
    AgentProfile,
    ModelPolicy,
    RoleAssignment,
    RunDemand,
    TaskLease,
    WorkItem,
)
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.scheduling import (
    AssignmentDecision,
    AssignmentDecisionStatus,
    ModelRoutingDecision,
    ModelRoutingDecisionStatus,
)

PlanningPreviewId = Annotated[str, StringConstraints(pattern=r"^planning_preview_[a-f0-9]{64}$")]


class PlannerRecordError(RuntimeError):
    """Base error for durable Planner run and completion records."""


class PlannerRecordIntegrityError(PlannerRecordError):
    """Raised when a Planner record or its nested facts were changed."""


class PlannerAgentErrorCode(StrEnum):
    TIMEOUT = "TIMEOUT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class PlannerRunOutcome(StrEnum):
    READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class PlannerRunRecord(DomainModel):
    """Journal-first receipt containing the exact accepted Planner outcome."""

    kind: Literal["planner_run_record"] = "planner_run_record"
    schema_version: Literal["v0.1"] = "v0.1"
    run_id: RunId
    project_id: ProjectId
    request_id: ProjectRequestId
    context_id: ContextId
    input_sha256: StageSha256
    input_request_revision_sha256: StageSha256
    design_checkpoint_sha256: StageSha256
    planning_authorization_sha256: StageSha256
    outcome: PlannerRunOutcome
    execution_plan: ExecutionPlan | None = None
    ready_request_revision: ProjectRequestRevision | None = None
    error_code: PlannerAgentErrorCode | None = None
    error_message: NonEmptyStr | None = None
    recorded_at: AwareDatetime
    run_record_sha256: StageSha256

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        success = self.outcome is PlannerRunOutcome.READY_FOR_DELIVERY
        if success:
            if (
                self.execution_plan is None
                or self.ready_request_revision is None
                or self.error_code is not None
                or self.error_message is not None
            ):
                raise ValueError("successful PlannerRunRecord requires only plan and revision")
            self._validate_success()
        elif (
            self.execution_plan is not None
            or self.ready_request_revision is not None
            or self.error_code is None
            or self.error_message is None
        ):
            raise ValueError("failed PlannerRunRecord requires only typed error facts")
        if (self.outcome is PlannerRunOutcome.TIMED_OUT) != (
            self.error_code is PlannerAgentErrorCode.TIMEOUT
        ):
            raise ValueError("Planner timeout outcome and error code must appear together")
        return self

    def _validate_success(self) -> None:
        plan = self.execution_plan
        revision = self.ready_request_revision
        assert plan is not None and revision is not None
        plan.validate_integrity()
        revision.validate_integrity()
        if (
            plan.project_id != self.project_id
            or plan.request_id != self.request_id
            or revision.request.project_id != self.project_id
            or revision.request.id != self.request_id
            or revision.request.status.value != "READY_FOR_DELIVERY"
            or revision.supersedes_sha256 != self.input_request_revision_sha256
        ):
            raise ValueError("Planner success facts do not form one exact delivery handoff")

    @classmethod
    def create(
        cls,
        *,
        run_id: RunId,
        project_id: ProjectId,
        request_id: ProjectRequestId,
        context_id: ContextId,
        input_sha256: StageSha256,
        input_request_revision_sha256: StageSha256,
        design_checkpoint_sha256: StageSha256,
        planning_authorization_sha256: StageSha256,
        outcome: PlannerRunOutcome,
        recorded_at: datetime,
        execution_plan: ExecutionPlan | None = None,
        ready_request_revision: ProjectRequestRevision | None = None,
        error_code: PlannerAgentErrorCode | None = None,
        error_message: str | None = None,
    ) -> PlannerRunRecord:
        provisional = cls(
            run_id=run_id,
            project_id=project_id,
            request_id=request_id,
            context_id=context_id,
            input_sha256=input_sha256,
            input_request_revision_sha256=input_request_revision_sha256,
            design_checkpoint_sha256=design_checkpoint_sha256,
            planning_authorization_sha256=planning_authorization_sha256,
            outcome=outcome,
            execution_plan=execution_plan,
            ready_request_revision=ready_request_revision,
            error_code=error_code,
            error_message=error_message,
            recorded_at=recorded_at,
            run_record_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={"run_record_sha256": _planner_run_digest(provisional)}
        )

    def validate_integrity(self) -> None:
        try:
            if self.outcome is PlannerRunOutcome.READY_FOR_DELIVERY:
                self._validate_success()
        except (RuntimeError, ValueError) as error:
            raise PlannerRecordIntegrityError(
                "PlannerRunRecord nested facts are invalid"
            ) from error
        if self.run_record_sha256 != _planner_run_digest(self):
            raise PlannerRecordIntegrityError("PlannerRunRecord digest does not match content")


class PlannerCommitCheckpoint(DomainModel):
    """Completion marker published after plan and READY revision exact read-back."""

    kind: Literal["planner_commit_checkpoint"] = "planner_commit_checkpoint"
    schema_version: Literal["v0.1"] = "v0.1"
    run_id: RunId
    project_id: ProjectId
    request_id: ProjectRequestId
    run_record_sha256: StageSha256
    design_checkpoint_sha256: StageSha256
    planning_authorization_sha256: StageSha256
    execution_plan_id: ExecutionPlanId
    execution_plan_sha256: StageSha256
    input_request_revision_sha256: StageSha256
    ready_request_revision: int
    ready_request_revision_sha256: StageSha256
    committed_at: AwareDatetime
    checkpoint_sha256: StageSha256

    @classmethod
    def create(
        cls,
        record: PlannerRunRecord,
        *,
        committed_at: datetime,
    ) -> PlannerCommitCheckpoint:
        if record.outcome is not PlannerRunOutcome.READY_FOR_DELIVERY:
            raise ValueError("only a successful Planner run can be committed")
        record.validate_integrity()
        plan = record.execution_plan
        revision = record.ready_request_revision
        assert plan is not None and revision is not None
        provisional = cls(
            run_id=record.run_id,
            project_id=record.project_id,
            request_id=record.request_id,
            run_record_sha256=record.run_record_sha256,
            design_checkpoint_sha256=record.design_checkpoint_sha256,
            planning_authorization_sha256=record.planning_authorization_sha256,
            execution_plan_id=plan.id,
            execution_plan_sha256=plan.execution_plan_sha256,
            input_request_revision_sha256=record.input_request_revision_sha256,
            ready_request_revision=revision.revision,
            ready_request_revision_sha256=revision.request_revision_sha256,
            committed_at=committed_at,
            checkpoint_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={"checkpoint_sha256": _planner_checkpoint_digest(provisional)}
        )

    def validate_integrity(self) -> None:
        if self.checkpoint_sha256 != _planner_checkpoint_digest(self):
            raise PlannerRecordIntegrityError(
                "PlannerCommitCheckpoint digest does not match content"
            )


class PlanningPreviewExpired(RuntimeError):
    """Raised when preview evidence is used outside its declared validity window."""


class PlanningPhasePreview(DomainModel):
    """One feasible, non-authoritative scheduling and model-routing preview."""

    phase_id: PlanPhaseId
    role: AgentRole
    demand: RunDemand
    assignment_decision: AssignmentDecision
    model_routing_decision: ModelRoutingDecision

    @model_validator(mode="after")
    def validate_phase_decisions(self) -> Self:
        assignment = self.assignment_decision
        routing = self.model_routing_decision
        if assignment.status is not AssignmentDecisionStatus.ASSIGNED:
            raise ValueError("PlanningPhasePreview requires an assigned scheduling decision")
        if routing.status is not ModelRoutingDecisionStatus.SELECTED:
            raise ValueError("PlanningPhasePreview requires a selected model-routing decision")
        if assignment.agent_id is None or assignment.assignment is None or assignment.lease is None:
            raise ValueError("PlanningPhasePreview assignment decision is incomplete")
        if routing.selection is None:
            raise ValueError("PlanningPhasePreview model-routing decision is incomplete")
        if (
            self.demand.task_id != assignment.task_id
            or self.demand.task_id != routing.task_id
            or self.demand.role is not self.role
            or assignment.role is not self.role
            or routing.role is not self.role
            or routing.agent_id != assignment.agent_id
        ):
            raise ValueError("PlanningPhasePreview task, role, or Agent identity does not align")
        return self

    @property
    def agent_id(self) -> AgentId:
        """Return the selected preview Agent after the model shape guard succeeds."""
        assert self.assignment_decision.agent_id is not None
        return self.assignment_decision.agent_id


class PlanningPreview(DomainModel):
    """Replayable feasibility evidence that never authorizes resource allocation."""

    kind: Literal["planning_preview"] = "planning_preview"
    schema_version: Literal["v0.1"] = "v0.1"
    id: PlanningPreviewId
    project_id: ProjectId
    task_id: TaskId
    task_sha256: StageSha256
    work_item_sha256: StageSha256
    execution_plan_id: ExecutionPlanId
    execution_plan_sha256: StageSha256
    workforce_snapshot_sha256: StageSha256
    phases: tuple[PlanningPhasePreview, PlanningPhasePreview, PlanningPhasePreview]
    previewed_at: AwareDatetime
    valid_until: AwareDatetime
    preview_sha256: StageSha256

    @model_validator(mode="after")
    def validate_preview_shape(self) -> Self:
        if self.valid_until <= self.previewed_at:
            raise ValueError("PlanningPreview valid_until must be later than previewed_at")
        expected_roles = (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)
        if tuple(phase.role for phase in self.phases) != expected_roles:
            raise ValueError("PlanningPreview phases must be coder, qa, reviewer in order")
        if any(phase.demand.task_id != self.task_id for phase in self.phases):
            raise ValueError("PlanningPreview phase demand does not match task identity")
        for phase in self.phases:
            decision = phase.assignment_decision
            assignment = decision.assignment
            lease = decision.lease
            routing = phase.model_routing_decision
            if assignment is None or lease is None:
                raise ValueError("PlanningPreview phase assignment is incomplete")
            if (
                decision.project_id != self.project_id
                or assignment.project_id != self.project_id
                or decision.task_id != self.task_id
                or assignment.task_id != self.task_id
                or lease.task_id != self.task_id
                or routing.task_id != self.task_id
                or assignment.role is not phase.role
            ):
                raise ValueError(
                    "PlanningPreview nested project, task, and role lineage does not align"
                )
        return self

    @classmethod
    def create(
        cls,
        *,
        task: Task,
        work_item: WorkItem,
        execution_plan: ExecutionPlan,
        workforce_snapshot_sha256: StageSha256,
        phases: tuple[PlanningPhasePreview, PlanningPhasePreview, PlanningPhasePreview],
        previewed_at: datetime,
        valid_until: datetime,
    ) -> PlanningPreview:
        provisional = cls(
            id=f"planning_preview_{'0' * 64}",
            project_id=work_item.project_id,
            task_id=task.id,
            task_sha256=delivery_task_digest(task),
            work_item_sha256=work_item_digest(work_item),
            execution_plan_id=execution_plan.id,
            execution_plan_sha256=execution_plan.execution_plan_sha256,
            workforce_snapshot_sha256=workforce_snapshot_sha256,
            phases=phases,
            previewed_at=previewed_at,
            valid_until=valid_until,
            preview_sha256="0" * 64,
        )
        digest = _preview_digest(provisional)
        return provisional.model_copy(
            update={"id": f"planning_preview_{digest}", "preview_sha256": digest}
        )

    def validate_integrity(self) -> None:
        expected = _preview_digest(self)
        if self.preview_sha256 != expected or self.id != f"planning_preview_{expected}":
            raise StageIntegrityError("PlanningPreview identity does not match content")

    def require_valid_at(self, at: datetime) -> None:
        """Fail closed on naive, pre-observation, expired, or tampered preview use."""
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("PlanningPreview evaluation time must be timezone-aware")
        self.validate_integrity()
        if at < self.previewed_at:
            raise ValueError("PlanningPreview cannot be used before previewed_at")
        if at >= self.valid_until:
            raise PlanningPreviewExpired(
                f"PlanningPreview expired at {self.valid_until.isoformat()}"
            )


def delivery_task_digest(task: Task) -> StageSha256:
    """Return the canonical identity of the exact derived Delivery Task snapshot."""
    return _wire_digest(task.to_wire())


def work_item_digest(work_item: WorkItem) -> StageSha256:
    """Return the canonical identity of one exact scheduling WorkItem snapshot."""
    return _wire_digest(work_item.to_wire())


def workforce_snapshot_digest(
    *,
    work_item: WorkItem,
    phase_demands: Sequence[RunDemand],
    agents: Sequence[AgentProfile],
    active_leases: Sequence[TaskLease],
    assignments: Sequence[RoleAssignment],
    policies: Sequence[ModelPolicy],
) -> StageSha256:
    """Hash current workforce facts independently of caller collection ordering."""
    payload = {
        "work_item": work_item.to_wire(),
        "phase_demands": [item.to_wire() for item in phase_demands],
        "agents": [item.to_wire() for item in sorted(agents, key=lambda item: item.id)],
        "active_leases": [
            item.to_wire() for item in sorted(active_leases, key=lambda item: item.id)
        ],
        "assignments": [item.to_wire() for item in sorted(assignments, key=lambda item: item.id)],
        "policies": [
            item.to_wire() for item in sorted(policies, key=lambda item: (item.id, item.version))
        ],
    }
    return _wire_digest(payload)


def _preview_digest(preview: PlanningPreview) -> StageSha256:
    payload = preview.model_dump(
        mode="json",
        exclude={"id", "preview_sha256"},
        exclude_none=True,
    )
    return _wire_digest(payload)


def _wire_digest(payload: object) -> StageSha256:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _planner_run_digest(record: PlannerRunRecord) -> StageSha256:
    return _wire_digest(
        record.model_dump(mode="json", exclude={"run_record_sha256"}, exclude_none=True)
    )


def _planner_checkpoint_digest(checkpoint: PlannerCommitCheckpoint) -> StageSha256:
    return _wire_digest(checkpoint.model_dump(mode="json", exclude={"checkpoint_sha256"}))


__all__ = [
    "PlannerAgentErrorCode",
    "PlannerCommitCheckpoint",
    "PlannerRecordError",
    "PlannerRecordIntegrityError",
    "PlannerRunOutcome",
    "PlannerRunRecord",
    "PlanningPhasePreview",
    "PlanningPreview",
    "PlanningPreviewExpired",
    "PlanningPreviewId",
    "delivery_task_digest",
    "work_item_digest",
    "workforce_snapshot_digest",
]
