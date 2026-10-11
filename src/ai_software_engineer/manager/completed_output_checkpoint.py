"""Truthful stopped native completion facts; unknown output grants no approval."""

from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator

from ai_software_engineer.agents.models import AgentErrorCode, AgentRequest, AgentRunStatus
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.git.mutation import (
    WorkspaceMutationInventory,
    changed_mutation_paths,
    is_execution_cache_path,
)
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome


class CompletedCoderOutputReason(StrEnum):
    """Derived classification of the sealed failure, never independent authority."""

    UNAVAILABLE = "completed_output_unavailable"
    REJECTED = "completed_output_rejected"


class CompletedCoderOutputUnavailableProof(DomainModel):
    """Original FAILED result plus real stop, never a workspace-ready declaration."""

    kind: Literal["completed_coder_output_unavailable"] = "completed_coder_output_unavailable"
    schema_version: Literal["v1"] = "v1"
    output_content_status: Literal["unknown"] = "unknown"
    outcome: DeliveryInvocationOutcome
    capture_start: ExecutionCaptureStart
    capture_stop: ExecutionCaptureStop
    proof_sha256: StageSha256

    @property
    def reason(self) -> CompletedCoderOutputReason:
        error = self.outcome.result.error
        if error is None:
            raise ValueError("未接纳产出缺少原封存失败原因")
        if error.code is AgentErrorCode.WORK_INTERRUPTED:
            return CompletedCoderOutputReason.UNAVAILABLE
        if error.code is AgentErrorCode.INVALID_OUTPUT:
            return CompletedCoderOutputReason.REJECTED
        raise ValueError("原封存失败不是可重新产出的已完成 Coder 调用")

    @model_validator(mode="after")
    def require_exact_native_completion(self) -> Self:
        outcome, start, stop = self.outcome, self.capture_start, self.capture_stop
        outcome.validate_integrity()
        start.validate_integrity()
        stop.validate_integrity()
        request, error = outcome.start.request, outcome.result.error
        if (
            request.role is not AgentRole.CODER
            or outcome.result.status is not AgentRunStatus.FAILED
            or outcome.result.artifact is not None
            or error is None
            or error.code not in {AgentErrorCode.WORK_INTERRUPTED, AgentErrorCode.INVALID_OUTPUT}
            or error.transient
            or start.request != request
            or start.claim.work_item.id != outcome.start.work_item_id
            or start.claim.lease.id != outcome.start.lease_id
            or start.task_revision != outcome.start.checkpoint_sequence
            or stop.capture_start_sha256 != start.start_sha256
            or stop.task_id != request.task_id
            or stop.run_id != request.run_id
            or stop.process_stop.kind != "completed"
            or stop.process_stop.returncode != 0
            or stop.process_stop.stopped_at < start.started_at
            or not stop.output_present
            or stop.cause is not None
            or stop.original_error_code is not None
        ):
            raise ValueError("完成但结果未接纳的证明未绑定精确原执行和真实停止")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"proof_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.proof_sha256 != self.recompute_sha256():
            raise ValueError("完成但结果未接纳的证明摘要不一致")

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "proof_sha256": "0" * 64})
        return value.model_copy(update={"proof_sha256": value.recompute_sha256()})


def validate_completed_output_capture(
    proof: CompletedCoderOutputUnavailableProof,
    dirty_capture: CapturedMutations,
    inventory: WorkspaceMutationInventory,
    permissions: AgentPermissions,
) -> None:
    """Pure wire validation; a complete plan must cover its full observed inventory."""
    proof.validate_integrity()
    request, start = proof.outcome.start.request, proof.capture_start
    validate_stopped_execution_capture(request, start, dirty_capture, inventory, permissions)


def validate_stopped_execution_capture(
    request: AgentRequest,
    start: ExecutionCaptureStart,
    dirty_capture: CapturedMutations,
    inventory: WorkspaceMutationInventory,
    permissions: AgentPermissions,
) -> None:
    """Cover the complete lawful draft after a separately verified stopped execution."""
    if start.request != request:
        raise ValueError("完整草稿没有绑定精确原执行")
    if (
        permissions != request.permissions
        or dirty_capture.task_id != request.task_id
        or dirty_capture.source_revision != request.source_revision
        or dirty_capture.worktree_path != start.worktree_path
    ):
        raise ValueError("完整草稿未绑定原执行源版本、工作区和冻结权限")
    mutations = changed_mutation_paths(start.inventory_before, inventory)
    observed = {item.path: item for item in inventory.files}
    if len(observed) != len(inventory.files):
        raise ValueError("完成但结果未接纳的完整现场含重复路径")
    for mutation in dirty_capture.mutations:
        actual = observed.get(mutation.path)
        if mutation.after is None:
            if actual is not None:
                raise ValueError("已删除草稿仍出现在完整现场中")
        elif actual is None or (actual.kind, actual.sha256, actual.mode, actual.size) != (
            "file",
            mutation.after.sha256,
            mutation.after.mode,
            mutation.after.size,
        ):
            raise ValueError("完整草稿正文与现场指纹不一致")
    noncache = {path for path in mutations if not is_execution_cache_path(path)}
    if not noncache.issubset(
        set(dirty_capture.to_capture().changed_paths) | set(request.continuation_changed_paths)
    ):
        raise ValueError("完成但结果未接纳的完整草稿未覆盖全部非缓存变更")


def require_completed_output_workspace(
    proof: CompletedCoderOutputUnavailableProof,
    dirty_capture: CapturedMutations,
    inventory: WorkspaceMutationInventory,
    permissions: AgentPermissions,
    denied_paths: tuple[str, ...],
) -> None:
    """Authorize all observed writes, including ignored noncache source mutations."""
    validate_completed_output_capture(proof, dirty_capture, inventory, permissions)
    request, start = proof.outcome.start.request, proof.capture_start
    require_stopped_execution_workspace(request, start, inventory, denied_paths)


def require_stopped_execution_workspace(
    request: AgentRequest,
    start: ExecutionCaptureStart,
    inventory: WorkspaceMutationInventory,
    denied_paths: tuple[str, ...],
) -> None:
    """Authorize every original invocation mutation after complete body validation."""
    NativeCoderContinuation._authorize_mutations(
        request,
        Path(start.worktree_path),
        changed_mutation_paths(start.inventory_before, inventory),
        denied_paths,
    )
