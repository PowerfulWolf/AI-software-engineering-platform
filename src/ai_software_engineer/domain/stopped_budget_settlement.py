"""An exhausted stopped Task is ended, never refunded or revived."""

from typing import Literal, Self

from pydantic import model_validator

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import DeliveryWaitInvestigation
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.models import digest


class StoppedFailureBudgetSettlement(DomainModel):
    kind: Literal["stopped_failure_budget_settlement"] = "stopped_failure_budget_settlement"
    schema_version: Literal["v1"] = "v1"
    task: Task
    investigation: DeliveryWaitInvestigation
    expected_item_sha256: Sha256
    closed_item_sha256: Sha256
    invocation_start_sha256: Sha256
    invocation_outcome_sha256: Sha256
    capture_start_sha256: Sha256
    capture_stop_sha256: Sha256
    inventory_sha256: Sha256
    retained_capture_sha256: Sha256
    event: StateEvent
    settlement_sha256: Sha256

    @model_validator(mode="after")
    def require_terminal_budget_event(self) -> Self:
        task, proof, event = self.task, self.investigation, self.event
        proof.validate_integrity()
        if (
            task.status is not TaskStatus.IMPLEMENTING
            or not task.work_budget_exhausted
            or proof.task_id != task.id
            or proof.task_snapshot_sha256 != digest(task.to_wire())
            or proof.task_intent_sha256 != task_intent_sha256(task)
            or proof.disposition.facts.role is not AgentRole.CODER
            or proof.disposition.facts.classification
            not in {"TRANSIENT_INFRA", "NONTRANSIENT_INFRA"}
            or proof.permitted_resolutions
            or event.task_id != task.id
            or event.from_status is not task.status
            or event.to_status is not TaskStatus.BLOCKED
            or event.attempt != task.attempts
            or event.source_revision != proof.source_revision
            or event.artifact_ids
            or not event.reason.startswith("BUDGET_EXHAUSTED: ")
        ):
            raise ValueError("stopped budget settlement requires an exact exhausted Task")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"settlement_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.settlement_sha256 != self.recompute_sha256():
            raise ValueError("stopped budget settlement digest mismatch")
