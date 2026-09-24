"""Adapter from browser intents to the existing Manager application interfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from ai_software_engineer.agents.structured import StructuredModelError
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
from ai_software_engineer.multi_directory.errors import (
    RequirementGitBaselineRequired,
    RequirementSourceRevisionDrift,
)
from ai_software_engineer.multi_directory.models import JointDeliveryResult, digest
from ai_software_engineer.multi_directory.service import (
    CloseRequirement,
    CreateRequirement,
    DeleteRequirement,
    JointDeliveryService,
    RecheckDesign,
    RecoverDesign,
    RestartRequirement,
    UpdateRequirement,
)
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.recovery import RecoveryRejected
from ai_software_engineer.recovery.entry import NativeRecoveryEntry
from ai_software_engineer.recovery.resume import DeliveryResumeResult
from ai_software_engineer.recovery.verification_entry import CandidateVerificationEntry
from ai_software_engineer.runtime_workspace import RuntimeWorkspaceError

from .core import ConsoleCommandRejected
from .models import (
    CloseRequirementIntent,
    ConsoleApprovalRequest,
    ConsoleCommandResult,
    ConsoleIntent,
    ContinueDeliveryIntent,
    CreateProjectIntent,
    CreateRequirementIntent,
    DeleteRequirementIntent,
    ProductApprovalIntent,
    ProductReplyIntent,
    RecheckDesignIntent,
    RecoverDesignIntent,
    RestartRequirementIntent,
    UpdateRequirementIntent,
)


class TeamConsoleHost(Protocol):
    def create_project(self, *, name: str, project_id: str | None = None) -> ProjectWorkspace: ...
    def project_entry(self, project_id: str | None = None) -> UnifiedProjectEntryService: ...
    def requirement_entry(self, project_id: str | None = None) -> JointDeliveryService: ...
    def recovery_entry(self, project_id: str | None = None) -> NativeRecoveryEntry: ...
    def verification_entry(self, project_id: str | None = None) -> CandidateVerificationEntry: ...

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
            if isinstance(intent, UpdateRequirementIntent):
                updated = self._host.requirement_entry(intent.project_id).update_requirement(
                    UpdateRequirement(
                        delivery_id=intent.delivery_id,
                        expected_checkpoint_sha256=intent.expected_checkpoint_sha256,
                        name=intent.name,
                        repository_roots=intent.repository_roots,
                    )
                )
                return _summarize(updated, project_id=intent.project_id)
            if isinstance(intent, CloseRequirementIntent):
                closed = self._host.requirement_entry(intent.project_id).close_requirement(
                    CloseRequirement(
                        delivery_id=intent.delivery_id,
                        expected_checkpoint_sha256=intent.expected_checkpoint_sha256,
                    )
                )
                return _summarize(closed, project_id=intent.project_id)
            if isinstance(intent, RestartRequirementIntent):
                restarted = self._host.requirement_entry(intent.project_id).restart_requirement(
                    RestartRequirement(
                        delivery_id=intent.delivery_id,
                        expected_checkpoint_sha256=intent.expected_checkpoint_sha256,
                    )
                )
                return _summarize(restarted, project_id=intent.project_id)
            if isinstance(intent, DeleteRequirementIntent):
                self._host.requirement_entry(intent.project_id).delete_requirement(
                    DeleteRequirement(
                        delivery_id=intent.delivery_id,
                        expected_checkpoint_sha256=intent.expected_checkpoint_sha256,
                    )
                )
                return ConsoleCommandResult(
                    project_id=intent.project_id,
                    stage="REQUIREMENT_DELETED",
                    next_action="Requirement removed from the current Project view.",
                )
            if isinstance(intent, ProductReplyIntent):
                replied = self._entry(intent.project_id, intent.delivery_id).reply(
                    ReplyToProduct(
                        delivery_id=intent.delivery_id,
                        expected_checkpoint_sha256=intent.expected_checkpoint_sha256,
                        message=intent.message,
                        screenshot_ids=intent.screenshot_ids,
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
            if isinstance(intent, RecheckDesignIntent):
                entry = self._entry(intent.project_id, intent.delivery_id)
                if not isinstance(entry, JointDeliveryService):
                    raise ConsoleCommandRejected(
                        "COMMAND_REJECTED", "Only joint upstream gaps can be rechecked."
                    )
                result = entry.recheck_design(
                    RecheckDesign(
                        delivery_id=intent.delivery_id,
                        expected_checkpoint_sha256=intent.expected_checkpoint_sha256,
                        operator_id="web-console",
                        request_reference="web-console-design-recheck:"
                        + intent.expected_checkpoint_sha256,
                    )
                )
                return _summarize(result, project_id=intent.project_id)
            if isinstance(intent, RecoverDesignIntent):
                recovered = self._entry(intent.project_id, intent.delivery_id)
                if not isinstance(recovered, JointDeliveryService):
                    raise ConsoleCommandRejected(
                        "COMMAND_REJECTED",
                        "Design recovery is only available for joint Requirements.",
                    )
                result = recovered.recover_design(
                    RecoverDesign(
                        delivery_id=intent.delivery_id,
                        expected_checkpoint_sha256=intent.expected_checkpoint_sha256,
                        operator_id="web-console",
                        rationale=(
                            "Approved knowledge resolution authorizes Design budget recovery."
                        ),
                        approval_reference=(
                            "web-console-design-recovery:" + intent.expected_checkpoint_sha256
                        ),
                    )
                )
                return _summarize(result, project_id=intent.project_id)
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
                        approved_scope_sha256=intent.approved_scope_sha256,
                        approval_reference=(
                            (
                                "web-console-scope:"
                                if intent.approved_scope_sha256 is not None
                                else "web-console-plan:"
                            )
                            + cast(
                                str,
                                intent.approved_plan_sha256 or intent.approved_scope_sha256,
                            )
                            if (
                                intent.approved_plan_sha256 is not None
                                or intent.approved_scope_sha256 is not None
                            )
                            else None
                        ),
                    ),
                    project_id=intent.project_id,
                )
                return _summarize(
                    continued,
                    project_id=intent.project_id,
                    host=self._host,
                )
            raise ConsoleCommandRejected("INVALID_INTENT", "Unsupported console operation.")
        except DeliveryCheckpointStale as error:
            raise ConsoleCommandRejected(
                "STALE_CHECKPOINT",
                "The displayed delivery changed. Refresh the workspace and try again.",
            ) from error
        except StructuredModelError as error:
            raise ConsoleCommandRejected("MODEL_" + error.code.value, error.safe_message) from error
        except RequirementGitBaselineRequired as error:
            raise ConsoleCommandRejected(
                "GIT_BASELINE_REQUIRED",
                _safe_summary(error),
            ) from error
        except RequirementSourceRevisionDrift as error:
            raise ConsoleCommandRejected(
                "SOURCE_REVISION_DRIFT",
                _safe_summary(error),
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
    host: TeamConsoleHost | None = None,
) -> ConsoleCommandResult:
    checkpoint = result.checkpoint
    approval: ConsoleApprovalRequest | None = None
    next_action = str(checkpoint.next_action)
    if isinstance(result, JointDeliveryResult) and result.integration_retry_proposal is not None:
        proposal = result.integration_retry_proposal
        approval = ConsoleApprovalRequest(
            kind="joint_integration",
            plan_sha256=digest(proposal),
            title="批准一次补充联合验收",
            facts=(
                "原有 3 次验收记录完整保留。仅为以下已通过 QA/Review 的候选增加 1 次机会。",
                "平台可能重新规划验收命令。不会重新执行已完成仓库的 Coder、QA 或 Reviewer。",
                *(
                    f"候选 {candidate.unit_id}: {candidate.revision}"
                    for candidate in proposal.candidates
                ),
            ),
        )
        next_action = "联合验收预算已用完。请确认候选并批准一次补充验收。"
    if isinstance(result, DeliveryResumeResult):
        next_action = result.next_action
        if result.verification_plan_sha256 is not None:
            if host is None:
                raise ValueError("verification approval requires a trusted plan reader")
            _, verification_plan = host.verification_entry(project_id).open_plan(
                Path(cast(str, result.verification_plan_file))
            )
            if verification_plan.plan_sha256 != result.verification_plan_sha256:
                raise ValueError("verification approval plan identity mismatch")
            accepted_qa = verification_plan.inputs.accepted_qa
            reviewer_only = accepted_qa is not None
            roles = tuple(
                f"{definition.role.value}: "
                f"{definition.provider or 'configured'} / {definition.model}"
                for definition in verification_plan.definitions
                if definition.role.value in ({"reviewer"} if reviewer_only else {"qa", "reviewer"})
            )
            qa_facts = (
                (f"复用已封存 QA PASS {accepted_qa.artifact_id}",)
                if accepted_qa is not None
                else ()
            )
            approval = ConsoleApprovalRequest(
                kind="candidate_verification",
                plan_sha256=verification_plan.plan_sha256,
                title=(
                    "复用已通过 QA 并只重新执行 Reviewer"
                    if reviewer_only
                    else "批准独立 QA 与 Reviewer 验证"
                ),
                facts=(
                    f"候选提交 {verification_plan.inputs.candidate_revision}",
                    *qa_facts,
                    *roles,
                ),
            )
            next_action = (
                "请检查并批准仅重新执行 Reviewer 的精确验证计划。"
                if reviewer_only
                else "Review and approve the exact candidate verification plan."
            )
        elif result.recovery_plan_sha256 is not None:
            if host is None:
                raise ValueError("Coder recovery approval requires a trusted plan reader")
            _, recovery_plan = host.recovery_entry(project_id).open_plan(
                Path(cast(str, result.recovery_plan_file))
            )
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
                    *(
                        f"已补充文件范围 {path}"
                        for path in (
                            recovery_plan.scope_supplement.paths
                            if recovery_plan.scope_supplement is not None
                            else ()
                        )
                    ),
                    *(
                        f"写入目录修正 {item.source_path} → {item.target_path}"
                        for item in recovery_plan.effective_path_rebindings
                    ),
                ),
            )
            next_action = "Review and approve the exact Coder recovery plan."
        elif result.scope_supplement_sha256 is not None:
            approval = ConsoleApprovalRequest(
                kind="coder_scope",
                plan_sha256=result.scope_supplement_sha256,
                title="批准补充 Coder 文件范围",
                facts=(
                    "以下改动文件不在原任务授权范围内。批准仅对本次恢复生效。",
                    *(f"待补充文件 {path}" for path in result.scope_supplement_paths),
                ),
            )
            next_action = "Review and approve the exact omitted file paths."
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
