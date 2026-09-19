"""Read queue facts inside the caller's existing read-only SQL snapshot."""

from datetime import datetime
from typing import Literal

from pymysql.cursors import DictCursor

from ai_software_engineer.domain import WorkItemStatus
from ai_software_engineer.domain.workforce import RoleAssignment, TaskLease
from ai_software_engineer.team_view.models import RoleQueueView
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
            )
        )
    if sum(view.status is not WorkItemStatus.CLOSED for view in result) > 1:
        raise ValueError("serial Task has multiple open queue steps")
    return tuple(result)
