"""Read exact retained parent lineage for baseline knowledge evidence only."""

from collections.abc import Callable

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain.project_delivery import ProjectPreparation, ProjectRequest
from ai_software_engineer.manager.delivery_checkpoint import (
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
    checkpoint_is_ancestor,
)
from ai_software_engineer.manager.dispatch import DeliveryAllocation, DispatchCommitId
from ai_software_engineer.multi_directory.models import ChildDelivery, JointCheckpoint
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.product import FileProductRecordStore
from ai_software_engineer.recovery.allocation_lineage import allocation_preparation_sha256
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected, RecoveryScope
from ai_software_engineer.recovery.native import _preparation
from ai_software_engineer.team_workspace import TeamWorkspace


def recovery_knowledge_requirement_id(
    config: ProductionConfig,
    plan: RecoveryPlan,
    native: ProjectDeliveryCheckpoint,
    *,
    load_allocation: Callable[[DispatchCommitId], DeliveryAllocation],
) -> str | None:
    """Derive a lane identity, without regenerating or replacing frozen Context."""
    plan.validate_integrity()
    source = plan.source
    if source.parent_delivery_id is None:
        return None
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name, read_only=True
    )
    project, repository = team.project_registry().locate_repository(source.scope.repository_id)
    if (
        str(repository.repository_root) != source.scope.repository_root
        or source.scope.team_id != team.manifest.team_id
    ):
        raise RecoveryRejected("基线知识调查的恢复仓库或团队绑定已改变")
    parents = JointJournal(project.requirements_root, read_only=True).history(
        source.parent_delivery_id
    )
    history = FileProjectDeliveryCheckpointStore(
        project.root / "repositories" / source.scope.repository_id / "state/project-deliveries",
        read_only=True,
    ).list(source.scope.delivery_id)
    interrupted = _interrupted_checkpoint(plan, history)
    if interrupted.dispatch_commit_id is None:
        raise RecoveryRejected("基线知识调查的原中断任务缺少执行分配")
    source_allocation = load_allocation(interrupted.dispatch_commit_id)
    source_request = (
        FileProductRecordStore(repository.root / "state/product", read_only=True)
        .current_request_revision(source_allocation.project_request_id)
        .request
    )
    source_preparation = _preparation(
        repository.root, source.scope.repository_id, source.preparation_sha256
    )
    if source_preparation.repository_workspace_root != str(
        repository.root
    ) or source_preparation.team_root != str(team.root):
        raise RecoveryRejected("基线知识调查的原准备记录工作空间绑定已改变")
    return _require_retained_parent(
        plan,
        native,
        parents=parents,
        history=history,
        team_id=team.manifest.team_id,
        team_manifest_sha256=team.manifest.manifest_sha256,
        project_id=project.manifest.project_id,
        project_manifest_sha256=project.manifest.manifest_sha256,
        source_allocation=source_allocation,
        source_request=source_request,
        source_preparation=source_preparation,
    )


def _interrupted_checkpoint(
    plan: RecoveryPlan, history: tuple[ProjectDeliveryCheckpoint, ...]
) -> ProjectDeliveryCheckpoint:
    matches = tuple(
        item for item in history if item.checkpoint_sha256 == plan.source.checkpoint_sha256
    )
    if len(matches) != 1:
        raise RecoveryRejected("基线知识调查缺少精确原中断交付记录")
    return matches[0]


def _matching_child(parent: JointCheckpoint, scope: RecoveryScope) -> ChildDelivery:
    children = tuple(
        child
        for child in parent.children
        if child.checkpoint.delivery_id == scope.delivery_id
        and child.checkpoint.repository_id == scope.repository_id
        and child.checkpoint.repository_root == scope.repository_root
    )
    if len(children) != 1:
        raise RecoveryRejected("基线知识调查的父需求仓库单元缺失或不唯一")
    return children[0]


