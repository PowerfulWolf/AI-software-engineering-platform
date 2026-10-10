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

from ai_software_engineer.agents.model_diagnostics import ModelCallDiagnostic
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    DeliveryWaitHandling,
    DeliveryWaitInvestigation,
    EngineeringDispositionRecord,
    InspectDeliveryWait,
)
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding, FullGitRevision
from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.prerequisite_repair import PrerequisiteRepairRequest
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.manager.baseline_models import ExecutionBaselinePlan
from ai_software_engineer.manager.baseline_production import (
    BaselineContinueCommand,
    BaselineExecuteCommand,
    BaselineProposeCommand,
)
from ai_software_engineer.manager.delivery import CheckpointDigest
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.manager.native_ui import NativeUiScenario
from ai_software_engineer.manager.python_verification import PytestSelection
from ai_software_engineer.multi_directory.attachments import RequirementAttachmentId
from ai_software_engineer.project_workspace import ProjectName
from ai_software_engineer.recovery.models import RecoveryScopeRequest

OperationId = Annotated[str, StringConstraints(pattern=r"^operation_[a-f0-9]{32}$")]
IdempotencyKey = Annotated[
    str,
    StringConstraints(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$"),
]


class ConsoleModelCall(DomainModel):
    """Content-addressed observation, separate from the immutable Operation hash chain."""

    operation_id: OperationId
    call: ModelCallDiagnostic

    @property
    def record_sha256(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class ConsoleAction(StrEnum):
    CREATE_PROJECT = "CREATE_PROJECT"
    CREATE_REQUIREMENT = "CREATE_REQUIREMENT"
    UPDATE_REQUIREMENT = "UPDATE_REQUIREMENT"
    CLOSE_REQUIREMENT = "CLOSE_REQUIREMENT"
    RESTART_REQUIREMENT = "RESTART_REQUIREMENT"
    DELETE_REQUIREMENT = "DELETE_REQUIREMENT"
    PRODUCT_REPLY = "PRODUCT_REPLY"
    PRODUCT_APPROVAL = "PRODUCT_APPROVAL"
    CONTINUE_DELIVERY = "CONTINUE_DELIVERY"
    RECOVER_DESIGN = "RECOVER_DESIGN"
    RECHECK_DESIGN = "RECHECK_DESIGN"
    INSPECT_DELIVERY_WAIT = "INSPECT_DELIVERY_WAIT"
    HANDLE_DELIVERY_WAIT = "HANDLE_DELIVERY_WAIT"
    RESOLVE_DELIVERY_WAIT = "RESOLVE_DELIVERY_WAIT"
    PROPOSE_EXECUTION_BASELINE = "PROPOSE_EXECUTION_BASELINE"
    EXECUTE_EXECUTION_BASELINE = "EXECUTE_EXECUTION_BASELINE"
    RESUME_EXECUTION_BASELINE = "RESUME_EXECUTION_BASELINE"


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
        return _absolute_unique_roots(values)


class UpdateRequirementIntent(DomainModel):
    action: Literal[ConsoleAction.UPDATE_REQUIREMENT] = ConsoleAction.UPDATE_REQUIREMENT
    project_id: ProjectId
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    repository_roots: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1, max_length=32)]

    @field_validator("repository_roots")
    @classmethod
    def absolute_unique_roots(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _absolute_unique_roots(values)


class DeleteRequirementIntent(DomainModel):
    action: Literal[ConsoleAction.DELETE_REQUIREMENT] = ConsoleAction.DELETE_REQUIREMENT
    project_id: ProjectId
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest


class CloseRequirementIntent(DomainModel):
    action: Literal[ConsoleAction.CLOSE_REQUIREMENT] = ConsoleAction.CLOSE_REQUIREMENT
    project_id: ProjectId
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest


class RestartRequirementIntent(DomainModel):
    action: Literal[ConsoleAction.RESTART_REQUIREMENT] = ConsoleAction.RESTART_REQUIREMENT
    project_id: ProjectId
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest


class ProductReplyIntent(DomainModel):
    action: Literal[ConsoleAction.PRODUCT_REPLY] = ConsoleAction.PRODUCT_REPLY
    project_id: ProjectId
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest
    message: Annotated[str, StringConstraints(max_length=20_000)] = ""
    screenshot_ids: Annotated[tuple[RequirementAttachmentId, ...], Field(max_length=4)] = ()

    @model_validator(mode="after")
    def require_reply_content(self) -> Self:
        if not self.message.strip() and not self.screenshot_ids:
            raise ValueError("Product reply requires text or screenshots")
        if len(set(self.screenshot_ids)) != len(self.screenshot_ids):
            raise ValueError("Product reply screenshots must be unique")
        return self


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
    approved_scope_sha256: CheckpointDigest | None = None
    coder_scope_request: RecoveryScopeRequest | None = None
    prerequisite_repair: PrerequisiteRepairRequest | None = None
    native_ui_scenario: NativeUiScenario | None = None
    python_mysql_tests: tuple[PytestSelection, ...] | None = Field(
        default=None, min_length=1, max_length=32
    )
    approved_repair_sha256: CheckpointDigest | None = None

    @model_validator(mode="after")
    def require_one_approval(self) -> Self:
        if (
            sum(
                value is not None
                for value in (
                    self.approved_plan_sha256,
                    self.approved_scope_sha256,
                    self.prerequisite_repair,
                    self.native_ui_scenario,
                    self.python_mysql_tests,
                    self.approved_repair_sha256,
                )
            )
            > 1
        ):
            raise ValueError("only one continuation approval may be submitted")
        if self.coder_scope_request is not None and any(
            value is not None
            for value in (
                self.approved_plan_sha256,
                self.approved_repair_sha256,
                self.prerequisite_repair,
                self.native_ui_scenario,
                self.python_mysql_tests,
            )
        ):
            raise ValueError("requested Coder scope may only accompany scope approval")
        return self


class RecoverDesignIntent(DomainModel):
    action: Literal[ConsoleAction.RECOVER_DESIGN] = ConsoleAction.RECOVER_DESIGN
    project_id: ProjectId
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest


class RecheckDesignIntent(DomainModel):
    action: Literal[ConsoleAction.RECHECK_DESIGN] = ConsoleAction.RECHECK_DESIGN
    project_id: ProjectId
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest


class _DeliveryWaitIntent(InspectDeliveryWait):
    project_id: ProjectId
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest


class InspectDeliveryWaitIntent(_DeliveryWaitIntent):
    action: Literal[ConsoleAction.INSPECT_DELIVERY_WAIT] = ConsoleAction.INSPECT_DELIVERY_WAIT


class HandleDeliveryWaitIntent(_DeliveryWaitIntent):
    action: Literal[ConsoleAction.HANDLE_DELIVERY_WAIT] = ConsoleAction.HANDLE_DELIVERY_WAIT


class ResolveDeliveryWaitIntent(_DeliveryWaitIntent):
    action: Literal[ConsoleAction.RESOLVE_DELIVERY_WAIT] = ConsoleAction.RESOLVE_DELIVERY_WAIT
    resolution_kind: DeliveryResolutionKind
    proof_sha256: CheckpointDigest


class ProposeExecutionBaselineIntent(BaselineProposeCommand):
    action: Literal[ConsoleAction.PROPOSE_EXECUTION_BASELINE] = (
        ConsoleAction.PROPOSE_EXECUTION_BASELINE
    )
    project_id: ProjectId
    expected_checkpoint_sha256: CheckpointDigest


class ExecuteExecutionBaselineIntent(BaselineExecuteCommand):
    action: Literal[ConsoleAction.EXECUTE_EXECUTION_BASELINE] = (
        ConsoleAction.EXECUTE_EXECUTION_BASELINE
    )
    project_id: ProjectId
    expected_checkpoint_sha256: CheckpointDigest


class ResumeExecutionBaselineIntent(BaselineContinueCommand):
    action: Literal[ConsoleAction.RESUME_EXECUTION_BASELINE] = (
        ConsoleAction.RESUME_EXECUTION_BASELINE
    )
    project_id: ProjectId
    expected_checkpoint_sha256: CheckpointDigest


ConsoleIntent = Annotated[
    CreateProjectIntent
    | CreateRequirementIntent
    | UpdateRequirementIntent
    | CloseRequirementIntent
    | RestartRequirementIntent
    | DeleteRequirementIntent
    | ProductReplyIntent
    | ProductApprovalIntent
    | ContinueDeliveryIntent
    | RecoverDesignIntent
    | RecheckDesignIntent
    | InspectDeliveryWaitIntent
    | HandleDeliveryWaitIntent
    | ResolveDeliveryWaitIntent
    | ProposeExecutionBaselineIntent
    | ExecuteExecutionBaselineIntent
    | ResumeExecutionBaselineIntent,
    Field(discriminator="action"),
]
CONSOLE_INTENT_ADAPTER: TypeAdapter[ConsoleIntent] = TypeAdapter(ConsoleIntent)


class ConsoleApprovalRequest(DomainModel):
    kind: Literal[
        "candidate_verification",
        "coder_recovery",
        "coder_interruption",
        "pre_execution_restart",
        "coder_scope",
        "joint_integration",
        "prerequisite_repair",
    ]
    plan_sha256: CheckpointDigest
    title: NonEmptyStr
    facts: tuple[NonEmptyStr, ...]
    technical_facts: tuple[NonEmptyStr, ...] = Field(default=(), exclude_if=lambda value: not value)
    coder_scope_request: RecoveryScopeRequest | None = None

    @model_validator(mode="after")
    def scope_request_kind(self) -> Self:
        if self.coder_scope_request is not None and self.kind != "coder_scope":
            raise ValueError("requested scope belongs only to a scope approval")
        return self


class LegacyRescuePreparation(DomainModel):
    """Bound prerequisite check, separate from human authorization and old Run outcome."""

    status: Literal["READY", "WAITING"]
    task_id: TaskId
    work_item_id: NonEmptyStr
    source_revision: FullGitRevision
    code: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,99}$")]
    summary: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    next_action: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    responsible_party: Literal["平台执行服务", "工程授权者"]


