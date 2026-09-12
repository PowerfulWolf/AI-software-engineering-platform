"""Durable browser intents and operation facts for the Manager console."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.manager.delivery import CheckpointDigest
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.project_workspace import ProjectName

OperationId = Annotated[str, StringConstraints(pattern=r"^operation_[a-f0-9]{32}$")]
IdempotencyKey = Annotated[
    str,
    StringConstraints(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$"),
]


class ConsoleAction(StrEnum):
    CREATE_PROJECT = "CREATE_PROJECT"
    CREATE_REQUIREMENT = "CREATE_REQUIREMENT"
    PRODUCT_REPLY = "PRODUCT_REPLY"
    PRODUCT_APPROVAL = "PRODUCT_APPROVAL"
    CONTINUE_DELIVERY = "CONTINUE_DELIVERY"


class ConsoleOperationStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class CreateProjectIntent(DomainModel):
    action: Literal[ConsoleAction.CREATE_PROJECT] = ConsoleAction.CREATE_PROJECT
    name: ProjectName
    project_id: ProjectId | None = None


class CreateRequirementIntent(DomainModel):
    action: Literal[ConsoleAction.CREATE_REQUIREMENT] = ConsoleAction.CREATE_REQUIREMENT
    project_id: ProjectId
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    repository_roots: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1, max_length=32)]

    @field_validator("repository_roots")
    @classmethod
    def absolute_unique_roots(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("project directories must be unique")
        for value in values:
            if (
                not Path(value).is_absolute()
                or any(ord(character) < 32 for character in value)
                or any(part == ".." for part in Path(value).parts)
            ):
                raise ValueError("project directories must be absolute safe paths")
        return values


class ProductReplyIntent(DomainModel):
    action: Literal[ConsoleAction.PRODUCT_REPLY] = ConsoleAction.PRODUCT_REPLY
    project_id: ProjectId
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest
    message: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]


class ProductApprovalIntent(DomainModel):
    action: Literal[ConsoleAction.PRODUCT_APPROVAL] = ConsoleAction.PRODUCT_APPROVAL
    project_id: ProjectId
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest


class ContinueDeliveryIntent(DomainModel):
    action: Literal[ConsoleAction.CONTINUE_DELIVERY] = ConsoleAction.CONTINUE_DELIVERY
    project_id: ProjectId
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest
    approved_plan_sha256: CheckpointDigest | None = None


ConsoleIntent = Annotated[
    CreateProjectIntent
    | CreateRequirementIntent
    | ProductReplyIntent
    | ProductApprovalIntent
    | ContinueDeliveryIntent,
    Field(discriminator="action"),
]
CONSOLE_INTENT_ADAPTER: TypeAdapter[ConsoleIntent] = TypeAdapter(ConsoleIntent)


class ConsoleApprovalRequest(DomainModel):
    kind: Literal["candidate_verification", "coder_recovery"]
    plan_sha256: CheckpointDigest
    title: NonEmptyStr
    facts: tuple[NonEmptyStr, ...]


class ConsoleCommandResult(DomainModel):
    project_id: ProjectId
    delivery_id: DeliveryId | None = None
    checkpoint_sha256: CheckpointDigest | None = None
    stage: NonEmptyStr
    next_action: NonEmptyStr
    approval: ConsoleApprovalRequest | None = None

    @model_validator(mode="after")
    def validate_resource_result(self) -> Self:
        if (self.delivery_id is None) != (self.checkpoint_sha256 is None):
            raise ValueError("delivery result requires both delivery ID and checkpoint")
        if self.approval is not None and self.delivery_id is None:
            raise ValueError("approval can only belong to a delivery result")
        return self


class ConsoleOperation(DomainModel):
    schema_version: Literal["v0.2"] = "v0.2"
    operation_id: OperationId
    team_id: TeamId
    idempotency_key: IdempotencyKey
    intent: ConsoleIntent
    intent_sha256: CheckpointDigest
    status: ConsoleOperationStatus
    sequence: Annotated[int, Field(ge=1)]
    requested_at: AwareDatetime
    updated_at: AwareDatetime
    previous_operation_sha256: CheckpointDigest | None = None
    result: ConsoleCommandResult | None = None
    error_code: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")] | None = None
    error_summary: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None
    operation_sha256: CheckpointDigest

    @property
    def delivery_id(self) -> str | None:
        return getattr(self.intent, "delivery_id", None)

    @property
    def terminal(self) -> bool:
        return self.status in {
            ConsoleOperationStatus.SUCCEEDED,
            ConsoleOperationStatus.FAILED,
            ConsoleOperationStatus.INTERRUPTED,
        }

    @classmethod
    def queued(
        cls,
        *,
        team_id: str,
        idempotency_key: str,
        intent: ConsoleIntent,
        requested_at: AwareDatetime,
    ) -> Self:
        intent_payload = intent.model_dump(mode="json", exclude_none=True)
        intent_sha256 = _digest(intent_payload)
        operation_id = (
            "operation_" + hashlib.sha256(f"{team_id}\n{idempotency_key}".encode()).hexdigest()[:32]
        )
        provisional = cls(
            operation_id=operation_id,
            team_id=team_id,
            idempotency_key=idempotency_key,
            intent=intent,
            intent_sha256=intent_sha256,
            status=ConsoleOperationStatus.QUEUED,
            sequence=1,
            requested_at=requested_at,
            updated_at=requested_at,
            operation_sha256="0" * 64,
        )
        return provisional._sealed()

    def transition(
        self,
        status: ConsoleOperationStatus,
        *,
        updated_at: AwareDatetime,
        result: ConsoleCommandResult | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> Self:
        allowed = {
            ConsoleOperationStatus.QUEUED: {ConsoleOperationStatus.RUNNING},
            ConsoleOperationStatus.RUNNING: {
                ConsoleOperationStatus.SUCCEEDED,
                ConsoleOperationStatus.FAILED,
                ConsoleOperationStatus.INTERRUPTED,
            },
        }
        if status not in allowed.get(self.status, set()):
            raise ValueError("invalid console operation transition")
        provisional = self.model_copy(
            update={
                "status": status,
                "sequence": self.sequence + 1,
                "updated_at": updated_at,
                "previous_operation_sha256": self.operation_sha256,
                "result": result,
                "error_code": error_code,
                "error_summary": error_summary,
                "operation_sha256": "0" * 64,
            }
        )
        return type(self).model_validate(provisional)._sealed()

    def recompute_sha256(self) -> str:
        return _digest(
            self.model_dump(mode="json", exclude_none=True, exclude={"operation_sha256"})
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.intent_sha256 != _digest(self.intent.model_dump(mode="json", exclude_none=True)):
            raise ValueError("console operation intent digest mismatch")
        if self.operation_sha256 != self.recompute_sha256():
            raise ValueError("console operation digest mismatch")

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.updated_at < self.requested_at:
            raise ValueError("console operation timestamp moved backwards")
        if self.sequence == 1:
            if (
                self.status is not ConsoleOperationStatus.QUEUED
                or self.previous_operation_sha256 is not None
            ):
                raise ValueError("initial console operation must be QUEUED")
        elif self.previous_operation_sha256 is None:
            raise ValueError("continued console operation requires a parent digest")
        if self.status is ConsoleOperationStatus.SUCCEEDED:
            if self.result is None or self.error_code is not None or self.error_summary is not None:
                raise ValueError("successful console operation requires only a result")
        elif self.status in {ConsoleOperationStatus.FAILED, ConsoleOperationStatus.INTERRUPTED}:
            if self.result is not None or self.error_code is None or self.error_summary is None:
                raise ValueError("failed console operation requires only a safe error")
        elif (
            self.result is not None or self.error_code is not None or self.error_summary is not None
        ):
            raise ValueError("active console operation cannot contain a result or error")
        return self

    def _sealed(self) -> Self:
        return self.model_copy(update={"operation_sha256": self.recompute_sha256()})


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


__all__ = [
    "CONSOLE_INTENT_ADAPTER",
    "ConsoleAction",
    "ConsoleApprovalRequest",
    "ConsoleCommandResult",
    "ConsoleIntent",
    "ConsoleOperation",
    "ConsoleOperationStatus",
    "ContinueDeliveryIntent",
    "CreateProjectIntent",
    "CreateRequirementIntent",
    "IdempotencyKey",
    "OperationId",
    "ProductApprovalIntent",
    "ProductReplyIntent",
]
