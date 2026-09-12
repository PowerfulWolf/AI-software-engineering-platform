"""Shared traversal of successor allocations back to the approved Planner dispatch."""

from __future__ import annotations

from collections.abc import Mapping

from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryStage,
    ProjectDeliveryCheckpoint,
    terminal_candidate_cursor_matches,
)
from ai_software_engineer.project_manager.dispatch import (
    ContinuationDispatchRecord,
    DeliveryAllocation,
    DispatchCommitRecord,
    RecoveryDispatchRecord,
)
from ai_software_engineer.recovery.models import RecoveryRejected


def continuation_source_checkpoints(
    history: tuple[ProjectDeliveryCheckpoint, ...],
    allocation: ContinuationDispatchRecord,
) -> tuple[ProjectDeliveryCheckpoint, ...]:
    """Locate source cursors; candidate authority remains in Task events/artifacts."""
    allocation.validate_integrity()
    return tuple(
        checkpoint
        for checkpoint in history
        if checkpoint.project_id == allocation.project_id
        and checkpoint.project_root == allocation.task.repository
        and checkpoint.delivery_id == allocation.source_delivery_id
        and checkpoint.dispatch_commit_id == allocation.source_dispatch_id
        and checkpoint.task_id == allocation.source_task_id
        and checkpoint.stage in {DeliveryStage.BLOCKED, DeliveryStage.FAILED}
        and terminal_candidate_cursor_matches(checkpoint, allocation.source_revision)
    )


def resolve_planner_dispatch(
    current: DeliveryAllocation,
    allocations: Mapping[str, DeliveryAllocation],
    history: tuple[ProjectDeliveryCheckpoint, ...],
) -> DispatchCommitRecord:
    """Follow sealed recovery/remediation links to the original Planner allocation."""
    seen: set[str] = set()
    allocation = current
    while not isinstance(allocation, DispatchCommitRecord):
        if allocation.id in seen:
            raise RecoveryRejected("candidate dispatch ancestry contains a cycle")
        seen.add(allocation.id)
        source_id: str | None = None
        if isinstance(allocation, ContinuationDispatchRecord):
            matches = continuation_source_checkpoints(history, allocation)
            if not matches:
                raise RecoveryRejected("continuation source is absent from Delivery history")
            source_id = allocation.source_dispatch_id
        elif isinstance(allocation, RecoveryDispatchRecord):
            source_checkpoint = allocation.task.metadata.get("recovery_source_checkpoint_sha256")
            source_task = allocation.task.metadata.get("recovery_of_task_id")
            source_delivery = allocation.task.metadata.get("recovery_of_delivery_id")
            matches = tuple(
                checkpoint
                for checkpoint in history
                if checkpoint.checkpoint_sha256 == source_checkpoint
                and checkpoint.delivery_id == source_delivery
                and checkpoint.task_id == source_task
                and checkpoint.candidate_revision is None
                and checkpoint.stage in {DeliveryStage.BLOCKED, DeliveryStage.FAILED}
            )
            if len(matches) != 1:
                raise RecoveryRejected("recovery source is absent from Delivery history")
            source_id = matches[0].dispatch_commit_id
        if source_id is None or source_id not in allocations:
            raise RecoveryRejected("candidate successor ancestry is incomplete")
        parent = allocations[source_id]
        if (
            parent.project_id != allocation.project_id
            or parent.project_request_id != allocation.project_request_id
            or parent.execution_plan_id != allocation.execution_plan_id
            or parent.execution_plan_sha256 != allocation.execution_plan_sha256
        ):
            raise RecoveryRejected("candidate successor changed its approved plan")
        allocation = parent
    return allocation


def allocation_preparation_sha256(
    allocation: DeliveryAllocation,
    original_preparation_sha256: str,
) -> str:
    """Resolve the preparation bound to the current Task without weakening ancestry."""
    if isinstance(allocation, ContinuationDispatchRecord):
        return allocation.target_preparation_sha256
    if isinstance(allocation, RecoveryDispatchRecord):
        value = allocation.task.metadata.get("recovery_target_preparation_sha256")
        if not isinstance(value, str):
            raise RecoveryRejected("recovery allocation has no target preparation")
        return value
    return original_preparation_sha256


__all__ = [
    "allocation_preparation_sha256",
    "continuation_source_checkpoints",
    "resolve_planner_dispatch",
]
