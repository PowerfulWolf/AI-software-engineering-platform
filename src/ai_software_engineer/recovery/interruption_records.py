"""Exact authority for one replacement invocation of an unchanged recovery seed."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StrictInt

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.domain.workforce import LeaseId, TaskLease
from ai_software_engineer.recovery.models import RecoveryRejected, RecoveryScope, digest
from ai_software_engineer.work_queue.models import WorkItemId


class RecoveryInterruptionPlan(DomainModel):
    kind: Literal["recovery_interruption_plan"] = "recovery_interruption_plan"
    schema_version: Literal["v0.1"] = "v0.1"
    scope: RecoveryScope
    recovery_plan_sha256: StageSha256
    authorization_sha256: StageSha256
    seed_record_sha256: StageSha256
    invocation_record_sha256: StageSha256
    task_id: TaskId
    task_sha256: StageSha256
    events_sha256: StageSha256
    task_revision: Annotated[StrictInt, Field(ge=1)]
    dispatch_sha256: StageSha256
    work_item_id: WorkItemId
    dispatch_sequence: Annotated[StrictInt, Field(ge=0)]
    expired_lease: TaskLease
    created_at: AwareDatetime
    plan_sha256: StageSha256

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"plan_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.plan_sha256 != self.recompute_sha256():
            raise RecoveryRejected("interruption plan digest mismatch")
        if self.expired_lease.expires_at > self.created_at:
            raise RecoveryRejected("interruption plan requires an expired lease")


class RecoveryInterruptionInvocation(DomainModel):
    kind: Literal["recovery_interruption_invocation"] = "recovery_interruption_invocation"
    schema_version: Literal["v0.1"] = "v0.1"
    plan_sha256: StageSha256
    authorization_sha256: StageSha256
    previous_invocation_sha256: StageSha256
    request: AgentRequest
    lease_id: LeaseId
    dispatch_sequence: Annotated[StrictInt, Field(ge=1)]
    admitted_at: AwareDatetime
    record_sha256: StageSha256

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"record_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.record_sha256 != self.recompute_sha256():
            raise RecoveryRejected("interruption invocation digest mismatch")
