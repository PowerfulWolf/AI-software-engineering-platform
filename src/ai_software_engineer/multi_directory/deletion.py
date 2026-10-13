"""Stop checks for product deletion without erasing immutable engineering facts."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
from collections.abc import Iterator
from contextlib import AbstractContextManager, ExitStack, closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import Field
from pymysql.cursors import DictCursor

from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import Task
from ai_software_engineer.domain.workforce import TaskLease
from ai_software_engineer.git.ports import WorktreeRef, WorktreeSpec
from ai_software_engineer.git.release import WorktreeReleaseArchive, WorktreeReleaseRejected
from ai_software_engineer.git.worktree import GitWorkspaceError, GitWorktreeManager
from ai_software_engineer.manager.delivery import _delivery_id
from ai_software_engineer.manager.delivery_checkpoint import (
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.dispatch import VerificationReservation
from ai_software_engineer.multi_directory.cancellation import (
    FileRequirementCancellationStore,
    RequirementCancellationAction,
    RequirementCancellationQueue,
    RequirementCancellationRejected,
    RequirementCancellationService,
    RequirementCancellationTarget,
)
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.production import DerivedStageInputs
from ai_software_engineer.multi_directory.purge import RequirementPurgePlan, RequirementPurger
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.verification_records import CandidateVerificationPlan
from ai_software_engineer.safe_files import _read_regular, _reject_symlinks
from ai_software_engineer.store.mysql_repository import (
    MySqlTaskRepository,
    _decode_task,
    open_mysql_connection,
)
from ai_software_engineer.work_queue.models import QueuedWorkItem


class _VerificationPlanEnvelope(DomainModel):
    record: CandidateVerificationPlan
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class RequirementDeletionRejected(ValueError):
    """An active or unverifiable delivery cannot be deleted from the product view."""


class RequirementDeletionGuard(Protocol):
    def protect(self, checkpoint: JointCheckpoint) -> AbstractContextManager[None]: ...


@runtime_checkable
class RequirementWaitingCloseGuard(Protocol):
    def protect_waiting_close(
        self, checkpoint: JointCheckpoint
    ) -> AbstractContextManager[None]: ...


@runtime_checkable
class RequirementPhysicalDeletionGuard(RequirementDeletionGuard, Protocol):
    def protect_physical_delete(
        self, checkpoint: JointCheckpoint
    ) -> AbstractContextManager[RequirementPurgePlan]: ...
    def purge_storage(
        self, plan: RequirementPurgePlan, *, already_fenced: bool = False
    ) -> None: ...


class RequirementExecutionQueue(Protocol):
    def items_for_task(self, task_id: str) -> tuple[QueuedWorkItem, ...]: ...
    def list_active_leases(self, *, now: datetime) -> tuple[TaskLease, ...]: ...


class ProductionRequirementDeletionGuard:
    """Hold existing Task process locks while checking durable execution facts."""

    def __init__(
        self, project: ProjectWorkspace, queue: RequirementExecutionQueue, dsn: str
    ) -> None:
        self.project, self.queue, self._dsn = project, queue, dsn

    def protect(self, checkpoint: JointCheckpoint) -> AbstractContextManager[None]:
        return self._protect_stopped(checkpoint, action="DELETE_REQUIREMENT")

    def protect_waiting_close(self, checkpoint: JointCheckpoint) -> AbstractContextManager[None]:
        return self._protect_stopped(checkpoint, action="CLOSE_REQUIREMENT")

    @contextmanager
    def _protect_stopped(
        self, checkpoint: JointCheckpoint, *, action: RequirementCancellationAction
    ) -> Iterator[None]:
        with self._protect(checkpoint, action=action):
            yield

    @contextmanager
    def protect_physical_delete(
        self, checkpoint: JointCheckpoint
    ) -> Iterator[RequirementPurgePlan]:
        with self._protect(checkpoint, action="DELETE_REQUIREMENT", physical=True) as plan:
            assert plan is not None
            yield plan

    def purge_storage(self, plan: RequirementPurgePlan, *, already_fenced: bool = False) -> None:
        RequirementPurger(self.project, self._dsn).execute(plan, already_fenced=already_fenced)

    def _native_identities(self, checkpoint: JointCheckpoint) -> dict[str, str]:
        identities: dict[str, str] = {}
        for record in JointJournal(self.project.requirements_root, read_only=True).history(
            checkpoint.delivery_id
        ):
            for child in record.children:
                identities[child.checkpoint.delivery_id] = child.checkpoint.repository_id
            if record.plan is not None:
                for unit in record.plan.units:
                    derived = DerivedStageInputs(record, unit.unit_id)
                    identities[
                        _delivery_id(derived.root, derived.requirement, namespace=record.project_id)
                    ] = derived.preparation.repository_id
        return identities

    @contextmanager
    def _protect(
        self,
        checkpoint: JointCheckpoint,
        *,
        action: RequirementCancellationAction,
        physical: bool = False,
    ) -> Iterator[RequirementPurgePlan | None]:
        targets = self._targets(checkpoint)
        with ExitStack() as stack:
            for task_id, (sidecar, _) in sorted(targets.items()):
                stack.enter_context(_task_lock(sidecar / "state/queue-worker-locks", task_id))
            if self._targets(checkpoint) != targets:
                raise RequirementDeletionRejected("工程执行记录已变化, 请刷新需求后再删除。")
            self._require_no_leases(targets)
            with self._verification_resources(checkpoint, targets):
                pass  # Refuse already-running independent verification before settlement.
            if action == "CLOSE_REQUIREMENT":
                if checkpoint.stage is JointStage.DELIVERING and (
                    not targets or not isinstance(self.queue, RequirementCancellationQueue)
                ):
                    raise RequirementDeletionRejected("未配置完整工程执行停止校验, 暂不能关闭。")
                if targets and isinstance(self.queue, RequirementCancellationQueue):
                    self._settle_cancelled(checkpoint, targets, action=action)
            elif targets and isinstance(self.queue, RequirementCancellationQueue):
                tasks = self._read_tasks(targets)
                needs_settlement = any(
                    task.status not in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}
                    for task in tasks.values()
                ) or any(
                    item.status is not WorkItemStatus.CLOSED
                    for task_id in targets
                    for item in self.queue.items_for_task(task_id)
                )
                if needs_settlement:
                    self._settle_cancelled(checkpoint, targets, action=action)
                else:
                    self._require_cancellation_history(checkpoint, targets)
            self._require_inactive(targets)
            stack.enter_context(self._native_resource_cleanup(checkpoint, targets))
            # Settlement may take the dispatch fence itself. Acquire it only after
            # settlement, and hold it through resource release and parent publication.
            with self._verification_resources(checkpoint, targets) as verification:
                self._require_inactive(targets)
                self._release_worktrees(checkpoint, targets, verification=verification)
                plan = (
                    RequirementPurger(self.project, self._dsn).prepare(
                        checkpoint,
                        {**targets, **verification},
                        native_ids=self._native_identities(checkpoint),
                    )
                    if physical
                    else None
                )
                yield plan

    @contextmanager
    def _native_resource_cleanup(
        self, checkpoint: JointCheckpoint, targets: dict[str, tuple[Path, str]]
    ) -> Iterator[None]:
        from ai_software_engineer.domain.engineering_authority import EngineeringScope
        from ai_software_engineer.manager.python_mysql_execution import (
            reconcile_python_mysql_resources,
        )
        from ai_software_engineer.multi_directory.purge_resources import native_stores
        from ai_software_engineer.recovery.store import RecoveryRecordMissing

        with ExitStack() as stack:
            try:
                for repo in self.project.repository_registry().discover():
                    tasks = {
                        task_id for task_id, (sidecar, _) in targets.items() if sidecar == repo.root
                    }
                    scope = EngineeringScope(
                        team_id=checkpoint.team_id,
                        project_id=checkpoint.project_id,
                        repository_id=repo.repository_id,
                        repository_root=str(repo.repository_root),
                    )
                    for store in native_stores(repo.root, tasks, scope, read_only=False):
                        stack.enter_context(store.execution_lock())
                        reconcile_python_mysql_resources(store, clock=lambda: datetime.now(UTC))
                        for resource in store.list_mysql_resource_intents():
                            try:
                                store.get_mysql_resource(resource.intent.resource_id, "CLEANED")
                            except RecoveryRecordMissing as error:
                                raise RequirementDeletionRejected(
                                    "验证隔离资源尚未释放, 请等待已到期资源回收后重试。"
                                ) from error
            except (OSError, ValueError) as error:
                raise RequirementDeletionRejected(
                    "原生验证停止或资源归属无法核验, 原资源保留。"
                ) from error
            yield

    def _settle_cancelled(
        self,
        checkpoint: JointCheckpoint,
        targets: dict[str, tuple[Path, str]],
        *,
        action: RequirementCancellationAction,
    ) -> None:
        assert isinstance(self.queue, RequirementCancellationQueue)
        self._require_no_leases(targets)
        # Read and validate every historical Task owner before opening a writer.
        tasks = self._read_tasks(targets)
        repositories = {
            repo.root: repo.repository_id for repo in self.project.repository_registry().discover()
        }
        inventory = tuple(
            RequirementCancellationTarget(task=tasks[task_id], repository_id=repositories[sidecar])
            for task_id, (sidecar, _) in sorted(targets.items())
        )
        records = FileRequirementCancellationStore(
            self.project.requirements_root / checkpoint.delivery_id
        )
        try:
            with MySqlTaskRepository(self._dsn) as repository:
                RequirementCancellationService(repository, self.queue, records).cancel(
                    checkpoint, inventory, action=action
                )
        except RequirementCancellationRejected as error:
            raise RequirementDeletionRejected(str(error)) from error

    def _require_cancellation_history(
        self, checkpoint: JointCheckpoint, targets: dict[str, tuple[Path, str]]
    ) -> None:
        try:
            receipt = FileRequirementCancellationStore(
                self.project.requirements_root / checkpoint.delivery_id
            ).find()
        except RequirementCancellationRejected as error:
            raise RequirementDeletionRejected(str(error)) from error
        if receipt is None:
            return
        history = JointJournal(self.project.requirements_root, read_only=True).history(
            checkpoint.delivery_id
        )
        bound = next(
            (value for value in history if value.checkpoint_sha256 == receipt.checkpoint_sha256),
            None,
        )
        if (
            bound is None
            or (
                receipt.team_id,
                receipt.team_manifest_sha256,
                receipt.project_id,
                receipt.project_manifest_sha256,
                receipt.delivery_id,
            )
            != (
                checkpoint.team_id,
                checkpoint.team_manifest_sha256,
                checkpoint.project_id,
                checkpoint.project_manifest_sha256,
                checkpoint.delivery_id,
            )
            or {value.task.id: value.task.repository for value in receipt.tasks}
            != {task_id: root for task_id, (_, root) in targets.items()}
        ):
            raise RequirementDeletionRejected("需求取消记录的归属或历史范围无法核验。")
        repositories = {
            repo.root: repo.repository_id for repo in self.project.repository_registry().discover()
        }
        if any(
            value.repository_id != repositories[targets[value.task.id][0]]
            for value in receipt.tasks
        ):
            raise RequirementDeletionRejected("需求取消记录的仓库归属无法核验。")
        if receipt.human_action.action == "DELETE_REQUIREMENT" and bound.stage not in {
            JointStage.BLOCKED,
            JointStage.CLOSED,
            JointStage.DONE,
        }:
            raise RequirementDeletionRejected("需求删除取消记录没有对应的停止历史。")
        if receipt.human_action.action == "CLOSE_REQUIREMENT" and (
            bound.stage not in {JointStage.DELIVERING, JointStage.BLOCKED}
            or not any(
                value.stage is JointStage.CLOSED
                and value.previous_checkpoint_sha256 == bound.checkpoint_sha256
                for value in history
            )
        ):
            raise RequirementDeletionRejected("需求关闭取消记录没有对应的完成历史。")

    def _targets(self, checkpoint: JointCheckpoint) -> dict[str, tuple[Path, str]]:
        self.project.validate_current()
        repositories = {
            repo.repository_id: repo for repo in self.project.repository_registry().discover()
        }
        journal = JointJournal(self.project.requirements_root, read_only=True)
        history = journal.history(checkpoint.delivery_id)
        if not history or history[-1] != checkpoint:
            raise RequirementDeletionRejected("需求记录已变化, 请刷新后再删除。")
        targets: dict[str, tuple[Path, str]] = {}
        child_histories: dict[tuple[str, str], tuple[ProjectDeliveryCheckpoint, ...]] = {}
        for record in history:
            identities = {
                (
                    child.checkpoint.repository_id,
                    child.checkpoint.delivery_id,
                    child.checkpoint.repository_root,
                )
                for child in record.children
            }
            if record.plan is not None:
                for unit in record.plan.units:
                    derived = DerivedStageInputs(record, unit.unit_id)
                    repository_id = derived.preparation.repository_id
                    identities.add(
                        (
                            repository_id,
                            _delivery_id(
                                derived.root, derived.requirement, namespace=record.project_id
                            ),
                            derived.root,
                        )
                    )
            for repository_id, delivery_id, repository_root in sorted(identities):
                repository = repositories.get(repository_id)
                if repository is None or str(repository.repository_root) != repository_root:
                    raise RequirementDeletionRejected("需求的仓库归属无法核验, 暂不能删除。")
                key = (repository_id, delivery_id)
                if key not in child_histories:
                    native_root = repository.root / "state/project-deliveries"
                    _reject_symlinks(native_root)
                    child_histories[key] = (
                        FileProjectDeliveryCheckpointStore(native_root, read_only=True).list(
                            delivery_id
                        )
                        if native_root.exists()
                        else ()
                    )
                child_history = child_histories[key]
                if any(
                    child.checkpoint not in child_history
                    for child in record.children
                    if child.checkpoint.delivery_id == delivery_id
                ):
                    raise RequirementDeletionRejected("需求的子交付记录无法核验, 暂不能删除。")
                for item in child_history:
                    if (
                        item.repository_id != repository_id
                        or item.repository_root != repository_root
                    ):
                        raise RequirementDeletionRejected("子交付历史的仓库归属无法核验。")
                    if item.task_id is None:
                        continue
                    target = (repository.root, repository_root)
                    if item.task_id in targets and targets[item.task_id] != target:
                        raise RequirementDeletionRejected("执行任务的仓库归属不一致, 暂不能删除。")
                    targets[item.task_id] = target
        return targets

    @contextmanager
    def _verification_resources(
        self, checkpoint: JointCheckpoint, targets: dict[str, tuple[Path, str]]
    ) -> Iterator[dict[str, tuple[Path, str]]]:
        """Fence independent verifier admission until CLOSED/retirement is durable."""
        with closing(open_mysql_connection(self._dsn)) as connection:
            try:
                connection.begin()
                with connection.cursor(DictCursor) as cursor:
                    cursor.execute("SELECT id FROM dispatch_authority_lock WHERE id=1 FOR UPDATE")
                    if cursor.fetchone() is None:
                        raise RequirementDeletionRejected("独立验证分配锁无法核验, 原资源仍保留。")
                    cursor.execute(
                        "SELECT plan_sha256,payload_json,completion_sha256,abandonment_sha256 "
                        "FROM verification_reservations ORDER BY plan_sha256"
                    )
                    resources = self._validated_verification_resources(
                        checkpoint, targets, cursor.fetchall()
                    )
                    yield resources
            finally:
                connection.rollback()

    def _validated_verification_resources(
        self,
        checkpoint: JointCheckpoint,
        targets: dict[str, tuple[Path, str]],
        rows: object,
    ) -> dict[str, tuple[Path, str]]:
        if not isinstance(rows, (list, tuple)):
            raise RequirementDeletionRejected("独立验证分配记录无法核验。")
        repositories = {repo.root: repo for repo in self.project.repository_registry().discover()}
        resources: dict[str, tuple[Path, str]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("payload_json"), str):
                raise RequirementDeletionRejected("独立验证分配记录无法核验。")
            reservation = VerificationReservation.model_validate_json(row["payload_json"])
            if reservation.plan_sha256 != row.get("plan_sha256"):
                raise RequirementDeletionRejected("独立验证分配身份不一致。")
            target = targets.get(reservation.source_task_id)
            if target is None:
                continue
            sidecar, repository_root = target
            if repositories[sidecar].repository_id != reservation.repository_id:
                raise RequirementDeletionRejected("独立验证分配仓库归属不一致。")
            released = [row.get("completion_sha256"), row.get("abandonment_sha256")]
            if sum(value is not None for value in released) != 1 or any(
                value is not None
                and (not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None)
                for value in released
            ):
                raise RequirementDeletionRejected(
                    "需求的独立验证尚未结束或无法核验, 请先停止验证。"
                )
            # Scope is taken only from the verified plan filename under this sidecar.
            candidates = tuple(
                (sidecar / "state").glob(
                    "candidate-verification-*/verification-plan-"
                    + reservation.plan_sha256
                    + ".json"
                )
            )
            if len(candidates) != 1:
                raise RequirementDeletionRejected("独立验证计划无法精确定位, 原资源仍保留。")
            path = candidates[0]
            plan = _VerificationPlanEnvelope.model_validate_json(
                _read_regular(path, 8_000_000)
            ).record
            plan.validate_integrity()
            native_history = FileProjectDeliveryCheckpointStore(
                sidecar / "state/project-deliveries", read_only=True
            ).list(plan.scope.delivery_id)
            if (
                plan.plan_sha256 != reservation.plan_sha256
                or plan.scope.team_id != checkpoint.team_id
                or plan.scope.repository_id != reservation.repository_id
                or plan.scope.repository_root != repository_root
                or plan.inputs.task_id != reservation.source_task_id
                or plan.execution_task_id != reservation.task_id
                or path.parent.name != "candidate-verification-" + plan.scope.delivery_id
                or not any(item.task_id == reservation.source_task_id for item in native_history)
                or (
                    plan.parent_delivery_id is not None
                    and plan.parent_delivery_id != checkpoint.delivery_id
                )
            ):
                raise RequirementDeletionRejected("独立验证计划的需求归属不一致, 原资源仍保留。")
            store = FileRecoveryStore(path.parent, scope=plan.scope)
            if store.get_verification_plan(plan.plan_sha256) != plan:
                raise RequirementDeletionRejected("独立验证完整计划无法核验。")
            if row.get("completion_sha256") is not None:
                completion = store.get_verification_completion(plan.plan_sha256)
                if completion.completion_sha256 != row["completion_sha256"]:
                    raise RequirementDeletionRejected("独立验证完成记录无法核验, 原资源仍保留。")
            if reservation.task_id in resources or reservation.task_id in targets:
                raise RequirementDeletionRejected("独立验证执行身份重复, 原资源仍保留。")
            resources[reservation.task_id] = target
        return resources

    def _release_worktrees(
        self,
        checkpoint: JointCheckpoint,
        targets: dict[str, tuple[Path, str]],
        *,
        verification: dict[str, tuple[Path, str]] | None = None,
    ) -> None:
        """Only deterministic registered resources of this complete stopped history."""
        try:
            self._release_owned_worktrees(checkpoint, targets, verification=verification or {})
        except (GitWorkspaceError, WorktreeReleaseRejected, OSError, ValueError) as error:
            raise RequirementDeletionRejected(
                "需求执行已停止, 但资源尚未完全释放;保全记录和剩余文件仍保留, 请检查后重试。"
            ) from error

    def _release_owned_worktrees(
        self,
        checkpoint: JointCheckpoint,
        targets: dict[str, tuple[Path, str]],
        *,
        verification: dict[str, tuple[Path, str]],
    ) -> None:
        platform = Path(self.project.team.manifest.platform_root)
        archive_root = self.project.requirements_root / checkpoint.delivery_id / "resource-archives"
        owned: dict[Path, tuple[GitWorktreeManager, str, AgentRole, int]] = {}
        tasks = self._read_tasks(targets) if targets else {}
        repositories = {repo.root: repo for repo in self.project.repository_registry().discover()}
        for task_id, task in tasks.items():
            sidecar, repository_root = targets[task_id]
            repo = repositories[sidecar]
            root = platform / "worktrees" / repo.repository_id
            _reject_symlinks(root)
            manager = GitWorktreeManager(
                repository_root, root, branch_names={task_id: task.branch_name}
            )
            directory = root / task_id
            _reject_symlinks(directory)
            for path in sorted(directory.glob("[a-z]*-attempt-*")):
                _reject_symlinks(path)
                role_text, attempt_text = path.name.split("-attempt-", 1)
                role, attempt = AgentRole(role_text), int(attempt_text)
                spec = WorktreeSpec(
                    task_id=task_id, role=role, attempt=attempt, source_revision=task.base_ref
                )
                if path != manager._target_path(spec):
                    raise RequirementDeletionRejected("工程工作区身份无法核验, 原文件仍保留。")
                owned[path] = (manager, task_id, role, attempt)
        for execution_id, (sidecar, repository_root) in verification.items():
            repo = repositories[sidecar]
            manager = GitWorktreeManager(
                repository_root, platform / "worktrees" / repo.repository_id
            )
            for role in (AgentRole.QA, AgentRole.REVIEWER):
                path = (
                    platform
                    / "worktrees"
                    / repo.repository_id
                    / execution_id
                    / f"{role.value}-attempt-01"
                )
                if path.exists() or path.is_symlink():
                    owned[path] = (manager, execution_id, role, 1)
        history = JointJournal(self.project.requirements_root, read_only=True).history(
            checkpoint.delivery_id
        )
        for record in history:
            for unit in record.scope.units:
                root = platform / "worktrees/requirements" / record.delivery_id / unit.id
                _reject_symlinks(root)
                manager = GitWorktreeManager(unit.root, root)
                task_id = (
                    "task_baseline_"
                    + hashlib.sha256(f"{record.delivery_id}:{unit.id}".encode()).hexdigest()[:32]
                )
                path = root / task_id / "reviewer-attempt-01"
                owned[path] = (manager, task_id, AgentRole.REVIEWER, 1)
                for child in record.children:
                    if child.unit_id != unit.id or child.checkpoint.candidate_revision is None:
                        continue
                    revision = child.checkpoint.candidate_revision
                    task_id = (
                        "task_candidate_"
                        + hashlib.sha256(
                            f"{record.delivery_id}:{unit.id}{revision}".encode()
                        ).hexdigest()[:32]
                    )
                    path = root / task_id / "reviewer-attempt-01"
                    owned[path] = (manager, task_id, AgentRole.REVIEWER, 1)
        archived: dict[Path, WorktreeReleaseArchive] = {}
        _reject_symlinks(archive_root)
        for path in sorted(archive_root.glob("*/archive.json")):
            manifest = WorktreeReleaseArchive.model_validate_json(
                _read_regular(path, 32 * 1024 * 1024)
            )
            target = Path(manifest.worktree_path)
            if manifest.task_id in targets or manifest.task_id in verification:
                sidecar, repository_root = {**targets, **verification}[manifest.task_id]
                archived_task = tasks.get(manifest.task_id)
                repo = repositories[sidecar]
                manager = GitWorktreeManager(
                    repository_root,
                    platform / "worktrees" / repo.repository_id,
                    branch_names={manifest.task_id: archived_task.branch_name}
                    if archived_task is not None
                    else None,
                )
                role = AgentRole(manifest.role)
                if archived_task is None and (
                    role not in {AgentRole.QA, AgentRole.REVIEWER} or manifest.attempt != 1
                ):
                    raise WorktreeReleaseRejected("独立验证保全身份不一致。")
                spec = WorktreeSpec(
                    task_id=manifest.task_id,
                    role=role,
                    attempt=manifest.attempt,
                    source_revision=manifest.head_revision,
                )
                if target != manager._target_path(spec):
                    raise WorktreeReleaseRejected("资源保全路径与受管身份不同。")
                owned[target] = (manager, manifest.task_id, role, manifest.attempt)
            if target not in owned:
                raise WorktreeReleaseRejected("资源保全不属于需求完整历史。")
            archived[target] = manifest
        # Validate every resource before the first archive/reset/remove.
        validated: list[tuple[GitWorktreeManager, WorktreeRef]] = []
        try:
            for path, (manager, task_id, role, attempt) in sorted(owned.items()):
                _reject_symlinks(path)
                if not path.exists():
                    saved = archived.get(path)
                    if saved is None:
                        continue
                    validated.append(
                        (
                            manager,
                            WorktreeRef(
                                task_id=task_id,
                                role=role,
                                attempt=attempt,
                                path=path,
                                head_revision=saved.head_revision,
                                branch=saved.branch,
                                detached=saved.branch is None,
                            ),
                        )
                    )
                    continue
                revision = manager._run_git(("rev-parse", "HEAD"), cwd=path)
                spec = WorktreeSpec(
                    task_id=task_id, role=role, attempt=attempt, source_revision=revision
                )
                validated.append((manager, manager.recover(spec)))
            for manager, worktree in validated:
                self._require_no_leases(targets)
                manager.archive_and_remove(
                    worktree,
                    archive_root=archive_root,
                    owner_sha256=hashlib.sha256(
                        (
                            checkpoint.team_id
                            + ":"
                            + checkpoint.project_id
                            + ":"
                            + checkpoint.delivery_id
                        ).encode()
                    ).hexdigest(),
                )
        except (GitWorkspaceError, WorktreeReleaseRejected, OSError, ValueError) as error:
            raise RequirementDeletionRejected(
                "需求执行已停止, 但资源尚未完全释放;已保存保全和原文件, 请检查资源记录后重试。"
            ) from error

    def _require_inactive(self, targets: dict[str, tuple[Path, str]]) -> None:
        if not targets:
            return
        self._require_no_leases(targets)
        repository_ids = {
            repo.root: repo.repository_id for repo in self.project.repository_registry().discover()
        }
        for task_id, (sidecar, repository_root) in targets.items():
            items = self.queue.items_for_task(task_id)
            if any(item.status is not WorkItemStatus.CLOSED for item in items):
                raise RequirementDeletionRejected("需求仍有未结束的工程队列, 请先停止执行后删除。")
            if any(
                item.task_id != task_id
                or item.repository_id != repository_ids[sidecar]
                or item.repository_scopes != (repository_root,)
                for item in items
            ):
                raise RequirementDeletionRejected("需求的工程队列归属无法核验, 暂不能删除。")
        for task in self._read_tasks(targets).values():
            if task.status not in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}:
                raise RequirementDeletionRejected("需求的工程任务尚未终止, 请先停止执行后删除。")

    def _require_no_leases(self, targets: dict[str, tuple[Path, str]]) -> None:
        now = datetime.now(UTC)
        if any(lease.task_id in targets for lease in self.queue.list_active_leases(now=now)):
            raise RequirementDeletionRejected("需求仍有有效的工程执行许可, 请等待执行停止后删除。")

    def _read_tasks(self, targets: dict[str, tuple[Path, str]]) -> dict[str, Task]:
        tasks: dict[str, Task] = {}
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            for task_id, (_, repository_root) in targets.items():
                cursor.execute("SELECT id,payload_json,status FROM tasks WHERE id=%s", (task_id,))
                row = cursor.fetchone()
                if (
                    row is None
                    or not isinstance(row["id"], str)
                    or not isinstance(row["payload_json"], str)
                ):
                    raise RequirementDeletionRejected("需求的执行任务快照无法核验, 暂不能删除。")
                task = _decode_task(row["id"], row["payload_json"])
                if (
                    task.id != task_id
                    or task.repository != repository_root
                    or task.status.value != row["status"]
                ):
                    raise RequirementDeletionRejected(
                        "需求的执行任务归属或状态不一致, 暂不能删除。"
                    )
                tasks[task_id] = task
        return tasks


@contextmanager
def _task_lock(root: Path, task_id: str) -> Iterator[None]:
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise RequirementDeletionRejected("工程执行锁路径无法安全核验, 暂不能删除。")
    root.mkdir(parents=True, exist_ok=True)
    path = root / (hashlib.sha256(task_id.encode()).hexdigest() + ".lock")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RequirementDeletionRejected(
                "需求仍有工程进程正在运行, 请等待停止后删除。"
            ) from error
        yield
    finally:
        os.close(fd)


__all__ = [
    "ProductionRequirementDeletionGuard",
    "RequirementDeletionGuard",
    "RequirementDeletionRejected",
    "RequirementWaitingCloseGuard",
]
