"""Typed current facts for reentering a released rejected-candidate pause.

This transient proof grants no authority on its own. Production composition
holds the real Task process lock and idle SQL fence while checking the committed
exact release and appending the public delivery cursor.
"""

from typing import Annotated

from pydantic import Field, StrictInt

from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import OperatorDuty
from ai_software_engineer.domain.enums import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.execution_baseline import BaselinePurpose, ExecutionBaselineBinding
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import Task, task_matches_dispatch
from ai_software_engineer.manager.baseline_models import (
    ExecutionBaselinePlan,
    require_rejected_candidate_binding,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryStage,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.work_queue.baseline import BaselineQueueRelease
from ai_software_engineer.work_queue.models import QueuedWorkItem


class RejectedCandidateReentryProof(DomainModel):
    """One committed, still-unclaimed exact RESUME of the current rescue."""

    checkpoint_sha256: StageSha256
    plan: ExecutionBaselinePlan
    binding: ExecutionBaselineBinding
    work_item: QueuedWorkItem
    release: BaselineQueueRelease | None
    task: Task
    task_revision: Annotated[StrictInt, Field(ge=1)]

    def require_for(self, checkpoint: ProjectDeliveryCheckpoint) -> None:
        self.plan.validate_integrity()
        binding, item = self.binding, self.work_item
        require_rejected_candidate_binding(self.plan, binding)
        binding.require_task(self.task)
        proof, reservation = self.plan.facts.rejected_candidate_output, self.plan.facts.continuation
        if proof is None or reservation is None:
            raise ValueError("候选恢复重新进入交付缺少原候选和普通工作预留")
        if (
            checkpoint.checkpoint_sha256 != self.checkpoint_sha256
            or checkpoint.stage not in {DeliveryStage.BLOCKED, DeliveryStage.FAILED}
            or checkpoint.failed_stage is not DeliveryStage.DELIVERING
            or checkpoint.failure_code is not DeliveryFailureCode.INVARIANT_VIOLATION
            or checkpoint.task_status is not TaskStatus.IMPLEMENTING
            or checkpoint.candidate_revision is not None
            or checkpoint.task_id != self.task.id
            or checkpoint.task_revision != self.task_revision
            or checkpoint.dispatch_commit_sha256 != proof.capture_start.scope.dispatch_sha256
            or checkpoint.delivery_id != proof.capture_start.scope.requirement_id
            or checkpoint.repository_id != binding.scope.repository_id
            or checkpoint.repository_root != binding.scope.repository_root
            or self.plan.purpose is not BaselinePurpose.REJECTED_CANDIDATE_RESCUE
            or self.task.status is not TaskStatus.IMPLEMENTING
            or not task_matches_dispatch(self.task, self.plan.facts.task)
            or self.task.attempts != reservation.next_execution_attempt
            or self.task.work_attempt != self.plan.facts.task.work_attempt + 1
            or self.task.retry_failures != self.plan.facts.task.retry_failures
            or item.task_id != self.task.id
            or item.attempt != self.task.attempts
            or item.parent_work_item_id != proof.work_item_id
            or item.repository_id != checkpoint.repository_id
            or item.repository_scopes != (checkpoint.repository_root,)
            or item.checkpoint_sequence != self.task_revision
        ):
            raise ValueError("已释放候选恢复与原需求、分配、Task或精确继续决定不一致")
        if self.release is None:
            disposition = item.wait_disposition
            if (
                item.status is not WorkItemStatus.WAITING_HUMAN
                or disposition is None
                or disposition.facts.classification != "EXECUTION_BASELINE_PAUSED"
                or disposition.facts.execution_baseline_sha256 != binding.binding_sha256
                or disposition.facts.source_revision != binding.execution_source_revision
                or disposition.facts.task_intent_sha256 != task_intent_sha256(self.task)
            ):
                raise ValueError("候选恢复尚未形成精确保留暂停")
            return
        release = BaselineQueueRelease.model_validate(self.release.to_wire())
        authorization = release.authorization
        authorization.principal.require_duty(OperatorDuty.ENGINEERING)
        if (
            release.binding != binding
            or release.ready_work_item != item
            or authorization.task_revision != self.task_revision
            or authorization.checkpoint_sequence != self.task_revision
            or authorization.task_intent_sha256 != task_intent_sha256(self.task)
        ):
            raise ValueError("候选恢复未绑定已提交的精确继续决定")
