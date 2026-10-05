"""Read the exact consumed engineering decision before replacing preparation intent."""

from __future__ import annotations

from contextlib import closing
from typing import TYPE_CHECKING

from pymysql.cursors import DictCursor

from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
)
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueConflict, QueueCorruption

if TYPE_CHECKING:
    from ai_software_engineer.manager.verifier_preparation import VerifierPreparationIntent
    from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue


class _ResolutionDetail(DomainModel):
    resolution_sha256: NonEmptyStr
    next_work_item_id: NonEmptyStr
    resolution: DeliveryResolution
    budget_refund: bool


class _ResolutionEvent(DomainModel):
    work_item: QueuedWorkItem
    detail: _ResolutionDetail


def preparation_resume_consumed(
    queue: MySqlRoleQueue, dsn: str, intent: VerifierPreparationIntent, claim: QueueClaim
) -> bool:
    """Lease expiry and generation growth alone never grant another native execution."""
    intent.validate_integrity()
    original = queue.original_claim(intent.lease_id)
    if queue.original_claim(claim.lease.id) != claim or (
        original.work_item.id,
        original.work_item.task_id,
        original.work_item.role,
        original.work_item.attempt,
        original.work_item.checkpoint_sequence,
        original.work_item.dispatch_sequence,
    ) != (
        intent.work_item_id,
        intent.task_id,
        intent.request.role,
        intent.request.attempt,
        intent.checkpoint_sequence,
        intent.dispatch_sequence,
    ):
        raise QueueConflict("验证准备继续请求不匹配原真实 claim")
    if (
        claim.work_item.id != intent.work_item_id
        or claim.work_item.dispatch_sequence <= intent.dispatch_sequence
    ):
        return False
    with (
        closing(open_mysql_connection(dsn)) as connection,
        connection.cursor(DictCursor) as cursor,
    ):
        cursor.execute(
            "SELECT sequence,lease_id FROM work_queue_events WHERE event_type='CLAIMED' "
            "AND lease_id IN (%s,%s)",
            (intent.lease_id, claim.lease.id),
        )
        rows = cursor.fetchall()
        sequences = {str(row["lease_id"]): int(row["sequence"]) for row in rows}
        if len(rows) != 2 or len(sequences) != 2:
            raise QueueCorruption("验证准备缺少唯一原 claim 和当前 claim 顺序")
        cursor.execute(
            "SELECT payload_json FROM work_queue_events WHERE work_item_id=%s "
            "AND event_type='WAIT_RESOLVED' AND sequence>%s AND sequence<%s "
            "ORDER BY sequence DESC LIMIT 1",
            (intent.work_item_id, sequences[intent.lease_id], sequences[claim.lease.id]),
        )
        row = cursor.fetchone()
    if row is None:
        return False
    event = _ResolutionEvent.model_validate_json(str(row["payload_json"]))
    decision = event.detail.resolution
    decision.validate_integrity()
    proof = decision.verifier_preparation
    if decision.resolution_kind is not DeliveryResolutionKind.RESUME_UNINVOKED or proof is None:
        return False
    return (
        not event.detail.budget_refund
        and event.detail.resolution_sha256 == decision.resolution_sha256
        and event.detail.next_work_item_id == claim.work_item.id == event.work_item.id
        and (
            event.work_item.task_id,
            event.work_item.repository_id,
            event.work_item.checkpoint_sequence,
        )
        == (
            claim.work_item.task_id,
            claim.work_item.repository_id,
            claim.work_item.checkpoint_sequence,
        )
        == (
            original.work_item.task_id,
            original.work_item.repository_id,
            original.work_item.checkpoint_sequence,
        )
        and event.work_item.dispatch_sequence == claim.work_item.dispatch_sequence
        and event.work_item.status.value == "READY"
        and event.work_item.role is claim.work_item.role is intent.request.role
        and event.work_item.attempt == claim.work_item.attempt == intent.request.attempt
        and decision.task_id == intent.task_id
        and decision.work_item_id == intent.work_item_id
        and decision.task_snapshot_sha256 == intent.task_snapshot_sha256
        and decision.expected_checkpoint_sequence == intent.checkpoint_sequence
        and decision.task_revision == intent.checkpoint_sequence
        and decision.expected_source_revision == intent.request.source_revision
        and decision.step_sha256 == digest(queue.step_for_claim(original).to_wire())
        and proof.native_execution_state == "NOT_STARTED"
        and proof.request_sha256 == intent.request_sha256
        and proof.previous_run_id == intent.request.run_id
        and proof.previous_context_manifest_id == intent.request.context_manifest_id
        and proof.candidate_revision == intent.request.source_revision
    )
