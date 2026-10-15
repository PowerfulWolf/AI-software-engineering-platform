"""Known stopped native Coder facts; the missing outcome remains unknown."""

from typing import Literal, Self

from pydantic import model_validator

from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.git.mutation import WorkspaceMutationInventory
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
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart


class StoppedCoderExecutionProof(DomainModel):
    """Exact real start/stop and historical claim, never an invented result or cause."""

    kind: Literal["stopped_coder_execution_without_outcome"] = (
        "stopped_coder_execution_without_outcome"
    )
    schema_version: Literal["v1"] = "v1"
    invocation_start: DeliveryInvocationStart
    capture_start: ExecutionCaptureStart
    capture_stop: ExecutionCaptureStop
    proof_sha256: StageSha256

    @model_validator(mode="after")
    def require_exact_stopped_execution(self) -> Self:
        invocation, start, stop = self.invocation_start, self.capture_start, self.capture_stop
        invocation.validate_integrity()
        start.validate_integrity()
        stop.validate_integrity()
        request = invocation.request
        session = stop.process_stop.session_proof
        if (
            request.role is not AgentRole.CODER
            or start.request != request
            or start.claim.work_item.id != invocation.work_item_id
            or start.claim.lease.id != invocation.lease_id
            or start.task_revision != invocation.checkpoint_sequence
            or stop.capture_start_sha256 != start.start_sha256
            or stop.task_id != request.task_id
            or stop.run_id != request.run_id
            or stop.process_stop.kind != "failed"
            or stop.process_stop.returncode in {None, 0}
            or stop.process_stop.stopped_at < start.started_at
            or stop.output_present
            or stop.cause is not None
            or session is None
            or session.proof_scope != "owned_session_empty"
        ):
            raise ValueError("已停止但结果未知的证明必须绑定精确原调用和完整owned-session停止")
        session.validate_integrity()
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"proof_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.proof_sha256 != self.recompute_sha256():
            raise ValueError("已停止但结果未知的执行证明摘要不一致")

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "proof_sha256": "0" * 64})
        return value.model_copy(update={"proof_sha256": value.recompute_sha256()})


def validate_stopped_coder_capture(
    proof: StoppedCoderExecutionProof,
    capture: CapturedMutations,
    inventory: WorkspaceMutationInventory,
    permissions: AgentPermissions,
) -> None:
    proof.validate_integrity()
    validate_stopped_execution_capture(
        proof.invocation_start.request, proof.capture_start, capture, inventory, permissions
    )


def require_stopped_coder_workspace(
    proof: StoppedCoderExecutionProof,
    capture: CapturedMutations,
    inventory: WorkspaceMutationInventory,
    permissions: AgentPermissions,
    denied_paths: tuple[str, ...],
) -> None:
    validate_stopped_coder_capture(proof, capture, inventory, permissions)
    require_stopped_execution_workspace(
        proof.invocation_start.request, proof.capture_start, inventory, denied_paths
    )
