"""Atomic Project Manager commit-dispatch boundary.

Planner previews are read-only evidence. This module reruns the scheduler and model router
against current facts before making one append-only store call.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from ai_software_engineer.domain.agent import AgentId
from ai_software_engineer.domain.enums import (
    AgentRole,
    BrainTier,
    ProjectRequestStatus,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.identity import ProjectId, RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import (
    ExecutionPlan,
    ExecutionPlanId,
    PlanPhaseId,
    ProductSpec,
    ProductSpecApproval,
    ProjectPreparation,
    ProjectRequest,
    ProjectRequestId,
    TechnicalDesign,
    derive_delivery_task,
)
from ai_software_engineer.domain.task import AttemptLimit, Task, TaskConstraints, TaskId
from ai_software_engineer.domain.workforce import (
    AgentProfile,
    ModelPolicy,
    ModelSelection,
    RoleAssignment,
    TaskLease,
    WorkItem,
)
from ai_software_engineer.planning.models import (
    PlannerCommitCheckpoint,
    PlannerRunOutcome,
    PlannerRunRecord,
    PlanningPreview,
    PlanningPreviewId,
    delivery_task_digest,
    work_item_digest,
    workforce_snapshot_digest,
)
from ai_software_engineer.planning.preview import derive_phase_demands
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.project_manager.stages import (
    ProjectStage,
    ProjectStageAdvancer,
    StageAdvanceAuthorization,
    StageAdvanceRequest,
)
from ai_software_engineer.scheduling.model_router import ModelRouter
from ai_software_engineer.scheduling.models import (
    AssignmentDecision,
    AssignmentDecisionStatus,
    ModelRoutingDecision,
    ModelRoutingDecisionStatus,
)
from ai_software_engineer.scheduling.portfolio import PortfolioScheduler

DispatchCommitId = Annotated[str, StringConstraints(pattern=r"^dispatch_commit_[a-f0-9]{64}$")]
DispatchSha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
_TIER_RANK = {
    BrainTier.ECONOMY: 0,
    BrainTier.STANDARD: 1,
    BrainTier.REASONING: 2,
    BrainTier.CRITICAL: 3,
}


class DispatchError(RuntimeError):
    """Base class for commit-dispatch failures."""


class DispatchStageMismatch(DispatchError):
    """The supplied stage authorization or lineage is not exact."""


class DispatchPreviewStale(DispatchError):
    """Preview evidence expired or its input facts changed."""


class DispatchAuthorityConflict(DispatchPreviewStale):
    """Authoritative workforce facts changed inside the commit window."""


class DispatchDecisionDrift(DispatchError):
    """Commit-time pure engines selected different Agent/model semantics."""


class DispatchRejected(DispatchError):
    """Current workforce or model policy cannot serve a phase."""

    def __init__(self, role: AgentRole, reason: str) -> None:
        self.role = role
        self.reason = reason
        super().__init__(f"{role.value} dispatch rejected: {reason}")


class DispatchStoreError(DispatchError):
    """Base error for immutable dispatch persistence."""


class DispatchCommitConflict(DispatchStoreError):
    """An existing commit identity contains different content."""


class DispatchCommitCorruption(DispatchStoreError):
    """A durable commit cannot be verified."""


class DispatchCommitNotFound(DispatchStoreError):
    """A dispatch commit does not exist."""


class DispatchCommitPathError(DispatchStoreError):
    """The store path is unsafe."""


class DispatchPhaseCommit(DomainModel):
    """Concrete commit-time allocation for one serial delivery role."""

    kind: Literal["dispatch_phase_commit"] = "dispatch_phase_commit"
    phase_id: PlanPhaseId
    role: AgentRole
    agent_id: AgentId
    assignment: RoleAssignment
    lease: TaskLease
    model_selection: ModelSelection

    @model_validator(mode="after")
    def validate_allocation(self) -> Self:
        if (
            self.assignment.role is not self.role
            or self.assignment.agent_id != self.agent_id
            or self.lease.agent_id != self.agent_id
            or self.lease.assignment_id != self.assignment.id
            or self.lease.id != self.assignment.lease_id
            or self.lease.task_id != self.assignment.task_id
        ):
            raise ValueError("dispatch phase assignment, lease, Agent, and role must match")
        return self


class DispatchWorkforceSnapshot(DomainModel):
    """Versioned current facts read from the organization-owned allocation authority."""

    kind: Literal["dispatch_workforce_snapshot"] = "dispatch_workforce_snapshot"
    schema_version: Literal["v0.1"] = "v0.1"
    project_id: ProjectId
    task_id: TaskId
    work_item: WorkItem
    agents: Annotated[tuple[AgentProfile, ...], Field(min_length=1)]
    active_leases: tuple[TaskLease, ...] = ()
    assignments: tuple[RoleAssignment, ...] = ()
    model_policies: Annotated[tuple[ModelPolicy, ...], Field(min_length=1)]
    snapshot_sha256: DispatchSha256

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.work_item.task_id != self.task_id or self.work_item.project_id != self.project_id:
            raise ValueError("authoritative WorkItem does not match snapshot task/project")
        _require_unique((agent.id for agent in self.agents), "AgentProfile IDs")
        _require_unique((lease.id for lease in self.active_leases), "TaskLease IDs")
        _require_unique((item.id for item in self.assignments), "RoleAssignment IDs")
        _require_unique((policy.id for policy in self.model_policies), "ModelPolicy IDs")
        return self

    @classmethod
    def create(
        cls,
        *,
        project_id: ProjectId,
        task_id: TaskId,
        work_item: WorkItem,
        agents: Iterable[AgentProfile],
        active_leases: Iterable[TaskLease] = (),
        assignments: Iterable[RoleAssignment] = (),
        model_policies: Iterable[ModelPolicy],
    ) -> DispatchWorkforceSnapshot:
        provisional = cls(
            project_id=project_id,
            task_id=task_id,
            work_item=work_item,
            agents=tuple(sorted(agents, key=lambda item: item.id)),
            active_leases=tuple(sorted(active_leases, key=lambda item: item.id)),
            assignments=tuple(sorted(assignments, key=lambda item: item.id)),
            model_policies=tuple(sorted(model_policies, key=lambda item: (item.id, item.version))),
            snapshot_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={"snapshot_sha256": _authority_snapshot_digest(provisional)}
        )

    def validate_integrity(self) -> None:
        if self.snapshot_sha256 != _authority_snapshot_digest(self):
            raise DispatchAuthorityConflict("authoritative workforce snapshot digest changed")


class DispatchCommitRecord(DomainModel):
    """One append-only Task plus all three delivery allocation commits."""

    kind: Literal["dispatch_commit"] = "dispatch_commit"
    schema_version: Literal["v0.1"] = "v0.1"
    id: DispatchCommitId
    project_id: ProjectId
    task_id: TaskId
    project_request_id: ProjectRequestId
    execution_plan_id: ExecutionPlanId
    execution_plan_sha256: DispatchSha256
    execution_plan_phase_ids: tuple[PlanPhaseId, PlanPhaseId, PlanPhaseId]
    ready_request_revision: Annotated[int, Field(ge=1)]
    ready_request_revision_sha256: DispatchSha256
    planner_run_id: RunId
    planner_run_record_sha256: DispatchSha256
    design_checkpoint_sha256: DispatchSha256
    planning_authorization_sha256: DispatchSha256
    planner_checkpoint_sha256: DispatchSha256
    planning_preview_id: PlanningPreviewId
    planning_preview_sha256: DispatchSha256
    workforce_snapshot_sha256: DispatchSha256
    stage_authorization_sha256: DispatchSha256
    task: Task
    phases: Annotated[tuple[DispatchPhaseCommit, ...], Field(min_length=3, max_length=3)]
    committed_at: AwareDatetime
    dispatch_sha256: DispatchSha256

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if self.task.id != self.task_id or self.task.status is not TaskStatus.NEW:
            raise ValueError("DispatchCommitRecord must contain its exact NEW Task")
        if self.task.metadata.get("project_id") != self.project_id:
            raise ValueError("DispatchCommitRecord Task project does not match")
        if self.task.metadata.get("project_request_id") != self.project_request_id:
            raise ValueError("DispatchCommitRecord Task request does not match")
        if (
            self.task.metadata.get("execution_plan_id") != self.execution_plan_id
            or self.task.metadata.get("execution_plan_sha256") != self.execution_plan_sha256
        ):
            raise ValueError("DispatchCommitRecord Task execution plan does not match")
        expected_roles = (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)
        if tuple(phase.role for phase in self.phases) != expected_roles:
            raise ValueError("dispatch phases must be coder, qa, reviewer in order")
        if len({phase.agent_id for phase in self.phases}) != len(self.phases):
            raise ValueError("Coder, QA, and Reviewer must be different Agents")
        _require_unique(
            (phase.assignment.id for phase in self.phases),
            "dispatch Assignment IDs",
        )
        _require_unique((phase.lease.id for phase in self.phases), "dispatch Lease IDs")
        if any(phase.assignment.task_id != self.task_id for phase in self.phases):
            raise ValueError("dispatch phase Task does not match commit")
        if any(phase.assignment.project_id != self.project_id for phase in self.phases):
            raise ValueError("dispatch phase project does not match commit")
        if tuple(phase.phase_id for phase in self.phases) != self.execution_plan_phase_ids:
            raise ValueError("dispatch phase IDs do not match ExecutionPlan")
        return self

    @classmethod
    def create(
        cls,
        *,
        project_id: ProjectId,
        execution_plan: ExecutionPlan,
        preview: PlanningPreview,
        ready_request_revision: ProjectRequestRevision,
        planner_run_record: PlannerRunRecord,
        planner_checkpoint: PlannerCommitCheckpoint,
        stage_authorization: StageAdvanceAuthorization,
        task: Task,
        phases: tuple[DispatchPhaseCommit, DispatchPhaseCommit, DispatchPhaseCommit],
        committed_at: datetime,
    ) -> DispatchCommitRecord:
        identity = _canonical_json(
            {
                "project_id": project_id,
                "task_id": task.id,
                "execution_plan_sha256": execution_plan.execution_plan_sha256,
                "ready_request_revision_sha256": (ready_request_revision.request_revision_sha256),
                "planner_checkpoint_sha256": planner_checkpoint.checkpoint_sha256,
            }
        )
        provisional = cls(
            id=f"dispatch_commit_{hashlib.sha256(identity.encode()).hexdigest()}",
            project_id=project_id,
            task_id=task.id,
            project_request_id=ready_request_revision.request.id,
            execution_plan_id=execution_plan.id,
            execution_plan_sha256=execution_plan.execution_plan_sha256,
            execution_plan_phase_ids=(
                execution_plan.phases[0].id,
                execution_plan.phases[1].id,
                execution_plan.phases[2].id,
            ),
            ready_request_revision=ready_request_revision.revision,
            ready_request_revision_sha256=(ready_request_revision.request_revision_sha256),
            planner_run_id=planner_run_record.run_id,
            planner_run_record_sha256=planner_run_record.run_record_sha256,
            design_checkpoint_sha256=planner_run_record.design_checkpoint_sha256,
            planning_authorization_sha256=(planner_run_record.planning_authorization_sha256),
            planner_checkpoint_sha256=planner_checkpoint.checkpoint_sha256,
            planning_preview_id=preview.id,
            planning_preview_sha256=preview.preview_sha256,
            workforce_snapshot_sha256=preview.workforce_snapshot_sha256,
            stage_authorization_sha256=stage_authorization.authorization_sha256,
            task=task,
            phases=phases,
            committed_at=committed_at,
            dispatch_sha256="0" * 64,
        )
        return provisional.model_copy(update={"dispatch_sha256": _record_digest(provisional)})

    def validate_integrity(self) -> None:
        if self.dispatch_sha256 != _record_digest(self):
            raise DispatchCommitCorruption("dispatch record digest does not match content")


class CommitDispatchRequest(DomainModel):
    """Exact current facts required to authorize one dispatch commit."""

    preparation: ProjectPreparation
    project_request: ProjectRequest
    product_spec: ProductSpec
    product_approval: ProductSpecApproval
    technical_design: TechnicalDesign
    execution_plan: ExecutionPlan
    ready_request_revision: ProjectRequestRevision
    planner_run_record: PlannerRunRecord
    planner_checkpoint: PlannerCommitCheckpoint
    stage_authorization: StageAdvanceAuthorization
    planning_preview: PlanningPreview
    task_id: TaskId
    repository: NonEmptyStr
    base_ref: NonEmptyStr
    max_attempts: AttemptLimit
    task_created_at: AwareDatetime
    committed_at: AwareDatetime
    constraints: TaskConstraints | None = None
    owner: NonEmptyStr | None = None
    labels: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_facts(self) -> Self:
        if self.committed_at < self.task_created_at:
            raise ValueError("committed_at cannot precede task_created_at")
        _require_unique(self.labels, "Task labels")
        return self


class DispatchCommitStore(Protocol):
    """Single-call atomic write port used only after all decisions succeed."""

    def commit(self, record: DispatchCommitRecord) -> DispatchCommitRecord: ...


class DispatchAuthority(Protocol):
    """Read and reserve organization facts under one shared allocation transaction.

    Implementations must compare ``expected_snapshot_sha256`` while holding the same lock or
    transaction used by every workforce reservation writer.  A successful call publishes the
    DispatchCommitRecord and its three assignments/leases as one allocation decision.
    """

    def current_snapshot(
        self,
        *,
        project_id: ProjectId,
        task_id: TaskId,
    ) -> DispatchWorkforceSnapshot: ...

    def commit_if_current(
        self,
        record: DispatchCommitRecord,
        *,
        expected_snapshot_sha256: DispatchSha256,
    ) -> DispatchCommitRecord: ...


class DispatchRequestRevisionReader(Protocol):
    """Read the authoritative current ProjectRequest revision."""

    def current_request_revision(self, request_id: str) -> ProjectRequestRevision: ...


class DispatchPlannerRecordReader(Protocol):
    """Read the complete authoritative Planner commit handoff."""

    def get_run(self, run_id: RunId | str) -> PlannerRunRecord: ...

    def get_checkpoint(self, run_id: RunId | str) -> PlannerCommitCheckpoint: ...

    def get_execution_plan(self, plan_id: ExecutionPlanId | str) -> ExecutionPlan: ...


class ProjectManagerDispatchService:
    """Revalidate a Planner preview and atomically persist current allocations."""

    def __init__(
        self,
        *,
        scheduler: PortfolioScheduler,
        model_router: ModelRouter,
        authority: DispatchAuthority,
        request_revisions: DispatchRequestRevisionReader,
        planner_records: DispatchPlannerRecordReader,
    ) -> None:
        self._scheduler = scheduler
        self._model_router = model_router
        self._authority = authority
        self._request_revisions = request_revisions
        self._planner_records = planner_records

    def commit_dispatch(self, request: CommitDispatchRequest) -> DispatchCommitRecord:
        self._validate_stage(request)
        self._validate_planner_handoff(request)
        task = self._derive_task(request)
        preview = request.planning_preview
        snapshot = self._authority.current_snapshot(
            project_id=request.preparation.project_id,
            task_id=task.id,
        )
        snapshot.validate_integrity()
        self._validate_preview(request, task, snapshot)

        profiles = {profile.id: profile for profile in snapshot.agents}
        policies = {policy.id: policy for policy in snapshot.model_policies}
        pending_leases = tuple(snapshot.active_leases)
        pending_assignments = tuple(snapshot.assignments)
        commits: list[DispatchPhaseCommit] = []

        for phase in preview.phases:
            phase_item = snapshot.work_item.model_copy(
                update={"required_capabilities": phase.demand.required_capabilities}
            )
            assignment = self._scheduler.match(
                phase_item,
                phase.role,
                snapshot.agents,
                pending_leases,
                pending_assignments,
                now=request.committed_at,
                attempt=1,
                work_items=(phase_item,),
            )
            self._require_assignment(phase.assignment_decision, assignment)
            assert assignment.agent_id is not None
            assert assignment.assignment is not None
            assert assignment.lease is not None
            profile = profiles[assignment.agent_id]
            policy = policies.get(profile.default_model_policy_id)
            if policy is None:
                raise DispatchRejected(
                    phase.role,
                    f"ModelPolicy {profile.default_model_policy_id} is not present",
                )
            routing = self._model_router.route(
                phase.demand,
                profile,
                policy,
                now=request.committed_at,
            )
            self._require_model_route(phase.model_routing_decision, routing)
            assert routing.selection is not None
            planned_phase = request.execution_plan.phases[len(commits)]
            if _TIER_RANK[routing.selection.tier] < _TIER_RANK[planned_phase.minimum_brain_tier]:
                raise DispatchRejected(
                    phase.role,
                    f"selected tier is below {planned_phase.minimum_brain_tier.value}",
                )
            commits.append(
                DispatchPhaseCommit(
                    phase_id=phase.phase_id,
                    role=phase.role,
                    agent_id=assignment.agent_id,
                    assignment=assignment.assignment,
                    lease=assignment.lease,
                    model_selection=routing.selection,
                )
            )
            pending_assignments += (assignment.assignment,)
            pending_leases += (assignment.lease,)

        record = DispatchCommitRecord.create(
            project_id=request.preparation.project_id,
            execution_plan=request.execution_plan,
            preview=preview,
            ready_request_revision=request.ready_request_revision,
            planner_run_record=request.planner_run_record,
            planner_checkpoint=request.planner_checkpoint,
            stage_authorization=request.stage_authorization,
            task=task,
            phases=(commits[0], commits[1], commits[2]),
            committed_at=request.committed_at,
        )
        # Cheap fail-fast recheck before entering the authority transaction. Production
        # authorities must repeat this durable handoff check inside their commit fence.
        self._validate_planner_handoff(request)
        return self._authority.commit_if_current(
            record,
            expected_snapshot_sha256=snapshot.snapshot_sha256,
        )

    def _validate_planner_handoff(self, request: CommitDispatchRequest) -> None:
        revision = request.ready_request_revision
        run = request.planner_run_record
        checkpoint = request.planner_checkpoint
        revision.validate_integrity()
        run.validate_integrity()
        checkpoint.validate_integrity()
        if revision.request.status is not ProjectRequestStatus.READY_FOR_DELIVERY:
            raise DispatchStageMismatch("dispatch requires a READY_FOR_DELIVERY revision")
        if revision.request != request.project_request:
            raise DispatchStageMismatch("stage chain does not use the exact READY revision")
        if (
            run.outcome is not PlannerRunOutcome.READY_FOR_DELIVERY
            or run.project_id != request.preparation.project_id
            or run.request_id != request.project_request.id
            or run.execution_plan != request.execution_plan
            or run.ready_request_revision != revision
            or run.run_record_sha256 != checkpoint.run_record_sha256
            or run.design_checkpoint_sha256 != checkpoint.design_checkpoint_sha256
            or run.planning_authorization_sha256 != checkpoint.planning_authorization_sha256
            or run.input_request_revision_sha256 != checkpoint.input_request_revision_sha256
            or checkpoint.run_id != run.run_id
            or checkpoint.project_id != request.preparation.project_id
            or checkpoint.request_id != request.project_request.id
            or checkpoint.execution_plan_id != request.execution_plan.id
            or checkpoint.execution_plan_sha256 != request.execution_plan.execution_plan_sha256
            or checkpoint.ready_request_revision != revision.revision
            or checkpoint.ready_request_revision_sha256 != revision.request_revision_sha256
        ):
            raise DispatchStageMismatch("Planner run/checkpoint lineage does not match dispatch")
        current = self._request_revisions.current_request_revision(request.project_request.id)
        durable_run = self._planner_records.get_run(run.run_id)
        durable_checkpoint = self._planner_records.get_checkpoint(checkpoint.run_id)
        durable_plan = self._planner_records.get_execution_plan(request.execution_plan.id)
        if (
            current != revision
            or durable_run != run
            or durable_checkpoint != checkpoint
            or durable_plan != request.execution_plan
        ):
            raise DispatchPreviewStale(
                "READY revision or complete Planner handoff is no longer authoritative"
            )

    @staticmethod
    def _validate_stage(request: CommitDispatchRequest) -> None:
        authorization = request.stage_authorization
        authorization.validate_integrity()
        if authorization.authorized_at > request.committed_at:
            raise DispatchStageMismatch("stage authorization cannot be from the future")
        expected = ProjectStageAdvancer().advance_stage(
            StageAdvanceRequest(
                target=ProjectStage.DELIVERY_DISPATCH,
                preparation=request.preparation,
                project_request=request.project_request,
                product_spec=request.product_spec,
                product_approval=request.product_approval,
                technical_design=request.technical_design,
                execution_plan=request.execution_plan,
            ),
            authorized_at=authorization.authorized_at,
        )
        if authorization != expected:
            raise DispatchStageMismatch("stage authorization does not match the exact chain")

    @staticmethod
    def _derive_task(request: CommitDispatchRequest) -> Task:
        return derive_delivery_task(
            request.preparation,
            request.project_request,
            request.product_spec,
            request.product_approval,
            request.technical_design,
            request.execution_plan,
            task_id=request.task_id,
            repository=request.repository,
            base_ref=request.base_ref,
            max_attempts=request.max_attempts,
            created_at=request.task_created_at,
            constraints=request.constraints,
            owner=request.owner,
            labels=request.labels,
        )

    @staticmethod
    def _validate_preview(
        request: CommitDispatchRequest,
        task: Task,
        snapshot: DispatchWorkforceSnapshot,
    ) -> None:
        preview = request.planning_preview
        preview.validate_integrity()
        if request.committed_at < preview.previewed_at:
            raise DispatchPreviewStale("commit time precedes preview time")
        if request.committed_at >= preview.valid_until:
            raise DispatchPreviewStale("planning preview expired")
        if (
            preview.project_id != request.preparation.project_id
            or preview.task_id != task.id
            or preview.execution_plan_id != request.execution_plan.id
            or preview.execution_plan_sha256 != request.execution_plan.execution_plan_sha256
            or preview.task_sha256 != delivery_task_digest(task)
        ):
            raise DispatchPreviewStale("planning preview stage or Task lineage changed")
        for planned, phase in zip(
            request.execution_plan.phases,
            preview.phases,
            strict=True,
        ):
            if (
                phase.phase_id != planned.id
                or phase.role is not planned.role
                or phase.demand.role is not planned.role
                or phase.demand.risk is not planned.risk
                or phase.demand.required_capabilities != planned.required_capabilities
                or phase.demand.touches_critical_paths is not planned.critical_path
            ):
                raise DispatchPreviewStale(
                    f"planning preview demand changed for phase {planned.id}"
                )
        if tuple(phase.demand for phase in preview.phases) != derive_phase_demands(
            task, request.execution_plan
        ):
            raise DispatchPreviewStale("planning preview demand is not deterministically derived")
        if snapshot.work_item.status is not WorkItemStatus.READY:
            raise DispatchPreviewStale("current WorkItem is not READY")
        if (
            snapshot.work_item.task_id != task.id
            or snapshot.work_item.project_id != request.preparation.project_id
            or preview.work_item_sha256 != work_item_digest(snapshot.work_item)
        ):
            raise DispatchPreviewStale("current WorkItem changed")
        current_digest = workforce_snapshot_digest(
            work_item=snapshot.work_item,
            agents=snapshot.agents,
            active_leases=snapshot.active_leases,
            assignments=snapshot.assignments,
            policies=snapshot.model_policies,
            phase_demands=tuple(phase.demand for phase in preview.phases),
        )
        if current_digest != preview.workforce_snapshot_sha256:
            raise DispatchPreviewStale("current workforce or ModelPolicy facts changed")

    @staticmethod
    def _require_assignment(preview: AssignmentDecision, current: AssignmentDecision) -> None:
        if current.status is not AssignmentDecisionStatus.ASSIGNED:
            reasons = "; ".join(reason.message for reason in current.reasons)
            raise DispatchRejected(current.role, reasons or "no Agent assignment")
        if preview.agent_id != current.agent_id:
            raise DispatchDecisionDrift(
                f"{current.role.value} Agent changed from {preview.agent_id} to {current.agent_id}"
            )

    @staticmethod
    def _require_model_route(
        preview: ModelRoutingDecision,
        current: ModelRoutingDecision,
    ) -> None:
        if current.status is not ModelRoutingDecisionStatus.SELECTED:
            reason = current.refusal.message if current.refusal is not None else "no model route"
            raise DispatchRejected(current.role, reason)
        if preview.selection is None or current.selection is None:
            raise DispatchDecisionDrift(f"{current.role.value} preview lacks a model selection")
        preview_semantics = (
            preview.selection.policy_id,
            preview.selection.policy_version,
            preview.selection.provider,
            preview.selection.model,
            preview.selection.tier,
        )
        current_semantics = (
            current.selection.policy_id,
            current.selection.policy_version,
            current.selection.provider,
            current.selection.model,
            current.selection.tier,
        )
        if preview_semantics != current_semantics:
            raise DispatchDecisionDrift(f"{current.role.value} model selection changed")


class FileDispatchCommitStore:
    """Filesystem append-only store with exact replay and fail-closed reads."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise DispatchCommitPathError("dispatch store root must be absolute")
        self._root = root
        self._ensure_root()

    def commit(self, record: DispatchCommitRecord) -> DispatchCommitRecord:
        record.validate_integrity()
        target_name = f"{record.id}.json"
        payload = _envelope_bytes(record)
        directory_fd = self._open_root()
        temporary_name = f".{record.id}.{secrets.token_hex(12)}.tmp"
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written == 0:
                        raise OSError("dispatch commit write made no progress")
                    offset += written
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            try:
                os.link(
                    temporary_name,
                    target_name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                os.fsync(directory_fd)
            except FileExistsError:
                existing = self._read_name(target_name, directory_fd)
                if existing != record:
                    raise DispatchCommitConflict(
                        f"dispatch commit {record.id} already has different content"
                    ) from None
                return existing
            return record
        except DispatchStoreError:
            raise
        except OSError as error:
            raise DispatchCommitPathError(f"cannot publish dispatch commit: {error}") from error
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_fd)
            os.close(directory_fd)

    def get(self, commit_id: DispatchCommitId) -> DispatchCommitRecord:
        if re.fullmatch(r"dispatch_commit_[a-f0-9]{64}", commit_id) is None:
            raise DispatchCommitPathError("invalid dispatch commit ID")
        directory_fd = self._open_root()
        try:
            return self._read_name(f"{commit_id}.json", directory_fd)
        finally:
            os.close(directory_fd)

    def _ensure_root(self) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            metadata = self._root.lstat()
        except OSError as error:
            raise DispatchCommitPathError(f"cannot prepare dispatch store root: {error}") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise DispatchCommitPathError("dispatch store root must be a real directory")

    def _open_root(self) -> int:
        try:
            descriptor = os.open(
                self._root,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as error:
            raise DispatchCommitPathError(f"cannot open dispatch store root: {error}") from error
        metadata = os.fstat(descriptor)
        try:
            current = self._root.lstat()
        except OSError as error:
            os.close(descriptor)
            raise DispatchCommitPathError(f"cannot verify dispatch store root: {error}") from error
        if stat.S_ISLNK(current.st_mode) or (metadata.st_dev, metadata.st_ino) != (
            current.st_dev,
            current.st_ino,
        ):
            os.close(descriptor)
            raise DispatchCommitPathError("dispatch store root changed during access")
        return descriptor

    @staticmethod
    def _read_name(name: str, directory_fd: int) -> DispatchCommitRecord:
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
        except FileNotFoundError as error:
            raise DispatchCommitNotFound(f"dispatch commit {name} was not found") from error
        except OSError as error:
            raise DispatchCommitPathError(f"cannot open dispatch commit: {error}") from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise DispatchCommitPathError("dispatch commit must be a single-link regular file")
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 64 * 1024):
                chunks.append(chunk)
            raw = b"".join(chunks)
        finally:
            os.close(descriptor)
        record = _decode_envelope(raw)
        if name != f"{record.id}.json":
            raise DispatchCommitCorruption("dispatch filename does not match record identity")
        return record


