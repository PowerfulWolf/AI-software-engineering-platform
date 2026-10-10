"""Small immutable preparation observations, never recovery authority or heartbeat."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.execution_baseline import FullGitRevision
from ai_software_engineer.domain.identity import OperationId, ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel, WirePayload
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.domain.workforce import AssignmentId, LeaseId
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.manager.dispatch import DispatchCommitId
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue.models import WorkItemId

if TYPE_CHECKING:
    from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
    from ai_software_engineer.orchestration.steps import RoleRunBoundary
    from ai_software_engineer.recovery.models import RecoveryAuthorization, RecoveryPlan
    from ai_software_engineer.recovery.records import RecoverySeedRecord, RecoveryTaskRecord
    from ai_software_engineer.web_console.models import ConsoleOperation
    from ai_software_engineer.work_queue.models import QueueClaim

_LOGGER = logging.getLogger(__name__)


class PreparationProgressScope(DomainModel):
    operation_id: OperationId = Field(pattern=r"^operation_[a-f0-9]{32}$")
    team_id: TeamId
    project_id: ProjectId
    delivery_id: DeliveryId
    expected_checkpoint_sha256: StageSha256
    approved_plan_sha256: StageSha256

    @property
    def task_id(self) -> str:
        return "task_recovery_" + self.approved_plan_sha256[:32]


class AuthorizationEvidence(DomainModel):
    authorization_sha256: StageSha256


class TaskSealedEvidence(DomainModel):
    task_id: TaskId
    task_record_sha256: StageSha256
    source_revision: FullGitRevision


class DispatchCommittedEvidence(DomainModel):
    task_id: TaskId
    dispatch_id: DispatchCommitId
    dispatch_sha256: StageSha256
    task_record_sha256: StageSha256


class SeedVerifiedEvidence(DomainModel):
    task_id: TaskId
    seed_record_sha256: StageSha256
    dispatch_sha256: StageSha256
    input_mode: Literal["preserve_draft", "coder_reapply"]


class ExecutionClaimedEvidence(DomainModel):
    task_id: TaskId
    work_item_id: WorkItemId
    lease_id: LeaseId
    assignment_id: AssignmentId
    claim_sha256: StageSha256
    dispatch_sha256: StageSha256
    source_revision: FullGitRevision
    role: Literal["coder"] = "coder"
    attempt: Literal[1] = 1


class _PreparationRecord(DomainModel):
    scope: PreparationProgressScope
    observed_at: AwareDatetime
    record_sha256: StageSha256

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"record_sha256"}))

    def validate_integrity(self) -> None:
        if self.record_sha256 != self.recompute_sha256():
            raise ValueError("preparation observation digest mismatch")


class AuthorizationRecorded(_PreparationRecord):
    kind: Literal["AUTHORIZATION_RECORDED"] = "AUTHORIZATION_RECORDED"
    evidence: AuthorizationEvidence


class TaskSealed(_PreparationRecord):
    kind: Literal["TASK_SEALED"] = "TASK_SEALED"
    evidence: TaskSealedEvidence


class DispatchCommitted(_PreparationRecord):
    kind: Literal["DISPATCH_COMMITTED"] = "DISPATCH_COMMITTED"
    evidence: DispatchCommittedEvidence


class SeedVerified(_PreparationRecord):
    kind: Literal["SEED_VERIFIED"] = "SEED_VERIFIED"
    evidence: SeedVerifiedEvidence


class ExecutionClaimed(_PreparationRecord):
    kind: Literal["EXECUTION_CLAIMED"] = "EXECUTION_CLAIMED"
    evidence: ExecutionClaimedEvidence


type PreparationRecord = Annotated[
    AuthorizationRecorded | TaskSealed | DispatchCommitted | SeedVerified | ExecutionClaimed,
    Field(discriminator="kind"),
]

PREPARATION_MILESTONES = (
    "AUTHORIZATION_RECORDED",
    "TASK_SEALED",
    "DISPATCH_COMMITTED",
    "SEED_VERIFIED",
    "EXECUTION_CLAIMED",
)


def seal_preparation_record[RecordT: _PreparationRecord](record: RecordT) -> RecordT:
    return record.model_copy(update={"record_sha256": record.recompute_sha256()})


class PreparationProgressView(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    scope: PreparationProgressScope | None
    records: tuple[PreparationRecord, ...] = Field(default=(), max_length=5)

    def to_wire(self) -> WirePayload:
        value = super().to_wire()
        if self.scope is None:
            value["scope"] = None
        return value

    @model_validator(mode="after")
    def require_exact_records(self) -> Self:
        if self.scope is None and self.records:
            raise ValueError("preparation records require an exact scope")
        if len({record.kind for record in self.records}) != len(self.records):
            raise ValueError("preparation observation kinds must be unique")
        for record in self.records:
            record.validate_integrity()
            if record.scope != self.scope:
                raise ValueError("preparation observation scope mismatch")
            if (
                not isinstance(record, AuthorizationRecorded)
                and record.evidence.task_id != record.scope.task_id
            ):
                raise ValueError("preparation observation Task mismatch")
            if isinstance(record, DispatchCommitted) and (
                record.evidence.dispatch_id
                != "dispatch_commit_" + record.scope.approved_plan_sha256
            ):
                raise ValueError("preparation observation dispatch mismatch")
        for field in ("dispatch_sha256", "task_record_sha256", "source_revision"):
            values = {
                getattr(record.evidence, field)
                for record in self.records
                if hasattr(record.evidence, field)
            }
            if len(values) > 1:
                raise ValueError("preparation observation evidence lineage mismatch")
        return self


def preparation_scope(operation: ConsoleOperation) -> PreparationProgressScope | None:
    # Keep Console composition outside the lower-level observation model graph.
    from ai_software_engineer.web_console.models import ContinueDeliveryIntent

    intent = operation.intent
    if not isinstance(intent, ContinueDeliveryIntent) or intent.approved_plan_sha256 is None:
        return None
    return PreparationProgressScope(
        operation_id=operation.operation_id,
        team_id=operation.team_id,
        project_id=intent.project_id,
        delivery_id=intent.delivery_id,
        expected_checkpoint_sha256=intent.expected_checkpoint_sha256,
        approved_plan_sha256=intent.approved_plan_sha256,
    )


type PreparationSink = Callable[[PreparationRecord], None]


@dataclass
class _Observer:
    scope: PreparationProgressScope
    sink: PreparationSink
    clock: Callable[[], datetime]
    dispatch_sha256: str | None = None
    source_revision: str | None = None


_OBSERVER: ContextVar[_Observer | None] = ContextVar("recovery_preparation_observer", default=None)


@contextmanager
def observe_recovery_preparation(
    operation: ConsoleOperation,
    sink: PreparationSink,
    *,
    clock: Callable[[], datetime] | None = None,
) -> Iterator[None]:
    """All observation setup is optional; its failure cannot replay delivery."""
    observer = None
    try:
        scope = preparation_scope(operation)
        if scope is not None:
            observer = _Observer(scope, sink, clock or (lambda: datetime.now(UTC)))
    except Exception:
        _LOGGER.error("PREPARATION_OBSERVATION_SETUP_FAILED")
    token = _OBSERVER.set(observer)
    try:
        yield
    finally:
        _OBSERVER.reset(token)


def _observe(build: Callable[[_Observer], PreparationRecord | None]) -> None:
    observer = _OBSERVER.get()
    if observer is None:
        return
    try:
        record = build(observer)
        if record is not None:
            sealed = seal_preparation_record(record)
            PreparationProgressView(scope=observer.scope, records=(sealed,))
    except Exception:
        # Even typed construction, hashing, the clock or storage may fail. None
        # changes the already completed authority/dispatch/claim boundary.
        _LOGGER.error("PREPARATION_OBSERVATION_BUILD_FAILED")
        return
    if record is not None:
        try:
            observer.sink(sealed)
        except Exception:
            _LOGGER.error("PREPARATION_OBSERVATION_STORE_FAILED")


def _matches_plan(observer: _Observer, plan: RecoveryPlan) -> bool:
    source = plan.source
    snapshot = plan.workspace_snapshot
    return (
        plan.plan_sha256 == observer.scope.approved_plan_sha256
        and source.scope.team_id == observer.scope.team_id
        and (source.parent_delivery_id or source.scope.delivery_id) == observer.scope.delivery_id
        and (source.parent_checkpoint_sha256 or source.checkpoint_sha256)
        == observer.scope.expected_checkpoint_sha256
        and (snapshot is None or snapshot.scope.project_id == observer.scope.project_id)
    )


def record_authorization(plan: RecoveryPlan, authorization: RecoveryAuthorization) -> None:
    def build(observer: _Observer) -> PreparationRecord | None:
        if (
            not _matches_plan(observer, plan)
            or authorization.command.plan_sha256 != plan.plan_sha256
            or not authorization.decision.approved
        ):
            return None
        return AuthorizationRecorded(
            scope=observer.scope,
            observed_at=observer.clock(),
            evidence=AuthorizationEvidence(authorization_sha256=authorization.authorization_sha256),
            record_sha256="0" * 64,
        )

    _observe(build)


def record_task_sealed(plan: RecoveryPlan, sealed: RecoveryTaskRecord) -> None:
    def build(observer: _Observer) -> PreparationRecord | None:
        if (
            not _matches_plan(observer, plan)
            or sealed.recovery_plan_sha256 != plan.plan_sha256
            or sealed.task.id != observer.scope.task_id
        ):
            return None
        observer.source_revision = sealed.task.base_ref
        return TaskSealed(
            scope=observer.scope,
            observed_at=observer.clock(),
            evidence=TaskSealedEvidence(
                task_id=sealed.task.id,
                task_record_sha256=sealed.record_sha256,
                source_revision=sealed.task.base_ref,
            ),
            record_sha256="0" * 64,
        )

    _observe(build)


def record_dispatch_committed(plan: RecoveryPlan, dispatch: RecoveryDispatchRecord) -> None:
    def build(observer: _Observer) -> PreparationRecord | None:
        if (
            not _matches_plan(observer, plan)
            or dispatch.recovery_plan_sha256 != plan.plan_sha256
            or dispatch.task_id != observer.scope.task_id
        ):
            return None
        observer.dispatch_sha256 = dispatch.dispatch_sha256
        observer.source_revision = dispatch.task.base_ref
        return DispatchCommitted(
            scope=observer.scope,
            observed_at=observer.clock(),
            evidence=DispatchCommittedEvidence(
                task_id=dispatch.task_id,
                dispatch_id=dispatch.id,
                dispatch_sha256=dispatch.dispatch_sha256,
                task_record_sha256=dispatch.recovery_task_record_sha256,
            ),
            record_sha256="0" * 64,
        )

    _observe(build)


def record_seed_verified(plan: RecoveryPlan, seed: RecoverySeedRecord, task_id: str) -> None:
    def build(observer: _Observer) -> PreparationRecord | None:
        if (
            not _matches_plan(observer, plan)
            or seed.recovery_plan_sha256 != plan.plan_sha256
            or task_id != observer.scope.task_id
            or seed.dispatch_sha256 != observer.dispatch_sha256
        ):
            return None
        return SeedVerified(
            scope=observer.scope,
            observed_at=observer.clock(),
            evidence=SeedVerifiedEvidence(
                task_id=task_id,
                seed_record_sha256=seed.record_sha256,
                dispatch_sha256=seed.dispatch_sha256,
                input_mode=plan.input_mode or "preserve_draft",
            ),
            record_sha256="0" * 64,
        )

    _observe(build)


def record_execution_claimed(
    claim: QueueClaim, boundary: RoleRunBoundary, allocation_sha256: str
) -> None:
    def build(observer: _Observer) -> PreparationRecord | None:
        item = claim.work_item
        if (
            item.task_id != observer.scope.task_id
            or item.role is not AgentRole.CODER
            or item.attempt != 1
            or item.parent_work_item_id is not None
            or allocation_sha256 != observer.dispatch_sha256
            or boundary.source_revision != observer.source_revision
            or (boundary.task_id, boundary.role, boundary.attempt, boundary.checkpoint_sequence)
            != (item.task_id, item.role, item.attempt, item.checkpoint_sequence)
        ):
            return None
        return ExecutionClaimed(
            scope=observer.scope,
            observed_at=observer.clock(),
            evidence=ExecutionClaimedEvidence(
                task_id=item.task_id,
                work_item_id=item.id,
                lease_id=claim.lease.id,
                assignment_id=claim.assignment.id,
                claim_sha256=digest(claim.to_wire()),
                dispatch_sha256=allocation_sha256,
                source_revision=boundary.source_revision,
            ),
            record_sha256="0" * 64,
        )

    _observe(build)
