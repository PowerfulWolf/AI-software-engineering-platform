"""Read the exact released queue checkpoint before adopting a recovery knowledge wait."""

from contextlib import closing
from pathlib import Path

from pymysql.cursors import DictCursor

from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.task import task_matches_dispatch
from ai_software_engineer.knowledge.gaps import KnowledgeGap, KnowledgeGapRouting
from ai_software_engineer.knowledge.models import KnowledgeRunManifest, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected
from ai_software_engineer.store.mysql_repository import _decode_task, open_mysql_connection
from ai_software_engineer.work_queue.execution_store import (
    QueuedRoleStep,
    RoleQueueAdmission,
    _decode,
)
from ai_software_engineer.work_queue.models import QueuedWorkItem


def pending_recovery_knowledge_wait(
    *,
    dsn: str,
    sidecar: Path,
    project_id: str,
    plan: RecoveryPlan,
    dispatch: RecoveryDispatchRecord,
) -> KnowledgeGap | None:
    """No DDL, claim, model call, journal write or worktree mutation."""
    with closing(open_mysql_connection(dsn)) as connection:
        try:
            with connection.cursor(DictCursor) as cursor:
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                cursor.execute("SELECT * FROM tasks WHERE id=%s", (plan.new_task_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
                task = _decode_task(plan.new_task_id, row["payload_json"])
                revision = row["revision"]
                if (
                    not task_matches_dispatch(task, dispatch.task)
                    or row["status"] != task.status.value
                ):
                    raise RecoveryRejected("knowledge wait Task differs from approved allocation")
                role = {
                    TaskStatus.IMPLEMENTING: AgentRole.CODER,
                    TaskStatus.QA: AgentRole.QA,
                    TaskStatus.REVIEW: AgentRole.REVIEWER,
                }.get(task.status)
                if role is None:
                    return None
                cursor.execute(
                    "SELECT id,task_id,status,payload_json FROM work_queue_items WHERE task_id=%s",
                    (task.id,),
                )
                items = []
                for item_row in cursor.fetchall():
                    item = QueuedWorkItem.model_validate_json(item_row["payload_json"])
                    if (item_row["id"], item_row["task_id"], item_row["status"]) != (
                        item.id,
                        task.id,
                        item.status.value,
                    ) or item.task_id != task.id:
                        raise RecoveryRejected("recovery knowledge wait queue row changed")
                    items.append(item)
                pending = tuple(item for item in items if item.status is not WorkItemStatus.CLOSED)
                if len(pending) > 1:
                    raise RecoveryRejected("recovery knowledge wait queue is ambiguous")
                if not pending:
                    return None
                item = pending[0]
                if item.status not in {
                    WorkItemStatus.WAITING_HUMAN,
                    WorkItemStatus.WAITING_DEPENDENCY,
                }:
                    return None
                parts = (item.wait_reason or "").split(":")
                if not parts or parts[0] != "KNOWLEDGE_GAP":
                    return None
                if len(parts) != 3:
                    raise RecoveryRejected("recovery knowledge wait reason is malformed")
                _, gap_id, route_sha256 = parts
                cursor.execute("SELECT * FROM work_queue_admissions WHERE id=%s", (task.id,))
                admission_row = cursor.fetchone()
                cursor.execute("SELECT * FROM work_queue_steps WHERE id=%s", (item.id,))
                step_row = cursor.fetchone()
                if admission_row is None or step_row is None:
                    raise RecoveryRejected("recovery knowledge wait admission is missing")
                admission = _decode(admission_row, RoleQueueAdmission)
                step = _decode(step_row, QueuedRoleStep)
                if (
                    admission.task_id != task.id
                    or admission.repository_id != dispatch.repository_id
                    or admission.allocation_sha256 != dispatch.dispatch_sha256
                    or step.allocation_sha256 != dispatch.dispatch_sha256
                    or step.work_item.id != item.id
                    or step.boundary.task_id != task.id
                    or step.boundary.role is not role
                    or step.boundary.attempt != task.attempts
                    or step.boundary.checkpoint_sequence != revision
                    or item.task_id != task.id
                    or item.repository_id != dispatch.repository_id
                    or item.role is not role
                    or item.attempt != step.boundary.attempt
                    or item.checkpoint_sequence != revision
                ):
                    raise RecoveryRejected("recovery knowledge wait queue binding changed")
                cursor.execute(
                    "SELECT state FROM work_queue_claims WHERE work_item_id=%s", (item.id,)
                )
                claims = cursor.fetchall()
                if not claims or any(claim["state"] == "ACTIVE" for claim in claims):
                    raise RecoveryRejected("recovery knowledge wait requires a released claim")
                records = KnowledgeRecordStore(sidecar / "knowledge/runs", read_only=True)
                gap = records.get("gaps", gap_id, KnowledgeGap)
                gap.validate_integrity()
                route = records.get("gap-routes", gap_id, KnowledgeGapRouting)
                if (
                    gap.gap_id != gap_id
                    or route.gap_id != gap.gap_id
                    or route.routing_sha256 != route_sha256
                    or route.routing_sha256
                    != digest(route.model_dump(mode="json", exclude={"routing_sha256"}))
                    or route.waiting_status != item.status.value
                ):
                    raise RecoveryRejected("recovery knowledge wait route changed")
                binding = gap.binding
                if (
                    gap.severity != "BLOCKING"
                    or binding.task_id != task.id
                    or binding.role.value != role.value
                    or binding.team_id != plan.source.scope.team_id
                    or binding.project_id != project_id
                    or binding.repository_ids != (dispatch.repository_id,)
                    or binding.requirement_id != (plan.source.parent_delivery_id or task.id)
                    or binding.source_revision != step.boundary.source_revision
                ):
                    raise RecoveryRejected("recovery knowledge gap binding changed")
                context = FileContextStore(sidecar / "contexts", read_only=True).get(
                    binding.context_manifest_id
                )
                manifest = records.get("manifests", gap.manifest_sha256, KnowledgeRunManifest)
                manifest.validate_integrity()
                if (
                    context.task_id != task.id
                    or context.role is not role
                    or context.attempt != item.attempt
                    or context.source_revision != binding.source_revision
                    or manifest.manifest_sha256 != gap.manifest_sha256
                    or manifest.binding != binding
                    or manifest.snapshot_sha256 != binding.snapshot_sha256
                    or manifest.evidence_ids != gap.evidence_ids
                ):
                    raise RecoveryRejected("recovery knowledge wait context or manifest changed")
                return gap
        finally:
            connection.rollback()
