"""Designer application service with journal-first recovery and commit checkpoint."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, Protocol, Self

from pydantic import model_validator

from ai_software_engineer.design.agents import (
    DesignerAgentAdapter,
    DesignerAgentRequest,
    DesignerAgentResult,
    DesignerAgentRunStatus,
)
from ai_software_engineer.design.context import DesignContextBuilder
from ai_software_engineer.design.models import (
    DesignCommitCheckpoint,
    DesignRunOutcome,
    DesignRunRecord,
)
from ai_software_engineer.design.store import DesignRecordStore
from ai_software_engineer.domain import (
    ProductSpec,
    ProductSpecApproval,
    ProjectPreparation,
    ProjectRequest,
    ProjectRequestStatus,
    TechnicalDesign,
    validate_technical_design,
)
from ai_software_engineer.domain.agent import TimeoutSeconds
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.product.store import ProductRecordLineageError, ProductRecordStore
from ai_software_engineer.project_manager.baseline import ProjectSpecBaseline
from ai_software_engineer.project_manager.stages import (
    ProjectStage,
    ProjectStageError,
    StageAdvanceAuthorization,
    StageAdvanceRequest,
)
from ai_software_engineer.project_profile import ProjectProfile


class DesignerServiceError(RuntimeError):
    """Base error for Designer application execution."""


class DesignerRunConflict(DesignerServiceError):
    """Raised when a run ID is replayed with changed exact input."""


class DesignerInputStale(DesignerServiceError):
    """Raised when Product facts no longer equal the supplied approved checkpoint."""


class DesignerOutputRejected(DesignerServiceError):
    """Raised when adapter identity, lineage, or coverage is invalid."""


class DesignerExecutionError(DesignerServiceError):
    """Raised when an adapter or Project Manager port violates its typed contract."""


class ProjectStageAdvancePort(Protocol):
    """Project Manager Skill port; it reopens current facts outside the Agent."""

    def advance_stage(self, request: StageAdvanceRequest) -> StageAdvanceAuthorization: ...


class RunDesignerCommand(DomainModel):
    """Complete Task-free design command; no hidden Product or project state."""

    kind: Literal["run_designer_command"] = "run_designer_command"
    schema_version: Literal["v0.1"] = "v0.1"
    run_id: RunId
    preparation: ProjectPreparation
    project_profile: ProjectProfile
    project_baseline: ProjectSpecBaseline
    request_revision: ProjectRequestRevision
    product_spec: ProductSpec
    product_approval: ProductSpecApproval
    solution_design_authorization: StageAdvanceAuthorization
    submitted_at: datetime
    timeout_seconds: TimeoutSeconds = 600

    @model_validator(mode="after")
    def require_aware_submission(self) -> Self:
        if self.submitted_at.tzinfo is None or self.submitted_at.utcoffset() is None:
            raise ValueError("submitted_at must be timezone-aware")
        return self


class DesignerServiceResult(DomainModel):
    """Replayable outcome; checkpoint exists only for a complete planning handoff."""

    kind: Literal["designer_service_result"] = "designer_service_result"
    schema_version: Literal["v0.1"] = "v0.1"
    run_record: DesignRunRecord
    replayed: bool = False
    checkpoint: DesignCommitCheckpoint | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        self.run_record.validate_integrity()
        success = self.run_record.outcome is DesignRunOutcome.READY_FOR_PLANNING
        if success != (self.checkpoint is not None):
            raise ValueError("only a completed Designer handoff has a commit checkpoint")
        if self.checkpoint is not None:
            self.checkpoint.validate_integrity()
            if (
                self.checkpoint.run_id != self.run_record.run_id
                or self.checkpoint.run_record_sha256 != self.run_record.run_record_sha256
            ):
                raise ValueError("Designer checkpoint does not bind the exact run receipt")
        return self

    @property
    def technical_design(self) -> TechnicalDesign | None:
        return self.run_record.technical_design

    @property
    def request_revision(self) -> ProjectRequestRevision | None:
        return self.run_record.next_request_revision

    @property
    def planning_authorization(self) -> StageAdvanceAuthorization | None:
        return self.run_record.planning_authorization


class DesignerService:
    """Validate Designer output, advance request to PLANNING, and commit atomically by marker."""

    def __init__(
        self,
        *,
        design_store: DesignRecordStore,
        product_store: ProductRecordStore,
        adapter: DesignerAgentAdapter,
        stage_advancer: ProjectStageAdvancePort,
        context_builder: DesignContextBuilder | None = None,
    ) -> None:
        self._design_store = design_store
        self._product_store = product_store
        self._adapter = adapter
        self._stage_advancer = stage_advancer
        self._context_builder = context_builder or DesignContextBuilder()

    def run(self, command: RunDesignerCommand) -> DesignerServiceResult:
        input_sha256 = _command_digest(command)
        prior = self._design_store.find_run(command.run_id)
        if prior is not None:
            if prior.input_sha256 != input_sha256:
                raise DesignerRunConflict(
                    f"Designer run ID already used with changed input: {command.run_id}"
                )
            return self._replay(prior)
        self._require_current_product_facts(command)
        context = self._context_builder.build(
            command.preparation,
            command.project_profile,
            command.project_baseline,
            command.request_revision.request,
            command.product_spec,
            command.product_approval,
            command.solution_design_authorization,
            built_at=command.submitted_at,
        )
        request = DesignerAgentRequest(
            run_id=command.run_id,
            project_id=command.preparation.project_id,
            request_id=command.request_revision.request.id,
            context=context,
            permissions=context.permissions,
            timeout_seconds=command.timeout_seconds,
        )
        try:
            result = self._adapter.run(request)
        except Exception as error:
            raise DesignerExecutionError(
                "DesignerAgentAdapter raised instead of returning typed failure"
            ) from error
        self._validate_agent_result(request, result)
        # The model call is an untrusted time window. Reopen every authoritative
        # Product fact before the first durable run receipt is allowed to exist.
        self._require_current_product_facts(command)
        if result.status is not DesignerAgentRunStatus.SUCCEEDED:
            return self._persist_failure(command, input_sha256, context.context_id, result)
        design = result.technical_design
        if design is None:
            raise DesignerOutputRejected("successful Designer result has no TechnicalDesign")
        try:
            validate_technical_design(command.product_spec, command.product_approval, design)
        except (RuntimeError, ValueError) as error:
            raise DesignerOutputRejected(
                "TechnicalDesign lineage or requirement/acceptance coverage is invalid"
            ) from error
        if design.version != 1:
            raise DesignerOutputRejected("v0.1 Designer supports one immutable design version")
        next_request = _request_with_status(
            command.request_revision.request,
            ProjectRequestStatus.PLANNING,
            command.submitted_at,
        )
        next_revision = ProjectRequestRevision.create(
            next_request,
            revision=command.request_revision.revision + 1,
            supersedes_sha256=command.request_revision.request_revision_sha256,
            recorded_at=command.submitted_at,
        )
        planning_authorization = self._authorize_planning(command, next_request, design)
        self._require_current_product_facts(command)
        receipt = DesignRunRecord.create(
            run_id=command.run_id,
            project_id=command.preparation.project_id,
            request_id=command.request_revision.request.id,
            context_id=context.context_id,
            input_sha256=input_sha256,
            input_request_revision_sha256=command.request_revision.request_revision_sha256,
            outcome=DesignRunOutcome.READY_FOR_PLANNING,
            technical_design=design,
            next_request_revision=next_revision,
            planning_authorization=planning_authorization,
            recorded_at=command.submitted_at,
        )
        receipt = self._design_store.put_run(receipt)
        return self._materialize_success(receipt, replayed=False)

    def _require_current_product_facts(self, command: RunDesignerCommand) -> None:
        current = self._product_store.current_request_revision(command.request_revision.request.id)
        stored_spec = self._product_store.find_product_spec(command.product_spec.id)
        stored_approval = self._product_store.find_approval(command.product_approval.id)
        if (
            current != command.request_revision
            or stored_spec != command.product_spec
            or stored_approval != command.product_approval
        ):
            raise DesignerInputStale("Designer input is not the current durable Product checkpoint")

    def _authorize_planning(
        self,
        command: RunDesignerCommand,
        next_request: ProjectRequest,
        design: TechnicalDesign,
    ) -> StageAdvanceAuthorization:
        request = StageAdvanceRequest(
            target=ProjectStage.PLANNING,
            preparation=command.preparation,
            project_request=next_request,
            product_spec=command.product_spec,
            product_approval=command.product_approval,
            technical_design=design,
        )
        try:
            candidate = self._stage_advancer.advance_stage(request)
            authorization = StageAdvanceAuthorization.model_validate(candidate.to_wire())
            authorization.validate_integrity()
        except (AttributeError, ProjectStageError, TypeError, ValueError) as error:
            raise DesignerExecutionError(
                "Project Manager returned invalid planning authorization"
            ) from error
        expected = (
            command.preparation.preparation_sha256,
            next_request.request_sha256,
            command.product_spec.product_spec_sha256,
            command.product_approval.approval_sha256,
            design.technical_design_sha256,
        )
        if (
            authorization.target is not ProjectStage.PLANNING
            or authorization.project_id != command.preparation.project_id
            or authorization.input_sha256s != expected
        ):
            raise DesignerExecutionError(
                "Project Manager planning authorization does not bind exact output"
            )
        return authorization

    def _persist_failure(
        self,
        command: RunDesignerCommand,
        input_sha256: str,
        context_id: str,
        result: DesignerAgentResult,
    ) -> DesignerServiceResult:
        if result.error is None:
            raise DesignerOutputRejected("failed Designer result has no typed error")
        receipt = DesignRunRecord.create(
            run_id=command.run_id,
            project_id=command.preparation.project_id,
            request_id=command.request_revision.request.id,
            context_id=context_id,
            input_sha256=input_sha256,
            input_request_revision_sha256=command.request_revision.request_revision_sha256,
            outcome=(
                DesignRunOutcome.TIMED_OUT
                if result.status is DesignerAgentRunStatus.TIMED_OUT
                else DesignRunOutcome.FAILED
            ),
            error_code=result.error.code,
            error_message=result.error.message,
            recorded_at=command.submitted_at,
        )
        return DesignerServiceResult(run_record=self._design_store.put_run(receipt))

    def _replay(self, receipt: DesignRunRecord) -> DesignerServiceResult:
        if receipt.outcome is DesignRunOutcome.READY_FOR_PLANNING:
            checkpoint = self._design_store.find_checkpoint(receipt.run_id)
            if checkpoint is not None:
                expected = DesignCommitCheckpoint.create(
                    receipt,
                    committed_at=receipt.recorded_at,
                )
                if checkpoint != expected:
                    raise DesignerExecutionError(
                        "Designer checkpoint does not match the exact run receipt"
                    )
                return DesignerServiceResult(
                    run_record=receipt,
                    replayed=True,
                    checkpoint=checkpoint,
                )
            return self._materialize_success(receipt, replayed=True)
        return DesignerServiceResult(run_record=receipt, replayed=True)

    def _materialize_success(
        self, receipt: DesignRunRecord, *, replayed: bool
    ) -> DesignerServiceResult:
        design = receipt.technical_design
        revision = receipt.next_request_revision
        authorization = receipt.planning_authorization
        assert design is not None and revision is not None and authorization is not None
        self._require_exact_recovery_predecessor(receipt)
        try:
            persisted_revision = self._product_store.compare_and_put_request_revision(
                revision,
                expected_current_sha256=receipt.input_request_revision_sha256,
            )
        except ProductRecordLineageError as error:
            raise DesignerInputStale(
                "Designer recovery predecessor changed before revision append"
            ) from error
        persisted_design = self._design_store.put_design(design)
        if persisted_design != design or persisted_revision != revision:
            raise DesignerExecutionError("Designer effects failed exact persistence read-back")
        if self._product_store.current_request_revision(receipt.request_id) != revision:
            raise DesignerInputStale(
                "PLANNING revision is no longer the current exact Designer output"
            )
        checkpoint = DesignCommitCheckpoint.create(receipt, committed_at=receipt.recorded_at)
        checkpoint = self._design_store.put_checkpoint(checkpoint)
        if self._design_store.get_design(design.id) != design:
            raise DesignerExecutionError("TechnicalDesign read-back does not match receipt")
        if (
            self._product_store.get_request_revision(revision.request.id, revision.revision)
            != revision
        ):
            raise DesignerExecutionError("PLANNING ProjectRequestRevision read-back failed")
        if self._design_store.get_checkpoint(receipt.run_id) != checkpoint:
            raise DesignerExecutionError("Designer commit checkpoint read-back failed")
        return DesignerServiceResult(
            run_record=receipt,
            replayed=replayed,
            checkpoint=checkpoint,
        )

    def _require_exact_recovery_predecessor(self, receipt: DesignRunRecord) -> None:
        revision = receipt.next_request_revision
        assert revision is not None
        current = self._product_store.current_request_revision(receipt.request_id)
        if current == revision:
            predecessor = self._product_store.get_request_revision(
                receipt.request_id,
                revision.revision - 1,
            )
            if predecessor.request_revision_sha256 == receipt.input_request_revision_sha256:
                return
        if current.request_revision_sha256 == receipt.input_request_revision_sha256:
            return
        raise DesignerInputStale(
            "Designer replay requires the exact predecessor or exact planned revision"
        )

    def _validate_agent_result(
        self, request: DesignerAgentRequest, result: DesignerAgentResult
    ) -> None:
        try:
            result = DesignerAgentResult.model_validate(result.to_wire())
        except (TypeError, ValueError) as error:
            raise DesignerOutputRejected("Designer adapter returned invalid output") from error
        if (
            result.run_id != request.run_id
            or result.project_id != request.project_id
            or result.request_id != request.request_id
            or result.context_id != request.context.context_id
        ):
            raise DesignerOutputRejected("Designer result identity does not match request")


def _request_with_status(
    current: ProjectRequest, status: ProjectRequestStatus, updated_at: datetime
) -> ProjectRequest:
    return ProjectRequest.create(
        request_id=current.id,
        project_id=current.project_id,
        preparation_sha256=current.preparation_sha256,
        title=current.title,
        original_request=current.original_request,
        status=status,
        created_at=current.created_at,
        updated_at=updated_at,
    )


def _command_digest(command: RunDesignerCommand) -> str:
    encoded = json.dumps(
        command.to_wire(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DesignerExecutionError",
    "DesignerInputStale",
    "DesignerOutputRejected",
    "DesignerRunConflict",
    "DesignerService",
    "DesignerServiceError",
    "DesignerServiceResult",
    "ProjectStageAdvancePort",
    "RunDesignerCommand",
]
