"""Known stopped native Coder facts; the missing outcome remains unknown."""

from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator

from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore
from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git.mutation import WorkspaceMutationInventory
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.completed_output_checkpoint import (
    require_stopped_execution_workspace,
    validate_stopped_execution_capture,
)
from ai_software_engineer.orchestration.capture_reconciliation import validate_capture_stop
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRecordMissing,
    ContinuationScope,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.store import TaskRepository
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueuedWorkItem


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


def read_stopped_coder_execution(
    task: Task,
    item: QueuedWorkItem,
    step: QueuedRoleStep,
    *,
    expected_scope: ContinuationScope,
    state: Path,
    route_root: Path | None,
    repository: TaskRepository,
    queue: MySqlRoleQueue,
    artifacts: ArtifactStore,
    permissions: AgentPermissions,
    task_lock: ExecutionGuard,
) -> StoppedCoderExecutionProof | None:
    """Read the same exact stopped facts under either trusted Task-lock scope.

    This reader never claims a lease, writes a receipt or requires an idle SQL
    fence. Baseline mutation still separately holds its original idle fence.
    """
    records = KnowledgeRecordStore(state / "invocations", read_only=True)
    start = records.find("invocation-starts", item.id, DeliveryInvocationStart)
    if start is None:
        return None
    ledger = FileContinuationStore(state / "continuations" / task.id, task_id=task.id)
    try:
        capture_start = ledger.capture_start(start.request.run_id)
        capture_stop = ledger.capture_stop(start.request.run_id)
    except ContinuationRecordMissing:
        return None
    proof = StoppedCoderExecutionProof.create(
        invocation_start=start, capture_start=capture_start, capture_stop=capture_stop
    )
    if capture_start.scope != expected_scope:
        raise ValueError("未知结果停止证明不属于当前需求和分配")

    def validate_inputs(request: AgentRequest) -> None:
        if route_root is not None and route_root.is_dir():
            routes = FileModelRouteAttemptStore(route_root, read_only=True).list_for_run(
                request.run_id
            )
            if routes:
                raise ValueError("原执行已有模型路由结果, 不能用未知结果恢复覆盖")
        if (
            request != start.request
            or repository.get(task.id) != task
            or request.permissions != permissions
            or request.source_revision != step.boundary.source_revision
            or (item.task_id, item.role, item.attempt, item.checkpoint_sequence)
            != (task.id, request.role, request.attempt, start.checkpoint_sequence)
            or (
                step.boundary.task_id,
                step.boundary.role,
                step.boundary.attempt,
                step.boundary.checkpoint_sequence,
            )
            != (task.id, request.role, request.attempt, start.checkpoint_sequence)
            or step.work_item.id != item.id
            or queue.get(item.id) != item
            or queue.step(item.id) != step
            or records.get("invocation-starts", item.id, DeliveryInvocationStart) != start
            or records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome) is not None
            or ledger.capture_start(request.run_id) != capture_start
            or ledger.capture_stop(request.run_id) != capture_stop
            or any(
                receipt.request.run_id == request.run_id
                for receipt in ledger.receipts_for_task(task.id)
            )
        ):
            raise ValueError("未知结果停止恢复已有原结果、收据或精确队列事实变化")
        if any(
            artifact.producer.run_id == request.run_id
            for artifact in artifacts.list_for_task(task.id)
        ):
            raise ValueError("原执行已有封存产物, 不能用未知结果恢复覆盖")
        retired = queue.rejected_output_artifact_ids(task.id)
        if any(
            accepted.work_item_id == item.id
            or (
                accepted.checkpoint_sequence >= start.checkpoint_sequence
                and accepted.receipt.artifact_id not in retired
            )
            for accepted in queue.accepted(task.id)
        ) or any(
            event.artifact_ids
            for event in repository.list_events(task.id)[capture_start.task_revision :]
        ):
            raise ValueError("原执行之后已有产物发布或交付采纳, 不能覆盖原结果")

    validate_capture_stop(
        start=capture_start,
        stop=capture_stop,
        task=task,
        task_revision=repository.current_revision(task.id),
        historical_claim=queue.original_claim(start.lease_id),
        task_lock=task_lock,
        validate_inputs=validate_inputs,
    )
    return proof


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
