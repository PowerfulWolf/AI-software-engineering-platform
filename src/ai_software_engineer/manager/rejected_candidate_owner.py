"""Auditable expiry of an exact stopped rejected-candidate owner, never a retry grant."""

from __future__ import annotations

from typing import Literal, Protocol, Self

from pydantic import AwareDatetime, Field, StrictInt, model_validator

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.rejected_candidate_output import RejectedCandidateOutputProof
from ai_software_engineer.work_queue.claim_snapshot import require_claim_snapshot
from ai_software_engineer.work_queue.models import QueueClaim

EXPIRED_OWNER_NAMESPACE = "rejected-candidate-owner-stops"
EXPIRED_OWNER_EVENT = "REJECTED_CANDIDATE_OWNER_EXPIRED"


class TaskProcessLockGuard(Protocol):
    @property
    def inherited_fds(self) -> tuple[int, ...]: ...

    def check_task_scope(self, task_id: str) -> None: ...


class RejectedCandidateExpiredOwnerSettlement(DomainModel):
    kind: Literal["rejected_candidate_expired_owner_settlement"] = (
        "rejected_candidate_expired_owner_settlement"
    )
    schema_version: Literal["v1"] = "v1"
    task_id: NonEmptyStr
    task_revision: StrictInt = Field(ge=1)
    proof: RejectedCandidateOutputProof
    current_claim: QueueClaim
    original_claim_sha256: Sha256
    current_claim_sha256: Sha256
    observed_at: AwareDatetime
    resulting_claim_state: Literal["EXPIRED"] = "EXPIRED"
    work_item_changed: Literal[False] = False
    budget_refund: Literal[False] = False
    settlement_sha256: Sha256

    @model_validator(mode="after")
    def exact_stopped_expired_owner(self) -> Self:
        self.proof.validate_integrity()
        require_claim_snapshot(self.proof.original_claim, self.current_claim)
        if (
            self.task_id != self.proof.task_id
            or self.task_revision != self.proof.task_revision
            or self.current_claim.lease.expires_at > self.observed_at
            or self.observed_at < self.proof.capture_stop.process_stop.stopped_at
            or self.original_claim_sha256 != digest(self.proof.original_claim.to_wire())
            or self.current_claim_sha256 != digest(self.current_claim.to_wire())
        ):
            raise ValueError("拒绝候选过期owner收尾缺少完整原停止、真实过期和精确身份")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.settlement_sha256 != self.recompute_sha256():
            raise ValueError("拒绝候选过期owner收尾记录摘要不一致")

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"settlement_sha256"}))

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "settlement_sha256": "0" * 64})
        return value.model_copy(update={"settlement_sha256": value.recompute_sha256()})
