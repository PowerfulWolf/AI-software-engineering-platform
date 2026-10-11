"""Versioned, bounded reading-only Operation projections and pagination."""

from __future__ import annotations

import base64
import binascii
import hashlib
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.manager.delivery import CheckpointDigest
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId

from .models import ConsoleAction, ConsoleOperation, ConsoleOperationStatus, OperationId

SUMMARY_CONTRACT_VERSION = "v0.1"
MAX_ACTIVE_SUMMARIES = 64
MAX_SUMMARY_PAGE_BYTES = 256 * 1024
SummaryText = Annotated[str, StringConstraints(max_length=512)]
CursorToken = Annotated[
    str, StringConstraints(min_length=1, max_length=4096, pattern=r"^[A-Za-z0-9_-]+$")
]
PageSize = Annotated[int, Field(strict=True, ge=1, le=50)]
type SubmittedApprovalKind = Literal["plan", "scope", "repair"]
_APPROVAL_LOCATORS: tuple[tuple[SubmittedApprovalKind, str], ...] = (
    ("plan", "approved_plan_sha256"),
    ("scope", "approved_scope_sha256"),
    ("repair", "approved_repair_sha256"),
)


class StaleOperationCursor(ValueError):
    """The caller's finite history page is no longer the current inventory."""


class OperationResultScopeRelation(StrEnum):
    NO_RESULT = "NO_RESULT"
    SAME_RESOURCE = "SAME_RESOURCE"
    CREATED_RESOURCE = "CREATED_RESOURCE"
    NO_RESOURCE = "NO_RESOURCE"
    UNVERIFIED_RESOURCE = "UNVERIFIED_RESOURCE"


def _result_scope_relation(operation: ConsoleOperation) -> OperationResultScopeRelation:
    result = operation.result
    if result is None:
        return OperationResultScopeRelation.NO_RESULT
    intent_project = getattr(operation.intent, "project_id", None)
    if intent_project is not None and result.project_id != intent_project:
        raise ValueError("operation summary result scope differs from submitted scope")
    if operation.intent.action == ConsoleAction.CREATE_PROJECT and intent_project is None:
        return OperationResultScopeRelation.CREATED_RESOURCE
    if operation.intent.action == ConsoleAction.CREATE_REQUIREMENT:
        return (
            OperationResultScopeRelation.CREATED_RESOURCE
            if result.delivery_id is not None
            else OperationResultScopeRelation.UNVERIFIED_RESOURCE
        )
    if operation.delivery_id == result.delivery_id:
        return OperationResultScopeRelation.SAME_RESOURCE
    if operation.intent.action == ConsoleAction.DELETE_REQUIREMENT and result.delivery_id is None:
        return OperationResultScopeRelation.NO_RESOURCE
    return OperationResultScopeRelation.UNVERIFIED_RESOURCE


class OperationSummaryScope(DomainModel):
    project_id: ProjectId | None = None
    delivery_id: DeliveryId | None = None

    @model_validator(mode="after")
    def require_project_scope(self) -> Self:
        if self.delivery_id is not None and self.project_id is None:
            raise ValueError("delivery summary filter requires project scope")
        return self


class OperationSummaryCursor(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    inventory_sha256: CheckpointDigest
    scope: OperationSummaryScope
    page_size: PageSize
    sort: Literal["requested_at_desc_operation_id_desc"] = "requested_at_desc_operation_id_desc"
    after_requested_at: AwareDatetime
    after_operation_id: OperationId

    def encode(self) -> str:
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str) -> Self:
        try:
            payload = base64.b64decode(
                token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
            )
            value = cls.model_validate_json(payload)
        except (ValueError, binascii.Error) as error:
            raise ValueError("invalid operation summary cursor") from error
        if value.encode() != token:
            raise ValueError("noncanonical operation summary cursor")
        return value


class OperationSummaryQuery(OperationSummaryScope):
    page_size: PageSize = 25
    cursor: CursorToken | None = None

    @field_validator("cursor")
    @classmethod
    def validate_cursor(cls, token: str | None) -> str | None:
        if token is not None:
            OperationSummaryCursor.decode(token)
        return token

    @property
    def scope(self) -> OperationSummaryScope:
        return OperationSummaryScope(project_id=self.project_id, delivery_id=self.delivery_id)


