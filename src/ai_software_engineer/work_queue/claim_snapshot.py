"""Validate independently sealed original claims against the real allocation."""

from __future__ import annotations

from dataclasses import dataclass

from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.work_queue.models import QueueClaim


@dataclass(frozen=True)
class OriginalClaimRecord:
    """Read-only provenance; an absent legacy snapshot cannot become immutable bytes."""

    claim: QueueClaim
    has_immutable_snapshot: bool


def require_claim_snapshot(
    snapshot: QueueClaim, historical: QueueClaim, *, expected_sha256: str | None = None
) -> QueueClaim:
    """Allow only renewable lease expiry to differ; retain complete raw digest proof."""
    if expected_sha256 is not None and digest(snapshot.to_wire()) != expected_sha256:
        raise ValueError("原 claim 快照与封存的完整摘要不一致")
    normalized = snapshot.model_copy(
        update={
            "lease": snapshot.lease.model_copy(update={"expires_at": historical.lease.expires_at})
        }
    )
    if normalized != historical:
        raise ValueError("原 claim 快照与真实历史分配不一致, 仅允许续租到期时间变化")
    return snapshot
