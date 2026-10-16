"""Stable original ownership identity, independent of recovery decisions."""

from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.work_queue.models import QueueClaim


def claim_identity_sha256(claim: QueueClaim) -> str:
    """Heartbeat expiry and mutable queue status cannot change original ownership."""
    item = claim.work_item
    return digest(
        {
            "work_item": item.model_dump(
                mode="json",
                exclude={"status", "updated_at", "available_at", "wait_reason", "wait_disposition"},
            ),
            "assignment": claim.assignment.to_wire(),
            "lease": claim.lease.model_dump(mode="json", exclude={"expires_at"}),
            "model_selection": claim.model_selection.to_wire(),
            "worker_id": claim.worker_id,
            "claimed_at": claim.claimed_at.isoformat(),
        }
    )
