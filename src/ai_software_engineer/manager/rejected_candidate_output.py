"""Pure sealed facts for re-reporting one unaccepted committed native candidate.

This record grants no execution or acceptance authority. A trusted collector must
reobserve Git ancestry, clean tracked/untracked state, the complete ignored-file
inventory and absence of publication while holding the original Task lock.
"""

from fnmatch import fnmatchcase
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator

from ai_software_engineer.agents.models import AgentRequest, AgentRunStatus
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.artifact import ImplementationReportArtifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole, ChangeType, TaskStatus
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git.mutation import (
    MAX_INVENTORY_BYTES,
    MAX_INVENTORY_FILE_BYTES,
    MAX_INVENTORY_FILES,
    WorkspaceMutationInventory,
    changed_mutation_paths,
    is_execution_cache_path,
)
from ai_software_engineer.git.policy import is_protected_rule_path
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.recovery.models import FullCommit
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from ai_software_engineer.work_queue.models import QueueClaim


class RejectedCandidateOutputProof(DomainModel):
    """Original successful output and a separately observed lawful candidate.

    ``publication_absent`` seals the trusted collector's fresh absence checks. It
    is not an absence proof derived from the Agent's report or a database query.
    The fixed rejection contract keeps historical decoding independent of future
    changes to the platform's currently supported artifact version.
    """

    kind: Literal["rejected_candidate_output"] = "rejected_candidate_output"
    schema_version: Literal["v1"] = "v1"
    rejection_reason: Literal["unsupported_schema_version"] = "unsupported_schema_version"
    rejected_supported_version: Literal["v0.1"] = "v0.1"
    scope: EngineeringScope
    task: Task
    task_revision: Annotated[StrictInt, Field(ge=1)]
    task_intent_sha256: StageSha256
    step: QueuedRoleStep
    outcome: DeliveryInvocationOutcome
    capture_start: ExecutionCaptureStart
    capture_stop: ExecutionCaptureStop
    candidate_revision: FullCommit
    candidate_parent_revision: FullCommit
    complete_capture: CapturedMutations
    inventory: WorkspaceMutationInventory
    publication_absent: Literal[True]
    proof_sha256: StageSha256

    @property
    def task_id(self) -> str:
        return self.task.id

    @property
    def work_item_id(self) -> str:
        return self.outcome.start.work_item_id

    @property
    def checkpoint_sequence(self) -> int:
        return self.outcome.start.checkpoint_sequence

    @property
    def request(self) -> AgentRequest:
        return self.outcome.start.request

    @property
    def original_claim(self) -> QueueClaim:
        return self.capture_start.claim

    @property
    def scope_sha256(self) -> str:
        return digest(self.scope.to_wire())

    @model_validator(mode="after")
    def require_exact_rejected_candidate(self) -> Self:
        self.outcome.validate_integrity()
        self.capture_start.validate_integrity()
        self.capture_stop.validate_integrity()
        request, result = self.request, self.outcome.result
        start, stop = self.capture_start, self.capture_stop
        invocation, session = self.outcome.start, stop.process_stop.session_proof
        report = result.artifact
        if (
            request.role is not AgentRole.CODER
            or result.status is not AgentRunStatus.SUCCEEDED
            or not isinstance(report, ImplementationReportArtifact)
            or report.schema_version == self.rejected_supported_version
            or report.content.blocked_reason is not None
            or report.producer.agent_id != start.claim.assignment.agent_id
            or report.parent_artifact_ids
            != (
                request.expected_parent_artifact_ids
                if request.expected_parent_artifact_ids is not None
                else request.input_artifact_ids
            )
            or (
                request.expected_supersedes_by_kind is not None
                and (
                    report.kind not in request.expected_supersedes_by_kind
                    or report.supersedes != request.expected_supersedes_by_kind[report.kind]
                )
            )
            or self.outcome.service_pause is not None
            or start.request != request
            or start.claim.work_item.id != invocation.work_item_id
            or start.claim.lease.id != invocation.lease_id
            or start.task_revision != invocation.checkpoint_sequence
            or start.claim.work_item.checkpoint_sequence != invocation.checkpoint_sequence
            or start.claim.claimed_at > start.started_at
            or start.started_at < invocation.started_at
            or stop.task_id != request.task_id
            or stop.run_id != request.run_id
            or stop.capture_start_sha256 != start.start_sha256
            or stop.process_stop.kind != "completed"
            or stop.process_stop.returncode != 0
            or stop.process_stop.stopped_at < start.started_at
            or not stop.output_present
            or stop.cause is not None
            or stop.original_error_code is not None
            or stop.execution_abort_reason is not None
            or session is None
            or session.proof_scope != "owned_session_empty"
            or session.observed_at < start.started_at
            or self.candidate_revision == request.source_revision
            or self.candidate_parent_revision != request.source_revision
            or report.content.commit_sha != self.candidate_revision
            or report.source_revision != self.candidate_revision
        ):
            raise ValueError("候选恢复必须绑定原unsupported-schema成功实现和真实完整停止")
        session.validate_integrity()
        self._validate_binding(self.task, self.step, self.scope, request.permissions, ())
        return self

    def _validate_binding(
        self,
        task: Task,
        step: QueuedRoleStep,
        scope: EngineeringScope,
        permissions: AgentPermissions,
        denied_paths: tuple[str, ...],
    ) -> None:
        request, start = self.request, self.capture_start
        item, original = step.work_item, self.original_claim.work_item
        boundary = step.boundary
        if (
            task != self.task
            or step != self.step
            or scope != self.scope
            or task.repository != scope.repository_root
            or task.id != request.task_id
            or task.status is not TaskStatus.IMPLEMENTING
            or task_intent_sha256(task) != self.task_intent_sha256
            or start.task_intent_sha256 != self.task_intent_sha256
            or (
                task.interruption_continuation_policy is not None
                and start.policy_sha256 != task.interruption_continuation_policy.policy_sha256
            )
            or self.task_revision < start.task_revision
            or task.attempts != request.attempt
            or permissions != request.permissions
            or permissions.can_change_state
            or permissions.can_merge
            or (start.scope.team_id, start.scope.project_id, start.scope.repository_id)
            != (scope.team_id, scope.project_id, scope.repository_id)
            or start.scope.dispatch_sha256 != step.allocation_sha256
            or item.id != original.id
            or item.repository_id != scope.repository_id
            or item.repository_scopes != original.repository_scopes
            or item.model_dump(
                mode="json",
                exclude={"status", "updated_at", "wait_reason", "wait_disposition", "available_at"},
            )
            != original.model_dump(
                mode="json",
                exclude={"status", "updated_at", "wait_reason", "wait_disposition", "available_at"},
            )
            or task.repository not in item.repository_scopes
            or (
                item.task_id,
                item.role,
                item.attempt,
                item.checkpoint_sequence,
                item.dispatch_sequence,
            )
            != (
                original.task_id,
                original.role,
                original.attempt,
                original.checkpoint_sequence,
                original.dispatch_sequence,
            )
            or (boundary.task_id, boundary.role, boundary.attempt, boundary.checkpoint_sequence)
            != (task.id, request.role, request.attempt, self.checkpoint_sequence)
            or boundary.source_revision != request.source_revision
        ):
            raise ValueError("候选恢复证明的Task、权限、scope或原队列身份变化")
        capture = self.complete_capture
        if (
            capture.task_id != task.id
            or capture.worktree_path != start.worktree_path
            or capture.source_revision != self.candidate_revision
            or capture.base_revision != request.source_revision
            or capture.index_diff_sha256 != sha256(capture.patch.encode("utf-8")).hexdigest()
            or capture.to_capture().worktree.branch
            != (task.branch_name or f"ai/{task.id}/attempt-1")
            or not capture.mutations
        ):
            raise ValueError("候选恢复必须保留原基线到候选的完整正文差异")
        report = self.outcome.result.artifact
        assert isinstance(report, ImplementationReportArtifact)
        changes = {item.path: item.change for item in report.content.changed_files}
        if set(changes) != {item.path for item in capture.mutations}:
            raise ValueError("候选报告路径必须精确覆盖完整候选差异")
        _validate_inventory(start.inventory_before)
        _validate_inventory(self.inventory)
        observed = {item.path: item for item in self.inventory.files}
        constraints = task.constraints
        denies = (*denied_paths, *(constraints.denied_paths if constraints else ()))
        task_allowed = constraints.allowed_paths if constraints else ()
        for mutation in capture.mutations:
            _authorize_path(mutation.path, permissions, task_allowed, denies)
            expected_change = (
                ChangeType.ADDED
                if mutation.before is None
                else ChangeType.DELETED
                if mutation.after is None
                else ChangeType.MODIFIED
            )
            if changes[mutation.path] is not expected_change:
                raise ValueError("候选报告变更类型与完整正文差异不一致")
            actual = observed.get(mutation.path)
            if mutation.after is None:
                if actual is not None:
                    raise ValueError("候选已删除文件仍存在于完整现场")
            elif actual is None or (actual.kind, actual.sha256, actual.mode, actual.size) != (
                "file",
                mutation.after.sha256,
                mutation.after.mode,
                mutation.after.size,
            ):
                raise ValueError("候选完整正文与观察到的现场内容不一致")
        captured = {item.path for item in capture.mutations}
        validate_rejected_candidate_inventory(
            WorkspaceMutationInventory(
                tuple(item for item in start.inventory_before.files if item.path not in captured)
            ),
            WorkspaceMutationInventory(
                tuple(item for item in self.inventory.files if item.path not in captured)
            ),
        )

    def validate_for(
        self,
        task: Task,
        step: QueuedRoleStep,
        scope: EngineeringScope,
        permissions: AgentPermissions,
        denied_paths: tuple[str, ...] = (),
    ) -> None:
        self.validate_integrity()
        self._validate_binding(task, step, scope, permissions, denied_paths)

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"proof_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.proof_sha256 != self.recompute_sha256():
            raise ValueError("候选恢复证明摘要不一致")

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "proof_sha256": "0" * 64})
        return value.model_copy(update={"proof_sha256": value.recompute_sha256()})


