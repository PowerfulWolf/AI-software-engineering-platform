"""Ending genuinely exhausted UNKNOWN work never asserts a historical outcome."""

from typing import Literal, Self

from pydantic import ConfigDict, model_validator

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import DeliveryWaitInvestigation
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.stopped_execution_checkpoint import StoppedCoderExecutionProof
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep, record_digest
from ai_software_engineer.work_queue.models import QueuedWorkItem

STOPPED_UNKNOWN_BUDGET_REASON = (
    "BUDGET_EXHAUSTED: 普通工作额度已耗尽; 原开发调用结果保持 UNKNOWN, "
    "已核验实际停止并完整保留草稿; 请准备恢复方案后精确批准。"
)


class StoppedUnknownBudgetSettlement(DomainModel):
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
                        "investigation": {
                            "properties": {
                                "permitted_resolutions": {"maxItems": 0},
                                "invocation_outcome_sha256": {"type": "null"},
                                "interruption_receipt_sha256": {"type": "null"},
                                "disposition": {
                                    "properties": {
                                        "facts": {
                                            "properties": {
                                                "role": {"const": "coder"},
                                                "classification": {"const": "EXECUTION_UNCERTAIN"},
                                            }
                                        }
                                    }
                                },
                            }
                        },
                        "event": {
                            "properties": {
                                "from_status": {"const": "IMPLEMENTING"},
                                "to_status": {"const": "BLOCKED"},
                                "artifact_ids": {"maxItems": 0},
                                "reason": {"const": STOPPED_UNKNOWN_BUDGET_REASON},
                            }
                        },
                    }
                }
            ]
        }
    )

    kind: Literal["stopped_unknown_budget_settlement"] = "stopped_unknown_budget_settlement"
    schema_version: Literal["v1"] = "v1"
    task: Task
    investigation: DeliveryWaitInvestigation
    work_item: QueuedWorkItem
    step: QueuedRoleStep
    stopped_execution: StoppedCoderExecutionProof
    expected_item_sha256: Sha256
    closed_item_sha256: Sha256
    inventory_sha256: Sha256
    retained_capture_sha256: Sha256
    event: StateEvent
    settlement_sha256: Sha256

    @model_validator(mode="after")
    def require_exact_unknown_exhaustion(self) -> Self:
        task, proof, item, step = self.task, self.investigation, self.work_item, self.step
        stopped, event = self.stopped_execution, self.event
        proof.validate_integrity()
        stopped.validate_integrity()
        start = stopped.invocation_start
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
            or proof.invocation_outcome_sha256 is not None
            or proof.interruption_receipt_sha256 is not None
            or proof.invocation_start_sha256 != start.start_sha256
            or proof.original_run_id != request.run_id
            or proof.source_revision != request.source_revision
            or proof.process_stop_sha256 != stopped.capture_stop.process_stop.stop_sha256
            or proof.task_revision != stopped.capture_start.task_revision
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
            or event.task_id != task.id
            or event.from_status is not task.status
            or event.to_status is not TaskStatus.BLOCKED
            or event.attempt != task.attempts
            or event.source_revision != request.source_revision
            or event.artifact_ids
            or event.reason != STOPPED_UNKNOWN_BUDGET_REASON
            or event.occurred_at < stopped.capture_stop.process_stop.stopped_at
        ):
            raise ValueError("unknown budget settlement requires exact exhausted stopped work")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"settlement_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.settlement_sha256 != self.recompute_sha256():
            raise ValueError("unknown budget settlement digest mismatch")
