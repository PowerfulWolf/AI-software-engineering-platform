"""Immutable product-discovery records independent of model session memory."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import DomainModel, JsonValue
from ai_software_engineer.domain.project_delivery import (
    ProductApprovalId,
    ProductSpecId,
    ProjectRequest,
    ProjectRequestId,
    StageContractError,
    StageSha256,
)

ProductDialogueId = Annotated[str, StringConstraints(pattern=r"^product_dialogue_[a-f0-9]{64}$")]
ProductOperationId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{2,127}$")]
ProductRecordSequence = Annotated[StrictInt, Field(ge=1)]
DialogueContent = Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
ResultIdentity = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class ProductRecordStoreError(RuntimeError):
    """Base error shared by product records and their durable store."""


class ProductRecordIntegrityError(ProductRecordStoreError):
    """Raised when a typed product record no longer matches its digest."""


class ProductDialogueActor(StrEnum):
    """The only identities allowed to append product discovery dialogue."""

    HUMAN = "HUMAN"
    PRODUCT_AGENT = "PRODUCT_AGENT"


class ProductDiscoveryStatus(StrEnum):
    """Recoverable product-discovery checkpoint states."""

    PRODUCT_DISCOVERY = "PRODUCT_DISCOVERY"
    WAITING_PRODUCT_APPROVAL = "WAITING_PRODUCT_APPROVAL"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"


class ProductOperationKind(StrEnum):
    """Idempotent Product application commands recorded after their effects."""

    START = "START"
    HUMAN_MESSAGE = "HUMAN_MESSAGE"
    PRODUCT_RUN = "PRODUCT_RUN"
    PRODUCT_DECISION = "PRODUCT_DECISION"


class ProductDialogueRecord(DomainModel):
    """One immutable human or Product Agent message in a digest-linked chain."""

    kind: Literal["product_dialogue_record"] = "product_dialogue_record"
    schema_version: Literal["v0.1"] = "v0.1"
    id: ProductDialogueId
    request_id: ProjectRequestId
    project_id: ProjectId
    sequence: ProductRecordSequence
    actor: ProductDialogueActor
    content: DialogueContent
    previous_dialogue_sha256: StageSha256 | None = None
    recorded_at: AwareDatetime
    dialogue_sha256: StageSha256

    @model_validator(mode="after")
    def validate_chain_shape(self) -> Self:
        if self.sequence == 1 and self.previous_dialogue_sha256 is not None:
            raise ValueError("first ProductDialogueRecord cannot have a previous digest")
        if self.sequence > 1 and self.previous_dialogue_sha256 is None:
            raise ValueError("later ProductDialogueRecord requires a previous digest")
        return self

    @classmethod
    def create(
        cls,
        *,
        request_id: ProjectRequestId,
        project_id: ProjectId,
        sequence: int,
        actor: ProductDialogueActor,
        content: str,
        previous_dialogue_sha256: StageSha256 | None,
        recorded_at: datetime,
    ) -> ProductDialogueRecord:
        provisional = cls(
            id=f"product_dialogue_{'0' * 64}",
            request_id=request_id,
            project_id=project_id,
            sequence=sequence,
            actor=actor,
            content=content,
            previous_dialogue_sha256=previous_dialogue_sha256,
            recorded_at=recorded_at,
            dialogue_sha256="0" * 64,
        )
        digest = _record_digest(provisional, "id", "dialogue_sha256")
        return provisional.model_copy(
            update={"id": f"product_dialogue_{digest}", "dialogue_sha256": digest}
        )

    def validate_integrity(self) -> None:
        expected = _record_digest(self, "id", "dialogue_sha256")
        if self.dialogue_sha256 != expected or self.id != f"product_dialogue_{expected}":
            raise ProductRecordIntegrityError(
                f"ProductDialogueRecord identity does not match content: {self.id}"
            )


class ProjectRequestRevision(DomainModel):
    """One append-only ProjectRequest state revision."""

    kind: Literal["project_request_revision"] = "project_request_revision"
    schema_version: Literal["v0.1"] = "v0.1"
    request: ProjectRequest
    revision: ProductRecordSequence
    supersedes_sha256: StageSha256 | None = None
    recorded_at: AwareDatetime
    request_revision_sha256: StageSha256

    @model_validator(mode="after")
    def validate_revision_shape(self) -> Self:
        if self.revision == 1 and self.supersedes_sha256 is not None:
            raise ValueError("first ProjectRequestRevision cannot supersede a revision")
        if self.revision > 1 and self.supersedes_sha256 is None:
            raise ValueError("later ProjectRequestRevision requires supersedes_sha256")
        if self.recorded_at < self.request.updated_at:
            raise ValueError("ProjectRequestRevision cannot precede its request update")
        return self

    @classmethod
    def create(
        cls,
        request: ProjectRequest,
        *,
        revision: int,
        supersedes_sha256: StageSha256 | None,
        recorded_at: datetime,
    ) -> ProjectRequestRevision:
        _validate_stage_record(request)
        provisional = cls(
            request=request,
            revision=revision,
            supersedes_sha256=supersedes_sha256,
            recorded_at=recorded_at,
            request_revision_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={
                "request_revision_sha256": _record_digest(provisional, "request_revision_sha256")
            }
        )

    def validate_integrity(self) -> None:
        _validate_stage_record(self.request)
        expected = _record_digest(self, "request_revision_sha256")
        if self.request_revision_sha256 != expected:
            raise ProductRecordIntegrityError(
                "ProjectRequestRevision digest does not match content: "
                f"{self.request.id}@{self.revision}"
            )


class ProductDiscoveryCheckpoint(DomainModel):
    """Immutable restart checkpoint resolving every current Product fact by digest."""

    kind: Literal["product_discovery_checkpoint"] = "product_discovery_checkpoint"
    schema_version: Literal["v0.1"] = "v0.1"
    request_id: ProjectRequestId
    project_id: ProjectId
    revision: ProductRecordSequence
    previous_checkpoint_sha256: StageSha256 | None = None
    request_revision: ProductRecordSequence
    request_sha256: StageSha256
    dialogue_count: Annotated[StrictInt, Field(ge=0)]
    dialogue_head_sha256: StageSha256 | None = None
    current_product_spec_id: ProductSpecId | None = None
    current_product_spec_sha256: StageSha256 | None = None
    current_product_spec_version: ProductRecordSequence | None = None
    current_approval_id: ProductApprovalId | None = None
    current_approval_sha256: StageSha256 | None = None
    status: ProductDiscoveryStatus
    updated_at: AwareDatetime
    checkpoint_sha256: StageSha256

    @model_validator(mode="after")
    def validate_checkpoint_shape(self) -> Self:
        if self.revision == 1 and self.previous_checkpoint_sha256 is not None:
            raise ValueError("first ProductDiscoveryCheckpoint cannot have a previous digest")
        if self.revision > 1 and self.previous_checkpoint_sha256 is None:
            raise ValueError("later ProductDiscoveryCheckpoint requires a previous digest")
        if (self.dialogue_count == 0) != (self.dialogue_head_sha256 is None):
            raise ValueError("dialogue_count and dialogue_head_sha256 must be empty together")
        spec_values = (
            self.current_product_spec_id,
            self.current_product_spec_sha256,
            self.current_product_spec_version,
        )
        if any(value is None for value in spec_values) != all(
            value is None for value in spec_values
        ):
            raise ValueError("current ProductSpec identity, digest, and version are all-or-none")
        approval_values = (self.current_approval_id, self.current_approval_sha256)
        if (self.current_approval_id is None) != (self.current_approval_sha256 is None):
            raise ValueError("current approval identity and digest are all-or-none")
        if approval_values[0] is not None and self.current_product_spec_id is None:
            raise ValueError("current approval requires a current ProductSpec")
        if self.status is ProductDiscoveryStatus.PRODUCT_DISCOVERY and any(
            value is not None for value in (*spec_values, *approval_values)
        ):
            raise ValueError("PRODUCT_DISCOVERY cannot expose a ProductSpec or approval")
        if self.status is ProductDiscoveryStatus.WAITING_PRODUCT_APPROVAL and (
            self.current_product_spec_id is None or self.current_approval_id is not None
        ):
            raise ValueError("WAITING_PRODUCT_APPROVAL requires only a current ProductSpec")
        if self.status in {
            ProductDiscoveryStatus.CHANGES_REQUESTED,
            ProductDiscoveryStatus.APPROVED,
        } and (self.current_product_spec_id is None or self.current_approval_id is None):
            raise ValueError(f"{self.status.value} requires a ProductSpec and approval")
        return self

    @classmethod
    def create(
        cls,
        *,
        request_id: ProjectRequestId,
        project_id: ProjectId,
        revision: int,
        previous_checkpoint_sha256: StageSha256 | None,
        request_revision: int,
        request_sha256: StageSha256,
        dialogue_count: int,
        dialogue_head_sha256: StageSha256 | None,
        status: ProductDiscoveryStatus,
        updated_at: datetime,
        current_product_spec_id: ProductSpecId | None = None,
        current_product_spec_sha256: StageSha256 | None = None,
        current_product_spec_version: int | None = None,
        current_approval_id: ProductApprovalId | None = None,
        current_approval_sha256: StageSha256 | None = None,
    ) -> ProductDiscoveryCheckpoint:
        provisional = cls(
            request_id=request_id,
            project_id=project_id,
            revision=revision,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
            request_revision=request_revision,
            request_sha256=request_sha256,
            dialogue_count=dialogue_count,
            dialogue_head_sha256=dialogue_head_sha256,
            current_product_spec_id=current_product_spec_id,
            current_product_spec_sha256=current_product_spec_sha256,
            current_product_spec_version=current_product_spec_version,
            current_approval_id=current_approval_id,
            current_approval_sha256=current_approval_sha256,
            status=status,
            updated_at=updated_at,
            checkpoint_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={"checkpoint_sha256": _record_digest(provisional, "checkpoint_sha256")}
        )

    def validate_integrity(self) -> None:
        expected = _record_digest(self, "checkpoint_sha256")
        if self.checkpoint_sha256 != expected:
            raise ProductRecordIntegrityError(
                "ProductDiscoveryCheckpoint digest does not match content: "
                f"{self.request_id}@{self.revision}"
            )


class ProductOperationRecord(DomainModel):
    """Durable command receipt used for exact replay after process restart."""

    kind: Literal["product_operation_record"] = "product_operation_record"
    schema_version: Literal["v0.1"] = "v0.1"
    operation_id: ProductOperationId
    request_id: ProjectRequestId
    operation_kind: ProductOperationKind
    input_sha256: StageSha256
    result_identity: ResultIdentity
    result_payload: dict[str, JsonValue] = Field(default_factory=dict)
    recorded_at: AwareDatetime
    operation_sha256: StageSha256

    @classmethod
    def create(
        cls,
        *,
        operation_id: ProductOperationId,
        request_id: ProjectRequestId,
        operation_kind: ProductOperationKind,
        input_sha256: StageSha256,
        result_identity: str,
        recorded_at: datetime,
        result_payload: dict[str, JsonValue] | None = None,
    ) -> ProductOperationRecord:
        provisional = cls(
            operation_id=operation_id,
            request_id=request_id,
            operation_kind=operation_kind,
            input_sha256=input_sha256,
            result_identity=result_identity,
            result_payload=result_payload or {},
            recorded_at=recorded_at,
            operation_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={"operation_sha256": _record_digest(provisional, "operation_sha256")}
        )

    def validate_integrity(self) -> None:
        expected = _record_digest(self, "operation_sha256")
        if self.operation_sha256 != expected:
            raise ProductRecordIntegrityError(
                f"ProductOperationRecord digest does not match content: {self.operation_id}"
            )


def _validate_stage_record(record: ProjectRequest) -> None:
    try:
        record.validate_integrity()
    except (StageContractError, ValueError) as error:
        raise ProductRecordIntegrityError(
            f"ProjectRequest digest does not match content: {record.id}"
        ) from error


def _record_digest(record: DomainModel, *excluded: str) -> str:
    payload = record.model_dump(mode="json", exclude=set(excluded), exclude_none=True)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ProductDialogueActor",
    "ProductDialogueRecord",
    "ProductDiscoveryCheckpoint",
    "ProductDiscoveryStatus",
    "ProductOperationKind",
    "ProductOperationRecord",
    "ProductRecordIntegrityError",
    "ProductRecordStoreError",
    "ProjectRequestRevision",
]