def validate_rejected_candidate_inventory(
    before: WorkspaceMutationInventory, after: WorkspaceMutationInventory
) -> None:
    """A retained candidate report may create only regular explicit execution caches."""
    _validate_inventory(before)
    _validate_inventory(after)
    old, new = {item.path: item for item in before.files}, {item.path: item for item in after.files}
    for path in changed_mutation_paths(before, after):
        if not is_execution_cache_path(path) or any(
            item is not None and (item.kind != "file" or item.mode not in {0o644, 0o755})
            for item in (old.get(path), new.get(path))
        ):
            raise ValueError("完整现场包含未入候选的非缓存、忽略或特殊文件变更")


def _safe_path(path: str) -> None:
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or any(ord(character) < 32 for character in path)
        or PurePosixPath(path).as_posix() != path
    ):
        raise ValueError("候选恢复路径不是规范仓库相对路径")


def _authorize_path(
    path: str,
    permissions: AgentPermissions,
    task_allowed: tuple[str, ...],
    denied_paths: tuple[str, ...],
) -> None:
    _safe_path(path)
    parts = PurePosixPath(path).parts
    name = parts[-1].casefold()
    if (
        is_protected_rule_path(path)
        or any(part.casefold() in {".git", ".ase", ".agents", ".codex"} for part in parts)
        or name in {"agents.md", ".editorconfig"}
        or name.startswith(("contributing", "readme"))
        or any(fnmatchcase(path, pattern) for pattern in denied_paths)
        or not any(fnmatchcase(path, pattern) for pattern in permissions.write_paths)
        or not any(fnmatchcase(path, pattern) for pattern in permissions.read_paths)
        or (task_allowed and not any(fnmatchcase(path, pattern) for pattern in task_allowed))
    ):
        raise ValueError("候选恢复差异超出原Coder权限或修改原生只读规则")


def _validate_inventory(inventory: WorkspaceMutationInventory) -> None:
    paths = tuple(item.path for item in inventory.files)
    if paths != tuple(sorted(set(paths))) or len(paths) > MAX_INVENTORY_FILES:
        raise ValueError("候选恢复完整现场路径必须排序、唯一且有界")
    total = 0
    for item in inventory.files:
        _safe_path(item.path)
        if (
            len(item.sha256) != 64
            or any(character not in "0123456789abcdef" for character in item.sha256)
            or not 0 <= item.mode <= 0o7777
            or not 0 <= item.size <= MAX_INVENTORY_FILE_BYTES
            or item.kind not in {"file", "symlink", "git_directory"}
            or (item.kind == "git_directory" and (item.path != ".git" or item.size != 0))
        ):
            raise ValueError("候选恢复完整现场指纹无效")
        total += item.size
    if total > MAX_INVENTORY_BYTES:
        raise ValueError("候选恢复完整现场超过字节上限")
