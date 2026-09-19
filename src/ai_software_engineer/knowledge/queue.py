"""Release one real Dispatcher claim for a verified knowledge wait.

This adapter belongs to trusted worker composition. It does not acquire claims,
create work, infer ownership, or migrate the legacy request runner onto the queue.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ai_software_engineer.domain.enums import WorkItemStatus
from ai_software_engineer.knowledge.gaps import KnowledgeGap, KnowledgeGapRouting
from ai_software_engineer.knowledge.models import KnowledgeError, KnowledgeRunBinding, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import PersistentWorkQueue, QueueConflict


class QueueKnowledgeWaitPort:
    """Exact run authority plus the queue's atomic owner/Lease fence.

    ``binding`` is supplied by the trusted worker for the consultation it is about
    to run, not by an Agent. QueueClaim carries Task/role/repository/attempt but does
    not carry Team/Project/run/context; this exact binding seals those coordinates.
    The queue remains the authority on current ownership and Lease expiry.
    """

    def __init__(
        self,
        queue: PersistentWorkQueue,
        *,
        claim: QueueClaim,
        owner_token: str,
        binding: KnowledgeRunBinding,
        records: KnowledgeRecordStore,
        clock: Callable[[], datetime],
    ) -> None:
        validated_claim = QueueClaim.model_validate(claim.to_wire())
        validated_binding = KnowledgeRunBinding.model_validate(binding.to_wire())
        if (
            validated_binding.task_id != validated_claim.work_item.task_id
            or validated_binding.role.value != validated_claim.work_item.role.value
            or validated_binding.repository_ids != (validated_claim.work_item.repository_id,)
        ):
            raise KnowledgeError("QUEUE_BINDING")
        if not owner_token:
            raise KnowledgeError("QUEUE_OWNER_REQUIRED")
        self._queue = queue
        self._claim = validated_claim
        self._binding = validated_binding
        self._owner_token = owner_token
        self._records = records
        self._clock = clock

    def wait(self, binding: KnowledgeRunBinding, routing: KnowledgeGapRouting) -> None:
        if binding != self._binding:
            raise KnowledgeError("QUEUE_BINDING")
        routing = KnowledgeGapRouting.model_validate(routing.to_wire())
        if routing.routing_sha256 != digest(
            routing.model_dump(mode="json", exclude={"routing_sha256"})
        ):
            raise KnowledgeError("QUEUE_ROUTE_INTEGRITY")
        gap = self._records.get("gaps", routing.gap_id, KnowledgeGap)
        gap.validate_integrity()
        persisted = self._records.get("gap-routes", routing.gap_id, KnowledgeGapRouting)
        expected_status = (
            "WAITING_DEPENDENCY"
            if routing.route in {"PRODUCT", "DESIGNER", "RESEARCH", "WAITING_DEPENDENCY"}
            else "WAITING_HUMAN"
        )
        if (
            persisted != routing
            or gap.binding != self._binding
            or gap.severity != "BLOCKING"
            or routing.waiting_status != expected_status
        ):
            raise KnowledgeError("QUEUE_ROUTE")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise KnowledgeError("QUEUE_CLOCK")
        if now < self._claim.claimed_at:
            raise QueueConflict("knowledge wait predates its claim")
        current = self._queue.get(self._claim.work_item.id)
        self._require_current_work(current)
        # Do not accept a waiting status as an idempotent success: that would let a
        # stale or foreign owner pretend it released a Lease. The queue checks the
        # exact active lease/token/expiry again inside its transaction.
        self._queue.wait(
            current.id,
            lease_id=self._claim.lease.id,
            owner_token=self._owner_token,
            status=WorkItemStatus(routing.waiting_status),
            reason=f"KNOWLEDGE_GAP:{routing.gap_id}:{routing.routing_sha256}",
            now=now,
        )

    def _require_current_work(self, current: QueuedWorkItem) -> None:
        claimed = self._claim.work_item
        if current.status not in {WorkItemStatus.LEASED, WorkItemStatus.RUNNING}:
            raise QueueConflict("knowledge wait requires active work")
        identity = (
            "id",
            "task_id",
            "repository_id",
            "role",
            "attempt",
            "checkpoint_sequence",
            "dispatch_sequence",
            "repository_scopes",
            "parent_work_item_id",
        )
        if any(getattr(current, field) != getattr(claimed, field) for field in identity):
            raise QueueConflict("knowledge wait claim no longer matches current work")
