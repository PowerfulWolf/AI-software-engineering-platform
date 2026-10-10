"""Production-only baseline facts: real process locks, idle queue and sealed calls.

Request bodies select an immutable target and exact plan. They cannot assert that
an executor stopped, grant write paths, or replace original native instructions.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, RouteAttemptOutcome
from ai_software_engineer.agents.models import AgentRunStatus
from ai_software_engineer.artifacts import ArtifactStore, artifact_digest
from ai_software_engineer.artifacts.ordering import latest_accepted_artifact
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.artifact import (
    CoderProgressArtifact,
    ImplementationReportArtifact,
    PlanArtifact,
    Sha256,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselineInputMode,
    BaselinePurpose,
    ExecutionBaselineBinding,
    FullGitRevision,
)
from ai_software_engineer.domain.execution_native_rules import (
    MAX_NATIVE_RULE_RAW_TOTAL_BYTES as MAX_NATIVE_RULE_TOTAL_BYTES,
)
from ai_software_engineer.domain.execution_native_rules import (
    MAX_NATIVE_RULE_SOURCE_BYTES as MAX_NATIVE_RULE_BYTES,
)
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.retry_policy import TRANSIENT_CODES, DeliveryRetryFailure
from ai_software_engineer.domain.task import Task, TaskId, task_matches_dispatch
from ai_software_engineer.domain.workforce import RoleAssignment
from ai_software_engineer.git import GitWorktreeManager, WorktreeNotFound
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.git.ports import WorktreeRef, WorktreeSpec
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import (
    BaselineContinueAuthorization,
    BaselineExecutionFacts,
    BaselineExecutionReservation,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
    require_rescue_confirmation,
)
from ai_software_engineer.manager.baseline_native_rules import build_native_rule_change
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.manager.delivery_preflight import (
    DeliveryPreflightCheckpoint,
    DeliveryPreflightReceipt,
)
from ai_software_engineer.manager.dispatch import DeliveryAllocation
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.manager.legacy_containment import (
    LegacyExecutionContainment,
    LocalBootObservation,
    LocalBootObserver,
    TrustedLocalBootObserver,
)
from ai_software_engineer.manager.legacy_local_execution import (
    LegacyLocalExecutionObserver,
    LegacyRescuePrerequisiteError,
    TrustedLegacyLocalExecutionObserver,
)
from ai_software_engineer.manager.legacy_snapshot import require_complete_legacy_inventory
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationScope,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.retry import _active_progress, _latest
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.repository_profile import NativeRuleSource, native_rule_kinds
from ai_software_engineer.spec_compiler import SpecRule
from ai_software_engineer.store import TaskRepository
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.worker import AcceptedArtifactStore, WorkerExecutionGuard


class BaselineProposeCommand(DomainModel):
    purpose: BaselinePurpose = Field(
        default=BaselinePurpose.SOURCE_REBIND,
        exclude_if=lambda value: value is BaselinePurpose.SOURCE_REBIND,
    )
    delivery_id: DeliveryId
    task_id: TaskId
    expected_task_intent_sha256: Sha256
    expected_task_revision: int = Field(ge=1)
    expected_work_item_id: NonEmptyStr
    expected_source_revision: FullGitRevision
    target_base_ref: FullGitRevision
    input_mode: BaselineInputMode = BaselineInputMode.PRESERVE_DRAFT

    def require_current(
        self, task: Task, revision: int, work_item_id: str, source_revision: str
    ) -> None:
        """Reject stale inputs before the collector publishes original facts."""
        if (
            task.id,
            task_intent_sha256(task),
            revision,
            work_item_id,
            source_revision,
        ) != (
            self.task_id,
            self.expected_task_intent_sha256,
            self.expected_task_revision,
            self.expected_work_item_id,
            self.expected_source_revision,
        ):
            raise ValueError("工程执行基线事实已变化, 请刷新后重新调查")

    def require_plan(self, plan: ExecutionBaselinePlan) -> None:
        plan.validate_integrity()
        facts = plan.facts
        if (
            facts.task.id,
            task_intent_sha256(facts.task),
            facts.task_revision,
            facts.work_item_id,
            plan.dirty_capture.source_revision,
            plan.target_base_ref,
            plan.input_mode,
            plan.purpose,
        ) != (
            self.task_id,
            self.expected_task_intent_sha256,
            self.expected_task_revision,
            self.expected_work_item_id,
            self.expected_source_revision,
            self.target_base_ref,
            self.input_mode,
            self.purpose,
        ):
            raise ValueError("工程执行基线事实已变化, 请刷新后重新调查")


class BaselineExecuteCommand(DomainModel):
    delivery_id: DeliveryId
    task_id: TaskId
    expected_plan_sha256: Sha256
    reference: NonEmptyStr = Field(max_length=2000)
    continuation_mode: BaselineContinuationMode = Field(
        default=BaselineContinuationMode.RESUME,
        exclude_if=lambda value: value is BaselineContinuationMode.RESUME,
    )
    approved_native_rule_change_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    confirm_legacy_containment: Literal[True] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    confirm_local_execution_stopped: Literal[True] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def distinct_confirmation(self) -> Self:
        if self.confirm_legacy_containment and self.confirm_local_execution_stopped:
            raise ValueError("两种旧执行恢复确认不能同时使用")
        return self

    def require_plan(self, plan: ExecutionBaselinePlan) -> None:
        plan.validate_integrity()
        if (plan.facts.task.id, plan.plan_sha256) != (self.task_id, self.expected_plan_sha256):
            raise ValueError("工程决定未绑定当前需求和精确执行基线计划")
        change = plan.facts.native_rule_change
        if self.approved_native_rule_change_sha256 != (
            change.change_sha256 if change is not None else None
        ):
            raise ValueError("请明确确认此精确目标版本的项目规范变更")
        require_rescue_confirmation(
            plan,
            confirm_legacy_containment=self.confirm_legacy_containment,
            confirm_local_execution_stopped=self.confirm_local_execution_stopped,
        )


class BaselineContinueCommand(DomainModel):
    """A distinct, exact decision to release a preserved execution baseline hold."""

    delivery_id: DeliveryId
    task_id: TaskId
    expected_task_intent_sha256: Sha256
    expected_task_revision: int = Field(ge=1)
    expected_work_item_id: NonEmptyStr
    expected_source_revision: FullGitRevision
    expected_execution_baseline_sha256: Sha256
    expected_disposition_sha256: Sha256
    reference: NonEmptyStr = Field(max_length=2000)


class BaselineInvocationProof(DomainModel):
    work_item_id: NonEmptyStr
    step_sha256: Sha256
    start_sha256: Sha256 | None = None
    outcome_sha256: Sha256 | None = None
    interruption_receipt_sha256: Sha256 | None = None
    preflight_checkpoint_sha256: Sha256 | None = None
    preflight_checkpoint_sha256s: tuple[Sha256, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    legacy_containment: LegacyExecutionContainment | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    legacy_binding_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    proof_kind: Literal[
        "definitive_outcome",
        "owned_process_stopped",
        "unclaimed",
        "claimed_preflight",
        "legacy_execution_contained",
    ]

    @model_validator(mode="after")
    def validate_legacy(self) -> Self:
        if self.proof_kind == "legacy_execution_contained":
            containment = self.legacy_containment
            if (
                containment is None
                or containment.original_start.work_item_id != self.work_item_id
                or containment.original_start.start_sha256 != self.start_sha256
                or self.outcome_sha256 is not None
                or self.interruption_receipt_sha256 is not None
            ):
                raise ValueError("旧执行观察不能替代原结果或原停止记录")
            containment.validate_integrity()
        elif self.legacy_containment is not None or self.legacy_binding_sha256 is not None:
            raise ValueError("旧执行隔离观察只能属于独立工程救援证明")
        return self


class BaselineQuiescenceProof(DomainModel):
    kind: Literal["baseline_quiescence_v1"] = "baseline_quiescence_v1"
    task_id: TaskId
    task_revision: int
    task_snapshot_sha256: Sha256
    task_events_sha256: Sha256
    allocation_sha256: Sha256
    queue_snapshot_sha256: Sha256
    assignments_sha256: Sha256
    task_process_lock: Literal["held"] = "held"
    queue_authority_and_task_row: Literal["held_no_active_claim"] = "held_no_active_claim"
    invocations: tuple[BaselineInvocationProof, ...]


def native_rules_at_revision(
    git: GitWorktreeManager,
    *,
    repository_id: str,
    revision: str,
) -> tuple[NativeRuleSource, ...]:
    """Discover the entire immutable tree, including newly added instruction files."""
    # Full SHA only; a movable branch cannot become an engineering plan input.
    if git._resolve_revision(revision) != revision:
        raise ValueError("执行基线只接受完整、不可变的 Git 提交")
    records = git._run_git_bytes(("ls-tree", "-r", "-z", revision), cwd=git._repository)
    result: list[NativeRuleSource] = []
    total = 0
    for record in records.split(b"\0"):
        if not record:
            continue
        metadata, separator, path_bytes = record.partition(b"\t")
        if not separator:
            raise ValueError("目标基线 Git 文件清单格式异常")
        relative = path_bytes.decode("utf-8")
        kinds = native_rule_kinds(relative)
        if not kinds:
            continue
        mode, kind, blob = metadata.decode("ascii").split(" ")
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("目标基线的原生规范必须是普通文本文件")
        size = int(git._run_git(("cat-file", "-s", blob), cwd=git._repository))
        total += size
        if size > MAX_NATIVE_RULE_BYTES or total > MAX_NATIVE_RULE_TOTAL_BYTES:
            raise ValueError("目标基线原生规范超过有界读取预算")
        body = git._run_git_bytes(("cat-file", "blob", blob), cwd=git._repository)
        body.decode("utf-8")
        if len(body) != size:
            raise ValueError("目标基线原生规范读取不完整")
        result.append(
            NativeRuleSource(
                uri=f"project://{repository_id}/{relative}",
                relative_path=relative,
                kinds=kinds,
                sha256=hashlib.sha256(body).hexdigest(),
                byte_length=size,
            )
        )
    return tuple(sorted(result, key=lambda item: item.relative_path))


class ProductionBaselineFactCollector:
    """Trusted service composition; no model/API supplied facts are accepted.

    Lock order matches the Worker: Task process lock, queue authority, Task row.
    All ACTIVE claims are excluded even if expired. Git mutations are deliberately
    not part of collect(): the sealed adapter plan owns its exact crash replay.
    """

    def __init__(
        self,
        *,
        allocation: DeliveryAllocation,
        scope: EngineeringScope,
        requirement_id: DeliveryId,
        repository: TaskRepository,
        queue: MySqlRoleQueue,
        artifacts: ArtifactStore,
        git: GitWorktreeManager,
        sidecar_state: Path,
        locks_root: Path,
        permissions: AgentPermissions,
        source_native_rules: tuple[NativeRuleSource, ...],
        runtime_manifest_sha256: str,
        inputs: StoredCoderExecutionInputResolver,
        structured_project_rules: tuple[SpecRule, ...] = (),
        purpose: BaselinePurpose = BaselinePurpose.SOURCE_REBIND,
        observer: LocalBootObserver | None = None,
        local_execution_observer: LegacyLocalExecutionObserver | None = None,
        route_root: Path | None = None,
    ) -> None:
        allocation.validate_integrity()
        self.allocation, self.scope, self.requirement_id = allocation, scope, requirement_id
        self.repository, self.queue, self.git = repository, queue, git
        self.state, self.locks_root, self.permissions = sidecar_state, locks_root, permissions
        self.native_rules, self.runtime_manifest_sha256, self.inputs = (
            source_native_rules,
            runtime_manifest_sha256,
            inputs,
        )
        self.guard = WorkerExecutionGuard()
        self.structured_project_rules = structured_project_rules
        self.artifacts = AcceptedArtifactStore(artifacts, queue, allocation.task_id, self.guard)
        self._scope_held = False
        self._idle_cursor: DictCursor | None = None
        self.purpose = purpose
        self.observer = observer if observer is not None else TrustedLocalBootObserver()
        self.local_execution_observer = (
            local_execution_observer
            if local_execution_observer is not None
            else TrustedLegacyLocalExecutionObserver()
        )
        self._sealed_legacy_observation: LegacyExecutionContainment | None = None
        self.route_root = route_root
        self._proposal_command: BaselineProposeCommand | None = None

    def bind_proposal(self, command: BaselineProposeCommand) -> None:
        """Bind one explicit preparation, never an execute/continue recollection."""
        if self._scope_held:
            raise ValueError("执行基线方案不能在调查期间替换当前命令")
        self._proposal_command = command

    def _collect_proposal_facts(
        self,
        task: Task,
        revision: int,
        step: QueuedRoleStep,
        source_revision: str,
        target_base_ref: str,
    ) -> None:
        if not self._scope_held or self._idle_cursor is None:
            raise ValueError("执行基线事实封存缺少真实任务锁和队列屏障")
        command = self._proposal_command
        if command is None:
            return
        command.require_current(task, revision, step.work_item.id, source_revision)
        if (
            command.delivery_id != self.requirement_id
            or command.purpose is not self.purpose
            or command.target_base_ref != target_base_ref
        ):
            raise ValueError("工程执行基线事实已变化, 请刷新后重新调查")
        item = self.queue.get(step.work_item.id)
        disposition = item.wait_disposition
        if (
            self.purpose is not BaselinePurpose.SOURCE_REBIND
            or item.status
            not in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
            or disposition is None
            or disposition.facts.classification not in {"EXECUTION_UNCERTAIN", "PLATFORM_BUG"}
        ):
            return
        if self.route_root is None:
            raise ValueError("执行基线事实封存缺少原调用路由记录位置")
        collector = DeliveryWaitFactCollector(
            sidecar_state=self.state,
            route_root=self.route_root,
            scope=self.scope,
            expected_continuation_scope=ContinuationScope(
                team_id=self.scope.team_id,
                project_id=self.scope.project_id,
                repository_id=self.scope.repository_id,
                requirement_id=self.requirement_id,
                dispatch_sha256=self.allocation.dispatch_sha256,
            ),
            git=self.git,
            queue=self.queue,
        )
        # execution_scope already owns both boundaries. Collection only appends
        # original outcome/receipt facts; HANDLE would also resolve and resume.
        collector.collect(task, step, self.guard)

    def bind_legacy_observation(self, containment: LegacyExecutionContainment) -> None:
        """Pin the approved evidence while collect independently checks it again."""
        containment.validate_integrity()
        if (
            containment.scope != self.scope
            or containment.requirement_id != self.requirement_id
            or containment.dispatch_sha256 != self.allocation.dispatch_sha256
        ):
            raise ValueError("旧执行恢复观察不属于当前精确需求和分配")
        self._sealed_legacy_observation = containment

    def _observe_legacy_boot(self) -> LocalBootObservation:
        try:
            return self.observer.observe()
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            raise LegacyRescuePrerequisiteError(
                code="LEGACY_LOCAL_OBSERVATION_UNAVAILABLE",
                safe_message="平台暂时无法读取可靠的本机身份和启动记录，不能准备旧执行恢复。",  # noqa: RUF001
                next_action="请让平台维护者检查当前系统的只读查询能力和权限，修复后重新检查恢复前提；不要清空工作区。",  # noqa: RUF001
            ) from error

    def _verify_legacy_observation(
        self, containment: LegacyExecutionContainment, *, worktree_root: Path
    ) -> None:
        containment.validate_integrity()
        boot = self._observe_legacy_boot()
        if boot.machine_sha256 != containment.boot.machine_sha256 or (
            not boot.same_boot(containment.boot) and boot.booted_at <= containment.boot.booted_at
        ):
            raise LegacyRescuePrerequisiteError(
                code="LOCAL_IDENTITY_CHANGED",
                safe_message="原执行所在电脑或启动依据已变化, 保留进度并重新准备恢复方案。",
                next_action="由工程授权者核对原执行所在电脑; 确认后重新准备方案。",
            )
        if containment.method == "operator_confirmed_local_stop":
            sealed = containment.local_execution_survey
            assert sealed is not None
            current = self.local_execution_observer.observe(worktree_root=worktree_root, boot=boot)
            current.require_idle()
            # A later real boot is acceptable to an already supplied local stop
            # declaration. It does not replace the immutable observation or stop history.
            if not sealed.same_boundary(
                current, allow_new_boot=not boot.same_boot(containment.boot)
            ):
                raise LegacyRescuePrerequisiteError(
                    code="LOCAL_IDENTITY_CHANGED",
                    safe_message="当前工作区、电脑、账户或检查范围与恢复方案不一致。",
                    next_action="保留原进度, 由工程授权者核对后重新准备恢复方案。",
                )
        if not boot.same_boot(self._observe_legacy_boot()):
            raise LegacyRescuePrerequisiteError(
                code="LOCAL_OBSERVATION_CHANGED",
                safe_message="检查期间电脑启动会话发生变化, 恢复尚未安排。",
                next_action="请等当前服务稳定后重新准备恢复方案。",
            )

    @contextmanager
    def execution_scope(self) -> Iterator[None]:
        if self._scope_held:
            raise ValueError("执行基线调查不允许嵌套执行")
        with (
            self.guard.task_scope(self.locks_root, self.allocation.task_id),
            self.queue.idle_task_scope(self.allocation.task_id) as cursor,
        ):
            self._scope_held = True
            self._idle_cursor = cursor
            try:
                yield
            finally:
                self._scope_held = False
                self._idle_cursor = None

    def publish_completion(
        self, plan: ExecutionBaselinePlan, binding: ExecutionBaselineBinding
    ) -> None:
        if not self._scope_held or self._idle_cursor is None:
            raise ValueError("基线队列接续缺少原持锁执行范围和 SQL 屏障")
        if binding.task_id != self.allocation.task_id or binding.scope != self.scope:
            raise ValueError("基线队列接续不属于当前需求和原批准范围")
        from ai_software_engineer.work_queue.baseline import consume_baseline

        def validate_new_consumption() -> None:
            if not self._scope_held or self._idle_cursor is None:
                raise ValueError("旧执行救援缺少原持锁执行和队列屏障")
            if plan.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                containment = plan.facts.legacy_containment
                if (
                    containment is None
                    or binding.legacy_containment_sha256 != containment.containment_sha256
                ):
                    raise ValueError("救援绑定与原精确检查事实不同, 原现场和工程决定保留")
                self._verify_legacy_observation(
                    containment, worktree_root=Path(plan.dirty_capture.worktree_path)
                )
                self.git.verify_mutations(
                    plan.dirty_capture.to_capture(),
                    plan.facts.permissions,
                    denied_paths=plan.facts.denied_paths,
                )
                self.git.verify_mutations(
                    plan.complete_capture.to_capture(),
                    plan.facts.permissions,
                    denied_paths=plan.facts.denied_paths,
                )
                inventory = capture_mutation_inventory(Path(plan.dirty_capture.worktree_path))
                if inventory != plan.before_inventory:
                    raise ValueError("救援封存后工作现场已变化, 保留文件并重新检查工程方案")
                require_complete_legacy_inventory(self.git, plan.dirty_capture, inventory)
                self._verify_legacy_observation(
                    containment, worktree_root=Path(plan.dirty_capture.worktree_path)
                )

        consume_baseline(
            self.queue,
            plan,
            binding,
            cursor=self._idle_cursor,
            validate_new_consumption=validate_new_consumption,
        )

    def publish_continuation(
        self, binding: ExecutionBaselineBinding, authority: BaselineContinueAuthorization
    ) -> bool:
        if not self._scope_held or self._idle_cursor is None or self.inputs.store is None:
            raise ValueError("工程继续缺少原持锁执行范围和 SQL 屏障")
        store = self.inputs.store

        def validate_new_release() -> None:
            facts = self.collect(binding.execution_base_ref)
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
            worktree = self.source_worktree(facts)
            if (str(worktree.path), worktree.head_revision) != (
                binding.worktree_path,
                binding.execution_source_revision,
            ) or capture_mutation_inventory(worktree.path).sha256 != binding.after_inventory_sha256:
                raise ValueError("保留现场已变化, 不能沿用原继续决定; 文件保持")
            plan = store.plan(binding.plan_sha256)
            for previous in store.bindings_for_task(binding.task_id):
                if previous.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                    saved = store.plan(previous.plan_sha256).facts.legacy_containment
                    if saved is None:
                        raise ValueError("原救援缺少完整实际停止前提, 保留进度")
                    self._verify_legacy_observation(saved, worktree_root=worktree.path)
            if binding.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                self.git.verify_mutations(
                    plan.dirty_capture.to_capture(),
                    facts.permissions,
                    denied_paths=facts.denied_paths,
                )
                self.git.verify_mutations(
                    plan.complete_capture.to_capture(),
                    facts.permissions,
                    denied_paths=facts.denied_paths,
                )
                return
            capture = self.git.capture_mutations(
                worktree, facts.permissions, denied_paths=facts.denied_paths
            )
            if capture.index_diff_sha256 != hashlib.sha256(b"").hexdigest():
                raise ValueError("保留现场暂存区已变化, 不能沿用原继续决定")
            from ai_software_engineer.git.baseline import GitExecutionBaselineAdapter

            adapter = GitExecutionBaselineAdapter(self.git)
            if (
                adapter._tree_for_worktree(
                    worktree.head_revision,
                    worktree.path,
                    facts.permissions,
                    facts.denied_paths,
                    worktree,
                )
                != plan.prepared_dirty_tree
            ):
                raise ValueError("保留的完整草稿与获批方案不同, 请重新检查")

        released = self.queue.release_baseline_pause(
            binding,
            authority,
            cursor=self._idle_cursor,
            validate_new_release=validate_new_release,
        )
        if released:
            return True
        if self.queue.pending_baseline_release(binding, authority, cursor=self._idle_cursor):
            validate_new_release()
            return True
        return False

    def collect(self, target_base_ref: str) -> BaselineExecutionFacts:
        if not self._scope_held:
            raise ValueError("执行基线调查缺少真实停机锁和队列屏障")
        task = self.repository.get(self.allocation.task_id)
        revision = self.repository.current_revision(task.id)
        if not task_matches_dispatch(task, self.allocation.task) or (
            task.repository != self.scope.repository_root
            or task.metadata.get("repository_id") != self.scope.repository_id
            or (task.engineering_policy is not None and task.engineering_policy.scope != self.scope)
            or task.status is not TaskStatus.IMPLEMENTING
        ):
            raise ValueError("执行基线调查与原批准范围或当前 Coder checkpoint 不一致")
        admission = self.queue.admission(task.id)
        if admission is None or admission.allocation_sha256 != self.allocation.dispatch_sha256:
            raise ValueError("执行基线缺少原分配的真实队列接纳记录")
        items = self.queue.items_for_task(task.id)
        current = tuple(item for item in items if item.status is not WorkItemStatus.CLOSED)
        if len(current) != 1:
            raise ValueError("执行基线必须对应唯一尚未结束的 Coder 工作项")
        item = current[0]
        if item.status in {WorkItemStatus.LEASED, WorkItemStatus.RUNNING} or (
            item.task_id,
            item.repository_id,
            item.role,
            item.checkpoint_sequence,
        ) != (task.id, self.scope.repository_id, AgentRole.CODER, revision):
            raise ValueError("Coder 工作项仍在执行或已偏离当前 Task checkpoint")
        step = self.queue.step(item.id)
        self._require_step(item, step)
        artifacts = self.artifacts.list_for_task(task.id)
        plan = _latest(artifacts, PlanArtifact)
        previous_source = self.inputs.current(task, implementation=None, progress=None)
        implementation = latest_accepted_artifact(
            artifacts,
            ImplementationReportArtifact,
            excluded_artifact_ids=previous_source.superseded_artifact_ids,
        )
        progress = latest_accepted_artifact(
            artifacts,
            CoderProgressArtifact,
            excluded_artifact_ids=previous_source.superseded_artifact_ids,
        )
        progress = _active_progress(progress, implementation, artifacts)
        if plan is None:
            raise ValueError("执行基线调查缺少已接纳的原始交付计划")
        for artifact in artifacts:
            if (
                not artifact.integrity.validated
                or artifact_digest(artifact) != artifact.integrity.sha256
            ):
                raise ValueError("执行基线输入产物完整性异常")
        source = self.inputs.current(task, implementation=implementation, progress=progress)
        if step.boundary.source_revision != source.source_revision:
            raise ValueError("Coder 队列源版本与当前已接纳输入不一致")
        self._collect_proposal_facts(task, revision, step, source.source_revision, target_base_ref)
        if self.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE and (
            target_base_ref != source.execution_base_ref or implementation is not None
        ):
            raise ValueError("旧执行救援只能保留原代码基线和草稿, 不能覆盖已接纳候选")
        target_rules = native_rules_at_revision(
            self.git, repository_id=self.scope.repository_id, revision=target_base_ref
        )
        epoch = self.inputs.native_rule_epoch(source)
        frozen_rules = tuple(
            sorted(
                epoch.rules if epoch is not None else self.native_rules,
                key=lambda rule: rule.relative_path,
            )
        )
        if self.inputs.store is None:
            raise ValueError("执行基线缺少可信 append-only 事实存储")
        if self.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE and target_rules != frozen_rules:
            raise ValueError("旧执行救援不能同时替换原规范, 请先保留进度并暂停")
        change = build_native_rule_change(
            git=self.git,
            records=self.inputs.store.records,
            scope=self.scope,
            task_id=task.id,
            source_revision=source.execution_base_ref,
            target_base_ref=target_base_ref,
            source_rules=frozen_rules,
            target_rules=target_rules,
            structured_project_rules=self.structured_project_rules,
        )
        assignments = tuple(
            assignment
            for assignment in self.queue.list_assignments()
            if assignment.task_id == task.id
        )
        receipts = self._receipts(task)
        legacy = (
            self._legacy_containment(task, item)
            if self.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE
            else None
        )
        invocation_proofs = self._invocations(task, items, receipts, assignments, legacy=legacy)
        reservation = self._reservation(task, item, receipts, legacy=legacy)
        proof = BaselineQuiescenceProof(
            task_id=task.id,
            task_revision=revision,
            task_snapshot_sha256=digest(task.to_wire()),
            task_events_sha256=digest(
                [event.to_wire() for event in self.repository.list_events(task.id)]
            ),
            allocation_sha256=self.allocation.dispatch_sha256,
            queue_snapshot_sha256=digest([queued.to_wire() for queued in items]),
            assignments_sha256=digest([assignment.to_wire() for assignment in assignments]),
            invocations=invocation_proofs,
        )
        if self.inputs.store is None:
            raise ValueError("执行基线缺少可信 append-only 事实存储")
        self.inputs.store.records.put("baseline-quiescence", digest(proof.to_wire()), proof)
        previous = source.baseline.resolved_interruption_receipt_sha256s if source.baseline else ()
        resolved = tuple(
            dict.fromkeys((*previous, *(receipt.receipt_sha256 for receipt in receipts)))
        )
        values = BaselineExecutionFacts(
            task=task,
            scope=self.scope,
            task_revision=revision,
            work_item_id=item.id,
            checkpoint_sequence=item.checkpoint_sequence,
            quiescence_proof_sha256=digest(proof.to_wire()),
            runtime_manifest_sha256=self.runtime_manifest_sha256,
            source_native_rules_sha256=digest([rule.to_wire() for rule in frozen_rules]),
            target_native_rules_sha256=digest([rule.to_wire() for rule in target_rules]),
            native_rule_change=change,
            source_artifact_ids=tuple(sorted(artifact.artifact_id for artifact in artifacts)),
            implementation_artifact_id=implementation.artifact_id if implementation else None,
            progress_artifact_id=progress.artifact_id if progress else None,
            resolved_interruption_receipt_sha256s=resolved,
            continuation=reservation,
            legacy_containment=legacy,
            permissions=self.permissions,
            denied_paths=task.constraints.denied_paths if task.constraints else (),
            facts_sha256="0" * 64,
        )
        return values.model_copy(
            update={
                "facts_sha256": digest(values.model_dump(mode="json", exclude={"facts_sha256"}))
            }
        )

    def completed_task(self, binding: ExecutionBaselineBinding) -> Task:
        if (
            not self._scope_held
            or binding.scope != self.scope
            or binding.task_id != self.allocation.task_id
        ):
            raise ValueError("已完成基线未绑定当前持锁需求")
        task = self.repository.get(binding.task_id)
        if not task_matches_dispatch(task, self.allocation.task):
            raise ValueError("已完成基线的原批准范围发生变化")
        binding.require_task(task)
        return task

    def source_worktree(self, facts: BaselineExecutionFacts) -> WorktreeRef:
        if not self._scope_held or facts.task.id != self.allocation.task_id:
            raise ValueError("执行基线工作区不属于当前持锁需求")
        artifacts = self.artifacts.list_for_task(facts.task.id)
        previous_source = self.inputs.current(facts.task, implementation=None, progress=None)
        implementation = latest_accepted_artifact(
            artifacts,
            ImplementationReportArtifact,
            excluded_artifact_ids=previous_source.superseded_artifact_ids,
        )
        progress = latest_accepted_artifact(
            artifacts,
            CoderProgressArtifact,
            excluded_artifact_ids=previous_source.superseded_artifact_ids,
        )
        progress = _active_progress(progress, implementation, artifacts)
        source = self.inputs.current(facts.task, implementation=implementation, progress=progress)
        spec = WorktreeSpec(
            task_id=facts.task.id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=source.source_revision,
        )
        try:
            return self.git.recover(spec)
        except WorktreeNotFound:
            # Preflight can stop before RoleAwareAgentAdapter creates any checkout.
            # This is the first clean checkout, never reconstruction of lost work.
            invocation_root = self.state / "invocations"
            starts = (
                KnowledgeRecordStore(invocation_root, read_only=True).list(
                    "invocation-starts", DeliveryInvocationStart
                )
                if invocation_root.is_dir()
                else ()
            )
            if (
                facts.continuation is None
                or facts.continuation.retry_cause != "uninvoked"
                or implementation is not None
                or progress is not None
                or source.baseline is not None
                or source.source_revision != facts.task.base_ref
                or self._receipts(facts.task)
                or any(
                    start.request.task_id == facts.task.id and start.request.role is AgentRole.CODER
                    for start in starts
                )
            ):
                raise ValueError("已开始执行的 Coder 工作区缺失, 保留历史并等待工程调查") from None
            # Git.create rejects any surviving branch, unsafe path or registration.
            return self.git.create(spec)

    def _require_step(self, item: QueuedWorkItem, step: QueuedRoleStep) -> None:
        if step.allocation_sha256 != self.allocation.dispatch_sha256 or (
            item.id,
            item.task_id,
            item.repository_id,
            item.role,
            item.attempt,
            item.checkpoint_sequence,
        ) != (
            step.work_item.id,
            step.work_item.task_id,
            step.work_item.repository_id,
            step.boundary.role,
            step.boundary.attempt,
            step.boundary.checkpoint_sequence,
        ):
            raise ValueError("执行基线队列工作项与原分配不一致")

    def _receipts(self, task: Task) -> tuple[ExecutionInterruptionReceipt, ...]:
        root = self.state / "continuations" / task.id
        if not root.exists():
            return ()
        receipts = FileContinuationStore(root, task_id=task.id).receipts_for_task(task.id)
        for receipt in receipts:
            policy = task.interruption_continuation_policy
            if (
                (
                    receipt.scope.team_id,
                    receipt.scope.project_id,
                    receipt.scope.repository_id,
                    receipt.scope.requirement_id,
                    receipt.scope.dispatch_sha256,
                    receipt.task_intent_sha256,
                    receipt.request.permissions,
                )
                != (
                    self.scope.team_id,
                    self.scope.project_id,
                    self.scope.repository_id,
                    self.requirement_id,
                    self.allocation.dispatch_sha256,
                    task_intent_sha256(task),
                    self.permissions,
                )
                or policy is None
                or receipt.policy_sha256 != policy.policy_sha256
            ):
                raise ValueError("原停机记录未绑定原需求、分配和冻结权限")
            NativeCoderContinuation._require_stopped(receipt.process_stop, receipt.request)
        return receipts

    def _invocations(
        self,
        task: Task,
        items: tuple[QueuedWorkItem, ...],
        receipts: tuple[ExecutionInterruptionReceipt, ...],
        assignments: tuple[RoleAssignment, ...],
        *,
        legacy: LegacyExecutionContainment | None = None,
    ) -> tuple[BaselineInvocationProof, ...]:
        root = self.state / "invocations"
        records = KnowledgeRecordStore(root, read_only=True) if root.is_dir() else None
        starts = (
            tuple(
                start
                for start in records.list("invocation-starts", DeliveryInvocationStart)
                if start.request.task_id == task.id
            )
            if records
            else ()
        )
        outcomes = (
            tuple(
                outcome
                for outcome in records.list("invocation-outcomes", DeliveryInvocationOutcome)
                if outcome.start.request.task_id == task.id
            )
            if records
            else ()
        )
        starts_by_id = {start.work_item_id: start for start in starts}
        outcomes_by_id = {outcome.start.work_item_id: outcome for outcome in outcomes}
        if len(starts_by_id) != len(starts) or len(outcomes_by_id) != len(outcomes):
            raise ValueError("原调用日志含重复执行身份")
        if not {receipt.request.run_id for receipt in receipts}.issubset(
            {start.request.run_id for start in starts}
        ):
            raise ValueError("原停机日志缺少相应调用启动记录")
        item_ids = {item.id for item in items}
        if not set(starts_by_id).issubset(item_ids) or not set(outcomes_by_id).issubset(item_ids):
            raise ValueError("原调用日志含未归属当前 Task 队列的执行")
        result = []
        for item in items:
            start, outcome = starts_by_id.get(item.id), outcomes_by_id.get(item.id)
            claims = self.queue.claims_for_work_item(item.id)
            preflight_claims = tuple(
                claim for claim in claims if start is None or claim.lease.id != start.lease_id
            )
            markers = self._preflight_markers(task, item, preflight_claims)
            step = (
                self.queue.step_for_invocation(item.id, start.request.execution_baseline_sha256)
                if start is not None
                else self.queue.step(item.id)
            )
            self._require_step(item, step)
            receipt = next(
                (
                    entry
                    for entry in receipts
                    if start and entry.request.run_id == start.request.run_id
                ),
                None,
            )
            if start is not None:
                start.validate_integrity()
                if (
                    start.work_item_id,
                    start.checkpoint_sequence,
                    start.request.task_id,
                    start.request.role,
                    start.request.attempt,
                    start.request.source_revision,
                ) != (
                    item.id,
                    item.checkpoint_sequence,
                    task.id,
                    item.role,
                    item.attempt,
                    step.boundary.source_revision,
                ):
                    raise ValueError("原调用未绑定精确队列角色、attempt 和源版本")
                claim = self.queue.original_claim(start.lease_id)
                if (
                    claim.work_item.id,
                    claim.work_item.task_id,
                    claim.work_item.role,
                    claim.work_item.attempt,
                    claim.work_item.checkpoint_sequence,
                ) != (item.id, task.id, item.role, item.attempt, item.checkpoint_sequence):
                    raise ValueError("原调用与真实历史 claim 不一致")
                if outcome is not None:
                    outcome.validate_integrity()
                    if outcome.start != start:
                        raise ValueError("原调用结果未绑定精确启动记录")
                    proof_kind: Literal[
                        "definitive_outcome", "owned_process_stopped", "legacy_execution_contained"
                    ] = "definitive_outcome"
                elif receipt is not None:
                    if (
                        receipt.request != start.request
                        or receipt.original_work_item_id != item.id
                        or receipt.claim_lease_id != start.lease_id
                    ):
                        raise ValueError("停机证明不属于精确原调用")
                    proof_kind = "owned_process_stopped"
                else:
                    historical_legacy = self._historical_legacy(task, start, claim)
                    containment = legacy if legacy and legacy.original_start == start else None
                    if containment is None and historical_legacy is not None:
                        containment = historical_legacy[0]
                    if containment is None or containment.original_claim != claim:
                        raise ValueError("原调用结果或真实停机事实不完整, 保留现场等待工程调查")
                    containment.validate_integrity()
                    proof_kind = "legacy_execution_contained"
                result.append(
                    BaselineInvocationProof(
                        work_item_id=item.id,
                        step_sha256=digest(step.to_wire()),
                        start_sha256=start.start_sha256,
                        outcome_sha256=outcome.outcome_sha256 if outcome else None,
                        interruption_receipt_sha256=receipt.receipt_sha256 if receipt else None,
                        preflight_checkpoint_sha256s=tuple(
                            marker.checkpoint_sha256 for marker in markers
                        ),
                        proof_kind=proof_kind,
                        legacy_containment=containment
                        if proof_kind == "legacy_execution_contained"
                        else None,
                        # Current rescue facts retain their pre-binding proof
                        # for exact crash replay. Historical traversal binds the
                        # saved authority only after this invocation is superseded.
                        legacy_binding_sha256=historical_legacy[1].binding_sha256
                        if (
                            proof_kind == "legacy_execution_contained"
                            and historical_legacy
                            and (legacy is None or legacy.original_start != start)
                        )
                        else None,
                    )
                )
                continue
            if outcome is not None or receipt is not None:
                raise ValueError("原调用缺少启动记录, 禁止猜测为未执行")
            # Another checkpoint can legitimately reuse the role/attempt. Only
            # this immutable WorkItem's real claims prove it was ever owned.
            result.append(
                BaselineInvocationProof(
                    work_item_id=item.id,
                    step_sha256=digest(step.to_wire()),
                    preflight_checkpoint_sha256=markers[0].checkpoint_sha256
                    if len(markers) == 1
                    else None,
                    preflight_checkpoint_sha256s=tuple(
                        marker.checkpoint_sha256 for marker in markers
                    ),
                    proof_kind="claimed_preflight" if markers else "unclaimed",
                )
            )
        return tuple(result)

    def _reservation(
        self,
        task: Task,
        item: QueuedWorkItem,
        receipts: tuple[ExecutionInterruptionReceipt, ...],
        *,
        legacy: LegacyExecutionContainment | None = None,
    ) -> BaselineExecutionReservation:
        root = self.state / "invocations"
        records = KnowledgeRecordStore(root, read_only=True) if root.is_dir() else None
        start = (
            records.find("invocation-starts", item.id, DeliveryInvocationStart) if records else None
        )
        if start is None:
            if item.attempt not in {max(task.attempts, 1), task.attempts + 1}:
                raise ValueError("未调用的工作项没有精确当前或下一执行预留")
            if item.attempt > task.attempts and (
                task.work_budget_exhausted or item.attempt > task.max_attempts
            ):
                raise ValueError("代码基线更新不补充原工作额度")
            return BaselineExecutionReservation(
                current_attempt=item.attempt,
                next_execution_attempt=item.attempt,
                retry_cause="uninvoked",
                reservation_already_applied=item.attempt == task.attempts,
            )
        outcome = (
            records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome)
            if records
            else None
        )
        receipt = next(
            (entry for entry in receipts if entry.request.run_id == start.request.run_id), None
        )
        if outcome is not None and outcome.result.status is AgentRunStatus.SUCCEEDED:
            raise ValueError("原调用已有成功结果, 需要先接纳封存结果, 不能用基线更新覆盖")
        failure = None
        if legacy is not None:
            legacy.validate_integrity()
            if (
                outcome is not None
                or receipt is not None
                or legacy.original_start != start
                or task.attempts != start.request.attempt
                or task.work_budget_exhausted
                or start.request.attempt + 1 > task.max_attempts
            ):
                raise ValueError("旧执行救援不补充工作额度, 需要精确原执行和下一次工作预留")
            return BaselineExecutionReservation(
                current_attempt=start.request.attempt,
                next_execution_attempt=start.request.attempt + 1,
                retry_cause="legacy_execution_abandoned",
                original_run_id=start.request.run_id,
                current_invocation_start_sha256=start.start_sha256,
                containment_sha256=legacy.containment_sha256,
            )
        if receipt is not None:
            cause = receipt.cause
            error_code = receipt.original_error_code.value
        elif (
            outcome is not None
            and outcome.result.error is not None
            and outcome.result.error.code.value in TRANSIENT_CODES
        ):
            cause = "provider_transient"
            error_code = outcome.result.error.code.value
        else:
            raise ValueError("基线更新没有明确、可预算的原调用终结事实")
        successor = start.request.attempt + 1
        if cause == "provider_transient":
            failure = DeliveryRetryFailure.model_validate(
                {
                    "role": "coder",
                    "attempt": start.request.attempt,
                    "run_id": start.request.run_id,
                    "code": error_code,
                }
            )
            reserved = task.with_retry_failure(failure)
            if reserved.attempts != successor:
                raise ValueError("基线接续没有剩余的服务故障额度")
            already = reserved == task
        else:
            already = task.attempts == successor
            if not already and (
                task.attempts != start.request.attempt
                or task.work_budget_exhausted
                or successor > task.max_attempts
            ):
                raise ValueError("基线接续没有剩余的工作额度或精确原执行身份")
        return BaselineExecutionReservation(
            current_attempt=start.request.attempt,
            next_execution_attempt=successor,
            retry_cause=cause,
            original_run_id=start.request.run_id,
            current_invocation_start_sha256=start.start_sha256,
            current_invocation_outcome_sha256=outcome.outcome_sha256 if outcome else None,
            interruption_receipt_sha256=receipt.receipt_sha256 if receipt else None,
            retry_failure=failure,
            reservation_already_applied=already,
        )

    def _legacy_containment(self, task: Task, item: QueuedWorkItem) -> LegacyExecutionContainment:
        disposition = item.wait_disposition
        if (
            item.status not in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
            or disposition is None
            or disposition.facts.classification not in {"EXECUTION_UNCERTAIN", "PLATFORM_BUG"}
            or disposition.facts.task_intent_sha256 != task_intent_sha256(task)
            or disposition.facts.checkpoint_sequence != item.checkpoint_sequence
        ):
            raise ValueError("旧执行救援只处理当前尚未确认结果的 Coder 等待")
        root = self.state / "invocations"
        if not root.is_dir():
            raise ValueError("旧执行救援缺少真实原调用启动记录")
        records = KnowledgeRecordStore(root, read_only=True)
        start = records.get("invocation-starts", item.id, DeliveryInvocationStart)
        start.validate_integrity()
        if (
            start.request.task_id != task.id
            or start.request.role is not AgentRole.CODER
            or start.request.permissions != self.permissions
            or start.request.source_revision != disposition.facts.source_revision
            or start.checkpoint_sequence != item.checkpoint_sequence
        ):
            raise ValueError("旧执行救援启动记录与当前原权限和等待版本不一致")
        if records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome) is not None:
            raise ValueError("原调用结果已存在, 请先让平台处理原结果, 无需旧执行救援")
        claim = self.queue.original_claim(start.lease_id)
        capture_root = self.state / "continuations" / task.id
        if any(
            (capture_root / name).exists() or (capture_root / name).is_symlink()
            for name in (
                f"capture-start-{start.request.run_id}.json",
                f"capture-stop-{start.request.run_id}.json",
                f"receipt-{start.request.run_id}.json",
            )
        ):
            raise ValueError("原执行已有现场或停止记录, 请使用原执行记录处理路径")
        self._require_legacy_routes(start)
        # Resolve only the original manager-owned checkout. A missing checkout is
        # not rebuilt, and HTTP cannot select a process-survey root.
        boot = self._observe_legacy_boot()
        sealed: LegacyExecutionContainment | None = getattr(
            self, "_sealed_legacy_observation", None
        )
        if sealed is not None:
            if sealed.original_start != start or sealed.original_claim != claim:
                raise ValueError("恢复方案的原调用或历史领取记录已变化")
            worktree_path = Path(self.scope.repository_root)
            if sealed.method == "operator_confirmed_local_stop":
                worktree_path = self.git.recover(
                    WorktreeSpec(
                        task_id=task.id,
                        role=AgentRole.CODER,
                        attempt=1,
                        source_revision=start.request.source_revision,
                    )
                ).path
            self._verify_legacy_observation(sealed, worktree_root=worktree_path)
            return sealed
        survey = None
        method: Literal["os_reboot", "operator_confirmed_local_stop"] = "os_reboot"
        if boot.booted_at <= start.started_at:
            worktree = self.git.recover(
                WorktreeSpec(
                    task_id=task.id,
                    role=AgentRole.CODER,
                    attempt=1,
                    source_revision=start.request.source_revision,
                )
            )
            survey = self.local_execution_observer.observe(worktree_root=worktree.path, boot=boot)
            survey.require_idle()
            if not boot.same_boot(self._observe_legacy_boot()):
                raise LegacyRescuePrerequisiteError(
                    code="LOCAL_OBSERVATION_CHANGED",
                    safe_message="检查期间电脑启动会话发生变化, 恢复尚未安排。",
                    next_action="请等当前服务稳定后重新准备恢复方案。",
                )
            method = "operator_confirmed_local_stop"
        containment = LegacyExecutionContainment.create(
            scope=self.scope,
            requirement_id=self.requirement_id,
            dispatch_sha256=self.allocation.dispatch_sha256,
            task_intent_sha256=task_intent_sha256(task),
            original_start=start,
            original_claim=claim,
            boot=boot,
            method=method,
            local_execution_survey=survey,
        )
        self._sealed_legacy_observation = containment
        return containment

    def _require_legacy_routes(self, start: DeliveryInvocationStart) -> None:
        root = self.route_root
        if root is None or not root.is_dir():
            return
        routes = FileModelRouteAttemptStore(root, read_only=True).list_for_run(start.request.run_id)
        for ordinal, route in enumerate(routes, start=1):
            route.validate_integrity()
            if route.route_index != ordinal or route.request_sha256 != digest(
                start.request.to_wire()
            ):
                raise ValueError("原模型路由记录与完整原调用不一致")
            if route.outcome is not RouteAttemptOutcome.FALLBACK:
                raise ValueError("原模型已有封存最终结果, 请先处理原结果")
            if route.route_kind != "codex_cli":
                raise ValueError("旧执行救援只支持可由原电脑整机重启隔离的本机执行")
        if routes:
            # A sealed fallback describes the completed previous route, not the
            # route which was entered afterwards. Missing next-route facts cannot
            # be interpreted as a local native invocation.
            raise ValueError("原执行发生过模型切换但后续路由尚未封存, 不能确认本机救援边界")

    def _historical_legacy(
        self, task: Task, start: DeliveryInvocationStart, claim: QueueClaim
    ) -> tuple[LegacyExecutionContainment, ExecutionBaselineBinding] | None:
        store = getattr(getattr(self, "inputs", None), "store", None)
        if store is None:
            return None
        matches: list[tuple[LegacyExecutionContainment, ExecutionBaselineBinding]] = []
        for binding in store.bindings_for_task(task.id):
            if binding.purpose is not BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                continue
            plan = store.plan(binding.plan_sha256)
            containment = plan.facts.legacy_containment
            if containment is None or containment.original_start != start:
                continue
            authority = store.records.get(
                "baseline-authorities", plan.plan_sha256, BaselineOperatorAuthorization
            )
            authority.validate_integrity()
            authority.require_plan_confirmation(plan)
            containment.validate_integrity()
            if (
                containment.original_claim != claim
                or containment.scope != self.scope
                or containment.requirement_id != self.requirement_id
                or containment.dispatch_sha256 != self.allocation.dispatch_sha256
                or containment.task_intent_sha256 != task_intent_sha256(task)
                or containment.original_start.request.permissions != self.permissions
                or binding.legacy_containment_sha256 != containment.containment_sha256
                or binding.authority_source != "engineering_operator_decision"
                or binding.authority_sha256 != authority.authorization_sha256
                or authority.plan_sha256 != plan.plan_sha256
                or authority.facts_sha256 != plan.facts.facts_sha256
                or authority.task_id != task.id
                or authority.task_intent_sha256 != task_intent_sha256(task)
            ):
                raise ValueError("旧执行历史隔离记录缺少精确原事实和工程确认")
            matches.append((containment, binding))
        if len(matches) > 1:
            raise ValueError("同一旧执行存在重复救援记录, 禁止重复预留")
        return matches[0] if matches else None

    def _preflight_markers(
        self, task: Task, item: QueuedWorkItem, claims: tuple[QueueClaim, ...]
    ) -> tuple[DeliveryPreflightCheckpoint, ...]:
        if not claims:
            return ()
        root = self.state / "delivery-preflight"
        if not root.is_dir():
            raise ValueError("历史 claim 没有可验证的调用或执行前停止记录")
        records = KnowledgeRecordStore(root, read_only=True)
        claims_by_lease = {claim.lease.id: claim for claim in claims}
        if len(claims_by_lease) != len(claims):
            raise ValueError("执行前停止调查含重复的历史 claim")
        matches: dict[str, DeliveryPreflightCheckpoint] = {}
        for marker in records.list("preflight-checkpoints", DeliveryPreflightCheckpoint):
            if marker.work_item_id != item.id or marker.lease_id not in claims_by_lease:
                continue
            marker.validate_integrity()
            prior = records.get(
                "preflight-receipts", marker.receipt_sha256, DeliveryPreflightReceipt
            )
            prior.validate_integrity()
            claim = claims_by_lease[marker.lease_id]
            step = self.queue.step_for_claim(claim)
            self._require_step(item, step)
            if (
                marker.task_id,
                marker.checkpoint_sequence,
                marker.source_revision,
                prior.task_id,
                prior.scope.repository_id,
                prior.scope.team_id,
                prior.scope.project_id,
                prior.scope.requirement_id,
                prior.source_revision,
                claim.work_item.id,
                claim.work_item.task_id,
                claim.work_item.role,
                claim.work_item.attempt,
                claim.work_item.checkpoint_sequence,
            ) != (
                task.id,
                item.checkpoint_sequence,
                step.boundary.source_revision,
                task.id,
                self.scope.repository_id,
                self.scope.team_id,
                self.scope.project_id,
                self.requirement_id,
                step.boundary.source_revision,
                item.id,
                task.id,
                item.role,
                item.attempt,
                item.checkpoint_sequence,
            ) or prior.status != "WAIT_ENGINEERING":
                raise ValueError("执行前停止记录与真实原 claim 不一致")
            if marker.lease_id in matches:
                raise ValueError("同一历史 claim 有多个执行前停止记录, 无法证明精确调用边界")
            matches[marker.lease_id] = marker
        if set(matches) != set(claims_by_lease):
            raise ValueError("历史 claim 没有可验证的调用或执行前停止记录")
        return tuple(matches[identity] for identity in sorted(matches))
