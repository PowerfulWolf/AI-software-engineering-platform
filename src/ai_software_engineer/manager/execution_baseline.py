"""Exact same-Task baseline recovery, separate from product approval and platform upgrade."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.artifact import CoderProgressArtifact, ImplementationReportArtifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import (
    EngineeringAdmission,
    EngineeringCapability,
)
from ai_software_engineer.domain.enums import TaskStatus
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselineInputMode,
    BaselinePurpose,
    CoderExecutionInput,
    ExecutionBaselineBinding,
    RetainedExecutionPatch,
    resolve_coder_execution_input,
)
from ai_software_engineer.domain.execution_native_rules import NativeRuleEpoch
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git.baseline import (
    BaselineGitConflict,
    BaselineGitPreview,
    GitExecutionBaselineAdapter,
)
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.git.mutation_capture import WorktreeMutationCapture
from ai_software_engineer.git.ports import WorktreeRef
from ai_software_engineer.manager.baseline_models import (
    BaselineContinueAuthorization,
    BaselineExecutionFacts,
    BaselineOperationStart,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
    require_context_capacity_binding,
    require_knowledge_isolation_binding,
    require_rejected_candidate_binding,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.completed_output_checkpoint import (
    CompletedCoderOutputReason,
    require_completed_output_workspace,
)
from ai_software_engineer.manager.engineering_authority import EngineeringAuthority
from ai_software_engineer.manager.knowledge_isolation import KnowledgePreparationIsolationProof
from ai_software_engineer.manager.legacy_containment import LegacyExecutionContainment
from ai_software_engineer.manager.legacy_snapshot import require_complete_legacy_inventory
from ai_software_engineer.manager.stopped_execution_checkpoint import (
    require_stopped_coder_workspace,
)
from ai_software_engineer.manager.stopped_failure_checkpoint import (
    require_stopped_failure_workspace,
)
from ai_software_engineer.manager.stopped_provider_checkpoint import (
    require_stopped_provider_workspace,
)
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.redaction import source_inspection_scope


class BaselineFactCollector(Protocol):
    """Trusted production composition holds an exclusive Task lock/queue fence.

    collect must verify no active lease/model process, exact stopped/definitive
    invocation proof, immutable selected artifacts/native rules, current Task
    revision and remaining budget. Target rules cannot expand Task permissions.
    """

    def collect(self, target_base_ref: str | None) -> BaselineExecutionFacts: ...

    def source_worktree(self, facts: BaselineExecutionFacts) -> WorktreeRef: ...

    def completed_task(self, binding: ExecutionBaselineBinding) -> Task: ...

    def execution_scope(self) -> AbstractContextManager[None]: ...

    def bind_legacy_observation(self, containment: LegacyExecutionContainment) -> None: ...

    def bind_knowledge_isolation(self, proof: KnowledgePreparationIsolationProof) -> None: ...


class ExecutionBaselineService:
    def __init__(
        self,
        *,
        store: FileExecutionBaselineStore,
        git: GitExecutionBaselineAdapter,
        facts: BaselineFactCollector,
        publish_completion: Callable[[ExecutionBaselinePlan, ExecutionBaselineBinding], None]
        | None = None,
        publish_continuation: Callable[
            [ExecutionBaselineBinding, BaselineContinueAuthorization], bool
        ]
        | None = None,
    ) -> None:
        self.store, self.git, self.facts = store, git, facts
        self.publish_completion = publish_completion
        self.publish_continuation = publish_continuation

    def propose(
        self,
        target_base_ref: str | None,
        *,
        input_mode: BaselineInputMode = BaselineInputMode.PRESERVE_DRAFT,
        purpose: BaselinePurpose = BaselinePurpose.SOURCE_REBIND,
    ) -> ExecutionBaselinePlan:
        if purpose in {
            BaselinePurpose.COMPLETED_OUTPUT_RESCUE,
            BaselinePurpose.REJECTED_CANDIDATE_RESCUE,
            BaselinePurpose.STOPPED_PROVIDER_RETRY,
            BaselinePurpose.STOPPED_FAILURE_RETRY,
            BaselinePurpose.STOPPED_EXECUTION_RESCUE,
            BaselinePurpose.CONTEXT_CAPACITY_RESUME,
            BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION,
        }:
            if target_base_ref is not None or input_mode is not BaselineInputMode.PRESERVE_DRAFT:
                raise ValueError(
                    "容量恢复由平台核验当前基线, 不能指定目标或重放模式"
                    if purpose is BaselinePurpose.CONTEXT_CAPACITY_RESUME
                    else "已结束执行恢复由平台核验原基线, 不能指定目标或重放模式"
                )
        elif target_base_ref is None:
            raise ValueError("执行基线准备缺少精确目标版本")
        with source_inspection_scope(), self.store.execution_lock(), self.facts.execution_scope():
            facts = self.facts.collect(target_base_ref)
            self._require_facts(facts)
            if (purpose is BaselinePurpose.REJECTED_CANDIDATE_RESCUE) != (
                facts.rejected_candidate_output is not None
            ):
                raise ValueError("候选报告恢复只能使用独立精确方案")
            if (purpose is BaselinePurpose.STOPPED_FAILURE_RETRY) != (
                facts.stopped_failure is not None
            ):
                raise ValueError("原执行失败恢复只能使用独立同基线方案")
            previous = self.store.bindings_for_task(facts.task.id)
            binding = previous[-1] if previous else None
            if purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                current_containment = facts.legacy_containment
                for completed in previous:
                    prior_plan = self.store.plan(completed.plan_sha256)
                    prior_containment = prior_plan.facts.legacy_containment
                    if (
                        current_containment is not None
                        and prior_containment is not None
                        and prior_containment.original_start == current_containment.original_start
                    ):
                        self.facts.bind_legacy_observation(prior_containment)
                        facts = self.facts.collect(target_base_ref)
                        self._require_facts(facts)
                        if facts != prior_plan.facts:
                            raise ValueError("已批准的救援输入发生变化, 保留现场并等待工程检查")
                        self.git.manager.verify_mutations(
                            prior_plan.dirty_capture.to_capture(),
                            facts.permissions,
                            denied_paths=facts.denied_paths,
                        )
                        self.git.manager.verify_mutations(
                            prior_plan.complete_capture.to_capture(),
                            facts.permissions,
                            denied_paths=facts.denied_paths,
                        )
                        inventory = capture_mutation_inventory(
                            Path(prior_plan.dirty_capture.worktree_path)
                        )
                        if inventory != prior_plan.before_inventory:
                            raise ValueError("已批准的救援现场发生变化, 保留文件并等待工程检查")
                        require_complete_legacy_inventory(
                            self.git.manager, prior_plan.dirty_capture, inventory
                        )
                        if (
                            self.facts.collect(target_base_ref) != facts
                            or capture_mutation_inventory(
                                Path(prior_plan.dirty_capture.worktree_path)
                            )
                            != inventory
                        ):
                            raise ValueError(
                                "检查期间已批准的救援现场发生变化, 保留文件并等待工程检查"
                            )
                        # Keep the old exact authority reachable from Console:
                        # a failed proposal must not hide its retry button.
                        return prior_plan
            worktree = self.facts.source_worktree(facts)
            expected_base = (
                binding.execution_base_ref if binding is not None else facts.task.base_ref
            )
            if purpose is BaselinePurpose.STOPPED_EXECUTION_RESCUE:
                if facts.stopped_execution is None:
                    raise ValueError("原执行不符合已停止但结果未知的精确恢复前提, 原现场保留")
                target_base_ref = expected_base
            elif purpose is BaselinePurpose.REJECTED_CANDIDATE_RESCUE:
                proof = facts.rejected_candidate_output
                if proof is None or proof.candidate_parent_revision != expected_base:
                    raise ValueError("原候选没有精确拒绝报告和完整停止证明, 原现场保留")
                prior_source = binding.execution_source_revision if binding else facts.task.base_ref
                if proof.request.source_revision != prior_source:
                    raise ValueError("原候选拒绝证明与先前执行源不同")
                target_base_ref = expected_base
            elif purpose is BaselinePurpose.COMPLETED_OUTPUT_RESCUE:
                if facts.completed_output is None or facts.legacy_containment is not None:
                    raise ValueError("原执行不符合已结束且报告未接纳的精确恢复前提, 原现场保留")
                target_base_ref = expected_base
            elif purpose is BaselinePurpose.STOPPED_PROVIDER_RETRY:
                if facts.stopped_provider_failure is None:
                    raise ValueError("原执行不符合已停止的提供方前提失败恢复条件, 原现场保留")
                target_base_ref = expected_base
            elif purpose is BaselinePurpose.STOPPED_FAILURE_RETRY:
                if facts.stopped_failure is None:
                    raise ValueError("原执行不符合已停止的原执行失败恢复条件, 原现场保留")
                target_base_ref = expected_base
            elif purpose is BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION:
                if facts.knowledge_isolation is None:
                    raise ValueError("当前知识隔离缺少完整可信调查")
                target_base_ref = expected_base
            elif purpose is BaselinePurpose.CONTEXT_CAPACITY_RESUME:
                if facts.context_capacity_receipt_sha256 is None:
                    raise ValueError("当前没有精确的调用前容量停止记录, 原进度保留")
                target_base_ref = expected_base
            assert target_base_ref is not None
            retained_paths = StoredCoderExecutionInputResolver(self.store).retained_source_paths(
                facts.task, workspace_root=worktree.path, permissions=facts.permissions
            )
            dirty = self.git.manager.capture_mutations(
                worktree,
                facts.permissions,
                denied_paths=facts.denied_paths,
                include_ignored=purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE,
                retained_source_paths=retained_paths,
            )
            complete = self.git.manager.capture_mutations(
                worktree,
                facts.permissions,
                denied_paths=facts.denied_paths,
                base_revision=expected_base,
                include_ignored=purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE,
                retained_source_paths=retained_paths,
            )
            before = capture_mutation_inventory(worktree.path)
            if facts.rejected_candidate_output is not None:
                proof = facts.rejected_candidate_output
                proof.validate_for(
                    task=facts.task,
                    step=proof.step,
                    scope=facts.scope,
                    permissions=facts.permissions,
                    denied_paths=facts.denied_paths,
                )
                if (
                    CapturedMutations.from_capture(complete) != proof.complete_capture
                    or before != proof.inventory
                    or dirty.changed_paths
                    or worktree.head_revision != proof.candidate_revision
                ):
                    raise ValueError("原候选、完整差异或干净现场已经变化")
            if facts.stopped_execution is not None:
                require_stopped_coder_workspace(
                    facts.stopped_execution,
                    CapturedMutations.from_capture(dirty),
                    before,
                    facts.permissions,
                    facts.denied_paths,
                )
            if facts.completed_output is not None:
                require_completed_output_workspace(
                    facts.completed_output,
                    CapturedMutations.from_capture(dirty),
                    before,
                    facts.permissions,
                    facts.denied_paths,
                )
            if facts.stopped_provider_failure is not None:
                require_stopped_provider_workspace(
                    facts.stopped_provider_failure,
                    CapturedMutations.from_capture(dirty),
                    before,
                    facts.permissions,
                    facts.denied_paths,
                )
            if facts.stopped_failure is not None:
                require_stopped_failure_workspace(
                    facts.stopped_failure,
                    CapturedMutations.from_capture(dirty),
                    before,
                    facts.permissions,
                    facts.denied_paths,
                )
            conflicted = False
            preview: BaselineGitPreview | None
            same_paused_base = (
                purpose is BaselinePurpose.SOURCE_REBIND
                and target_base_ref == expected_base
                and facts.continuation is not None
                and facts.continuation.retry_cause == "service_pause"
            )
            if same_paused_base or purpose in {
                BaselinePurpose.COMPLETED_OUTPUT_RESCUE,
                BaselinePurpose.REJECTED_CANDIDATE_RESCUE,
                BaselinePurpose.STOPPED_PROVIDER_RETRY,
                BaselinePurpose.STOPPED_FAILURE_RETRY,
                BaselinePurpose.STOPPED_EXECUTION_RESCUE,
                BaselinePurpose.CONTEXT_CAPACITY_RESUME,
                BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION,
            }:
                preview = BaselineGitPreview(
                    worktree.head_revision,
                    self.git._tree_for_worktree(
                        worktree.head_revision,
                        worktree.path,
                        facts.permissions,
                        facts.denied_paths,
                        worktree,
                        retained_source_paths=dirty.changed_paths,
                    ),
                    dirty.patch.decode("utf-8"),
                )
            elif purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                if (
                    facts.legacy_containment is None
                    or input_mode is not BaselineInputMode.PRESERVE_DRAFT
                    or target_base_ref != expected_base
                    or worktree.head_revision
                    != facts.legacy_containment.original_start.request.source_revision
                ):
                    raise ValueError("旧执行救援必须保留原代码版本和完整草稿, 不能更换基线")
                require_complete_legacy_inventory(
                    self.git.manager, CapturedMutations.from_capture(dirty), before
                )
                preview = BaselineGitPreview(
                    worktree.head_revision,
                    self.git._tree_for_worktree(
                        worktree.head_revision,
                        worktree.path,
                        facts.permissions,
                        facts.denied_paths,
                        worktree,
                        retained_source_paths=dirty.changed_paths,
                    ),
                    dirty.patch.decode("utf-8"),
                )
            else:
                if facts.legacy_containment is not None:
                    raise ValueError("遗留执行隔离证据只能用于独立救援决定")
                preview = self._preview(dirty, complete, target_base_ref, facts, input_mode)
                conflicted = preview is None
                if preview is None:
                    preview = BaselineGitPreview(
                        target_base_ref,
                        self.git.manager._run_git(
                            ("rev-parse", f"{target_base_ref}^{{tree}}"), cwd=worktree.path
                        ),
                        "",
                    )
            if (
                self.facts.collect(target_base_ref) != facts
                or capture_mutation_inventory(worktree.path) != before
            ):
                raise ValueError("baseline source changed during exact proposal")
            assert preview is not None
            plan = ExecutionBaselinePlan.create(
                purpose=purpose,
                facts=facts,
                previous_binding=binding,
                input_mode=input_mode,
                target_base_ref=target_base_ref,
                prepared_source_revision=preview.source_revision,
                prepared_dirty_tree=preview.dirty_tree,
                prepared_dirty_patch=preview.dirty_patch,
                dirty_capture=CapturedMutations.from_capture(dirty),
                complete_capture=CapturedMutations.from_capture(complete),
                before_inventory=before,
                conflicted=conflicted,
            )
            return self.store.put_plan(plan)

    def _preview(
        self,
        dirty: WorktreeMutationCapture,
        complete: WorktreeMutationCapture,
        target_base_ref: str,
        facts: BaselineExecutionFacts,
        input_mode: BaselineInputMode,
    ) -> BaselineGitPreview | None:
        try:
            preview = self.git.preview(
                dirty=dirty,
                complete=complete,
                target_base=target_base_ref,
                permissions=facts.permissions,
                denied_paths=facts.denied_paths,
                input_mode=input_mode,
            )
        except BaselineGitConflict:
            # Keep the exact refused preserve plan for audit. A separately
            # proposed coder_reapply plan has a different digest/authority.
            return None
        return preview

    @staticmethod
    def _require_facts(facts: BaselineExecutionFacts) -> None:
        facts.validate_integrity()
        if facts.task.status is not TaskStatus.IMPLEMENTING or facts.task.branch_name is None:
            raise ValueError(
                "baseline migration requires the same nonterminal named Coder checkpoint"
            )
        work_limit = (
            facts.task.retry_policy.max_work_attempts
            if facts.task.retry_policy is not None
            else facts.task.max_attempts
        )
        if facts.task.work_attempt > work_limit:
            raise ValueError("baseline update does not grant new Coder budget")

    @staticmethod
    def _require_authority(
        plan: ExecutionBaselinePlan, authority: EngineeringAdmission | BaselineOperatorAuthorization
    ) -> tuple[Literal["organization_engineering_policy", "engineering_operator_decision"], str]:
        authority.validate_integrity()
        if isinstance(authority, BaselineOperatorAuthorization):
            authority.require_plan_confirmation(plan)
        elif plan.facts.native_rule_change is not None:
            raise ValueError("项目规范变化需要精确人工确认, 原源码更新能力不能自动批准")
        if plan.purpose is BaselinePurpose.REJECTED_CANDIDATE_RESCUE:
            if not isinstance(authority, BaselineOperatorAuthorization):
                raise ValueError("候选报告恢复需要精确 ENGINEERING 决定, 不得自动批准")
            authority.require_plan_confirmation(plan)
        if plan.purpose is BaselinePurpose.STOPPED_EXECUTION_RESCUE:
            if not isinstance(authority, BaselineOperatorAuthorization):
                raise ValueError("未知结果停止恢复需要精确人工工程确认, 不能自动审批")
            authority.require_plan_confirmation(plan)
        if plan.purpose is BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION:
            if not isinstance(authority, BaselineOperatorAuthorization):
                raise ValueError("当前知识隔离需要精确 ENGINEERING 决定, 不得自动批准")
            authority.require_plan_confirmation(plan)
        if plan.purpose is BaselinePurpose.CONTEXT_CAPACITY_RESUME:
            if not isinstance(authority, BaselineOperatorAuthorization):
                raise ValueError("容量恢复需要精确人工工程确认, 不能自动审批")
            authority.require_plan_confirmation(plan)
        if plan.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
            if not isinstance(authority, BaselineOperatorAuthorization):
                raise ValueError("旧执行救援需要精确人工工程确认, 不能自动审批")
            authority.require_plan_confirmation(plan)
        if plan.purpose is BaselinePurpose.COMPLETED_OUTPUT_RESCUE or (
            plan.facts.completed_output is not None
            and plan.facts.completed_output.reason is CompletedCoderOutputReason.REJECTED
        ):
            if not isinstance(authority, BaselineOperatorAuthorization):
                raise ValueError("已结束执行恢复需要精确人工工程确认, 不能自动审批")
            authority.require_plan_confirmation(plan)
        if plan.facts.stopped_provider_failure is not None:
            if not isinstance(authority, BaselineOperatorAuthorization):
                raise ValueError("提供方前提失败恢复需要精确人工工程确认, 不能自动审批")
            authority.require_plan_confirmation(plan)
        if plan.facts.stopped_failure is not None:
            if not isinstance(authority, BaselineOperatorAuthorization):
                raise ValueError("原执行失败恢复需要精确人工工程确认, 不能自动审批")
            authority.require_plan_confirmation(plan)
        task = plan.facts.task
        if (
            authority.task_id != task.id
            or authority.task_intent_sha256 != task_intent_sha256(task)
            or authority.plan_sha256 != plan.plan_sha256
            or authority.facts_sha256 != plan.facts.facts_sha256
        ):
            raise ValueError("baseline authority is not for this exact new plan and source facts")
        if isinstance(authority, EngineeringAdmission):
            EngineeringAuthority.validate(task=task, record=authority)
            if authority.capabilities != (EngineeringCapability.EXECUTION_BASELINE_REBIND,):
                raise ValueError("baseline action has no exact versioned engineering capability")
            return authority.authorization_source, authority.admission_sha256
        return authority.authorization_source, authority.authorization_sha256

    def execute(
        self, plan_sha256: str, *, authority: EngineeringAdmission | BaselineOperatorAuthorization
    ) -> ExecutionBaselineBinding:
        with source_inspection_scope(), self.store.execution_lock(), self.facts.execution_scope():
            plan = self.store.plan(plan_sha256)
            source, authority_sha = self._require_authority(plan, authority)
            if plan.conflicted:
                raise BaselineGitConflict(
                    "conflicted preserve plan requires a new exact coder_reapply authorization"
                )
            existing = self.store.bindings_for_task(plan.facts.task.id)
            prior_completion = next(
                (item for item in existing if item.plan_sha256 == plan.plan_sha256), None
            )
            if prior_completion is not None:
                # Publication proved the exact Git operation completed. A later
                # queue consumption or role run legitimately changes counters,
                # source and artifacts; do not recollect the old mutation facts.
                prior_completion.require_task(self.facts.completed_task(prior_completion))
                if (source, authority_sha) != (
                    prior_completion.authority_source,
                    prior_completion.authority_sha256,
                ):
                    raise ValueError("completed baseline cannot acquire another authorization")
                if self.publish_completion is not None:
                    self.publish_completion(plan, prior_completion)
                return prior_completion
            if plan.facts.legacy_containment is not None:
                self.facts.bind_legacy_observation(plan.facts.legacy_containment)
            if plan.facts.knowledge_isolation is not None:
                self.facts.bind_knowledge_isolation(plan.facts.knowledge_isolation)
            current = self.facts.collect(plan.target_base_ref)
            self._require_facts(current)
            expected_previous = existing[-1] if existing else None
            if expected_previous != plan.previous_binding or current != plan.facts:
                raise ValueError(
                    "baseline plan/source/queue facts drifted; request a new exact plan"
                )
            if (
                expected_previous is not None
                and expected_previous.continuation_mode is BaselineContinuationMode.PAUSE
                and (
                    not isinstance(authority, BaselineOperatorAuthorization)
                    or authority.continuation_mode is not BaselineContinuationMode.PAUSE
                )
            ):
                raise ValueError("已保留进度的需求需保持暂停, 更新完成后再明确继续")
            self.store.put_authority(authority)
            started = self.store.start(plan_sha256)
            if started is None:
                self.git.manager.verify_mutations(
                    plan.dirty_capture.to_capture(),
                    current.permissions,
                    denied_paths=current.denied_paths,
                )
                self.git.manager.verify_mutations(
                    plan.complete_capture.to_capture(),
                    current.permissions,
                    denied_paths=current.denied_paths,
                )
                if (
                    capture_mutation_inventory(Path(plan.dirty_capture.worktree_path))
                    != plan.before_inventory
                ):
                    raise ValueError("baseline source inventory drifted before execution")
                start = BaselineOperationStart(
                    plan=plan,
                    authority_source=source,
                    authority_sha256=authority_sha,
                    started_at=datetime.now(UTC),
                    start_sha256="0" * 64,
                )
                start = start.model_copy(
                    update={
                        "start_sha256": digest(
                            start.model_dump(mode="json", exclude={"start_sha256"})
                        )
                    }
                )
                self.store.put_start(start)
            elif started.plan != plan or (started.authority_source, started.authority_sha256) != (
                source,
                authority_sha,
            ):
                raise ValueError("baseline operation start changed; preserve all existing state")
            if plan.preserves_paused_baseline or plan.purpose in {
                BaselinePurpose.LEGACY_WORKSPACE_RESCUE,
                BaselinePurpose.COMPLETED_OUTPUT_RESCUE,
                BaselinePurpose.REJECTED_CANDIDATE_RESCUE,
                BaselinePurpose.STOPPED_PROVIDER_RETRY,
                BaselinePurpose.STOPPED_FAILURE_RETRY,
                BaselinePurpose.STOPPED_EXECUTION_RESCUE,
                BaselinePurpose.CONTEXT_CAPACITY_RESUME,
                BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION,
            }:
                self.git.manager.verify_mutations(
                    plan.dirty_capture.to_capture(),
                    current.permissions,
                    denied_paths=current.denied_paths,
                )
                self.git.manager.verify_mutations(
                    plan.complete_capture.to_capture(),
                    current.permissions,
                    denied_paths=current.denied_paths,
                )
                inventory = capture_mutation_inventory(Path(plan.dirty_capture.worktree_path))
                if inventory != plan.before_inventory:
                    raise ValueError("救援方案封存后现场已变化, 请重新准备方案; 原文件保留")
                if plan.purpose is BaselinePurpose.REJECTED_CANDIDATE_RESCUE:
                    proof = current.rejected_candidate_output
                    if proof is None or (
                        plan.complete_capture != proof.complete_capture
                        or inventory != proof.inventory
                        or plan.dirty_capture.source_revision != proof.candidate_revision
                        or plan.dirty_capture.to_capture().changed_paths
                    ):
                        raise ValueError("原候选现场与精确恢复证明不同")
                    proof.validate_for(
                        task=current.task,
                        step=proof.step,
                        scope=current.scope,
                        permissions=current.permissions,
                        denied_paths=current.denied_paths,
                    )
                elif plan.purpose is BaselinePurpose.STOPPED_EXECUTION_RESCUE:
                    assert current.stopped_execution is not None
                    require_stopped_coder_workspace(
                        current.stopped_execution,
                        plan.dirty_capture,
                        inventory,
                        current.permissions,
                        current.denied_paths,
                    )
                elif plan.purpose is BaselinePurpose.COMPLETED_OUTPUT_RESCUE:
                    assert current.completed_output is not None
                    require_completed_output_workspace(
                        current.completed_output,
                        plan.dirty_capture,
                        inventory,
                        current.permissions,
                        current.denied_paths,
                    )
                elif plan.purpose is BaselinePurpose.STOPPED_PROVIDER_RETRY:
                    assert current.stopped_provider_failure is not None
                    require_stopped_provider_workspace(
                        current.stopped_provider_failure,
                        plan.dirty_capture,
                        inventory,
                        current.permissions,
                        current.denied_paths,
                    )
                elif plan.purpose is BaselinePurpose.STOPPED_FAILURE_RETRY:
                    assert current.stopped_failure is not None
                    require_stopped_failure_workspace(
                        current.stopped_failure,
                        plan.dirty_capture,
                        inventory,
                        current.permissions,
                        current.denied_paths,
                    )
                elif plan.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                    require_complete_legacy_inventory(
                        self.git.manager, plan.dirty_capture, inventory
                    )
                reference, after_inventory = (
                    plan.dirty_capture.to_capture().worktree,
                    inventory.sha256,
                )
            else:
                reference, after_inventory = self.git.apply(
                    dirty=plan.dirty_capture.to_capture(),
                    complete=plan.complete_capture.to_capture(),
                    preview=BaselineGitPreview(
                        plan.prepared_source_revision,
                        plan.prepared_dirty_tree,
                        plan.prepared_dirty_patch,
                    ),
                    plan_sha256=plan_sha256,
                    permissions=current.permissions,
                    denied_paths=current.denied_paths,
                    original_inventory=plan.before_inventory,
                )
            if self.facts.collect(plan.target_base_ref) != current:
                raise ValueError(
                    "baseline Task/queue/native rules changed during mutation; "
                    "preserve the admitted operation"
                )
            patch_body = plan.complete_capture.patch.encode("utf-8")
            previous = plan.previous_binding
            binding = ExecutionBaselineBinding.create(
                purpose=plan.purpose,
                continuation_mode=(
                    authority.continuation_mode
                    if isinstance(authority, BaselineOperatorAuthorization)
                    else BaselineContinuationMode.RESUME
                ),
                native_rule_epoch_sha256=(
                    current.native_rule_change.target.epoch_sha256
                    if current.native_rule_change is not None
                    else previous.native_rule_epoch_sha256
                    if previous is not None
                    else None
                ),
                legacy_containment_sha256=(
                    current.legacy_containment.containment_sha256
                    if current.legacy_containment is not None
                    else None
                ),
                knowledge_isolation_sha256=(
                    current.knowledge_isolation.proof_sha256
                    if current.knowledge_isolation
                    else None
                ),
                stopped_execution_sha256=current.stopped_execution.proof_sha256
                if current.stopped_execution
                else None,
                rejected_candidate_output_sha256=(
                    current.rejected_candidate_output.proof_sha256
                    if current.rejected_candidate_output is not None
                    else None
                ),
                completed_output_sha256=(
                    current.completed_output.proof_sha256
                    if current.completed_output is not None
                    and (
                        plan.purpose is BaselinePurpose.COMPLETED_OUTPUT_RESCUE
                        or current.completed_output.reason is CompletedCoderOutputReason.REJECTED
                    )
                    else None
                ),
                stopped_provider_failure_sha256=(
                    current.stopped_provider_failure.proof_sha256
                    if current.stopped_provider_failure is not None
                    else None
                ),
                stopped_failure_sha256=(
                    current.stopped_failure.proof_sha256 if current.stopped_failure else None
                ),
                scope=current.scope,
                task_id=current.task.id,
                task_intent_sha256=task_intent_sha256(current.task),
                sequence=len(existing) + 1,
                previous_binding_sha256=previous.binding_sha256 if previous is not None else None,
                approved_base_ref=current.task.base_ref,
                branch_name=current.task.branch_name,
                worktree_path=str(reference.path),
                prior_execution_base_ref=previous.execution_base_ref
                if previous is not None
                else current.task.base_ref,
                prior_source_revision=(
                    current.rejected_candidate_output.request.source_revision
                    if current.rejected_candidate_output is not None
                    else plan.dirty_capture.source_revision
                ),
                execution_base_ref=plan.target_base_ref,
                execution_source_revision=reference.head_revision,
                input_mode=plan.input_mode,
                superseded_implementation_artifact_id=(
                    None
                    if plan.purpose
                    in {
                        BaselinePurpose.CONTEXT_CAPACITY_RESUME,
                        BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION,
                    }
                    else current.implementation_artifact_id
                ),
                superseded_progress_artifact_id=(
                    None
                    if plan.purpose
                    in {
                        BaselinePurpose.CONTEXT_CAPACITY_RESUME,
                        BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION,
                        BaselinePurpose.STOPPED_FAILURE_RETRY,
                        BaselinePurpose.STOPPED_EXECUTION_RESCUE,
                    }
                    else current.progress_artifact_id
                ),
                context_capacity_receipt_sha256=(
                    current.context_capacity_receipt_sha256
                    if plan.purpose is BaselinePurpose.CONTEXT_CAPACITY_RESUME
                    else None
                ),
                service_pause_outcome_sha256=(
                    current.continuation.current_invocation_outcome_sha256
                    if current.continuation is not None
                    and current.continuation.retry_cause == "service_pause"
                    else None
                ),
                source_artifact_ids=current.source_artifact_ids,
                resolved_interruption_receipt_sha256s=current.resolved_interruption_receipt_sha256s,
                retained_patch=RetainedExecutionPatch(
                    uri=self.store.patch_uri(plan_sha256),
                    sha256=hashlib.sha256(patch_body).hexdigest(),
                    bytes=len(patch_body),
                ),
                authority_source=source,
                authority_sha256=authority_sha,
                plan_sha256=plan_sha256,
                facts_sha256=current.facts_sha256,
                prior_task_revision=current.task_revision,
                before_inventory_sha256=plan.before_inventory.sha256,
                after_inventory_sha256=after_inventory,
                completed_at=datetime.now(UTC),
            )
            require_rejected_candidate_binding(plan, binding)
            require_knowledge_isolation_binding(plan, binding)
            require_context_capacity_binding(plan, binding)
            completed = self.store.put_binding(binding)
            if self.publish_completion is not None:
                self.publish_completion(plan, completed)
            return completed

    def continue_execution(
        self, binding_sha256: str, *, authority: BaselineContinueAuthorization
    ) -> bool:
        """Release the latest pause or kick its exact still-unstarted READY replay."""
        authority.validate_integrity()
        if authority.execution_baseline_sha256 != binding_sha256:
            raise ValueError("继续决定与当前已保存版本不同, 请刷新后确认")
        if self.publish_continuation is None:
            raise ValueError("平台未提供受控继续入口, 已保存进度保持暂停")
        with source_inspection_scope(), self.store.execution_lock(), self.facts.execution_scope():
            bindings = self.store.bindings_for_task(authority.task_id)
            if not bindings or bindings[-1].binding_sha256 != binding_sha256:
                raise ValueError("代码或恢复方案已经更新, 原继续决定已失效")
            binding = bindings[-1]
            if binding.continuation_mode is not BaselineContinuationMode.PAUSE:
                raise ValueError("当前工程输入没有等待明确继续的暂停记录")
            binding.require_task(self.facts.completed_task(binding))
            if (
                authority.scope,
                authority.task_intent_sha256,
                authority.expected_source_revision,
                authority.inventory_sha256,
            ) != (
                binding.scope,
                binding.task_intent_sha256,
                binding.execution_source_revision,
                binding.after_inventory_sha256,
            ):
                raise ValueError("继续决定与已保存的完整工程输入不同")
            prior = self.store.records.find(
                "baseline-continuations", binding_sha256, BaselineContinueAuthorization
            )
            if prior is not None:
                prior.validate_integrity()
                if prior != authority:
                    raise ValueError("当前暂停已有另一份明确继续决定, 原记录保留")
                # The fenced queue release distinguishes exact replay from new work.
                return self.publish_continuation(binding, prior)
            facts = self.facts.collect(binding.execution_base_ref)
            self._require_facts(facts)
            if (
                facts.task.id,
                facts.task_revision,
                facts.work_item_id,
                facts.checkpoint_sequence,
            ) != (
                authority.task_id,
                authority.task_revision,
                authority.work_item_id,
                authority.checkpoint_sequence,
            ):
                raise ValueError("暂停工作项或任务版本已变化, 请重新查看当前输入")
            worktree = self.facts.source_worktree(facts)
            if (str(worktree.path), worktree.head_revision) != (
                binding.worktree_path,
                binding.execution_source_revision,
            ) or capture_mutation_inventory(worktree.path).sha256 != binding.after_inventory_sha256:
                raise ValueError("保留现场已变化, 不能沿用原继续决定; 文件保持")
            self.store.records.put("baseline-continuations", binding_sha256, authority)
            return self.publish_continuation(binding, authority)


class StoredCoderExecutionInputResolver:
    """All runtime consumers share this append-only selector and verified patch body."""

    def __init__(self, store: FileExecutionBaselineStore | None) -> None:
        self.store = store

    def current(
        self,
        task: Task,
        *,
        implementation: ImplementationReportArtifact | None,
        progress: CoderProgressArtifact | None,
    ) -> CoderExecutionInput:
        history = self.store.bindings_for_task(task.id) if self.store is not None else ()
        return resolve_coder_execution_input(
            task,
            implementation=implementation,
            progress=progress,
            baseline=history[-1] if history else None,
            baseline_history=history,
        )

    def required_context(self, source: CoderExecutionInput) -> str | None:
        if source.baseline is None:
            return None
        if self.store is None:
            raise ValueError("bound baseline has no immutable patch body store")
        return self.store.required_context(source.baseline)

    def retained_source_paths(
        self, task: Task, *, workspace_root: Path, permissions: AgentPermissions
    ) -> tuple[str, ...]:
        """Read exact retained additions from fully validated immutable rescue lineage.

        Git ignore patterns are not write authority. Only already sealed source
        additions can receive the retained-file treatment on later invocations;
        each use still checks the frozen policy and actual current file body.
        """
        if self.store is None:
            return ()
        history = self.store.bindings_for_task(task.id)
        if not history:
            return ()
        source = self.current(task, implementation=None, progress=None)
        assert source.baseline is not None
        if str(workspace_root) != source.baseline.worktree_path:
            raise ValueError("保留源码不属于原需求的精确工作区")
        current_plan = self.store.plan(source.baseline.plan_sha256)
        if permissions != current_plan.facts.permissions:
            raise ValueError("保留源码不能改变冻结的执行权限")
        paths: set[str] = set()
        for binding in history:
            if binding.purpose is not BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                continue
            plan = self.store.plan(binding.plan_sha256)
            if plan.facts.permissions != permissions:
                raise ValueError("原救援源码权限与当前冻结权限不一致")
            paths.update(
                item.path
                for item in plan.dirty_capture.mutations
                if item.before is None and item.after is not None
            )
        return tuple(sorted(paths))

    def require_current(self, binding: ExecutionBaselineBinding, task: Task) -> None:
        """Reopen all authority/epoch/patch evidence before trusting a v2 projection."""
        binding.require_task(task)
        source = self.current(task, implementation=None, progress=None)
        # current() reads the complete append-only store and validates each
        # operation, authority, native epoch, retained patch SHA and UTF-8 body.
        if source.baseline != binding:
            raise ValueError("执行基线上下文不是最新的完整可信执行绑定")

    def native_rule_epoch(self, source: CoderExecutionInput) -> NativeRuleEpoch | None:
        if source.baseline is None or source.baseline.native_rule_epoch_sha256 is None:
            return None
        if self.store is None:
            raise ValueError("执行规范版本缺少可信完整正文存储")
        epoch = self.store.native_rule_epoch(source.baseline.native_rule_epoch_sha256)
        if (epoch.scope, epoch.task_id) != (source.baseline.scope, source.baseline.task_id):
            raise ValueError("执行规范版本不属于当前任务和工作空间")
        return epoch


def retained_source_paths_for_request(
    state: Path, task: Task, request: AgentRequest, root: Path
) -> tuple[str, ...]:
    """Reopen trusted retained lineage during idle reconciliation without writing stores."""
    directory = state / "execution-baselines" / task.id
    resolver = StoredCoderExecutionInputResolver(
        FileExecutionBaselineStore(directory, read_only=True) if directory.is_dir() else None
    )
    source = resolver.current(task, implementation=None, progress=None)
    if request.task_id != task.id or request.execution_baseline_sha256 != (
        source.baseline.binding_sha256 if source.baseline is not None else None
    ):
        raise ValueError("保留源码与当前需求的执行基线绑定不一致")
    return resolver.retained_source_paths(
        task, workspace_root=root, permissions=request.permissions
    )
