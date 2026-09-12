"""Adapter from browser intents to the existing Manager application interfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    DeliveryCheckpointStale,
    ProjectDeliveryResult,
    ReplyToProduct,
    ResumeProjectDelivery,
    UnifiedProjectEntryError,
    UnifiedProjectEntryService,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    ProjectDeliveryCheckpointError,
)
from ai_software_engineer.multi_directory.models import JointDeliveryResult
from ai_software_engineer.multi_directory.service import (
    CreateRequirement,
    JointDeliveryService,
)
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.recovery import RecoveryPlan, RecoveryRejected
from ai_software_engineer.recovery.resume import DeliveryResumeResult
from ai_software_engineer.recovery.verification_records import CandidateVerificationPlan
from ai_software_engineer.runtime_workspace import RuntimeWorkspaceError

from .core import ConsoleCommandRejected
from .models import (
    ConsoleApprovalRequest,
    ConsoleCommandResult,
    ConsoleIntent,
    ContinueDeliveryIntent,
    CreateProjectIntent,
    CreateRequirementIntent,
    ProductApprovalIntent,
    ProductReplyIntent,
)


class TeamConsoleHost(Protocol):
    def create_project(self, *, name: str, project_id: str | None = None) -> ProjectWorkspace: ...
    def project_entry(self, project_id: str | None = None) -> UnifiedProjectEntryService: ...
    def requirement_entry(self, project_id: str | None = None) -> JointDeliveryService: ...

    def resume_delivery(
        self, command: ResumeProjectDelivery, *, project_id: str | None = None
    ) -> DeliveryResumeResult | JointDeliveryResult: ...


class ManagerConsoleAdapter:
    """Keep checkpoint, approval and recovery mechanics behind one intent interface."""

    def __init__(self, host: TeamConsoleHost) -> None:
        self._host = host

    def execute(self, intent: ConsoleIntent) -> ConsoleCommandResult:
        try:
            if isinstance(intent, CreateProjectIntent):
                project = self._host.create_project(
                    name=intent.name,
                    project_id=intent.project_id,
                )
                return ConsoleCommandResult(
                    project_id=project.manifest.project_id,
                    stage="PROJECT_READY",
                    next_action="Create a Requirement and select one or more Repository roots.",
                )
            if isinstance(intent, CreateRequirementIntent):
                created = self._host.requirement_entry(intent.project_id).create(
                    CreateRequirement(
                        name=intent.name,
                        repository_roots=intent.repository_roots,
                    )
                )
                return _summarize(created, project_id=intent.project_id)
            if isinstance(intent, ProductReplyIntent):
                replied = self._entry(intent.project_id, intent.delivery_id).reply(
                    ReplyToProduct(
                        delivery_id=intent.delivery_id,
                        expected_checkpoint_sha256=intent.expected_checkpoint_sha256,
                        message=intent.message,
                    )
                )
                return _summarize(replied, project_id=intent.project_id)
            if isinstance(intent, ProductApprovalIntent):
                approved = self._entry(intent.project_id, intent.delivery_id).approve(
                    ApproveProductSpec(
                        delivery_id=intent.delivery_id,
                        expected_checkpoint_sha256=intent.expected_checkpoint_sha256,
                        approval_reference=(
                            "web-console-product:" + intent.expected_checkpoint_sha256
                        ),
                    )
                )
                return _summarize(approved, project_id=intent.project_id)
            if isinstance(intent, ContinueDeliveryIntent):
                current = (
                    self._entry(intent.project_id, intent.delivery_id)
                    .status(intent.delivery_id)
                    .checkpoint
                )
                if current.checkpoint_sha256 != intent.expected_checkpoint_sha256:
                    raise DeliveryCheckpointStale("displayed delivery checkpoint changed")
                continued = self._host.resume_delivery(
                    ResumeProjectDelivery(
                        delivery_id=intent.delivery_id,
                        approved_plan_sha256=intent.approved_plan_sha256,
                        approval_reference=(
                            "web-console-plan:" + intent.approved_plan_sha256
                            if intent.approved_plan_sha256 is not None
                            else None
                        ),
                    ),
                    project_id=intent.project_id,
                )
                return _summarize(continued, project_id=intent.project_id)
            raise ConsoleCommandRejected("INVALID_INTENT", "Unsupported console operation.")
        except DeliveryCheckpointStale as error:
            raise ConsoleCommandRejected(
                "STALE_CHECKPOINT",
                "The displayed delivery changed. Refresh the workspace and try again.",
            ) from error
        except (
            ProjectDeliveryCheckpointError,
            RecoveryRejected,
            RuntimeWorkspaceError,
            UnifiedProjectEntryError,
            ValueError,
        ) as error:
            raise ConsoleCommandRejected("COMMAND_REJECTED", _safe_summary(error)) from error

    def _entry(
        self, project_id: str, delivery_id: str
    ) -> JointDeliveryService | UnifiedProjectEntryService:
        if delivery_id.startswith("delivery_multi_"):
            return self._host.requirement_entry(project_id)
        return self._host.project_entry(project_id)


def _summarize(
    result: JointDeliveryResult | ProjectDeliveryResult | DeliveryResumeResult,
    *,
    project_id: str,
) -> ConsoleCommandResult:
    checkpoint = result.checkpoint
    approval: ConsoleApprovalRequest | None = None
    next_action = str(checkpoint.next_action)
    if isinstance(result, DeliveryResumeResult):
        next_action = result.next_action
        if result.verification_plan_sha256 is not None:
            verification_plan = CandidateVerificationPlan.model_validate_json(
                Path(cast(str, result.verification_plan_file)).read_text(encoding="utf-8")
            )
            verification_plan.validate_integrity()
            if verification_plan.plan_sha256 != result.verification_plan_sha256:
                raise ValueError("verification approval plan identity mismatch")
            roles = tuple(
                f"{definition.role.value}: "
                f"{definition.provider or 'configured'} / {definition.model}"
                for definition in verification_plan.definitions
                if definition.role.value in {"qa", "reviewer"}
            )
            approval = ConsoleApprovalRequest(
                kind="candidate_verification",
                plan_sha256=verification_plan.plan_sha256,
                title="批准独立 QA 与 Reviewer 验证",
                facts=(f"候选提交 {verification_plan.inputs.candidate_revision}", *roles),
            )
            next_action = "Review and approve the exact candidate verification plan."
        elif result.recovery_plan_sha256 is not None:
            recovery_plan = RecoveryPlan.model_validate_json(
                Path(cast(str, result.recovery_plan_file)).read_text(encoding="utf-8")
            )
            recovery_plan.validate_integrity()
            if recovery_plan.plan_sha256 != result.recovery_plan_sha256:
                raise ValueError("Coder recovery plan identity mismatch")
            approval = ConsoleApprovalRequest(
                kind="coder_recovery",
                plan_sha256=recovery_plan.plan_sha256,
                title="批准 Coder 恢复任务",
                facts=(
                    f"源任务 {recovery_plan.source.task_id}",
                    f"保留改动 {len(recovery_plan.capture.files)} 个文件",
                    f"目标基线 {recovery_plan.target_base_revision}",
                ),
            )
            next_action = "Review and approve the exact Coder recovery plan."
    return ConsoleCommandResult(
        project_id=project_id,
        delivery_id=checkpoint.delivery_id,
        checkpoint_sha256=checkpoint.checkpoint_sha256,
        stage=str(checkpoint.stage),
        next_action=next_action,
        approval=approval,
    )


def _safe_summary(error: Exception) -> str:
    value = str(error).strip()
    if (
        not value
        or len(value) > 500
        or any(ord(character) < 32 and character not in "\t\n" for character in value)
    ):
        return "Manager rejected the operation; inspect current delivery facts."
    return value


__all__ = ["ManagerConsoleAdapter", "TeamConsoleHost"]
