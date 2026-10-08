"""Stopped execution facts and deterministic one-use engineering admissions.

Receipts retain interrupted work without asserting Coder progress or accepting a
candidate. Admission is a policy decision; the service must resolve its current
stop, mutation, budget and owner-fenced queue facts before publishing it.
"""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator

from ai_software_engineer.agents.continuation import InterruptionAdmissionRejected
from ai_software_engineer.agents.execution import (
    ExecutionStop,
    NativeProcessStop,
    SynchronousToolLoopStop,
)
from ai_software_engineer.agents.models import AgentErrorCode, AgentRequest
from ai_software_engineer.domain.continuation import ContinuationCause
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.identity import ProjectId, RepositoryId, RunId, TeamId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.retry_policy import TRANSIENT_CODES, ExecutionAttempt
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.domain.workforce import LeaseId
from ai_software_engineer.git.mutation import WorkspaceMutationInventory
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.recovery.models import AbsolutePath, CapturedChanges, RelativePath, digest
from ai_software_engineer.work_queue.models import QueueClaim, WorkItemId


class ContinuationRejected(InterruptionAdmissionRejected):
    """A continuation fact or admission cannot be trusted."""


class ContinuationConflict(ContinuationRejected):
    """A one-use identity was already bound to different facts."""


class ContinuationRecordMissing(ContinuationRejected):
    """An exact interruption fact or admission has not been published."""


class ContinuationScope(DomainModel):
    team_id: TeamId
    project_id: ProjectId
    repository_id: RepositoryId
    requirement_id: DeliveryId
    dispatch_sha256: StageSha256


class ExecutionCaptureStart(DomainModel):
    """Original claimed inventory, sealed before the native invocation starts."""

    kind: Literal["execution_capture_start"] = "execution_capture_start"
    schema_version: Literal["v1"] = "v1"
    scope: ContinuationScope
    request: AgentRequest
    claim: QueueClaim
    task_intent_sha256: StageSha256
    task_revision: Annotated[StrictInt, Field(ge=1)]
    policy_sha256: StageSha256
    worktree_path: AbsolutePath
    inventory_before: WorkspaceMutationInventory
    started_at: AwareDatetime
    start_sha256: StageSha256

    @model_validator(mode="after")
    def require_original_claim(self) -> Self:
        item, request = self.claim.work_item, self.request
        if (item.task_id, item.repository_id, item.role, item.attempt) != (
            request.task_id,
            self.scope.repository_id,
            AgentRole.CODER,
            request.attempt,
        ) or request.role is not AgentRole.CODER:
            raise ValueError("capture start requires the original claimed Coder invocation")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"start_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.start_sha256 != self.recompute_sha256():
            raise ContinuationRejected("capture start digest mismatch")

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "start_sha256": "0" * 64})
        return value.model_copy(update={"start_sha256": value.recompute_sha256()})


class ExecutionCaptureStop(DomainModel):
    """Owned-runner final observation; it grants no retry or artifact authority."""

    kind: Literal["execution_capture_stop"] = "execution_capture_stop"
    schema_version: Literal["v1"] = "v1"
    task_id: TaskId
    run_id: RunId
    capture_start_sha256: StageSha256
    process_stop: NativeProcessStop
    output_present: StrictBool
    cause: ContinuationCause | None = None
    original_error_code: AgentErrorCode | None = None
    observation_sha256: StageSha256

    @model_validator(mode="after")
    def require_real_cause(self) -> Self:
        self.process_stop.validate_integrity()
        if self.cause == "local_execution_limit" and (
            self.process_stop.kind != "local_execution_limit"
            or self.original_error_code is not AgentErrorCode.TIMEOUT
        ):
            raise ValueError("local capture stop requires a real execution limit")
        if self.cause == "provider_transient" and (
            self.process_stop.kind != "failed"
            or self.original_error_code is None
            or self.original_error_code.value not in TRANSIENT_CODES
        ):
            raise ValueError("provider capture stop requires a typed transient failure")
        return self

    def recompute_sha256(self) -> str:
        return digest(
            self.model_dump(mode="json", exclude_none=True, exclude={"observation_sha256"})
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.observation_sha256 != self.recompute_sha256():
            raise ContinuationRejected("capture stop digest mismatch")

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "observation_sha256": "0" * 64})
        return value.model_copy(update={"observation_sha256": value.recompute_sha256()})


