"""Sealed recovery Task input, never an allocation/dispatch or candidate verdict."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self

from pydantic import Field, model_validator

from ai_software_engineer.domain import ProjectRequest, Task, TaskStatus
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.recovery.models import (
    RecoveryAuthorization,
    RecoveryPlan,
    RecoveryRejected,
    canonical_bytes,
    digest,
)
from ai_software_engineer.redaction import redact_text

if TYPE_CHECKING:
    from ai_software_engineer.recovery.task import RecoveryTaskDraft


class RecoveryTaskRecord(DomainModel):
    kind: Literal["recovery_task_record"] = "recovery_task_record"
    schema_version: Literal["v0.1"] = "v0.1"
    recovery_plan_sha256: StageSha256
    authorization_sha256: StageSha256
    rebound_request: ProjectRequest
    task: Task = Field(
        json_schema_extra={
            "allOf": [{"properties": {"status": {"const": "NEW"}, "attempts": {"const": 0}}}]
        }
    )
    record_sha256: StageSha256

    @classmethod
    def create(
        cls, draft: RecoveryTaskDraft, authorization: RecoveryAuthorization
    ) -> RecoveryTaskRecord:
        authorization.validate_integrity()
        if (
            not authorization.decision.approved
            or authorization.command.plan_sha256 != draft.recovery_plan_sha256
        ):
            raise RecoveryRejected("Task record requires exact approved recovery")
        provisional = cls(
            recovery_plan_sha256=draft.recovery_plan_sha256,
            authorization_sha256=authorization.authorization_sha256,
            rebound_request=draft.rebound_request,
            task=draft.task,
            record_sha256="0" * 64,
        )
        return provisional.model_copy(update={"record_sha256": provisional.recompute_sha256()})

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        self.rebound_request.validate_integrity()
        if self.task.status is not TaskStatus.NEW or self.task.attempts != 0:
            raise ValueError("recovery record requires an unstarted NEW Task")
        if self.task.id != "task_recovery_" + self.recovery_plan_sha256[:32]:
            raise ValueError("recovery Task identity mismatch")
        expected = {
            "recovery_plan_sha256": self.recovery_plan_sha256,
            "recovery_rebound_request_sha256": self.rebound_request.request_sha256,
            "recovery_target_preparation_sha256": self.rebound_request.preparation_sha256,
            "project_request_id": self.rebound_request.id,
            "project_id": self.rebound_request.project_id,
        }
        if any(self.task.metadata.get(key) != value for key, value in expected.items()):
            raise ValueError("recovery Task/request metadata mismatch")
        if redact_text(canonical_bytes(self.to_wire()).decode()).occurrences:
            raise ValueError("recovery Task record contains sensitive content")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude_none=True, exclude={"record_sha256"}))

    def validate_integrity(self) -> None:
        RecoveryTaskRecord.model_validate(self.to_wire())
        if self.record_sha256 != self.recompute_sha256():
            raise RecoveryRejected("recovery Task record integrity mismatch")

    def validate_binding(self, plan: RecoveryPlan, authorization: RecoveryAuthorization) -> None:
        self.validate_integrity()
        plan.validate_integrity()
        authorization.validate_integrity()
        expected = {
            "recovery_of_task_id": plan.source.task_id,
            "recovery_of_delivery_id": plan.source.scope.delivery_id,
            "recovery_source_checkpoint_sha256": plan.source.checkpoint_sha256,
            "product_spec_sha256": plan.source.product_spec_sha256,
            "technical_design_sha256": plan.source.technical_design_sha256,
            "execution_plan_sha256": plan.source.execution_plan_sha256,
        }
        if (
            self.recovery_plan_sha256 != plan.plan_sha256
            or authorization.command.plan_sha256 != plan.plan_sha256
            or self.authorization_sha256 != authorization.authorization_sha256
            or not authorization.decision.approved
            or self.task.repository != plan.source.scope.project_root
            or self.task.base_ref != plan.target_base_revision
            or self.task.created_at != plan.created_at
            or self.task.updated_at != plan.created_at
            or self.rebound_request.project_id != plan.source.scope.project_id
            or self.rebound_request.preparation_sha256 != plan.target_preparation_sha256
            or any(self.task.metadata.get(key) != value for key, value in expected.items())
        ):
            raise RecoveryRejected("recovery Task record does not match approved plan")
