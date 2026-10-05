"""Exact durable invocation guard; lease expiry never proves a call did not happen."""

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import AwareDatetime, model_validator

from ai_software_engineer.agents.continuation import ContinuationExecutionUncertain
from ai_software_engineer.agents.models import AgentRequest, AgentResult
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.work_queue.ports import QueueConflict
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


class DeliveryInvocationStart(DomainModel):
    kind: Literal["delivery_invocation_start"] = "delivery_invocation_start"
    work_item_id: NonEmptyStr
    checkpoint_sequence: int
    request: AgentRequest
    lease_id: NonEmptyStr
    started_at: AwareDatetime
    start_sha256: StageSha256

    def validate_integrity(self) -> None:
        if self.start_sha256 != digest(self.model_dump(mode="json", exclude={"start_sha256"})):
            raise ValueError("invocation start integrity mismatch")


class DeliveryInvocationOutcome(DomainModel):
    kind: Literal["delivery_invocation_outcome"] = "delivery_invocation_outcome"
    start: DeliveryInvocationStart
    result: AgentResult
    outcome_sha256: StageSha256

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        self.start.validate_integrity()
        request, result = self.start.request, self.result
        if (
            result.run_id,
            result.task_id,
            result.role,
            result.attempt,
            result.source_revision,
            result.context_manifest_id,
        ) != (
            request.run_id,
            request.task_id,
            request.role,
            request.attempt,
            request.source_revision,
            request.context_manifest_id,
        ):
            raise ValueError("invocation outcome belongs to another exact request")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.outcome_sha256 != digest(self.model_dump(mode="json", exclude={"outcome_sha256"})):
            raise ValueError("invocation outcome integrity mismatch")


class DurableInvocationControl:
    """A Worker can replay a definitive result, never re-call an unknown invocation."""

    def __init__(self, records: KnowledgeRecordStore, guard: WorkerExecutionGuard) -> None:
        self.records, self.guard = records, guard

    def _identity(self, request: AgentRequest) -> tuple[str, int, str]:
        self.guard.check()
        lease = self.guard.lease
        if lease is None:
            raise QueueConflict("invocation requires a real role claim")
        item = lease.claim.work_item
        if (item.task_id, item.role, item.attempt) != (
            request.task_id,
            request.role,
            request.attempt,
        ):
            raise QueueConflict("invocation request changed the claimed role identity")
        return item.id, item.checkpoint_sequence, lease.claim.lease.id

    def prepare(self, request: AgentRequest) -> AgentRequest:
        key, sequence, lease_id = self._identity(request)
        start = self.records.find("invocation-starts", key, DeliveryInvocationStart)
        if start is not None:
            start.validate_integrity()
            # A newly built Context/Run may be unused after restart. Reuse only the
            # sealed original identity with exactly the same semantic input.
            excluded = {"run_id", "context_manifest_id"}
            if start.checkpoint_sequence != sequence or (
                start.request.model_dump(mode="json", exclude=excluded)
                != request.model_dump(mode="json", exclude=excluded)
            ):
                raise QueueConflict("invocation replay changed its frozen inputs")
            outcome = self.records.find("invocation-outcomes", key, DeliveryInvocationOutcome)
            if outcome is None:
                raise ContinuationExecutionUncertain("原调用已记录, 结果尚未封存; 禁止重复调用")
            outcome.validate_integrity()
            if outcome.start != start:
                raise QueueConflict("invocation result changed its sealed start")
            return start.request
        start = DeliveryInvocationStart(
            work_item_id=key,
            checkpoint_sequence=sequence,
            request=request,
            lease_id=lease_id,
            started_at=datetime.now(UTC),
            start_sha256="0" * 64,
        )
        start = start.model_copy(
            update={
                "start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"})),
            }
        )
        with self.guard.write_scope():
            self.records.put("invocation-starts", key, start)
        return request

    def has_started(self, request: AgentRequest) -> bool:
        key, _, _ = self._identity(request)
        return self.records.find("invocation-starts", key, DeliveryInvocationStart) is not None

    def result(self, request: AgentRequest) -> AgentResult | None:
        key, _, _ = self._identity(request)
        outcome = self.records.find("invocation-outcomes", key, DeliveryInvocationOutcome)
        if outcome is None:
            return None
        outcome.validate_integrity()
        if outcome.start.request != request:
            raise QueueConflict("invocation result is not for this exact request")
        return outcome.result

    def completed(self, request: AgentRequest, result: AgentResult) -> None:
        key, _, _ = self._identity(request)
        start = self.records.get("invocation-starts", key, DeliveryInvocationStart)
        if start.request != request:
            raise QueueConflict("invocation completion changed its request")
        outcome = DeliveryInvocationOutcome(start=start, result=result, outcome_sha256="0" * 64)
        outcome = outcome.model_copy(
            update={
                "outcome_sha256": digest(
                    outcome.model_dump(mode="json", exclude={"outcome_sha256"})
                ),
            }
        )
        with self.guard.write_scope():
            self.records.put("invocation-outcomes", key, outcome)
