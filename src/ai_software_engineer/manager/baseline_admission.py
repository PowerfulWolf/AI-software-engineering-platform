"""Trusted same-Task baseline draft admission, never an arbitrary dirty allowance."""

from collections.abc import Callable
from pathlib import Path

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.artifacts.ordering import latest_accepted_artifact
from ai_software_engineer.domain.artifact import CoderProgressArtifact, ImplementationReportArtifact
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.execution_baseline import (
    BaselineInputMode,
    BaselinePurpose,
    CoderExecutionInput,
)
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import (
    capture_mutation_inventory,
)
from ai_software_engineer.git.mutation_capture import WorktreeMutationCapture
from ai_software_engineer.manager.baseline_models import (
    ExecutionBaselinePlan,
    require_rejected_candidate_binding,
)
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.manager.rejected_candidate_output import (
    validate_rejected_candidate_inventory,
)
from ai_software_engineer.orchestration.retry import _active_progress
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


class BaselineInitialWorkspaceAdmission:
    def __init__(
        self,
        *,
        inputs: StoredCoderExecutionInputResolver,
        task_reader: Callable[[], Task],
        artifacts: ArtifactStore,
        git: GitWorktreeManager,
        guard: WorkerExecutionGuard,
    ) -> None:
        self.inputs, self.task_reader, self.artifacts, self.git, self.guard = (
            inputs,
            task_reader,
            artifacts,
            git,
            guard,
        )

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None:
        self.guard.check()
        task = self.task_reader()
        artifacts = self.artifacts.list_for_task(task.id)
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
        source = self.inputs.current(task, implementation=implementation, progress=progress)
        binding = source.baseline
        claim = self.guard.lease.claim if self.guard.lease is not None else None
        if (
            binding is None
            or self.inputs.store is None
            or claim is None
            or request.role is not AgentRole.CODER
            or request.task_id != task.id
            or request.source_revision != source.source_revision
            or request.execution_baseline_sha256 != binding.binding_sha256
            or request.execution_base_ref != binding.execution_base_ref
            or (claim.work_item.task_id, claim.work_item.role, claim.work_item.attempt)
            != (request.task_id, request.role, request.attempt)
        ):
            raise ValueError("执行基线草稿没有当前 Task、源版本和真实 Coder claim 的精确准入")
        binding.require_task(task)
        plan = self.inputs.store.plan(binding.plan_sha256)
        if request.permissions != plan.facts.permissions or (
            task.constraints is not None
            and task.constraints.denied_paths != plan.facts.denied_paths
        ):
            raise ValueError("执行基线草稿不能改变原冻结的路径或命令权限")
        worktree = self.git.recover(
            WorktreeSpec(
                task_id=task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=source.source_revision,
            )
        )
        if str(worktree.path) != binding.worktree_path or workspace_root != worktree.path:
            raise ValueError("执行基线草稿不在原需求的同一隔离分支和工作区")
        retained_paths = self.inputs.retained_source_paths(
            task, workspace_root=workspace_root, permissions=request.permissions
        )
        capture = self.git.capture_mutations(
            worktree,
            request.permissions,
            denied_paths=plan.facts.denied_paths,
            retained_source_paths=retained_paths,
        )
        if source.active_progress is not None:
            checkpoint = source.active_progress
            paths = tuple(sorted(change.path for change in checkpoint.content.changed_files))
            if (
                request.continuation_checkpoint_id != checkpoint.artifact_id
                or request.continuation_changed_paths != paths
            ):
                raise ValueError("执行基线后的继续草稿不匹配已接纳的精确 checkpoint")
            if checkpoint.artifact_id == plan.facts.progress_artifact_id:
                require_preserved_progress_capture(
                    request=request,
                    source=source,
                    plan=plan,
                    capture=capture,
                    git=self.git,
                    retained_source_paths=retained_paths,
                )
            elif capture.changed_paths != paths:
                raise ValueError("执行基线后的继续草稿不匹配已接纳的精确 checkpoint")
        elif request.continuation_checkpoint_id is not None:
            raise ValueError("旧 progress 不能在新执行基线中复活")
        elif source.source_revision == binding.execution_source_revision:
            if capture_mutation_inventory(worktree.path).sha256 != binding.after_inventory_sha256:
                raise ValueError("执行基线发布后草稿现场发生漂移, 禁止开始 Coder")
        elif capture.changed_paths:
            raise ValueError("后续候选返工必须从已接纳的干净输入开始")
        self.guard.check()

    def retained_candidate_report_base(
        self,
        request: AgentRequest,
        workspace_root: Path,
        artifact: ImplementationReportArtifact,
    ) -> str:
        """Reopen an exactly consumed candidate rescue under its fresh Coder claim.

        Only this unchanged retained candidate may be reported without a new commit.
        Actual test caches may change; every noncache byte and the full Git capture
        must still match the independently sealed original candidate.
        """
        from ai_software_engineer.work_queue.baseline import consumptions

        self.guard.check()
        task = self.task_reader()
        source = self.inputs.current(task, implementation=None, progress=None)
        binding, store = source.baseline, self.inputs.store
        lease = self.guard.lease
        if (
            binding is None
            or store is None
            or lease is None
            or binding.purpose is not BaselinePurpose.REJECTED_CANDIDATE_RESCUE
            or request.role is not AgentRole.CODER
            or request.task_id != task.id
            or request.source_revision != binding.execution_source_revision
            or request.execution_baseline_sha256 != binding.binding_sha256
            or request.execution_base_ref != binding.execution_base_ref
            or artifact.source_revision != binding.execution_source_revision
            or artifact.content.commit_sha != binding.execution_source_revision
            or (
                lease.claim.work_item.task_id,
                lease.claim.work_item.role,
                lease.claim.work_item.attempt,
            )
            != (request.task_id, request.role, request.attempt)
        ):
            raise ValueError("保留候选报告缺少最新精确工程绑定和真实 Coder claim")
        self.inputs.require_current(binding, task)
        plan = store.plan(binding.plan_sha256)
        require_rejected_candidate_binding(plan, binding)
        proof = plan.facts.rejected_candidate_output
        assert proof is not None
        if request.permissions != plan.facts.permissions:
            raise ValueError("保留候选报告不能改变原冻结的执行权限")
        matching = tuple(
            item
            for item in consumptions(lease.queue, task.id)
            if item.binding.binding_sha256 == binding.binding_sha256
        )
        if len(matching) != 1 or (
            matching[0].binding != binding
            or matching[0].plan != plan
            or matching[0].next_work_item_id != lease.claim.work_item.id
            or plan.facts.continuation is None
            or plan.facts.continuation.next_execution_attempt != request.attempt
        ):
            raise ValueError("保留候选报告没有当前 claim 对应的唯一已消费普通工作决定")
        accepted = self.artifacts.list_for_task(task.id)
        if (
            latest_accepted_artifact(
                accepted,
                ImplementationReportArtifact,
                excluded_artifact_ids=source.superseded_artifact_ids,
            )
            is not None
        ):
            raise ValueError("已接纳实现报告不能再次使用未接纳候选恢复入口")
        worktree = self.git.recover(
            WorktreeSpec(
                task_id=task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=binding.execution_source_revision,
            )
        )
        if workspace_root != worktree.path or str(worktree.path) != binding.worktree_path:
            raise ValueError("保留候选报告不在原需求的精确工作区")
        retained_paths = self.inputs.retained_source_paths(
            task,
            workspace_root=workspace_root,
            permissions=request.permissions,
        )
        dirty = self.git.capture_mutations(
            worktree,
            request.permissions,
            denied_paths=plan.facts.denied_paths,
            retained_source_paths=retained_paths,
        )
        complete = self.git.capture_mutations(
            worktree,
            request.permissions,
            denied_paths=plan.facts.denied_paths,
            base_revision=binding.execution_base_ref,
            retained_source_paths=retained_paths,
        )
        current_inventory = capture_mutation_inventory(worktree.path)
        if dirty.changed_paths or complete != proof.complete_capture.to_capture():
            raise ValueError("保留候选的完整代码、索引或非缓存现场已经变化")
        validate_rejected_candidate_inventory(proof.inventory, current_inventory)
        self.guard.check()
        return binding.execution_base_ref


