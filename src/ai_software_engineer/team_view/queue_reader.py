"""Read queue facts inside the caller's existing read-only SQL snapshot."""

from datetime import datetime
from typing import Literal

from pymysql.cursors import DictCursor

from ai_software_engineer.domain import WorkItemStatus
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import TaskStatus
from ai_software_engineer.domain.task import Task
from ai_software_engineer.domain.workforce import RoleAssignment, TaskLease
from ai_software_engineer.manager.baseline_models import BaselineContinueAuthorization
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.team_view.models import RoleQueueView
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption, BaselineQueueRelease
from ai_software_engineer.work_queue.execution_store import RoleQueueAdmission, _decode
from ai_software_engineer.work_queue.models import QueuedWorkItem


def read_role_queue(
    cursor: DictCursor, *, task_id: str, repository_id: str, allocation_sha256: str, now: datetime
) -> tuple[RoleQueueView, ...]:
    cursor.execute(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='work_queue_admissions'"
    )
    row = cursor.fetchone()
    if row is None:
        return ()
    if row.get("TABLE_NAME") != "work_queue_admissions":
        raise ValueError("unexpected queue schema discovery")
    cursor.execute(
        "SELECT id,task_id,payload_json,sha256 FROM work_queue_admissions WHERE id=%s",
        (task_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return ()
    admission = _decode(row, RoleQueueAdmission)
    if (admission.task_id, admission.repository_id, admission.allocation_sha256) != (
        task_id,
        repository_id,
        allocation_sha256,
    ):
        raise ValueError("queue adoption does not match delivery")
    cursor.execute(
        "SELECT id,task_id,payload_json FROM work_queue_items WHERE task_id=%s "
        "ORDER BY checkpoint_sequence,attempt,id",
        (task_id,),
    )
    result = []
    for item_row in cursor.fetchall():
        item = QueuedWorkItem.model_validate_json(item_row["payload_json"])
        if (item.id, item.task_id, item.repository_id) != (
            item_row["id"],
            item_row["task_id"],
            repository_id,
        ) or item.task_id != task_id:
            raise ValueError("queue item identity mismatch")
        cursor.execute(
            "SELECT lease_id,assignment_json,lease_json,state,last_heartbeat_at,expires_at "
            "FROM work_queue_claims WHERE work_item_id=%s ORDER BY acquired_at DESC,lease_id DESC",
            (item.id,),
        )
        claims = cursor.fetchall()
        agent_id = None
        heartbeat = expiry = None
        lease_state = None
        if claims:
            claim = claims[0]
            assignment = RoleAssignment.model_validate_json(claim["assignment_json"])
            lease = TaskLease.model_validate_json(claim["lease_json"])
            heartbeat = datetime.fromisoformat(claim["last_heartbeat_at"])
            expiry = datetime.fromisoformat(claim["expires_at"])
            if (
                assignment.task_id != item.task_id
                or assignment.role is not item.role
                or assignment.repository_id != item.repository_id
                or assignment.attempt != item.attempt
                or lease.id != claim["lease_id"]
                or lease.assignment_id != assignment.id
                or assignment.lease_id != lease.id
                or lease.agent_id != assignment.agent_id
                or lease.task_id != item.task_id
                or expiry != lease.expires_at
                or heartbeat.tzinfo is None
                or not lease.acquired_at <= heartbeat < expiry
            ):
                raise ValueError("queue lease read binding mismatch")
            agent_id = assignment.agent_id
            lease_state = claim["state"]
        liveness: Literal["UNKNOWN", "LEASE_VALID", "LEASE_EXPIRED"] = "UNKNOWN"
        if lease_state == "ACTIVE" and expiry is not None:
            liveness = "LEASE_VALID" if expiry > now else "LEASE_EXPIRED"
        elif (
            lease_state == "EXPIRED"
            and expiry is not None
            and expiry <= now
            and item.status is WorkItemStatus.RETRY_SCHEDULED
            and item.wait_reason == f"lease_expired:{lease.id}"
        ):
            liveness = "LEASE_EXPIRED"
        result.append(
            RoleQueueView(
                work_item_id=item.id,
                role=item.role,
                attempt=item.attempt,
                status=item.status,
                agent_id=agent_id,
                heartbeat_at=heartbeat,
                lease_expires_at=expiry,
                lease_liveness=liveness,
                wait_reason=item.wait_reason,
                wait_disposition=item.wait_disposition,
                wait_disposition_sha256=(
                    item.wait_disposition.disposition_sha256
                    if item.wait_disposition is not None
                    else None
                ),
                available_at=item.available_at,
            )
        )
    if sum(view.status is not WorkItemStatus.CLOSED for view in result) > 1:
        raise ValueError("serial Task has multiple open queue steps")
    return tuple(result)


def read_pending_baseline_continuation(
    cursor: DictCursor,
    *,
    task: Task,
    task_revision: int,
    scope: EngineeringScope,
    baselines: FileExecutionBaselineStore | None,
    views: tuple[RoleQueueView, ...],
) -> tuple[RoleQueueView, ...]:
    """Expose only a verified saved release still awaiting its first real claim.

    All SQL uses the caller's existing read-only snapshot; no queue construction,
    locks, schema initialization, Host preparation or state reconciliation.
    """
    ready = tuple(view for view in views if view.status is WorkItemStatus.READY)
    if task.status is not TaskStatus.IMPLEMENTING or not ready:
        return views
    if baselines is None:
        return views
    if not baselines.read_only:
        raise ValueError("继续状态读取只能使用既有只读工程记录")
    store = baselines
    bindings = store.bindings_for_task(task.id)
    if not bindings:
        return views
    binding = bindings[-1]
    authority = store.records.find(
        "baseline-continuations", binding.binding_sha256, BaselineContinueAuthorization
    )
    if authority is None:
        return views
    authority.validate_integrity()
    binding.require_task(task)
    if (
        authority.scope != scope
        or binding.scope != scope
        or authority.task_id != task.id
        or authority.task_intent_sha256 != binding.task_intent_sha256
        or authority.execution_baseline_sha256 != binding.binding_sha256
        or authority.expected_source_revision != binding.execution_source_revision
        or authority.inventory_sha256 != binding.after_inventory_sha256
    ):
        raise ValueError("待接续的明确决定不属于当前仓库")
    cursor.execute(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='work_queue_baseline_releases'"
    )
    if cursor.fetchone() is None:
        return views
    cursor.execute(
        "SELECT id,task_id,payload_json,sha256 FROM work_queue_baseline_releases WHERE id=%s",
        (authority.authorization_sha256,),
    )
    row = cursor.fetchone()
    if row is None:
        return views
    release = _decode(row, BaselineQueueRelease)
    if release.binding != binding or release.authorization != authority:
        raise ValueError("已保存继续决定与真实队列释放记录不同")
    cursor.execute(
        "SELECT id,task_id,payload_json,sha256 FROM work_queue_execution_baselines "
        "WHERE task_id=%s",
        (task.id,),
    )
    consumed = tuple(_decode(row, BaselineQueueConsumption) for row in cursor.fetchall())
    if len({item.binding.sequence for item in consumed}) != len(consumed):
        raise ValueError("工程输入队列消费存在重复版本")
    latest = max(consumed, key=lambda item: item.binding.sequence, default=None)
    if (
        latest is None
        or latest.binding != binding
        or latest.next_work_item_id != authority.work_item_id
    ):
        raise ValueError("明确继续记录未绑定当前最新工程输入")
    cursor.execute(
        "SELECT id,task_id,payload_json FROM work_queue_items WHERE id=%s",
        (authority.work_item_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError("已授权接续的原工作项缺失")
    item = QueuedWorkItem.model_validate_json(row["payload_json"])
    if (item.id, item.task_id) != (row["id"], row["task_id"]):
        raise ValueError("待接续工作项身份不一致")
    if (
        item != release.ready_work_item
        or authority.task_revision != task_revision
        or task.attempts != item.attempt
    ):
        return views
    cursor.execute(
        "SELECT lease_id FROM work_queue_claims WHERE task_id=%s AND state='ACTIVE'",
        (task.id,),
    )
    if cursor.fetchone() is not None:
        return views
    return tuple(
        view.model_copy(update={"pending_baseline_continuation": authority})
        if view.work_item_id == item.id
        else view
        for view in views
    )
