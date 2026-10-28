"""Shared validation for a live delivery successor that has not reached the native journal yet.

The native delivery checkpoint is published after a role run returns.  A recovery or
continuation dispatch can therefore own the live Task while the checkpoint still points at
its predecessor.  Every caller must use the same lineage checks when projecting or acting on
that successor; timestamps and titles are not sufficient evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ai_software_engineer.manager.delivery_checkpoint import ProjectDeliveryCheckpoint
from ai_software_engineer.manager.dispatch import (
    ContinuationDispatchRecord,
    DeliveryAllocation,
    RecoveryDispatchRecord,
)

_TERMINAL_TASK_STATUSES = frozenset({"DONE", "BLOCKED", "FAILED"})


def active_successor_dispatch(
    checkpoint: ProjectDeliveryCheckpoint,
    history: tuple[ProjectDeliveryCheckpoint, ...],
    dispatches: Iterable[DeliveryAllocation],
    *,
    task_status: Callable[[str], str | None],
) -> DeliveryAllocation | None:
    """Return the unique nonterminal successor bound to ``checkpoint``.

    ``history`` is the complete validated native prefix for this delivery.  A successor is
    accepted only when its typed dispatch names that delivery and one task in the prefix.  A
    recovery additionally binds the exact source checkpoint digest.  The caller supplies a
    read-only status lookup from the same SQL snapshot used to decode the dispatches.
    """

    if not history:
        return None
    if history[-1] != checkpoint:
        raise ValueError("native checkpoint is not the current history head")
    for record in history:
        if (
            record.delivery_id != checkpoint.delivery_id
            or record.repository_id != checkpoint.repository_id
            or record.repository_root != checkpoint.repository_root
        ):
            raise ValueError("native checkpoint history binding mismatch")
    known_tasks = {record.task_id for record in history if record.task_id is not None}
    candidates: list[DeliveryAllocation] = []
    for dispatch in dispatches:
        if dispatch.repository_id != checkpoint.repository_id:
            continue
        if dispatch.task_id == checkpoint.task_id or dispatch.committed_at <= (
            checkpoint.checkpointed_at
        ):
            continue
        source_task_id: str | None = None
        source_delivery_id: str | None = None
        if isinstance(dispatch, RecoveryDispatchRecord):
            source_task_id = str(dispatch.task.metadata.get("recovery_of_task_id", ""))
            source_delivery_id = str(dispatch.task.metadata.get("recovery_of_delivery_id", ""))
            if source_delivery_id == checkpoint.delivery_id and (
                source_task_id != checkpoint.task_id
                or dispatch.task.metadata.get("recovery_source_checkpoint_sha256")
                != checkpoint.checkpoint_sha256
            ):
                raise ValueError("active recovery source checkpoint mismatch")
        elif isinstance(dispatch, ContinuationDispatchRecord):
            source_task_id = str(dispatch.source_task_id)
            source_delivery_id = str(dispatch.source_delivery_id)
        if source_task_id not in known_tasks or source_delivery_id != checkpoint.delivery_id:
            continue
        status = task_status(dispatch.task_id)
        if status is None or status in _TERMINAL_TASK_STATUSES:
            continue
        candidates.append(dispatch)
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("ambiguous active successor dispatch")
    return candidates[0]
