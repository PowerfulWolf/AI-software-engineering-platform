"""Read a released current recovery wait without dispatch, DDL or state mutation."""

from contextlib import closing
from dataclasses import dataclass

from pymysql.cursors import DictCursor

from ai_software_engineer.domain import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import DeliveryDisposition, DeliveryNextAction
from ai_software_engineer.domain.task import task_matches_dispatch
from ai_software_engineer.manager.delivery import DeliveryFailureSnapshot
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected
from ai_software_engineer.store.mysql_repository import (
    _decode_event,
    _decode_task,
    _non_negative_int,
    _text,
    open_mysql_connection,
)
from ai_software_engineer.work_queue.execution_store import (
    QueuedRoleStep,
    RoleQueueAdmission,
    _decode,
)
from ai_software_engineer.work_queue.models import QueuedWorkItem


@dataclass(frozen=True)
class PendingRecoveryWait:
    snapshot: DeliveryFailureSnapshot
    disposition: DeliveryDisposition


def read_pending_recovery_wait(
    *,
    dsn: str,
    plan: RecoveryPlan,
    dispatch: RecoveryDispatchRecord,
) -> PendingRecoveryWait | None:
    """Only a unique exact typed wait with released ownership can be adopted."""
    with closing(open_mysql_connection(dsn)) as connection:
        try:
            with connection.cursor(DictCursor) as cursor:
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                cursor.execute("SELECT * FROM tasks WHERE id=%s", (plan.new_task_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
                task = _decode_task(plan.new_task_id, _text(row, "payload_json"))
                revision = _non_negative_int(row, "revision")
                if (
                    not task_matches_dispatch(task, dispatch.task)
                    or _text(row, "id") != task.id
                    or _text(row, "status") != task.status.value
                ):
                    raise RecoveryRejected("恢复等待的任务记录与已批准任务不一致。")
                role = {
                    TaskStatus.IMPLEMENTING: AgentRole.CODER,
                    TaskStatus.QA: AgentRole.QA,
                    TaskStatus.REVIEW: AgentRole.REVIEWER,
                }.get(task.status)
                if role is None:
                    return None
                cursor.execute(
                    "SELECT * FROM state_events WHERE task_id=%s ORDER BY revision", (task.id,)
                )
                event_rows = tuple(cursor.fetchall())
                if tuple(row["revision"] for row in event_rows) != tuple(range(1, revision + 1)):
                    raise RecoveryRejected("恢复等待的任务事件版本不完整, 暂不能接回原需求。")
                events = tuple(_decode_event(_text(row, "payload_json")) for row in event_rows)
                status = dispatch.task.status
                for event, event_row in zip(events, event_rows, strict=True):
                    if (
                        event.event_id != _text(event_row, "event_id")
                        or event.task_id != _text(event_row, "task_id")
                        or event.task_id != task.id
                        or event.from_status is not status
                    ):
                        raise RecoveryRejected("恢复等待的任务事件身份或阶段不一致。")
                    status = event.to_status
                if status is not task.status:
                    raise RecoveryRejected("恢复等待的任务状态与事件记录不一致。")
                snapshot = DeliveryFailureSnapshot(
                    task=task,
                    task_revision=revision,
                    candidate_revision=next(
                        (
                            event.source_revision
                            for event in reversed(events)
                            if event.reason in {"candidate_ready", "candidate_recovered"}
                        ),
                        None,
                    ),
                )
                cursor.execute("SELECT * FROM work_queue_items WHERE task_id=%s", (task.id,))
                items = []
                for item_row in cursor.fetchall():
                    item = QueuedWorkItem.model_validate_json(item_row["payload_json"])
                    if (
                        tuple(
                            item_row[key]
                            for key in (
                                "id",
                                "task_id",
                                "repository_id",
                                "role",
                                "attempt",
                                "checkpoint_sequence",
                                "status",
                            )
                        )
                        != (
                            item.id,
                            task.id,
                            item.repository_id,
                            item.role.value,
                            item.attempt,
                            item.checkpoint_sequence,
                            item.status.value,
                        )
                        or item.task_id != task.id
                    ):
                        raise RecoveryRejected("恢复等待的队列索引与记录不一致。")
                    items.append(item)
                pending = tuple(item for item in items if item.status is not WorkItemStatus.CLOSED)
                if len(pending) > 1:
                    raise RecoveryRejected("恢复任务存在多条当前队列记录, 暂不能接回原需求。")
                if not pending:
                    return None
                item = pending[0]
                if item.status not in {
                    WorkItemStatus.WAITING_HUMAN,
                    WorkItemStatus.WAITING_DEPENDENCY,
                }:
                    return None
                disposition = item.wait_disposition
                if disposition is None:
                    return None
                cursor.execute("SELECT * FROM work_queue_admissions WHERE id=%s", (task.id,))
                admission_row = cursor.fetchone()
                cursor.execute("SELECT * FROM work_queue_steps WHERE id=%s", (item.id,))
                step_row = cursor.fetchone()
                if admission_row is None or step_row is None:
                    raise RecoveryRejected("恢复等待缺少已提交的分派或执行边界记录。")
                admission = _decode(admission_row, RoleQueueAdmission)
                step = _decode(step_row, QueuedRoleStep)
                facts = disposition.facts
                if (
                    admission.task_id != task.id
                    or admission.repository_id != dispatch.repository_id
                    or admission.allocation_sha256 != dispatch.dispatch_sha256
                    or step.allocation_sha256 != dispatch.dispatch_sha256
                    or step.work_item.id != item.id
                    or step.work_item.dispatch_sequence != item.dispatch_sequence
                    or step.work_item.repository_scopes != item.repository_scopes
                    or item.repository_id != dispatch.repository_id
                    or item.repository_scopes != (task.repository,)
                    or item.role is not role
                    or item.attempt != task.attempts
                    or item.checkpoint_sequence != revision
                    or step.boundary.task_id != task.id
                    or step.boundary.role is not role
                    or step.boundary.attempt != task.attempts
                    or step.boundary.checkpoint_sequence != revision
                    or facts.task_id != task.id
                    or facts.work_item_id != item.id
                    or facts.role is not role
                    or facts.source_revision != step.boundary.source_revision
                    or facts.task_intent_sha256 != task_intent_sha256(task)
                    or facts.checkpoint_sequence != revision
                    or item.wait_reason != disposition.reason
                    or disposition.action is DeliveryNextAction.TERMINATE
                ):
                    raise RecoveryRejected("恢复等待的身份、阶段或代码版本已变化, 不能接回原需求。")
                cursor.execute(
                    "SELECT task_id,work_item_id,state,ended_at "
                    "FROM work_queue_claims WHERE task_id=%s",
                    (task.id,),
                )
                claims = cursor.fetchall()
                current_claims = tuple(
                    claim for claim in claims if claim["work_item_id"] == item.id
                )
                if (
                    not current_claims
                    or any(
                        claim["task_id"] != task.id or claim["state"] == "ACTIVE"
                        for claim in claims
                    )
                    or any(
                        claim["state"] not in {"RELEASED", "EXPIRED"} or claim["ended_at"] is None
                        for claim in current_claims
                    )
                ):
                    raise RecoveryRejected(
                        "恢复等待尚无可靠的已释放执行领取记录, 暂不能接回原需求。"
                    )
                return PendingRecoveryWait(snapshot, disposition)
        finally:
            connection.rollback()