def require_preserved_progress_capture(
    *,
    request: AgentRequest,
    source: CoderExecutionInput,
    plan: ExecutionBaselinePlan,
    capture: WorktreeMutationCapture,
    git: GitWorktreeManager,
    retained_source_paths: tuple[str, ...],
) -> None:
    """Revalidate the exact complete approved draft around its retained old checkpoint.

    The original progress declares accepted work. The baseline separately seals
    the complete retained draft, including lawful unfinished paths; neither fact
    changes the other. This exception cannot admit a new checkpoint or drift.
    """
    binding, checkpoint = source.baseline, source.active_progress
    if (
        binding is None
        or checkpoint is None
        or checkpoint.artifact_id != plan.facts.progress_artifact_id
        or checkpoint.artifact_id not in plan.facts.source_artifact_ids
        or checkpoint.artifact_id not in binding.source_artifact_ids
        or checkpoint.artifact_id not in request.input_artifact_ids
        or checkpoint.source_revision != source.source_revision
        or binding.input_mode is not BaselineInputMode.PRESERVE_DRAFT
        or plan.input_mode is not BaselineInputMode.PRESERVE_DRAFT
        or request.continuation_checkpoint_id != checkpoint.artifact_id
        or request.continuation_changed_paths
        != tuple(sorted(change.path for change in checkpoint.content.changed_files))
        or source.source_revision != binding.execution_source_revision
        or request.source_revision != source.source_revision
        or request.execution_baseline_sha256 != binding.binding_sha256
        or request.execution_base_ref != binding.execution_base_ref
        or request.permissions != plan.facts.permissions
        or capture != plan.dirty_capture.to_capture()
        or capture_mutation_inventory(capture.worktree.path).sha256
        != binding.after_inventory_sha256
    ):
        raise ValueError("原进度与完整批准的执行基线草稿不一致, 禁止开始 Coder")
    complete = git.capture_mutations(
        capture.worktree,
        request.permissions,
        denied_paths=plan.facts.denied_paths,
        base_revision=plan.complete_capture.base_revision,
        retained_source_paths=retained_source_paths,
    )
    if complete != plan.complete_capture.to_capture():
        raise ValueError("完整批准草稿的内容、路径或索引已变化, 禁止开始 Coder")
