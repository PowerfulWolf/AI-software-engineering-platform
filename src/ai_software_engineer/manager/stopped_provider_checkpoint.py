"""Exact stopped provider failure; prerequisite repair remains a human decision."""

from typing import Literal, Self

from pydantic import model_validator

from ai_software_engineer.agents.models import AgentErrorCode, AgentRunStatus
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
from ai_software_engineer.manager.completed_output_checkpoint import (
    require_stopped_execution_workspace,
    validate_stopped_execution_capture,
)
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome


class StoppedProviderFailureProof(DomainModel):
    """Original permanent failure and exact native stop, never a health assertion."""

    kind: Literal["stopped_provider_failure"] = "stopped_provider_failure"
    schema_version: Literal["v1"] = "v1"
    outcome: DeliveryInvocationOutcome
    capture_start: ExecutionCaptureStart
    capture_stop: ExecutionCaptureStop
    proof_sha256: StageSha256

    @model_validator(mode="after")
    def require_exact_stopped_failure(self) -> Self:
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
            or error.code is not AgentErrorCode.AUTHENTICATION_ERROR
            or error.transient
            or start.request != request
            or start.claim.work_item.id != outcome.start.work_item_id
            or start.claim.lease.id != outcome.start.lease_id
            or start.task_revision != outcome.start.checkpoint_sequence
            or stop.capture_start_sha256 != start.start_sha256
            or stop.task_id != request.task_id
            or stop.run_id != request.run_id
            or stop.process_stop.kind != "failed"
            or stop.process_stop.returncode == 0
            or stop.output_present
            or stop.process_stop.stopped_at < start.started_at
            or stop.cause is not None
            or stop.original_error_code not in {None, AgentErrorCode.AUTHENTICATION_ERROR}
        ):
            raise ValueError("提供方前提失败证明未绑定精确永久失败和真实停止")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"proof_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.proof_sha256 != self.recompute_sha256():
            raise ValueError("提供方前提失败证明摘要不一致")

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "proof_sha256": "0" * 64})
        return value.model_copy(update={"proof_sha256": value.recompute_sha256()})


def validate_stopped_provider_capture(
    proof: StoppedProviderFailureProof,
    dirty_capture: CapturedMutations,
    inventory: WorkspaceMutationInventory,
    permissions: AgentPermissions,
) -> None:
    proof.validate_integrity()
    validate_stopped_execution_capture(
        proof.outcome.start.request, proof.capture_start, dirty_capture, inventory, permissions
    )
    if any(
        not is_execution_cache_path(path)
        for path in changed_mutation_paths(proof.capture_start.inventory_before, inventory)
    ):
        raise ValueError("永久提供方前提失败不能接纳原调用之后新增的源码变更, 原现场保留")


def require_stopped_provider_workspace(
    proof: StoppedProviderFailureProof,
    dirty_capture: CapturedMutations,
    inventory: WorkspaceMutationInventory,
    permissions: AgentPermissions,
    denied_paths: tuple[str, ...],
) -> None:
    validate_stopped_provider_capture(proof, dirty_capture, inventory, permissions)
    require_stopped_execution_workspace(
        proof.outcome.start.request, proof.capture_start, inventory, denied_paths
    )
