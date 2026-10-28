"""A start-only Coder can be contained without inventing a historical stop."""

from typing import Literal, Self

from pydantic import AwareDatetime, ConfigDict, model_validator

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryProofMissing,
    DeliveryWaitInvestigation,
    LocalStopReference,
)
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal, OperatorDuty
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.legacy_containment import LegacyExecutionContainment
from ai_software_engineer.orchestration.continuation_models import ExecutionCaptureStart
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep, record_digest
from ai_software_engineer.work_queue.models import QueuedWorkItem

CONTAINED_UNKNOWN_BUDGET_REASON = (
    "BUDGET_EXHAUSTED: 普通工作额度已耗尽; 原开发调用结果及停止记录保持 UNKNOWN, "
    "人工确认旧本机执行全结束且不会再写, 完整草稿已封存; 请精确批准新恢复方案。"
)


class LocalStopConfirmation(DomainModel):
    """An ENGINEERING declaration about the current local boundary, not old process evidence."""

    kind: Literal["local_stop_confirmation"] = "local_stop_confirmation"
    task_id: NonEmptyStr
    work_item_id: NonEmptyStr
    run_id: NonEmptyStr
    invocation_start_sha256: Sha256
    capture_start_sha256: Sha256
    containment_sha256: Sha256
    principal: LocalOperatorPrincipal
    reference: LocalStopReference
    confirmed_at: AwareDatetime
    same_machine_and_account: Literal[True] = True
    never_remote: Literal[True] = True
    all_derived_tools_ended: Literal[True] = True
    no_future_workspace_writes: Literal[True] = True
    confirmation_sha256: Sha256

    @model_validator(mode="after")
    def require_engineering_principal(self) -> Self:
        self.principal.require_duty(OperatorDuty.ENGINEERING)
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"confirmation_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.confirmation_sha256 != self.recompute_sha256():
            raise ValueError("本机旧执行人工确认摘要不一致")

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "confirmation_sha256": "0" * 64})
        return value.model_copy(update={"confirmation_sha256": value.recompute_sha256()})


class ContainedUnknownBudgetSettlement(DomainModel):
    """Close exhausted work after current containment while preserving old UNKNOWN."""

    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "properties": {
                        "task": {"properties": {"status": {"const": "IMPLEMENTING"}}},
                        "work_item": {
                            "properties": {
                                "role": {"const": "coder"},
                                "status": {"enum": ["WAITING_HUMAN", "WAITING_DEPENDENCY"]},
                            }
                        },
                        "event": {
                            "properties": {
                                "from_status": {"const": "IMPLEMENTING"},
                                "to_status": {"const": "BLOCKED"},
                                "artifact_ids": {"maxItems": 0},
                                "reason": {"const": CONTAINED_UNKNOWN_BUDGET_REASON},
                            }
                        },
                    }
                }
            ]
        }
    )

    kind: Literal["contained_unknown_budget_settlement"] = "contained_unknown_budget_settlement"
    schema_version: Literal["v1"] = "v1"
    task: Task
    investigation: DeliveryWaitInvestigation
    work_item: QueuedWorkItem
    step: QueuedRoleStep
    containment: LegacyExecutionContainment
    capture_start: ExecutionCaptureStart
    human_confirmation: LocalStopConfirmation
    expected_item_sha256: Sha256
    closed_item_sha256: Sha256
    inventory_sha256: Sha256
    retained_capture_sha256: Sha256
    event: StateEvent
    settlement_sha256: Sha256

    @model_validator(mode="after")
    def require_exact_contained_unknown(self) -> Self:
        task, proof, item, step = self.task, self.investigation, self.work_item, self.step
        containment, capture, human, event = (
            self.containment,
            self.capture_start,
            self.human_confirmation,
            self.event,
        )
        proof.validate_integrity()
        containment.validate_integrity()
        capture.validate_integrity()
        human.validate_integrity()
        start, claim = containment.original_start, containment.original_claim
        request = start.request
        closed = item.model_copy(
            update={
                "status": WorkItemStatus.CLOSED,
                "wait_reason": None,
                "wait_disposition": None,
                "available_at": None,
                "updated_at": event.occurred_at,
            }
        )
        if (
            task.status is not TaskStatus.IMPLEMENTING
            or not task.work_budget_exhausted
            or proof.task_id != task.id
            or proof.task_snapshot_sha256 != digest(task.to_wire())
            or proof.task_intent_sha256 != task_intent_sha256(task)
            or proof.disposition.facts.role is not AgentRole.CODER
            or proof.disposition.facts.classification != "EXECUTION_UNCERTAIN"
            or proof.permitted_resolutions
            or not proof.local_stop_confirmation_available
            or set(proof.missing)
            != {
                DeliveryProofMissing.OUTCOME_UNKNOWN,
                DeliveryProofMissing.STOP_UNRECORDED,
                DeliveryProofMissing.CHECKPOINT_UNAVAILABLE,
                DeliveryProofMissing.BUDGET_EXHAUSTED,
            }
            or proof.invocation_outcome_sha256 is not None
            or proof.interruption_receipt_sha256 is not None
            or proof.process_stop_sha256 is not None
            or proof.invocation_start_sha256 != start.start_sha256
            or proof.original_run_id != request.run_id
            or proof.source_revision != request.source_revision
            or proof.task_revision != capture.task_revision
            or proof.checkpoint_sequence != start.checkpoint_sequence
            or item.task_id != task.id
            or item.id != proof.work_item_id
            or item.id != start.work_item_id
            or item.wait_disposition != proof.disposition
            or item.status not in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
            or item.role is not AgentRole.CODER
            or item.attempt != task.attempts
            or request.task_id != task.id
            or request.attempt != task.attempts
            or step.work_item.id != item.id
            or record_digest(step) != proof.step_sha256
            or step.boundary.source_revision != request.source_revision
            or record_digest(item) != self.expected_item_sha256
            or record_digest(closed) != self.closed_item_sha256
            or capture.request != request
            or capture.claim.work_item.id != claim.work_item.id
            or capture.claim.lease.id != claim.lease.id
            or containment.task_intent_sha256 != task_intent_sha256(task)
            or containment.method != "operator_confirmed_local_stop"
            or human.task_id != task.id
            or human.work_item_id != item.id
            or human.run_id != request.run_id
            or human.invocation_start_sha256 != start.start_sha256
            or human.capture_start_sha256 != capture.start_sha256
            or human.containment_sha256 != containment.containment_sha256
            or human.confirmed_at < start.started_at
            or event.task_id != task.id
            or event.from_status is not task.status
            or event.to_status is not TaskStatus.BLOCKED
            or event.attempt != task.attempts
            or event.source_revision != request.source_revision
            or event.artifact_ids
            or event.reason != CONTAINED_UNKNOWN_BUDGET_REASON
            or event.occurred_at < human.confirmed_at
        ):
            raise ValueError("本机隔离额度收尾缺少精确旧调用、人工声明或完整现场")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"settlement_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.settlement_sha256 != self.recompute_sha256():
            raise ValueError("本机隔离额度收尾摘要不一致")