class ConsoleCommandResult(DomainModel):
    project_id: ProjectId
    delivery_id: DeliveryId | None = None
    checkpoint_sha256: CheckpointDigest | None = None
    stage: NonEmptyStr
    next_action: NonEmptyStr
    diagnostic: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None
    approval: ConsoleApprovalRequest | None = None
    engineering_wait_investigation: DeliveryWaitInvestigation | None = None
    engineering_wait_handling: DeliveryWaitHandling | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    engineering_wait_resolution: DeliveryResolution | None = None
    engineering_disposition: EngineeringDispositionRecord | None = None
    execution_baseline_plan: ExecutionBaselinePlan | None = None
    execution_baseline_binding: ExecutionBaselineBinding | None = None
    legacy_rescue_preparation: LegacyRescuePreparation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_resource_result(self) -> Self:
        if (self.delivery_id is None) != (self.checkpoint_sha256 is None):
            raise ValueError("delivery result requires both delivery ID and checkpoint")
        if self.approval is not None and self.delivery_id is None:
            raise ValueError("approval can only belong to a delivery result")
        preparation = self.legacy_rescue_preparation
        if preparation is not None:
            plan = self.execution_baseline_plan
            if (
                self.delivery_id is None
                or self.execution_baseline_binding is not None
                or self.approval is not None
            ):
                raise ValueError("rescue check requires a delivery and cannot execute a binding")
            if (preparation.status == "READY") != (plan is not None):
                raise ValueError("only a ready rescue check can include an exact plan")
            if plan is not None and (
                plan.purpose.value != "legacy_workspace_rescue"
                or plan.facts.task.id != preparation.task_id
                or plan.facts.work_item_id != preparation.work_item_id
                or plan.dirty_capture.source_revision != preparation.source_revision
            ):
                raise ValueError("rescue check must bind its exact preserved workspace plan")
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


def _absolute_unique_roots(values: tuple[str, ...]) -> tuple[str, ...]:
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


__all__ = [
    "CONSOLE_INTENT_ADAPTER",
    "CloseRequirementIntent",
    "ConsoleAction",
    "ConsoleApprovalRequest",
    "ConsoleCommandResult",
    "ConsoleIntent",
    "ConsoleOperation",
    "ConsoleOperationStatus",
    "ContinueDeliveryIntent",
    "CreateProjectIntent",
    "CreateRequirementIntent",
    "DeleteRequirementIntent",
    "HandleDeliveryWaitIntent",
    "IdempotencyKey",
    "InspectDeliveryWaitIntent",
    "LegacyRescuePreparation",
    "OperationId",
    "ProductApprovalIntent",
    "ProductReplyIntent",
    "RecheckDesignIntent",
    "RecoverDesignIntent",
    "ResolveDeliveryWaitIntent",
    "RestartRequirementIntent",
    "UpdateRequirementIntent",
]
