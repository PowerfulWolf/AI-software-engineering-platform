"""Typed ownership validation at the physical-delete SQL boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

from ai_software_engineer.domain.enums import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.workforce import ModelSelection, RoleAssignment, TaskLease
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.dispatch import VerificationReservation
from ai_software_engineer.manager.model_execution import ManagerContext, ManagerRunRecord
from ai_software_engineer.manager.model_store import MySqlManagerRecordStore
from ai_software_engineer.manager.mysql_dispatch_authority import (
    _decode_allocation,
    _decode_snapshot,
)
from ai_software_engineer.store.mysql_repository import _decode_event, _decode_task
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption, BaselineQueueRelease
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    QueuedRoleStep,
    RoleQueueAdmission,
    _decode,
)
from ai_software_engineer.work_queue.models import QueuedWorkItem
from ai_software_engineer.work_queue.mysql import MySqlPersistentWorkQueue


def manager_context_keys(
    rows: list[dict[str, object]], identities: set[str], team_id: str, project_id: str
) -> set[str]:
    owned: set[str] = set()
    others: set[str] = set()
    for row in rows:
        if row.get("namespace") not in {"manager-start", "manager-final"}:
            continue
        record = MySqlManagerRecordStore._decode(row, ManagerRunRecord)
        ManagerRunRecord.model_validate(record.to_wire())
        if row["record_key"] != digest(record.run_id):
            raise ValueError("Manager run index differs")
        key = digest(record.context_manifest_id.removeprefix("ctx_manager_"))
        if record.scope.requirement_id in identities:
            if row["team_id"] != team_id or record.scope.project_id != project_id:
                raise ValueError("Manager run owner differs")
            owned.add(key)
        else:
            others.add(key)
    return owned - others


def verify_row(
    table: str,
    row: dict[str, object],
    *,
    roots: Mapping[str, str],
    repositories: Mapping[str, str],
    team_id: str,
    project_id: str,
    identities: set[str],
) -> None:
    if table.endswith("_legacy_project_v01"):
        raise ValueError("旧版执行记录缺少完整物理清理合同, 原数据保留。")

    def owner(key: str, repository_id: str | None = None, root: str | None = None) -> None:
        if (
            key not in roots
            or (repository_id is not None and repositories[key] != repository_id)
            or (root is not None and roots[key] != root)
        ):
            raise ValueError("SQL task repository owner differs")

    if table == "tasks":
        task = _decode_task(str(row["id"]), str(row["payload_json"]))
        owner(task.id, root=task.repository)
        if task.status not in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED} or (
            row["status"] != task.status.value
        ):
            raise ValueError("SQL Task is active or changed")
        if task.engineering_policy is not None:
            scope = task.engineering_policy.scope
            if (scope.team_id, scope.project_id, scope.repository_id, scope.repository_root) != (
                team_id,
                project_id,
                repositories[task.id],
                roots[task.id],
            ):
                raise ValueError("Task frozen engineering scope differs")
        repository_id = task.metadata.get("repository_id")
        if repository_id is not None and repository_id != repositories[task.id]:
            raise ValueError("SQL Task repository metadata differs")
    elif table == "state_events":
        event = _decode_event(str(row["payload_json"]))
        owner(event.task_id)
        if row["event_id"] != event.event_id or row["task_id"] != event.task_id:
            raise ValueError("StateEvent index differs")
    elif table.startswith("dispatch_"):
        allocation = (
            _decode_snapshot(row)
            if table == "dispatch_workforce_snapshots"
            else _decode_allocation(row)
        )
        owner(allocation.task_id, allocation.repository_id)
    elif table == "verification_reservations":
        reservation = VerificationReservation.model_validate_json(str(row["payload_json"]))
        reservation.validate_integrity()
        owner(reservation.task_id, reservation.repository_id)
        owner(reservation.source_task_id, reservation.repository_id)
        if row["plan_sha256"] != reservation.plan_sha256 or not (
            bool(row.get("completion_sha256")) ^ bool(row.get("abandonment_sha256"))
        ):
            raise ValueError("Verification reservation is active or differs")
    elif table == "work_queue_items":
        item = MySqlPersistentWorkQueue._decode_item(row)
        owner(item.task_id, item.repository_id)
        for key in ("task_id", "repository_id", "role", "attempt", "checkpoint_sequence", "status"):
            value = getattr(item, key)
            if row[key] != getattr(value, "value", value):
                raise ValueError("WorkItem index differs")
        if (
            item.repository_scopes != (roots[item.task_id],)
            or item.status is not WorkItemStatus.CLOSED
        ):
            raise ValueError("WorkItem is active or has another repository scope")
    elif table == "work_queue_claims":
        assignment = RoleAssignment.model_validate_json(str(row["assignment_json"]))
        lease = TaskLease.model_validate_json(str(row["lease_json"]))
        ModelSelection.model_validate_json(str(row["model_selection_json"]))
        owner(assignment.task_id, assignment.repository_id)
        if (
            (row["task_id"], row["lease_id"], row["agent_id"], row["capacity_units"])
            != (assignment.task_id, lease.id, lease.agent_id, lease.capacity_units)
            or (assignment.lease_id, assignment.agent_id, assignment.id, assignment.task_id)
            != (lease.id, lease.agent_id, lease.assignment_id, lease.task_id)
            or row["state"] == "ACTIVE"
        ):
            raise ValueError("Lease is active or has changed identity")
        if datetime.fromisoformat(str(row["acquired_at"])) != lease.acquired_at or (
            datetime.fromisoformat(str(row["expires_at"])) != lease.expires_at
        ):
            raise ValueError("Lease time index differs")
    elif table == "work_queue_events":
        payload = json.loads(str(row["payload_json"]))
        item = QueuedWorkItem.model_validate(payload["work_item"])
        owner(item.task_id, item.repository_id)
        if (row["work_item_id"], row["to_status"]) != (item.id, item.status.value):
            raise ValueError("Queue event index differs")
    elif table == "work_queue_admissions":
        admission = _decode(row, RoleQueueAdmission)
        owner(admission.task_id, admission.repository_id)
    elif table == "work_queue_steps":
        step = _decode(row, QueuedRoleStep)
        owner(step.work_item.task_id, step.work_item.repository_id)
        if step.work_item.repository_scopes != (roots[step.work_item.task_id],):
            raise ValueError("Role step repository scope differs")
    elif table == "work_queue_accepted_artifacts":
        accepted = _decode(row, AcceptedRoleArtifact)
        owner(accepted.task_id)
    elif table in {"work_queue_execution_baselines", "work_queue_baseline_releases"}:
        record = (
            _decode(row, BaselineQueueConsumption)
            if table == "work_queue_execution_baselines"
            else _decode(row, BaselineQueueRelease)
        )
        owner(
            record.task_id, record.binding.scope.repository_id, record.binding.scope.repository_root
        )
    elif table == "manager_coordination_records":
        if row["team_id"] != team_id:
            raise ValueError("Manager record Team owner differs")
        if row["namespace"] == "manager-context":
            context = MySqlManagerRecordStore._decode(row, ManagerContext)
            if row["record_key"] != digest(context.input_sha256):
                raise ValueError("Manager Context index differs")
        else:
            run = MySqlManagerRecordStore._decode(row, ManagerRunRecord)
            ManagerRunRecord.model_validate(run.to_wire())
            if (
                run.scope.requirement_id not in identities
                or run.scope.project_id != project_id
                or (row["record_key"] != digest(run.run_id))
            ):
                raise ValueError("Manager run owner differs")
    else:
        raise ValueError("unsupported deletion table")