def _require_retained_parent(
    plan: RecoveryPlan,
    native: ProjectDeliveryCheckpoint,
    *,
    parents: tuple[JointCheckpoint, ...],
    history: tuple[ProjectDeliveryCheckpoint, ...],
    team_id: str,
    team_manifest_sha256: str,
    project_id: str,
    project_manifest_sha256: str,
    source_allocation: DeliveryAllocation,
    source_request: ProjectRequest,
    source_preparation: ProjectPreparation,
) -> str:
    """Require exact snapshots from already fully validated append-only readers."""
    source = plan.source
    matches = tuple(
        item for item in parents if item.checkpoint_sha256 == source.parent_checkpoint_sha256
    )
    if source.parent_delivery_id is None or len(matches) != 1:
        raise RecoveryRejected("基线知识调查缺少精确获批父需求历史记录")
    original, current = matches[0], parents[-1]
    if any(
        parent.delivery_id != source.parent_delivery_id
        or parent.team_id != team_id
        or parent.team_manifest_sha256 != team_manifest_sha256
        or parent.project_id != project_id
        or parent.project_manifest_sha256 != project_manifest_sha256
        for parent in (original, current)
    ):
        raise RecoveryRejected("基线知识调查的父需求组织或项目绑定已改变")
    if (
        original.approval is None
        or original.product_spec is None
        or original.design is None
        or original.plan is None
        or any(
            getattr(current, field) != getattr(original, field)
            for field in ("scope", "product_spec", "approval", "design", "plan")
        )
    ):
        raise RecoveryRejected("基线知识调查的父需求原批准范围或阶段产物已改变")
    old_child = _matching_child(original, source.scope)
    latest_child = _matching_child(current, source.scope)
    interrupted = _interrupted_checkpoint(plan, history)
    source_allocation.validate_integrity()
    source_request.validate_integrity()
    source_preparation.validate_integrity()
    if (
        source_allocation.id != interrupted.dispatch_commit_id
        or source_allocation.dispatch_sha256 != source.dispatch_sha256
        or source_allocation.task_id != source.task_id
        or source_allocation.repository_id != source.scope.repository_id
        or source_allocation.task.repository != source.scope.repository_root
        or source_request.id != interrupted.request_id
        or source_request.id != source_allocation.project_request_id
        or source_request.repository_id != source.scope.repository_id
        or source_request.preparation_sha256 != source.preparation_sha256
        or source_preparation.preparation_sha256 != source.preparation_sha256
        or source_preparation.team_id != team_id
        or source_preparation.project_id != project_id
        or source_preparation.project_manifest_sha256 != project_manifest_sha256
        or source_preparation.repository_id != source.scope.repository_id
        or source_preparation.repository_root != source.scope.repository_root
        or allocation_preparation_sha256(source_allocation, source.preparation_sha256)
        != interrupted.preparation_sha256
    ):
        raise RecoveryRejected("基线知识调查的原准备记录与获批请求或执行分配不一致")
    if (
        old_child.unit_id != latest_child.unit_id
        or native.delivery_id != source.scope.delivery_id
        or native.repository_id != source.scope.repository_id
        or native.repository_root != source.scope.repository_root
        or native.task_id != plan.new_task_id
        or interrupted.task_id != source.task_id
        or interrupted.task_revision != source.task_revision
        or interrupted.dispatch_commit_sha256 != source.dispatch_sha256
        or interrupted.product_spec_sha256 != source.product_spec_sha256
        or interrupted.approval_sha256 != source.approval_sha256
        or interrupted.technical_design_sha256 != source.technical_design_sha256
        or interrupted.execution_plan_sha256 != source.execution_plan_sha256
        or not history
        or history[-1] != native
        or any(
            not checkpoint_is_ancestor(history, child)
            for child in (old_child.checkpoint, interrupted, latest_child.checkpoint)
        )
        or old_child.checkpoint.sequence > interrupted.sequence
        or interrupted.sequence > latest_child.checkpoint.sequence
        or latest_child.checkpoint.task_id != native.task_id
    ):
        raise RecoveryRejected("基线知识调查的父子需求与原恢复任务历史链不一致")
    return source.parent_delivery_id