class ExecutionInterruptionReceipt(DomainModel):
    """Capture plus trusted executor references, never progress or a verdict."""

    kind: Literal["execution_interruption_receipt"] = "execution_interruption_receipt"
    schema_version: Literal["v1", "v2"] = "v1"
    scope: ContinuationScope
    request: AgentRequest
    task_intent_sha256: StageSha256
    task_revision: Annotated[StrictInt, Field(ge=1)]
    original_work_item_id: WorkItemId
    claim_lease_id: LeaseId
    policy_sha256: StageSha256
    cause: ContinuationCause
    original_error_code: AgentErrorCode
    process_stop: ExecutionStop
    process_stop_sha256: StageSha256
    capture: CapturedChanges | CapturedMutations
    inventory_before: WorkspaceMutationInventory
    inventory_after: WorkspaceMutationInventory
    inventory_before_sha256: StageSha256
    inventory_after_sha256: StageSha256
    mutation_paths: tuple[RelativePath, ...]
    created_at: AwareDatetime
    receipt_sha256: StageSha256
    previous_admission_sha256: StageSha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_validate({**values, "receipt_sha256": "0" * 64})
        return provisional.model_copy(update={"receipt_sha256": provisional.recompute_sha256()})

    @model_validator(mode="after")
    def validate_interruption_identity(self) -> Self:
        request, capture = self.request, self.capture
        if (self.schema_version == "v1" and not isinstance(capture, CapturedChanges)) or (
            self.schema_version == "v2" and not isinstance(capture, CapturedMutations)
        ):
            raise ValueError("interruption version must bind its exact capture capability")
        if isinstance(capture, CapturedMutations):
            observed = {item.path: item for item in self.inventory_after.files}
            for mutation in capture.mutations:
                actual = observed.get(mutation.path)
                if mutation.after is None:
                    if actual is not None:
                        raise ValueError("deleted mutation must be absent from final inventory")
                elif (
                    actual is None
                    or actual.kind != "file"
                    or actual.sha256 != mutation.after.sha256
                    or actual.mode != mutation.after.mode
                    or actual.size != mutation.after.size
                ):
                    raise ValueError("mutation after-body must match complete final inventory")
        if (
            self.inventory_before.sha256 != self.inventory_before_sha256
            or self.inventory_after.sha256 != self.inventory_after_sha256
        ):
            raise ValueError("interruption receipt inventory body and digest must match")
        self.process_stop.validate_integrity()
        if isinstance(self.process_stop, SynchronousToolLoopStop):
            if self.schema_version != "v2" or (self.cause == "local_execution_limit") != (
                self.process_stop.kind == "local_execution_limit"
            ):
                raise ValueError("synchronous provider stops require the v2 continuation contract")
            self.process_stop.require_request(request)
        if (
            self.process_stop_sha256 != self.process_stop.stop_sha256
            or self.created_at < self.process_stop.stopped_at
            or (
                self.cause == "local_execution_limit"
                and self.process_stop.kind != "local_execution_limit"
            )
        ):
            raise ValueError("interruption receipt must bind the prior exact process stop")
        if (
            request.role is not AgentRole.CODER
            or (
                self.schema_version == "v1"
                and (
                    request.attempt != 1
                    or request.continuation_checkpoint_id is not None
                    or self.previous_admission_sha256 is not None
                )
            )
            or capture.task_id != request.task_id
            or capture.attempt != 1
            or capture.source_revision != request.source_revision
            or capture.to_capture().effective_base_revision != request.source_revision
        ):
            raise ValueError("interruption capture must bind the exact Coder checkout identity")
        if self.schema_version == "v1" and not self.mutation_paths:
            raise ValueError("v1 interruption requires nonempty mutation paths")
        if self.mutation_paths != tuple(sorted(set(self.mutation_paths))):
            raise ValueError("interruption mutation paths must be sorted and unique")
        if (
            self.cause == "local_execution_limit"
            and self.original_error_code is not AgentErrorCode.TIMEOUT
        ) or (
            self.cause == "provider_transient"
            and self.original_error_code.value not in TRANSIENT_CODES
        ):
            raise ValueError("interruption cause must preserve the original typed failure")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude_none=True, exclude={"receipt_sha256"}))

    def validate_integrity(self) -> None:
        try:
            type(self).model_validate(self.to_wire())
        except ValueError as error:
            raise ContinuationRejected("invalid interruption receipt structure") from error
        if self.receipt_sha256 != self.recompute_sha256():
            raise ContinuationRejected("interruption receipt digest mismatch")


class ContinuationAdmission(DomainModel):
    """One Task's replacement invocation, authorized by frozen engineering policy."""

    kind: Literal["continuation_admission"] = "continuation_admission"
    schema_version: Literal["v1", "v2"] = "v1"
    authorization_source: Literal["authorized_by_policy"] = "authorized_by_policy"
    scope: ContinuationScope
    task_id: TaskId
    interrupted_run_id: RunId
    receipt_sha256: StageSha256
    policy_sha256: StageSha256
    new_request: AgentRequest
    next_work_item_id: WorkItemId
    next_lease_id: LeaseId
    created_at: AwareDatetime
    admission_sha256: StageSha256
    interrupted_attempt: ExecutionAttempt | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_validate({**values, "admission_sha256": "0" * 64})
        return provisional.model_copy(update={"admission_sha256": provisional.recompute_sha256()})

    @model_validator(mode="after")
    def validate_replacement_identity(self) -> Self:
        request = self.new_request
        if (
            request.task_id != self.task_id
            or request.role is not AgentRole.CODER
            or request.run_id == self.interrupted_run_id
            or (
                self.schema_version == "v1"
                and (
                    request.attempt != 2
                    or request.continuation_checkpoint_id is not None
                    or self.interrupted_attempt is not None
                )
            )
            or (
                self.schema_version == "v2"
                and (
                    self.interrupted_attempt is None
                    or request.attempt != self.interrupted_attempt + 1
                )
            )
        ):
            raise ValueError(
                "continuation admission requires the exact distinct successor Coder Run"
            )
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude_none=True, exclude={"admission_sha256"}))

    def validate_integrity(self) -> None:
        try:
            type(self).model_validate(self.to_wire())
        except ValueError as error:
            raise ContinuationRejected("invalid continuation admission structure") from error
        if self.admission_sha256 != self.recompute_sha256():
            raise ContinuationRejected("continuation admission digest mismatch")
