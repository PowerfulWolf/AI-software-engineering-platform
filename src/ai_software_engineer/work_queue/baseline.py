"""Append-only source overlays and fenced accounting for the same delivery Task."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing, contextmanager
from typing import TYPE_CHECKING, Literal, Self

from pydantic import model_validator
from pymysql.cursors import DictCursor

from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.manager.baseline_models import ExecutionBaselinePlan
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store.mysql_repository import _decode_task, _encode, open_mysql_connection
from ai_software_engineer.work_queue.execution_store import (
    QueuedRoleStep,
    _decode,
    _put,
    record_digest,
)
from ai_software_engineer.work_queue.models import QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueConflict, QueueCorruption, QueueLeaseLost

if TYPE_CHECKING:
    from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue

TABLE = "work_queue_execution_baselines"


class BaselineQueueConsumption(DomainModel):
    kind: Literal["baseline_queue_consumption"] = "baseline_queue_consumption"
    task_id: NonEmptyStr
    work_item_id: NonEmptyStr
    next_work_item_id: NonEmptyStr
    prior_step_sha256: NonEmptyStr
    plan: ExecutionBaselinePlan
    binding: ExecutionBaselineBinding

    @model_validator(mode="after")
    def exact_completed_operation(self) -> Self:
        self.plan.validate_integrity()
        self.binding.require_task(self.plan.facts.task)
        if (
            self.task_id != self.binding.task_id
            or self.work_item_id != self.plan.facts.work_item_id
            or self.binding.plan_sha256 != self.plan.plan_sha256
            or self.binding.facts_sha256 != self.plan.facts.facts_sha256
            or self.binding.execution_source_revision != self.plan.prepared_source_revision
            or self.binding.execution_base_ref != self.plan.target_base_ref
            or self.binding.prior_source_revision != self.plan.dirty_capture.source_revision
        ):
            raise ValueError("baseline queue record changed the sealed operation")
        return self


def consumptions(queue: MySqlRoleQueue, task_id: str) -> tuple[BaselineQueueConsumption, ...]:
    with (
        closing(open_mysql_connection(queue._dsn)) as connection,
        connection.cursor(DictCursor) as cursor,
    ):
        cursor.execute(
            f"SELECT id,task_id,payload_json,sha256 FROM {TABLE} WHERE task_id=%s",
            (task_id,),
        )
        records = tuple(_decode(row, BaselineQueueConsumption) for row in cursor.fetchall())
    return tuple(sorted(records, key=lambda record: record.binding.sequence))


def effective_step(
    queue: MySqlRoleQueue,
    original: QueuedRoleStep,
    *,
    baseline_sha256: str | None = None,
    latest: bool = True,
) -> QueuedRoleStep:
    """Resolve source at an exact historical invocation, or the current uninvoked input."""
    selected = original
    found = baseline_sha256 is None
    for record in consumptions(queue, original.work_item.task_id):
        if (
            record.work_item_id != original.work_item.id
            or record.next_work_item_id != record.work_item_id
        ):
            continue
        if record_digest(selected) != record.prior_step_sha256:
            raise QueueCorruption("baseline overlay does not extend its immutable predecessor")
        boundary = selected.boundary
        selected = selected.model_copy(
            update={
                "boundary": RoleRunBoundary(
                    boundary.task_id,
                    boundary.role,
                    boundary.attempt,
                    boundary.checkpoint_sequence,
                    record.binding.execution_source_revision,
                ),
            }
        )
        if record.binding.binding_sha256 == baseline_sha256:
            found = True
            if not latest:
                return selected
    if not latest:
        if baseline_sha256 is None:
            return original
        # A newly reserved item already binds the source in its original step.
        exact = next(
            (
                r
                for r in consumptions(queue, original.work_item.task_id)
                if r.binding.binding_sha256 == baseline_sha256
                and r.next_work_item_id == original.work_item.id
            ),
            None,
        )
        if (
            exact is not None
            and original.boundary.source_revision == exact.binding.execution_source_revision
        ):
            return original
        if not found:
            raise QueueCorruption("historical invocation has no exact baseline source record")
    return selected


def consume_baseline(
    queue: MySqlRoleQueue,
    plan: ExecutionBaselinePlan,
    binding: ExecutionBaselineBinding,
    *,
    cursor: DictCursor | None = None,
) -> QueuedWorkItem:
    """Publish Git completion into scheduling once, without changing approved intent/events."""
    plan.validate_integrity()
    binding.require_task(plan.facts.task)
    now = queue._clock()
    with _consumption_cursor(queue, cursor) as cursor:
        queue._lock_authority(cursor)
        cursor.execute(
            f"SELECT id,task_id,payload_json,sha256 FROM {TABLE} WHERE id=%s FOR UPDATE",
            (binding.binding_sha256,),
        )
        prior = cursor.fetchone()
        if prior is not None:
            sealed = _decode(prior, BaselineQueueConsumption)
            if sealed.plan != plan or sealed.binding != binding:
                raise QueueConflict("baseline already consumed another exact operation")
            return queue._get_locked(cursor, sealed.next_work_item_id, lock=True)
        current = queue._get_locked(cursor, plan.facts.work_item_id, lock=True)
        step = queue.step(current.id)
        cursor.execute(
            "SELECT payload_json,revision FROM tasks WHERE id=%s FOR UPDATE", (binding.task_id,)
        )
        row = cursor.fetchone()
        if row is None:
            raise QueueCorruption("baseline Task is missing")
        task = _decode_task(binding.task_id, str(row["payload_json"]))
        binding.require_task(task)
        reservation = plan.facts.continuation
        if (
            reservation is None
            or task != plan.facts.task
            or row["revision"] != plan.facts.task_revision
            or task.status is not TaskStatus.IMPLEMENTING
            or current.role is not AgentRole.CODER
            or current.status
            not in {
                WorkItemStatus.READY,
                WorkItemStatus.WAITING_HUMAN,
                WorkItemStatus.WAITING_DEPENDENCY,
                WorkItemStatus.RETRY_SCHEDULED,
            }
            or current.checkpoint_sequence != plan.facts.checkpoint_sequence
            or current.attempt != reservation.current_attempt
            or step.boundary.source_revision != binding.prior_source_revision
        ):
            raise QueueConflict("baseline queue/task/current reservation drifted")
        cursor.execute(
            "SELECT lease_id FROM work_queue_claims WHERE task_id=%s AND state='ACTIVE' FOR UPDATE",
            (task.id,),
        )
        if cursor.fetchone() is not None:
            raise QueueLeaseLost("baseline queue consumption requires all role owners released")
        if reservation.retry_cause == "uninvoked":
            next_item = current.model_copy(
                update={
                    "status": WorkItemStatus.READY,
                    "updated_at": now,
                    "wait_reason": None,
                    "wait_disposition": None,
                    "available_at": None,
                    "dispatch_sequence": current.dispatch_sequence + 1,
                }
            )
            settled = next_item
        else:
            updated = task
            if not reservation.reservation_already_applied:
                if reservation.retry_cause == "provider_transient":
                    if reservation.retry_failure is None:
                        raise QueueConflict("baseline transient reservation lacks original failure")
                    updated = task.with_retry_failure(reservation.retry_failure)
                else:
                    if task.work_budget_exhausted or task.attempts >= task.max_attempts:
                        raise QueueConflict("baseline has no remaining frozen work allowance")
                    updated = type(task).model_validate(
                        {**task.to_wire(), "attempts": task.attempts + 1}
                    )
            if updated.attempts != reservation.next_execution_attempt:
                raise QueueConflict("baseline cannot change exact reserved execution accounting")
            cursor.execute(
                "UPDATE tasks SET payload_json=%s WHERE id=%s",
                (_encode(updated.to_wire()), task.id),
            )
            next_item = QueuedWorkItem.model_validate(
                {
                    **current.to_wire(),
                    "id": "work_" + binding.binding_sha256,
                    "attempt": updated.attempts,
                    "status": WorkItemStatus.READY,
                    "wait_reason": None,
                    "wait_disposition": None,
                    "available_at": None,
                    "parent_work_item_id": current.id,
                    "dispatch_sequence": 0,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            next_step = QueuedRoleStep(
                work_item=next_item,
                boundary=RoleRunBoundary(
                    task.id,
                    AgentRole.CODER,
                    updated.attempts,
                    current.checkpoint_sequence,
                    binding.execution_source_revision,
                ),
                allocation_sha256=step.allocation_sha256,
            )
            _put(cursor, "work_queue_steps", next_item.id, task.id, next_step)
            next_item = queue._enqueue_locked(cursor, next_item)
            settled = current.model_copy(
                update={
                    "status": WorkItemStatus.CLOSED,
                    "updated_at": now,
                    "wait_reason": None,
                    "wait_disposition": None,
                }
            )
        record = BaselineQueueConsumption(
            task_id=task.id,
            work_item_id=current.id,
            next_work_item_id=next_item.id,
            prior_step_sha256=record_digest(step),
            plan=plan,
            binding=binding,
        )
        _put(cursor, TABLE, binding.binding_sha256, task.id, record)
        queue._update_item(cursor, settled)
        queue._append_event(
            cursor,
            settled,
            from_status=current.status,
            event_type="EXECUTION_BASELINE_REBOUND",
            lease_id=None,
            occurred_at=now,
            detail={
                "binding_sha256": binding.binding_sha256,
                "next_work_item_id": next_item.id,
                "plan_sha256": plan.plan_sha256,
                "budget_refund": False,
                "reservation": reservation.to_wire(),
            },
        )
        return next_item


@contextmanager
def _consumption_cursor(queue: MySqlRoleQueue, existing: DictCursor | None) -> Iterator[DictCursor]:
    if existing is not None:
        yield existing
        return
    with (
        closing(open_mysql_connection(queue._dsn)) as connection,
        queue._transaction(connection),
        connection.cursor(DictCursor) as cursor,
    ):
        yield cursor
