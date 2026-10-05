"""Adapter from browser intents to the existing Manager application interfaces."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from ai_software_engineer.agents.diagnostics import safe_diagnostic
from ai_software_engineer.agents.structured import StructuredModelError
from ai_software_engineer.context.ports import ContextBudgetExceeded
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryWaitInvestigation,
    InspectDeliveryWait,
    ResolveDeliveryWait,
)
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.domain.project_delivery import PlanTestMatrixError
from ai_software_engineer.manager.baseline_models import ExecutionBaselinePlan
from ai_software_engineer.manager.baseline_production import (
    BaselineExecuteCommand,
    BaselineProposeCommand,
)
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
from ai_software_engineer.manager.model_execution import ManagerExecutionRejected
from ai_software_engineer.manager.python_verification import PythonMysqlSandboxCapability
from ai_software_engineer.manager.verification_environment import SwiftSandboxCapability
from ai_software_engineer.multi_directory.deletion import RequirementDeletionRejected
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
from ai_software_engineer.orchestration import AgentRunFailed
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.recovery import RecoveryRejected
from ai_software_engineer.recovery.entry import NativeRecoveryEntry
from ai_software_engineer.recovery.resume import DeliveryResumeResult, JointDeliveryResumeResult
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
    ExecuteExecutionBaselineIntent,
    InspectDeliveryWaitIntent,
    ProductApprovalIntent,
    ProductReplyIntent,
    ProposeExecutionBaselineIntent,
    RecheckDesignIntent,
    RecoverDesignIntent,
    ResolveDeliveryWaitIntent,
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

    def inspect_delivery_wait(
        self,
        command: InspectDeliveryWait,
        *,
        project_id: str,
        delivery_id: str,
    ) -> DeliveryWaitInvestigation: ...

    def resolve_delivery_wait(
        self,
        command: ResolveDeliveryWait,
        *,
        project_id: str,
        delivery_id: str,
    ) -> DeliveryResolution: ...

    def propose_execution_baseline(
        self,
        command: BaselineProposeCommand,
        *,
        project_id: str,
    ) -> ExecutionBaselinePlan: ...

    def execute_execution_baseline(
        self,
        command: BaselineExecuteCommand,
        *,
        project_id: str,
    ) -> ExecutionBaselineBinding: ...


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
                    next_action="需求已删除, 历史交付记录保留用于审计。",
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
            if isinstance(intent, (ProposeExecutionBaselineIntent, ExecuteExecutionBaselineIntent)):
                current = (
                    self._entry(intent.project_id, intent.delivery_id)
                    .status(intent.delivery_id)
                    .checkpoint
                )
                if current.checkpoint_sha256 != intent.expected_checkpoint_sha256:
                    raise DeliveryCheckpointStale("工程执行基线显示的需求 checkpoint 已变化")
                data = intent.model_dump(
                    mode="json", exclude={"action", "project_id", "expected_checkpoint_sha256"}
                )
                if isinstance(intent, ProposeExecutionBaselineIntent):
                    plan = self._host.propose_execution_baseline(
                        BaselineProposeCommand.model_validate(data),
                        project_id=intent.project_id,
                    )
                    return ConsoleCommandResult(
                        project_id=intent.project_id,
                        delivery_id=intent.delivery_id,
                        checkpoint_sha256=current.checkpoint_sha256,
                        stage="ENGINEERING_BASELINE_PLAN",
                        next_action=(
                            "旧改动与目标代码存在冲突, 请提出明确的 Coder 适配计划。"
                            if plan.conflicted
                            else "工程基线计划已封存, 工程人员可决定在原分支继续。"
                        ),
                        execution_baseline_plan=plan,
                    )
                binding = self._host.execute_execution_baseline(
                    BaselineExecuteCommand.model_validate(data),
                    project_id=intent.project_id,
                )
                return ConsoleCommandResult(
                    project_id=intent.project_id,
                    delivery_id=intent.delivery_id,
                    checkpoint_sha256=current.checkpoint_sha256,
                    stage="ENGINEERING_BASELINE_UPDATED",
                    next_action="原分支执行基线已更新并记录工程决定, 继续原需求的独立交付验收。",
                    execution_baseline_binding=binding,
                )
            if isinstance(intent, (InspectDeliveryWaitIntent, ResolveDeliveryWaitIntent)):
                current = (
                    self._entry(intent.project_id, intent.delivery_id)
                    .status(intent.delivery_id)
                    .checkpoint
                )
                if current.checkpoint_sha256 != intent.expected_checkpoint_sha256:
                    raise DeliveryCheckpointStale("displayed engineering wait checkpoint changed")
                bound = {
                    "work_item_id": intent.work_item_id,
                    "expected_disposition_sha256": intent.expected_disposition_sha256,
                    "expected_task_intent_sha256": intent.expected_task_intent_sha256,
                    "expected_source_revision": intent.expected_source_revision,
                    "expected_checkpoint_sequence": intent.expected_checkpoint_sequence,
                }
                if isinstance(intent, InspectDeliveryWaitIntent):
                    proof = self._host.inspect_delivery_wait(
                        InspectDeliveryWait.model_validate(bound),
                        project_id=intent.project_id,
                        delivery_id=intent.delivery_id,
                    )
                    return ConsoleCommandResult(
                        project_id=intent.project_id,
                        delivery_id=intent.delivery_id,
                        checkpoint_sha256=current.checkpoint_sha256,
                        stage="ENGINEERING_INVESTIGATION",
                        next_action=proof.next_action,
                        engineering_wait_investigation=proof,
                    )
                resolution = self._host.resolve_delivery_wait(
                    ResolveDeliveryWait.model_validate(
                        {
                            **bound,
                            "resolution_kind": intent.resolution_kind,
                            "proof_sha256": intent.proof_sha256,
                            "submitted_at": datetime.now(UTC),
                        }
                    ),
                    project_id=intent.project_id,
                    delivery_id=intent.delivery_id,
                )
                return ConsoleCommandResult(
                    project_id=intent.project_id,
                    delivery_id=intent.delivery_id,
                    checkpoint_sha256=current.checkpoint_sha256,
                    stage="ENGINEERING_WAIT_RESOLVED",
                    next_action=(
                        "精确工程决定已记录, 平台以新的执行身份继续原 Task; "
                        "验收仍由独立 QA 和 Review 完成。"
                    ),
                    engineering_wait_resolution=resolution,
                )
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
                        coder_scope_request=intent.coder_scope_request,
                        prerequisite_repair=intent.prerequisite_repair,
                        native_ui_scenario=intent.native_ui_scenario,
                        python_mysql_tests=intent.python_mysql_tests,
                        approved_repair_sha256=intent.approved_repair_sha256,
                        approval_reference=(
                            (
                                "web-console-repair:"
                                if intent.approved_repair_sha256 is not None
                                else "web-console-scope:"
                                if intent.approved_scope_sha256 is not None
                                else "web-console-plan:"
                            )
                            + cast(
                                str,
                                intent.approved_plan_sha256
                                or intent.approved_scope_sha256
                                or intent.approved_repair_sha256,
                            )
                            if (
                                intent.approved_plan_sha256 is not None
                                or intent.approved_scope_sha256 is not None
                                or intent.approved_repair_sha256 is not None
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
        except RequirementDeletionRejected as error:
            raise ConsoleCommandRejected("REQUIREMENT_ACTIVE", _safe_summary(error)) from error
        except ContextBudgetExceeded as error:
            raise ConsoleCommandRejected(
                "CONTEXT_BUDGET_EXHAUSTED",
                "必要上下文超过已配置预算, 未启动受影响的 Agent; 不代表业务验收失败。"
                "已封存报告和审批历史保留。由 Manager 协调上下文配置修复后, "
                "通过继续交付生成并审批新计划; 不要重复执行已消费的审批。",
            ) from error
        except ManagerExecutionRejected as error:
            raise ConsoleCommandRejected("MANAGER_COORDINATION_STOP", str(error)) from error
        except StructuredModelError as error:
            code = (
                "MODEL_EXECUTION_LIMIT" if error.expandable_timeout else "MODEL_" + error.code.value
            )
            raise ConsoleCommandRejected(code, error.safe_message) from error
        except AgentRunFailed as error:
            failure = error.result.error
            code = failure.code.value if failure is not None else error.result.status.value
            detail = (
                failure.message if failure is not None else "Agent returned no successful artifact"
            )
            raise ConsoleCommandRejected(
                "MODEL_" + code,
                safe_diagnostic(f"{error.result.role.value}: {detail}"),
            ) from error
        except PlanTestMatrixError as error:
            raise ConsoleCommandRejected(
                "PLANNER_TEST_MATRIX_REJECTED", _safe_summary(error)
            ) from error
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
    result_diagnostic = (
        result.diagnostic
        if isinstance(result, (ProjectDeliveryResult, DeliveryResumeResult))
        else None
    )
    diagnostic = safe_diagnostic(result_diagnostic) if result_diagnostic else None
    engineering_disposition = None
    # Read-only preparation drift must be visible as the operation's actionable
    # result.  Keeping the checkpoint cursor and exposing the diagnostic are
    # separate facts: the cursor remains immutable, while the browser must not
    # continue to render the stale RUN_DELIVERY action.
    if diagnostic is not None:
        next_action = diagnostic
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
    if isinstance(result, JointDeliveryResumeResult):
        # Approval facts belong to the native plan, but the browser's next command
        # must remain fenced to the newly synchronized parent checkpoint above.
        result = result.continuation
    if isinstance(result, DeliveryResumeResult):
        next_action = result.next_action
        engineering_disposition = result.engineering_disposition
        if result.verification_plan_sha256 is not None:
            if host is None:
                raise ValueError("verification approval requires a trusted plan reader")
            _, verification_plan = host.verification_entry(project_id).open_plan(
                Path(cast(str, result.verification_plan_file))
            )
            if verification_plan.plan_sha256 != result.verification_plan_sha256:
                raise ValueError("verification approval plan identity mismatch")
            accepted_qa = verification_plan.reused_qa
            reviewer_only = accepted_qa is not None
            inconclusive = not reviewer_only and result.verification_completion_sha256 is not None
            roles = tuple(
                f"{definition.role.value}: "
                f"{definition.provider or 'configured'} / {definition.model}"
                for definition in verification_plan.definitions
                if definition.role.value in ({"reviewer"} if reviewer_only else {"qa", "reviewer"})
            )
            qa_facts = (
                (
                    f"复用已封存 QA PASS {accepted_qa.artifact_id}",
                    *(
                        (
                            f"独立验证 QA 来源计划 {verification_plan.retained_qa.plan_sha256}; "
                            f"QA 入场 {verification_plan.retained_qa.qa_invocation_sha256}; "
                            "仅恢复 Reviewer, 不补造原 Task 的 QA 通过事件。",
                        )
                        if verification_plan.retained_qa is not None
                        else ()
                    ),
                )
                if accepted_qa is not None
                else ()
            )
            swift_commands = tuple(
                sorted(
                    {
                        command
                        for definition in verification_plan.definitions
                        if definition.role.value in {"qa", "reviewer"}
                        for command in definition.permissions.commands
                        if command.startswith("swift ")
                    }
                )
            )
            approval = ConsoleApprovalRequest(
                kind="candidate_verification",
                plan_sha256=verification_plan.plan_sha256,
                title=(
                    "复用已通过 QA 并只重新执行 Reviewer"
                    if reviewer_only
                    else (
                        "解决 QA 验证阻塞后重新批准"
                        if inconclusive
                        else "批准独立 QA 与 Reviewer 验证"
                    )
                ),
                facts=(
                    f"候选提交 {verification_plan.inputs.candidate_revision}",
                    *(
                        (
                            f"Manager 协调方案 {verification_plan.manager_advice.advice_sha256}: "
                            f"{verification_plan.manager_advice.draft.summary}",
                            *(
                                f"{criterion.criterion_id}: {', '.join(criterion.step_names)}; "
                                f"预期观察: {criterion.expected_observation}"
                                for criterion in verification_plan.manager_advice.draft.criteria
                            ),
                        )
                        if verification_plan.manager_advice
                        else ()
                    ),
                    *qa_facts,
                    *(
                        (
                            "复用精确历史 QA 图片证据: "
                            f"计划 {verification_plan.prior_visual_evidence.plan_sha256}; "
                            f"记录 {verification_plan.prior_visual_evidence.record_sha256}。"
                            "仅同候选前驱记录, 最多 6 张旧图加 6 张本轮新图; "
                            "不重放旧操作、不继承旧验收结论。",
                        )
                        if verification_plan.prior_visual_evidence is not None
                        else ()
                    ),
                    *(
                        (
                            "Manager 环境阻塞记录: "
                            f"{verification_plan.prerequisite_incident_sha256}; "
                            "等待人工核对前提",
                        )
                        if verification_plan.prerequisite_incident_sha256
                        else ()
                    ),
                    *(
                        (
                            "受控能力 codex_sandbox_swiftpm_v1: "
                            "独立 QA/Reviewer 的 build 与 XCTest; "
                            "仅执行器关闭 SwiftPM 内层沙箱, 保留 Codex 外层源码只读、"
                            "独立临时目录可写、网络禁用。不授权普通 Agent 命令扩权; "
                            "UI 验收仍须单独完成。",
                        )
                        if isinstance(verification_plan.executor_capability, SwiftSandboxCapability)
                        else ()
                    ),
                    *(
                        (
                            "受控 Python/MySQL 验证: 每个独立角色使用短寿命、无网络的专用 MySQL; "
                            "源码只读, Task 禁止路径不可读, 仅私有 scratch 可写。仅证明 SQL 行为, "
                            "不证明 TCP/DNS/TLS; 不扩大普通 Agent 命令权限。",
                            *(
                                f"精确增量测试 {s.node_id}: {', '.join(s.criterion_ids)}"
                                for s in verification_plan.executor_capability.selections
                            ),
                        )
                        if isinstance(
                            verification_plan.executor_capability, PythonMysqlSandboxCapability
                        )
                        else ()
                    ),
                    *((safe_diagnostic(result.next_action),) if inconclusive else ()),
                    *(
                        (
                            "独立原生 UI 能力 macos_mock_ax_v1: 仅启动隔离 Mock, "
                            "构建仍用 Codex 沙箱; GUI 使用独立 Seatbelt 禁网、源码不可写、"
                            "用户目录/Keychain 不可读、仅私有临时目录可写。"
                            "AX 驱动只读写此子进程的指定窗口, 不操作系统菜单或其他 App。",
                            f"精确 UI 计划: {verification_plan.native_ui.model_dump_json()}",
                        )
                        if verification_plan.native_ui is not None
                        else ()
                    ),
                    *(f"受限验证命令: {command}" for command in swift_commands),
                    *roles,
                ),
            )
            next_action = (
                "请检查并批准仅重新执行 Reviewer 的精确验证计划。"
                if reviewer_only
                else safe_diagnostic(result.next_action)
            )
        elif result.prerequisite_repair_plan is not None:
            repair = result.prerequisite_repair_plan
            repair.validate_integrity()
            approval = ConsoleApprovalRequest(
                kind="prerequisite_repair",
                plan_sha256=repair.plan_sha256,
                title="批准源码前提修复任务",
                facts=(
                    (
                        f"执行器前提证据 {repair.executor_prerequisite_sha256} (非 QA 结论)"
                        if repair.executor_prerequisite_sha256 is not None
                        else f"Manager 阻塞 {repair.incident_sha256}"
                    ),
                    f"源候选 {repair.candidate_revision}",
                    f"目标基线 {repair.target_base_revision}",
                    f"修复目标 {repair.request.objective}",
                    *(f"补充写入范围 {path}" for path in repair.request.write_paths),
                    "由 ASE Coder 实施, 不导入操作员草稿; "
                    "保留原验收标准, 独立 QA/Reviewer 验收新候选。",
                    "不授权安装、网络、合并、部署、凭据访问或修改历史结论。",
                ),
            )
        elif result.interruption_plan is not None:
            interruption = result.interruption_plan
            interruption.validate_integrity()
            approval = ConsoleApprovalRequest(
                kind="coder_interruption",
                plan_sha256=interruption.plan_sha256,
                title="批准中断后的单次 Coder 续跑",
                facts=(
                    f"保留同一任务 {interruption.task_id} 和工作目录",
                    f"旧执行租约于 {interruption.expired_lease.expires_at.isoformat()} 失效",
                    *(
                        (
                            "旧执行已停止。本次批准中断时的完整改动快照, 原 seed 与历史不改写。",
                            f"保留快照 {interruption.stopped_capture.capture_sha256}",
                            *(
                                f"保留文件 {file.path}"
                                for file in interruption.stopped_capture.files
                            ),
                        )
                        if interruption.stopped_capture is not None
                        else ("旧执行已停止。保留改动与已批准 seed 完全一致。",)
                    ),
                    "没有候选或后续角色验收结果。",
                    "只批准一次新租约、新 Run。原调用、审批和失败历史保留。不退还或重置预算。",
                    "权限和验收范围不变。完成实现后仍须独立 QA 和 Reviewer。不授权合并或部署。",
                ),
            )
        elif result.restart_plan is not None:
            restart = result.restart_plan
            restart.validate_integrity()
            approval = ConsoleApprovalRequest(
                kind="pre_execution_restart",
                plan_sha256=restart.plan_sha256,
                title="批准 Coder 启动前重启",
                facts=(
                    f"原任务 {restart.source_task_id}",
                    (
                        "原任务在 Coder 知识咨询时超时; 知识模型调用已保留, "
                        "代码开发尚未启动, 没有代码或候选需要恢复。"
                        if restart.restart_kind == "pre_agent_knowledge_timeout"
                        else "原任务在 Coder 启动前安全停止, 没有代码或候选需要恢复。"
                    ),
                    *(
                        (f"原基线 {restart.source_base_revision}",)
                        if restart.source_base_revision
                        else ()
                    ),
                    f"目标基线 {restart.target_base_revision}",
                    *(
                        (f"目标分支 {restart.target_branch_name}",)
                        if restart.target_branch_name
                        else ()
                    ),
                    f"上下文输入上限 {restart.context_budget.max_input_tokens}; "
                    f"输出预留 {restart.context_budget.reserved_output_tokens}",
                    "保留原需求、审批和失败历史; 创建新 Task, 不重置旧 Task。",
                    "新 Task 仍须经过独立 Coder、QA、Reviewer, 不授权扩范围、合并或部署。",
                ),
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
                        ("从干净基线重新实现; 完整旧补丁作为历史输入, 不直接应用。",)
                        if recovery_plan.input_mode == "coder_reapply"
                        else ()
                    ),
                    *(
                        f"仅保留审计, 禁止重新应用的规范改动 {path}"
                        for path in (recovery_plan.quarantined_paths or ())
                    ),
                    *(
                        (f"目标分支 {recovery_plan.target_branch_name}",)
                        if recovery_plan.target_branch_name is not None
                        else ()
                    ),
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
            next_action = "请检查并批准精确的 Coder 恢复计划。"
        elif result.scope_supplement_sha256 is not None:
            approval = ConsoleApprovalRequest(
                kind="coder_scope",
                plan_sha256=result.scope_supplement_sha256,
                title="批准补充 Coder 文件范围",
                coder_scope_request=result.coder_scope_request,
                facts=(
                    "以下精确文件不在原任务授权范围内。批准仅对本次恢复生效。",
                    *(
                        (
                            f"已接纳 Coder 进度 {result.coder_scope_request.progress_artifact_id}; "
                            f"SHA-256 {result.coder_scope_request.progress_sha256}",
                            f"补充原因 {result.coder_scope_request.reason}",
                            "请求中的文件尚未修改; 批准只扩大新恢复任务的精确文件范围。",
                        )
                        if result.coder_scope_request
                        else ()
                    ),
                    *(f"待补充文件 {path}" for path in result.scope_supplement_paths),
                ),
            )
            next_action = "请检查并批准精确的遗漏文件路径。"
    return ConsoleCommandResult(
        project_id=project_id,
        delivery_id=checkpoint.delivery_id,
        checkpoint_sha256=checkpoint.checkpoint_sha256,
        stage=str(checkpoint.stage),
        next_action=next_action,
        diagnostic=diagnostic,
        approval=approval,
        engineering_disposition=engineering_disposition,
    )


def _safe_summary(error: Exception) -> str:
    value = str(error).strip()
    if (
        not value
        or len(value) > 500
        or any(ord(character) < 32 and character not in "\t\n" for character in value)
    ):
        return "Manager 拒绝了该操作，请检查当前交付事实。"  # noqa: RUF001
    return value


__all__ = ["ManagerConsoleAdapter", "TeamConsoleHost"]
