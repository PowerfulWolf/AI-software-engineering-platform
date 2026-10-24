"""Private immutable pipe counters bound to an existing start and stop.

These records are diagnostics only. They grant no execution, continuation,
provider classification, command receipt or artifact authority.
"""

from typing import Literal, Self

from pydantic import AwareDatetime, model_validator

from ai_software_engineer.agents.native_observation import NativeOutputObservation
from ai_software_engineer.context.models import ContextId
from ai_software_engineer.domain.execution_baseline import FullGitRevision
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.domain.workforce import LeaseId
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ContinuationScope,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue.models import WorkItemId


class NativeExecutionObservation(DomainModel):
    kind: Literal["native_execution_observation"] = "native_execution_observation"
    schema_version: Literal["v1"] = "v1"
    scope: ContinuationScope
    task_id: TaskId
    run_id: RunId
    work_item_id: WorkItemId
    lease_id: LeaseId
    source_revision: FullGitRevision
    context_manifest_id: ContextId
    request_sha256: StageSha256
    capture_start_sha256: StageSha256
    capture_stop_sha256: StageSha256
    output: NativeOutputObservation
    recorded_at: AwareDatetime
    observation_sha256: StageSha256

    def recompute_sha256(self) -> str:
        return digest(
            self.model_dump(mode="json", exclude_none=True, exclude={"observation_sha256"})
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.observation_sha256 != self.recompute_sha256():
            raise ContinuationRejected("native observation digest mismatch")

    def validate_capture(self, start: ExecutionCaptureStart, stop: ExecutionCaptureStop) -> None:
        start.validate_integrity()
        stop.validate_integrity()
        if (
            stop.task_id != start.request.task_id
            or stop.run_id != start.request.run_id
            or stop.capture_start_sha256 != start.start_sha256
            or self.recorded_at < stop.process_stop.stopped_at
            or self._binding() != self._capture_binding(start, stop)
        ):
            raise ContinuationRejected("native observation changed its exact original capture")

    def _binding(self) -> tuple[object, ...]:
        return (
            self.scope,
            self.task_id,
            self.run_id,
            self.work_item_id,
            self.lease_id,
            self.source_revision,
            self.context_manifest_id,
            self.request_sha256,
            self.capture_start_sha256,
            self.capture_stop_sha256,
        )

    @staticmethod
    def _capture_binding(
        start: ExecutionCaptureStart, stop: ExecutionCaptureStop
    ) -> tuple[object, ...]:
        return (
            start.scope,
            start.request.task_id,
            start.request.run_id,
            start.claim.work_item.id,
            start.claim.lease.id,
            start.request.source_revision,
            start.request.context_manifest_id,
            digest(start.request.to_wire()),
            start.start_sha256,
            stop.observation_sha256,
        )

    @classmethod
    def from_capture(
        cls,
        *,
        start: ExecutionCaptureStart,
        stop: ExecutionCaptureStop,
        output: NativeOutputObservation,
        recorded_at: AwareDatetime,
    ) -> Self:
        record = cls(
            scope=start.scope,
            task_id=start.request.task_id,
            run_id=start.request.run_id,
            work_item_id=start.claim.work_item.id,
            lease_id=start.claim.lease.id,
            source_revision=start.request.source_revision,
            context_manifest_id=start.request.context_manifest_id,
            request_sha256=digest(start.request.to_wire()),
            capture_start_sha256=start.start_sha256,
            capture_stop_sha256=stop.observation_sha256,
            output=output,
            recorded_at=recorded_at,
            observation_sha256="0" * 64,
        )
        record.validate_capture(start, stop)
        return record.model_copy(update={"observation_sha256": record.recompute_sha256()})


class NativeObservationRead(DomainModel):
    """Missing counters are unavailable, while invalid records still fail closed."""

    availability: Literal["AVAILABLE", "UNAVAILABLE"]
    record: NativeExecutionObservation | None = None

    @model_validator(mode="after")
    def explicit_availability(self) -> Self:
        if (self.availability == "AVAILABLE") != (self.record is not None):
            raise ValueError("native observation availability must match its record")
        return self