def _record_digest(record: DispatchCommitRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"dispatch_sha256"}, exclude_none=True)
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _authority_snapshot_digest(snapshot: DispatchWorkforceSnapshot) -> str:
    payload = snapshot.model_dump(
        mode="json",
        exclude={"snapshot_sha256"},
        exclude_none=True,
    )
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _envelope_bytes(record: DispatchCommitRecord) -> bytes:
    record_payload = record.to_wire()
    envelope_sha256 = hashlib.sha256(_canonical_json(record_payload).encode()).hexdigest()
    return (
        _canonical_json({"envelope_sha256": envelope_sha256, "record": record_payload}) + "\n"
    ).encode()


def _decode_envelope(raw: bytes) -> DispatchCommitRecord:
    try:
        decoded = json.loads(raw)
        if not isinstance(decoded, dict) or set(decoded) != {"envelope_sha256", "record"}:
            raise ValueError("invalid envelope shape")
        record_payload = decoded["record"]
        if not isinstance(record_payload, dict):
            raise ValueError("record must be an object")
        expected = hashlib.sha256(_canonical_json(record_payload).encode()).hexdigest()
        if decoded["envelope_sha256"] != expected:
            raise ValueError("envelope digest does not match")
        record = DispatchCommitRecord.model_validate(record_payload)
        record.validate_integrity()
        return record
    except (DispatchCommitCorruption, ValueError, TypeError, json.JSONDecodeError) as error:
        raise DispatchCommitCorruption(f"invalid dispatch commit: {error}") from error


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _require_unique(values: Iterable[object], label: str) -> None:
    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{label} must be unique")


__all__ = [
    "CommitDispatchRequest",
    "DispatchAuthority",
    "DispatchAuthorityConflict",
    "DispatchCommitConflict",
    "DispatchCommitCorruption",
    "DispatchCommitNotFound",
    "DispatchCommitPathError",
    "DispatchCommitRecord",
    "DispatchCommitStore",
    "DispatchDecisionDrift",
    "DispatchError",
    "DispatchPhaseCommit",
    "DispatchPlannerRecordReader",
    "DispatchPreviewStale",
    "DispatchRejected",
    "DispatchRequestRevisionReader",
    "DispatchStageMismatch",
    "DispatchStoreError",
    "DispatchWorkforceSnapshot",
    "FileDispatchCommitStore",
    "ProjectManagerDispatchService",
]