class OperationSummary(DomainModel):
    """Short reading text and identities, never an approval or command input."""

    operation_id: OperationId
    team_id: TeamId
    project_id: ProjectId | None = None
    delivery_id: DeliveryId | None = None
    result_scope_relation: OperationResultScopeRelation = OperationResultScopeRelation.NO_RESULT
    result_project_id: ProjectId | None = None
    result_delivery_id: DeliveryId | None = None
    action: ConsoleAction
    status: ConsoleOperationStatus
    sequence: Annotated[int, Field(ge=1)]
    requested_at: AwareDatetime
    updated_at: AwareDatetime
    operation_sha256: CheckpointDigest
    error_code: Annotated[str, StringConstraints(max_length=64)] | None = None
    error_summary: SummaryText | None = None
    result_stage: Annotated[str, StringConstraints(max_length=128)] | None = None
    result_checkpoint_sha256: CheckpointDigest | None = None
    intent_checkpoint_sha256: CheckpointDigest | None = None
    submitted_approval_sha256: CheckpointDigest | None = None
    submitted_approval_kind: SubmittedApprovalKind | None = None
    intent_plan_sha256: CheckpointDigest | None = None
    task_id: TaskId | None = None
    work_item_id: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    approval_plan_sha256: CheckpointDigest | None = None
    baseline_plan_sha256: CheckpointDigest | None = None
    baseline_purpose: Annotated[str, StringConstraints(max_length=64)] | None = None
    has_baseline_binding: bool = False
    next_step: SummaryText | None = None
    summary: SummaryText | None = None
    approval_kind: Annotated[str, StringConstraints(max_length=64)] | None = None
    has_details: Literal[True] = True

    @classmethod
    def from_operation(cls, operation: ConsoleOperation) -> Self:
        original_result = operation.result
        relation = _result_scope_relation(operation)
        result = (
            original_result
            if relation
            in {
                OperationResultScopeRelation.SAME_RESOURCE,
                OperationResultScopeRelation.CREATED_RESOURCE,
            }
            else None
        )
        intent_project = getattr(operation.intent, "project_id", None)
        approval = next(
            (
                (kind, value)
                for kind, name in _APPROVAL_LOCATORS
                if (value := getattr(operation.intent, name, None)) is not None
            ),
            (None, None),
        )
        task_id = getattr(operation.intent, "task_id", None)
        work_item_id = getattr(operation.intent, "work_item_id", None) or getattr(
            operation.intent, "expected_work_item_id", None
        )
        if result is not None:
            for fact in (
                result.legacy_rescue_preparation,
                result.engineering_wait_handling,
                result.engineering_wait_investigation,
                result.engineering_wait_resolution,
            ):
                if fact is not None:
                    task_id = task_id or fact.task_id
                    work_item_id = work_item_id or fact.work_item_id
            if result.execution_baseline_binding is not None:
                task_id = task_id or result.execution_baseline_binding.task_id
            if result.execution_baseline_plan is not None:
                task_id = task_id or result.execution_baseline_plan.facts.task.id
                work_item_id = work_item_id or result.execution_baseline_plan.facts.work_item_id
        # An opaque legacy identifier cannot be truncated into a different ID.
        if work_item_id is not None and len(work_item_id) > 128:
            work_item_id = None
        return cls(
            operation_id=operation.operation_id,
            team_id=operation.team_id,
            project_id=intent_project or (result.project_id if result else None),
            delivery_id=operation.delivery_id
            or (
                result.delivery_id
                if result and relation == OperationResultScopeRelation.CREATED_RESOURCE
                else None
            ),
            result_scope_relation=relation,
            result_project_id=original_result.project_id if original_result else None,
            result_delivery_id=original_result.delivery_id if original_result else None,
            action=operation.intent.action,
            status=operation.status,
            sequence=operation.sequence,
            requested_at=operation.requested_at,
            updated_at=operation.updated_at,
            operation_sha256=operation.operation_sha256,
            error_code=operation.error_code,
            error_summary=_short(operation.error_summary),
            result_stage=_short(result.stage, 128) if result else None,
            result_checkpoint_sha256=result.checkpoint_sha256 if result else None,
            intent_checkpoint_sha256=getattr(operation.intent, "expected_checkpoint_sha256", None),
            submitted_approval_sha256=approval[1],
            submitted_approval_kind=approval[0],
            intent_plan_sha256=getattr(operation.intent, "expected_plan_sha256", None),
            task_id=task_id,
            work_item_id=work_item_id,
            approval_plan_sha256=result.approval.plan_sha256
            if result and result.approval
            else None,
            baseline_plan_sha256=result.execution_baseline_plan.plan_sha256
            if result and result.execution_baseline_plan
            else None,
            baseline_purpose=result.execution_baseline_plan.purpose.value
            if result and result.execution_baseline_plan
            else None,
            has_baseline_binding=bool(result and result.execution_baseline_binding),
            next_step=_short(result.next_action) if result else None,
            summary=_short(result.diagnostic) if result else None,
            approval_kind=result.approval.kind if result and result.approval else None,
        )

    @property
    def active(self) -> bool:
        return self.status in {ConsoleOperationStatus.QUEUED, ConsoleOperationStatus.RUNNING}


class OperationSummaryPage(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    team_id: TeamId
    scope: OperationSummaryScope
    inventory_sha256: CheckpointDigest
    items: Annotated[tuple[OperationSummary, ...], Field(max_length=50)]
    next_cursor: CursorToken | None = None
    total_count: Annotated[int, Field(ge=0)]
    active: Annotated[tuple[OperationSummary, ...], Field(max_length=MAX_ACTIVE_SUMMARIES)]
    active_complete: Literal[True] = True

    @property
    def etag(self) -> str:
        return '"' + hashlib.sha256(self.model_dump_json().encode()).hexdigest() + '"'


def _short(value: str | None, maximum: int = 512) -> str | None:
    if value is None or len(value) <= maximum:
        return value
    return value[: maximum - 1] + "…"
