"""Trusted same-Task baseline draft admission, never an arbitrary dirty allowance."""

from collections.abc import Callable
from pathlib import Path

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.domain.artifact import CoderProgressArtifact, ImplementationReportArtifact
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.orchestration.retry import _active_progress, _latest
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
        implementation = _latest(artifacts, ImplementationReportArtifact)
        progress = _latest(artifacts, CoderProgressArtifact)
        previous_source = self.inputs.current(task, implementation=implementation, progress=None)
        current_implementation = implementation
        if previous_source.baseline is not None:
            baseline = previous_source.baseline
            if (
                progress is not None
                and progress.artifact_id == baseline.superseded_progress_artifact_id
            ):
                progress = None
            if (
                current_implementation is not None
                and current_implementation.artifact_id
                == baseline.superseded_implementation_artifact_id
            ):
                current_implementation = None
        progress = _active_progress(progress, current_implementation, artifacts)
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
        capture = self.git.capture_mutations(
            worktree,
            request.permissions,
            denied_paths=plan.facts.denied_paths,
        )
        if source.active_progress is not None:
            checkpoint = source.active_progress
            paths = tuple(sorted(change.path for change in checkpoint.content.changed_files))
            if (
                request.continuation_checkpoint_id != checkpoint.artifact_id
                or request.continuation_changed_paths != paths
                or capture.changed_paths != paths
            ):
                raise ValueError("执行基线后的继续草稿不匹配已接纳的精确 checkpoint")
        elif request.continuation_checkpoint_id is not None:
            raise ValueError("旧 progress 不能在新执行基线中复活")
        elif source.source_revision == binding.execution_source_revision:
            if capture_mutation_inventory(worktree.path).sha256 != binding.after_inventory_sha256:
                raise ValueError("执行基线发布后草稿现场发生漂移, 禁止开始 Coder")
        elif capture.changed_paths:
            raise ValueError("后续候选返工必须从已接纳的干净输入开始")
        self.guard.check()
