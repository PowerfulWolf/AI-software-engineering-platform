"""Immutable Designer run receipts used for exact restart replay."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, model_validator

from ai_software_engineer.domain import ProjectRequestStatus, TechnicalDesign
from ai_software_engineer.domain.identity import ContextId, ProjectId, RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import (
    ProjectRequestId,
    StageSha256,
    TechnicalDesignId,
)
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.project_manager.stages import ProjectStage, StageAdvanceAuthorization


class DesignRecordError(RuntimeError):
    """Base error for durable Designer records."""


class DesignRecordIntegrityError(DesignRecordError):
    """Raised when a Designer record no longer matches its digest or nested facts."""


class DesignerAgentErrorCode(StrEnum):
    TIMEOUT = "TIMEOUT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class DesignRunOutcome(StrEnum):
    READY_FOR_PLANNING = "READY_FOR_PLANNING"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class DesignRunRecord(DomainModel):
    """First durable receipt for one validated Designer invocation."""

    kind: Literal["design_run_record"] = "design_run_record"
    schema_version: Literal["v0.1"] = "v0.1"
    run_id: RunId
    project_id: ProjectId
    request_id: ProjectRequestId
    context_id: ContextId
    input_sha256: StageSha256
    input_request_revision_sha256: StageSha256
    outcome: DesignRunOutcome
    technical_design: TechnicalDesign | None = None
    next_request_revision: ProjectRequestRevision | None = None
    planning_authorization: StageAdvanceAuthorization | None = None
    error_code: DesignerAgentErrorCode | None = None
    error_message: NonEmptyStr | None = None
    recorded_at: AwareDatetime
    run_record_sha256: StageSha256

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        success = self.outcome is DesignRunOutcome.READY_FOR_PLANNING
        outputs = (
            self.technical_design,
            self.next_request_revision,
            self.planning_authorization,
        )
        if success:
            if any(value is None for value in outputs) or any(
                value is not None for value in (self.error_code, self.error_message)
            ):
                raise ValueError("successful DesignRunRecord requires only all output facts")
            self._validate_success()
        elif any(value is not None for value in outputs) or any(
            value is None for value in (self.error_code, self.error_message)
        ):
            raise ValueError("failed DesignRunRecord requires only error facts")
        if (self.outcome is DesignRunOutcome.TIMED_OUT) != (
            self.error_code is DesignerAgentErrorCode.TIMEOUT
        ):
            raise ValueError("TIMEOUT error and TIMED_OUT outcome must appear together")
        return self

    def _validate_success(self) -> None:
        design = self.technical_design
        revision = self.next_request_revision
        authorization = self.planning_authorization
        assert design is not None and revision is not None and authorization is not None
        design.validate_integrity()
        revision.validate_integrity()
        authorization.validate_integrity()
        if (
            design.project_id != self.project_id
            or design.request_id != self.request_id
            or revision.request.id != self.request_id
            or revision.request.project_id != self.project_id
            or revision.request.status is not ProjectRequestStatus.PLANNING
            or revision.supersedes_sha256 != self.input_request_revision_sha256
            or authorization.target is not ProjectStage.PLANNING
            or authorization.project_id != self.project_id
            or authorization.input_sha256s[1] != revision.request.request_sha256
            or authorization.input_sha256s[-1] != design.technical_design_sha256
        ):
            raise ValueError("Designer success facts do not form one exact planning handoff")

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
        outcome: DesignRunOutcome,
        recorded_at: datetime,
        technical_design: TechnicalDesign | None = None,
        next_request_revision: ProjectRequestRevision | None = None,
        planning_authorization: StageAdvanceAuthorization | None = None,
        error_code: DesignerAgentErrorCode | None = None,
        error_message: str | None = None,
    ) -> DesignRunRecord:
        provisional = cls(
            run_id=run_id,
            project_id=project_id,
            request_id=request_id,
            context_id=context_id,
            input_sha256=input_sha256,
            input_request_revision_sha256=input_request_revision_sha256,
            outcome=outcome,
            technical_design=technical_design,
            next_request_revision=next_request_revision,
            planning_authorization=planning_authorization,
            error_code=error_code,
            error_message=error_message,
            recorded_at=recorded_at,
            run_record_sha256="0" * 64,
        )
        return provisional.model_copy(update={"run_record_sha256": _digest(provisional)})

    def validate_integrity(self) -> None:
        try:
            if self.outcome is DesignRunOutcome.READY_FOR_PLANNING:
                self._validate_success()
        except (RuntimeError, ValueError) as error:
            raise DesignRecordIntegrityError("DesignRunRecord nested facts are invalid") from error
        if self.run_record_sha256 != _digest(self):
            raise DesignRecordIntegrityError("DesignRunRecord digest does not match content")


class DesignCommitCheckpoint(DomainModel):
    """Commit point published only after design and request revision read back exactly."""

    kind: Literal["design_commit_checkpoint"] = "design_commit_checkpoint"
    schema_version: Literal["v0.1"] = "v0.1"
    run_id: RunId
    project_id: ProjectId
    request_id: ProjectRequestId
    run_record_sha256: StageSha256
    technical_design_id: TechnicalDesignId
    technical_design_sha256: StageSha256
    input_request_revision_sha256: StageSha256
    request_revision: int
    request_revision_sha256: StageSha256
    planning_authorization_sha256: StageSha256
    committed_at: AwareDatetime
    checkpoint_sha256: StageSha256

    @classmethod
    def create(
        cls,
        record: DesignRunRecord,
        *,
        committed_at: datetime,
    ) -> DesignCommitCheckpoint:
        if record.outcome is not DesignRunOutcome.READY_FOR_PLANNING:
            raise ValueError("only a successful Designer run can be committed")
        record.validate_integrity()
        design = record.technical_design
        revision = record.next_request_revision
        authorization = record.planning_authorization
        assert design is not None and revision is not None and authorization is not None
        provisional = cls(
            run_id=record.run_id,
            project_id=record.project_id,
            request_id=record.request_id,
            run_record_sha256=record.run_record_sha256,
            technical_design_id=design.id,
            technical_design_sha256=design.technical_design_sha256,
            input_request_revision_sha256=record.input_request_revision_sha256,
            request_revision=revision.revision,
            request_revision_sha256=revision.request_revision_sha256,
            planning_authorization_sha256=authorization.authorization_sha256,
            committed_at=committed_at,
            checkpoint_sha256="0" * 64,
        )
        return provisional.model_copy(update={"checkpoint_sha256": _checkpoint_digest(provisional)})

    def validate_integrity(self) -> None:
        if self.checkpoint_sha256 != _checkpoint_digest(self):
            raise DesignRecordIntegrityError("DesignCommitCheckpoint digest does not match content")


def _digest(record: DesignRunRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"run_record_sha256"}, exclude_none=True)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _checkpoint_digest(checkpoint: DesignCommitCheckpoint) -> str:
    payload = checkpoint.model_dump(mode="json", exclude={"checkpoint_sha256"})
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DesignCommitCheckpoint",
    "DesignRecordError",
    "DesignRecordIntegrityError",
    "DesignRunOutcome",
    "DesignRunRecord",
    "DesignerAgentErrorCode",
]
