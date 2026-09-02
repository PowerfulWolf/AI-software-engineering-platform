"""Planner stage service with journal-first crash recovery."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import AwareDatetime, Field

from ai_software_engineer.design.models import DesignCommitCheckpoint
from ai_software_engineer.design.store import DesignRecordStore
from ai_software_engineer.domain.enums import ProjectRequestStatus
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import (
    ExecutionPlan,
    ProductSpec,
    ProductSpecApproval,
    ProjectRequest,
    StageSha256,
    TechnicalDesign,
    validate_execution_plan,
)
from ai_software_engineer.planning.agents import (
    PlannerAgentAdapter,
    PlannerAgentError,
    PlannerAgentRequest,
    PlannerAgentRunStatus,
    validate_planner_result,
)
from ai_software_engineer.planning.context import PlannerContextBuilder
from ai_software_engineer.planning.models import (
    PlannerCommitCheckpoint,
    PlannerRunOutcome,
    PlannerRunRecord,
)
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.product.store import ProductRecordLineageError
from ai_software_engineer.project_manager.stages import StageAdvanceAuthorization


class PlanningStageError(RuntimeError):
    """Base error for Planner production and immutable stage publication."""


class PlanningStagePersistenceError(PlanningStageError):
    """Raised when a write port does not return the exact immutable record."""


class PlanningStageStaleRequest(PlanningStageError):
    """Raised when command input is no longer the current request revision."""


class PlanningStageRunConflict(PlanningStageError):
    """Raised when a Planner run ID is replayed with changed input."""


class PlanningStageAgentFailed(PlanningStageError):
    """Raised after a typed failed Planner outcome has been durably journaled."""


class ExecutionPlanRecordPort(Protocol):
    """Minimal append-only plan port held by the Planner stage service."""

    def put_execution_plan(self, plan: ExecutionPlan) -> ExecutionPlan: ...

    def find_for_request(self, request_id: str) -> ExecutionPlan | None: ...

    def put_run(self, record: PlannerRunRecord) -> PlannerRunRecord: ...

    def find_run(self, run_id: RunId | str) -> PlannerRunRecord | None: ...

    def put_checkpoint(self, checkpoint: PlannerCommitCheckpoint) -> PlannerCommitCheckpoint: ...

    def find_checkpoint(self, run_id: RunId | str) -> PlannerCommitCheckpoint | None: ...


class ProjectRequestRevisionPort(Protocol):
    """Minimal append-only request revision port; implementations must not overwrite."""

    def compare_and_put_request_revision(
        self,
        revision: ProjectRequestRevision,
        *,
        expected_current_sha256: StageSha256 | None,
    ) -> ProjectRequestRevision: ...

    def get_request_revision(self, request_id: str, revision: int) -> ProjectRequestRevision: ...

    def current_request_revision(self, request_id: str) -> ProjectRequestRevision: ...


class ProduceExecutionPlanCommand(DomainModel):
    """Exact, replay-safe Planner production command."""

    run_id: RunId
    current_request_revision: ProjectRequestRevision
    product_spec: ProductSpec
    product_approval: ProductSpecApproval
    technical_design: TechnicalDesign
    design_checkpoint: DesignCommitCheckpoint
    planning_authorization: StageAdvanceAuthorization
    expected_execution_plan_version: int = Field(ge=1)
    transitioned_at: AwareDatetime


class PlanningStageResult(DomainModel):
    """Published abstract plan and the immutable READY_FOR_DELIVERY request revision."""

    execution_plan: ExecutionPlan
    ready_request_revision: ProjectRequestRevision
    run_record: PlannerRunRecord
    checkpoint: PlannerCommitCheckpoint
    replayed: bool = False

    @property
    def ready_request(self) -> ProjectRequest:
        return self.ready_request_revision.request


class PlannerStageService:
    """Produce an ExecutionPlan, then append the next ProjectRequest stage revision."""

    def __init__(
        self,
        *,
        context_builder: PlannerContextBuilder,
        adapter: PlannerAgentAdapter,
        execution_plans: ExecutionPlanRecordPort,
        request_revisions: ProjectRequestRevisionPort,
        design_records: DesignRecordStore,
    ) -> None:
        self._context_builder = context_builder
        self._adapter = adapter
        self._execution_plans = execution_plans
        self._request_revisions = request_revisions
        self._design_records = design_records

    def produce(self, command: ProduceExecutionPlanCommand) -> PlanningStageResult:
        """Journal one accepted Agent result before materializing its effects."""
        input_sha256 = _command_digest(command)
        prior = self._execution_plans.find_run(command.run_id)
        if prior is not None:
            if prior.input_sha256 != input_sha256:
                raise PlanningStageRunConflict(
                    f"Planner run ID already used with changed input: {command.run_id}"
                )
            return self._replay(prior)
        self._require_current_input(command)
        current_revision = command.current_request_revision
        current_request = current_revision.request
        context = self._context_builder.build(
            project_request_revision=current_revision,
            product_spec=command.product_spec,
            product_approval=command.product_approval,
            technical_design=command.technical_design,
            design_checkpoint=command.design_checkpoint,
            planning_authorization=command.planning_authorization,
            expected_execution_plan_version=command.expected_execution_plan_version,
            built_at=command.transitioned_at,
        )
        request = PlannerAgentRequest(
            run_id=command.run_id,
            project_id=current_request.project_id,
            request_id=current_request.id,
            context=context,
        )
        try:
            result = self._adapter.run(request)
        except Exception as error:
            raise PlanningStageError(
                "PlannerAgentAdapter raised instead of returning typed failure"
            ) from error
        # Agent execution is an untrusted time window. Reopen authoritative facts
        # before the first durable effect, including a failure receipt.
        self._require_current_input(command)
        if result.status is not PlannerAgentRunStatus.SUCCEEDED:
            if result.error is None:
                raise PlanningStageError("failed Planner result has no typed error")
            failed = PlannerRunRecord.create(
                run_id=command.run_id,
                project_id=current_request.project_id,
                request_id=current_request.id,
                context_id=context.context_id,
                input_sha256=input_sha256,
                input_request_revision_sha256=current_revision.request_revision_sha256,
                design_checkpoint_sha256=command.design_checkpoint.checkpoint_sha256,
                planning_authorization_sha256=command.planning_authorization.authorization_sha256,
                outcome=(
                    PlannerRunOutcome.TIMED_OUT
                    if result.status is PlannerAgentRunStatus.TIMED_OUT
                    else PlannerRunOutcome.FAILED
                ),
                error_code=result.error.code,
                error_message=result.error.message,
                recorded_at=command.transitioned_at,
            )
            self._execution_plans.put_run(failed)
            raise PlanningStageAgentFailed(
                f"Planner Agent did not produce an ExecutionPlan: {result.error.code.value}"
            )
        try:
            plan = validate_planner_result(request, result)
            validate_execution_plan(command.product_spec, command.technical_design, plan)
        except (PlannerAgentError, RuntimeError, ValueError) as error:
            raise PlanningStageError("Planner Agent output is invalid") from error
        ready_revision = ProjectRequestRevision.create(
            _ready_request(current_request, transitioned_at=command.transitioned_at),
            revision=current_revision.revision + 1,
            supersedes_sha256=current_revision.request_revision_sha256,
            recorded_at=command.transitioned_at,
        )
        self._require_current_input(command)
        receipt = PlannerRunRecord.create(
            run_id=command.run_id,
            project_id=current_request.project_id,
            request_id=current_request.id,
            context_id=context.context_id,
            input_sha256=input_sha256,
            input_request_revision_sha256=current_revision.request_revision_sha256,
            design_checkpoint_sha256=command.design_checkpoint.checkpoint_sha256,
            planning_authorization_sha256=command.planning_authorization.authorization_sha256,
            outcome=PlannerRunOutcome.READY_FOR_DELIVERY,
            execution_plan=plan,
            ready_request_revision=ready_revision,
            recorded_at=command.transitioned_at,
        )
        receipt = self._execution_plans.put_run(receipt)
        return self._materialize_success(receipt, replayed=False)

    def _require_current_input(self, command: ProduceExecutionPlanCommand) -> None:
        current = self._request_revisions.current_request_revision(
            command.current_request_revision.request.id
        )
        if current != command.current_request_revision:
            raise PlanningStageStaleRequest(
                "Planner input is not the current ProjectRequest revision"
            )
        if current.request.status is not ProjectRequestStatus.PLANNING:
            raise PlanningStageError("Planner requires current ProjectRequest status PLANNING")
        durable_checkpoint = self._design_records.get_checkpoint(command.design_checkpoint.run_id)
        durable_run = self._design_records.get_run(command.design_checkpoint.run_id)
        if (
            durable_checkpoint != command.design_checkpoint
            or durable_run.run_record_sha256 != command.design_checkpoint.run_record_sha256
            or durable_run.technical_design != command.technical_design
            or durable_run.next_request_revision != command.current_request_revision
            or durable_run.planning_authorization != command.planning_authorization
        ):
            raise PlanningStageStaleRequest(
                "Planner design, revision, or authorization is not the committed handoff"
            )

    def _replay(self, receipt: PlannerRunRecord) -> PlanningStageResult:
        if receipt.outcome is not PlannerRunOutcome.READY_FOR_DELIVERY:
            code = receipt.error_code.value if receipt.error_code is not None else "UNKNOWN"
            raise PlanningStageAgentFailed(f"Planner run already failed: {code}")
        checkpoint = self._execution_plans.find_checkpoint(receipt.run_id)
        if checkpoint is not None:
            expected = PlannerCommitCheckpoint.create(receipt, committed_at=receipt.recorded_at)
            if checkpoint != expected:
                raise PlanningStagePersistenceError(
                    "Planner checkpoint does not match exact run receipt"
                )
            current = self._request_revisions.current_request_revision(receipt.request_id)
            if current != receipt.ready_request_revision:
                raise PlanningStageStaleRequest(
                    "completed Planner checkpoint is not the current READY revision"
                )
            return self._result(receipt, checkpoint, replayed=True)
        return self._materialize_success(receipt, replayed=True)

    def _materialize_success(
        self, receipt: PlannerRunRecord, *, replayed: bool
    ) -> PlanningStageResult:
        plan = receipt.execution_plan
        revision = receipt.ready_request_revision
        assert plan is not None and revision is not None
        self._require_exact_recovery_predecessor(receipt)
        try:
            persisted_revision = self._request_revisions.compare_and_put_request_revision(
                revision,
                expected_current_sha256=receipt.input_request_revision_sha256,
            )
        except ProductRecordLineageError as error:
            raise PlanningStageStaleRequest(
                "Planner recovery predecessor changed before READY append"
            ) from error
        if persisted_revision != revision:
            raise PlanningStagePersistenceError(
                "request revision port did not return the exact READY revision"
            )
        persisted_plan = self._execution_plans.put_execution_plan(plan)
        if persisted_plan != plan:
            raise PlanningStagePersistenceError(
                "ExecutionPlan port did not return the exact immutable plan"
            )
        if self._request_revisions.current_request_revision(receipt.request_id) != revision:
            raise PlanningStageStaleRequest(
                "READY revision is no longer the exact current Planner output"
            )
        checkpoint = PlannerCommitCheckpoint.create(receipt, committed_at=receipt.recorded_at)
        checkpoint = self._execution_plans.put_checkpoint(checkpoint)
        if (
            self._execution_plans.find_for_request(receipt.request_id) != plan
            or self._execution_plans.find_checkpoint(receipt.run_id) != checkpoint
        ):
            raise PlanningStagePersistenceError("Planner completion exact read-back failed")
        return self._result(receipt, checkpoint, replayed=replayed)

    def _require_exact_recovery_predecessor(self, receipt: PlannerRunRecord) -> None:
        ready = receipt.ready_request_revision
        assert ready is not None
        current = self._request_revisions.current_request_revision(receipt.request_id)
        if current == ready:
            predecessor = self._request_revisions.get_request_revision(
                receipt.request_id, ready.revision - 1
            )
            if predecessor.request_revision_sha256 == receipt.input_request_revision_sha256:
                return
        if current.request_revision_sha256 == receipt.input_request_revision_sha256:
            return
        raise PlanningStageStaleRequest(
            "Planner replay requires the exact predecessor or exact READY revision"
        )

    @staticmethod
    def _result(
        receipt: PlannerRunRecord,
        checkpoint: PlannerCommitCheckpoint,
        *,
        replayed: bool,
    ) -> PlanningStageResult:
        plan = receipt.execution_plan
        revision = receipt.ready_request_revision
        assert plan is not None and revision is not None
        return PlanningStageResult(
            execution_plan=plan,
            ready_request_revision=revision,
            run_record=receipt,
            checkpoint=checkpoint,
            replayed=replayed,
        )


def _ready_request(request: ProjectRequest, *, transitioned_at: AwareDatetime) -> ProjectRequest:
    return ProjectRequest.create(
        request_id=request.id,
        project_id=request.project_id,
        preparation_sha256=request.preparation_sha256,
        title=request.title,
        original_request=request.original_request,
        status=ProjectRequestStatus.READY_FOR_DELIVERY,
        created_at=request.created_at,
        updated_at=transitioned_at,
    )


def _command_digest(command: ProduceExecutionPlanCommand) -> StageSha256:
    encoded = json.dumps(
        command.to_wire(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ExecutionPlanRecordPort",
    "PlannerStageService",
    "PlanningStageAgentFailed",
    "PlanningStageError",
    "PlanningStagePersistenceError",
    "PlanningStageResult",
    "PlanningStageRunConflict",
    "PlanningStageStaleRequest",
    "ProduceExecutionPlanCommand",
    "ProjectRequestRevisionPort",
]
