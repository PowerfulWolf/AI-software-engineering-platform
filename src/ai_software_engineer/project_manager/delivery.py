"""Unified Project Manager entry point for one resumable serial delivery."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Protocol

from pydantic import AwareDatetime, Field, StringConstraints, field_validator

from ai_software_engineer.design import DesignerServiceResult
from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.orchestration.retry import (
    BlockedResult,
    RetryDeliveryResult,
    RetryResult,
)
from ai_software_engineer.planning import PlanningStageResult
from ai_software_engineer.product import ProductDiscoveryOutcome, ProductDiscoveryResult
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryId,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
    ProjectDeliveryCheckpointConflict,
    ProjectDeliveryCheckpointNotFound,
    ProjectDeliveryIntake,
)
from ai_software_engineer.project_manager.dispatch import DispatchCommitRecord
from ai_software_engineer.project_manager.preparation import (
    PrepareProjectResult,
    PrepareProjectStatus,
)

CheckpointDigest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class UnifiedProjectEntryError(RuntimeError):
    """Base error exposed by the Project Manager delivery facade."""


class DeliveryCheckpointStale(UnifiedProjectEntryError):
    """A human command references a checkpoint that is no longer current."""


class DeliveryCommandRejected(UnifiedProjectEntryError):
    """A command is not valid for the current delivery stage."""


class DeliveryCatalogError(UnifiedProjectEntryError):
    """The external project workspace catalog is missing, unsafe, or ambiguous."""


class DeliveryBackendFailure(UnifiedProjectEntryError):
    """Expected native-stage failure already classified by the application backend."""

    def __init__(self, code: DeliveryFailureCode, safe_summary: str) -> None:
        if (
            not safe_summary
            or len(safe_summary) > 500
            or any(ord(character) < 32 and character not in "\t\n" for character in safe_summary)
        ):
            raise ValueError("backend failure summary is not safe for a checkpoint")
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary


class StartProjectDelivery(DomainModel):
    project_root: NonEmptyStr
    requirement: NonEmptyStr
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)] = (
        "Software delivery request"
    )
    submitted_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("project_root")
    @classmethod
    def require_absolute_project_root(cls, value: str) -> str:
        if not Path(value).is_absolute() or any(ord(character) < 32 for character in value):
            raise ValueError("project_root must be absolute and contain no controls")
        return value


class ReplyToProduct(DomainModel):
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest
    message: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
    submitted_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class ApproveProductSpec(DomainModel):
    delivery_id: DeliveryId
    expected_checkpoint_sha256: CheckpointDigest
    approval_reference: NonEmptyStr
    submitted_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class ResumeProjectDelivery(DomainModel):
    delivery_id: DeliveryId
    submitted_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectDeliveryResult(DomainModel):
    """Current user-visible cursor plus optional Product review material."""

    checkpoint: ProjectDeliveryCheckpoint
    product: ProductDiscoveryResult | None = None
    delivery: RetryResult | None = None


class ProjectDeliveryBackend(Protocol):
    """Native services composed behind the Project Manager Agent Skill facade.

    Implementations own adapters, stores, workforce policy, and Runtime paths.  None of
    those implementation details become CLI arguments.
    """

    def prepare(self, project_root: str) -> PrepareProjectResult: ...

    def start_product(
        self,
        delivery_id: DeliveryId,
        preparation: PrepareProjectResult,
        command: StartProjectDelivery,
    ) -> ProductDiscoveryResult: ...

    def reply_product(
        self,
        checkpoint: ProjectDeliveryCheckpoint,
        command: ReplyToProduct,
    ) -> ProductDiscoveryResult: ...

    def approve_product(
        self,
        checkpoint: ProjectDeliveryCheckpoint,
        command: ApproveProductSpec,
    ) -> ProductDiscoveryResult: ...

    def run_designer(self, checkpoint: ProjectDeliveryCheckpoint) -> DesignerServiceResult: ...

    def run_planner(self, checkpoint: ProjectDeliveryCheckpoint) -> PlanningStageResult: ...

    def commit_dispatch(self, checkpoint: ProjectDeliveryCheckpoint) -> DispatchCommitRecord: ...

    def run_delivery(self, checkpoint: ProjectDeliveryCheckpoint) -> RetryResult: ...

    def reconcile(self, checkpoint: ProjectDeliveryCheckpoint) -> None: ...


class ProjectDeliveryCheckpointCatalog:
    """Find per-project checkpoint journals without a mutable global database."""

    def __init__(self, project_registry_root: str | Path) -> None:
        configured = Path(project_registry_root).expanduser()
        if configured.is_symlink():
            raise DeliveryCatalogError("project registry root cannot be a symlink")
        self._root = configured.resolve(strict=False)
        self._root.mkdir(parents=True, exist_ok=True)

    def for_project(self, project_id: ProjectId | str) -> FileProjectDeliveryCheckpointStore:
        sidecar = self._root / str(project_id)
        if sidecar.is_symlink() or not sidecar.is_dir():
            raise DeliveryCatalogError(f"project sidecar is missing: {project_id}")
        state = sidecar / "state"
        if state.is_symlink() or not state.is_dir():
            raise DeliveryCatalogError(f"project state root is missing: {project_id}")
        return FileProjectDeliveryCheckpointStore(state / "project-deliveries")

    def for_delivery(self, delivery_id: DeliveryId | str) -> FileProjectDeliveryCheckpointStore:
        matches: list[FileProjectDeliveryCheckpointStore] = []
        for sidecar in sorted(self._root.iterdir()):
            if sidecar.is_symlink() or not sidecar.is_dir():
                continue
            state = sidecar / "state"
            delivery = state / "project-deliveries" / str(delivery_id)
            if delivery.is_dir() and not delivery.is_symlink():
                matches.append(FileProjectDeliveryCheckpointStore(state / "project-deliveries"))
        if not matches:
            raise ProjectDeliveryCheckpointNotFound(str(delivery_id))
        if len(matches) != 1:
            raise DeliveryCatalogError(f"delivery ID is ambiguous: {delivery_id}")
        return matches[0]


class UnifiedProjectEntryService:
    """Drive prepare → Product gate → Design → Plan → Dispatch → Delivery."""

    def __init__(
        self,
        *,
        backend: ProjectDeliveryBackend,
        catalog: ProjectDeliveryCheckpointCatalog,
    ) -> None:
        self._backend = backend
        self._catalog = catalog

    def start(self, command: StartProjectDelivery) -> ProjectDeliveryResult:
        delivery_id = _delivery_id(command.project_root, command.requirement)
        preparation = self._backend.prepare(command.project_root)
        store = self._catalog.for_project(preparation.project_id)
        try:
            current = store.current(delivery_id)
        except ProjectDeliveryCheckpointNotFound:
            current = None
        if current is not None:
            if current.project_root != str(Path(command.project_root).resolve()):
                raise ProjectDeliveryCheckpointConflict("delivery ID belongs to another project")
            intake = store.get_intake(delivery_id)
            self._require_same_intake(intake, command)
            command = self._start_command(intake)
            self._backend.reconcile(current)
            if current.stage not in {
                DeliveryStage.PREPARING,
                DeliveryStage.PRODUCT_DISCOVERY,
            }:
                return ProjectDeliveryResult(checkpoint=current)

        attempts = DeliveryStageAttempts(preparing=1)
        first = current
        if first is None:
            try:
                intake = store.get_intake(delivery_id)
                self._require_same_intake(intake, command)
                if intake.project_id != preparation.project_id:
                    raise ProjectDeliveryCheckpointConflict(
                        "delivery intake belongs to another project"
                    )
            except ProjectDeliveryCheckpointNotFound:
                intake = store.put_intake(
                    ProjectDeliveryIntake.create(
                        delivery_id=delivery_id,
                        project_id=preparation.project_id,
                        project_root=str(Path(command.project_root).resolve()),
                        title=command.title,
                        requirement=command.requirement,
                        submitted_at=command.submitted_at,
                    )
                )
            command = self._start_command(intake)
            first = self._append(
                store,
                delivery_id=delivery_id,
                project_id=preparation.project_id,
                project_root=str(Path(command.project_root).resolve()),
                stage=DeliveryStage.PREPARING,
                attempts=attempts,
                next_action=DeliveryNextAction.PREPARE_PROJECT,
                at=command.submitted_at,
                preparation_sha256=(
                    preparation.preparation.preparation_sha256
                    if preparation.preparation is not None
                    else None
                ),
            )
        if preparation.status is PrepareProjectStatus.WAITING_HUMAN:
            blocked = self._next(
                store,
                first,
                stage=DeliveryStage.WAITING_HUMAN,
                next_action=DeliveryNextAction.REQUEST_HUMAN,
                failure_code=DeliveryFailureCode.PROJECT_SPEC_CONFLICT,
                failure_summary="project and organization rules require a human decision",
                at=command.submitted_at,
            )
            return ProjectDeliveryResult(checkpoint=blocked)
        if preparation.preparation is None:
            raise UnifiedProjectEntryError("PREPARED result has no ProjectPreparation")
        prepared = first
        if prepared.stage is DeliveryStage.PREPARING:
            prepared = self._next(
                store,
                first,
                stage=DeliveryStage.PRODUCT_DISCOVERY,
                next_action=DeliveryNextAction.CONTINUE_PRODUCT_DISCOVERY,
                preparation_sha256=preparation.preparation.preparation_sha256,
                attempts=first.stage_attempts.increment(DeliveryStage.PRODUCT_DISCOVERY),
                at=command.submitted_at,
            )
        try:
            product = self._backend.start_product(delivery_id, preparation, command)
        except DeliveryBackendFailure as error:
            return self._stage_failure(
                store,
                prepared,
                error.code,
                error.safe_summary,
                command.submitted_at,
            )
        return self._checkpoint_product(store, prepared, product, at=command.submitted_at)

    def reply(self, command: ReplyToProduct) -> ProjectDeliveryResult:
        store, current = self._current(command.delivery_id)
        self._require_expected(current, command.expected_checkpoint_sha256)
        if current.stage is not DeliveryStage.WAITING_PRODUCT_REPLY:
            raise DeliveryCommandRejected("reply requires WAITING_PRODUCT_REPLY")
        self._backend.reconcile(current)
        try:
            product = self._backend.reply_product(current, command)
        except DeliveryBackendFailure as error:
            return self._stage_failure(
                store,
                current,
                error.code,
                error.safe_summary,
                command.submitted_at,
            )
        return self._checkpoint_product(store, current, product, at=command.submitted_at)

    def approve(self, command: ApproveProductSpec) -> ProjectDeliveryResult:
        store, current = self._current(command.delivery_id)
        self._require_expected(current, command.expected_checkpoint_sha256)
        if current.stage is not DeliveryStage.WAITING_PRODUCT_APPROVAL:
            raise DeliveryCommandRejected("approve requires WAITING_PRODUCT_APPROVAL")
        self._backend.reconcile(current)
        try:
            product = self._backend.approve_product(current, command)
        except DeliveryBackendFailure as error:
            return self._stage_failure(
                store,
                current,
                error.code,
                error.safe_summary,
                command.submitted_at,
            )
        if product.outcome is not ProductDiscoveryOutcome.APPROVED or product.approval is None:
            raise UnifiedProjectEntryError("Product approval did not produce an approved fact")
        current = self._next(
            store,
            current,
            stage=DeliveryStage.DESIGNING,
            next_action=DeliveryNextAction.RUN_DESIGNER,
            product=product,
            at=command.submitted_at,
        )
        return self._continue_after_product(store, current, product, at=command.submitted_at)

    def resume(self, command: ResumeProjectDelivery) -> ProjectDeliveryResult:
        store, current = self._current(command.delivery_id)
        self._backend.reconcile(current)
        if current.stage in {
            DeliveryStage.WAITING_PRODUCT_REPLY,
            DeliveryStage.WAITING_PRODUCT_APPROVAL,
            DeliveryStage.WAITING_HUMAN,
            DeliveryStage.BLOCKED,
            DeliveryStage.FAILED,
            DeliveryStage.DONE,
        }:
            return ProjectDeliveryResult(checkpoint=current)
        if current.stage in {DeliveryStage.PREPARING, DeliveryStage.PRODUCT_DISCOVERY}:
            intake = store.get_intake(command.delivery_id)
            preparation = self._backend.prepare(intake.project_root)
            if preparation.project_id != current.project_id:
                raise DeliveryCheckpointStale("prepared project no longer matches delivery intake")
            if preparation.status is PrepareProjectStatus.WAITING_HUMAN:
                return self._stage_failure(
                    store,
                    current,
                    DeliveryFailureCode.PROJECT_SPEC_CONFLICT,
                    "project and organization rules require a human decision",
                    command.submitted_at,
                )
            if preparation.preparation is None:
                raise UnifiedProjectEntryError("PREPARED result has no ProjectPreparation")
            if current.stage is DeliveryStage.PREPARING:
                current = self._next(
                    store,
                    current,
                    stage=DeliveryStage.PRODUCT_DISCOVERY,
                    next_action=DeliveryNextAction.CONTINUE_PRODUCT_DISCOVERY,
                    preparation_sha256=preparation.preparation.preparation_sha256,
                    attempts=current.stage_attempts.increment(DeliveryStage.PRODUCT_DISCOVERY),
                    at=command.submitted_at,
                )
            try:
                product = self._backend.start_product(
                    command.delivery_id,
                    preparation,
                    self._start_command(intake),
                )
            except DeliveryBackendFailure as error:
                return self._stage_failure(
                    store,
                    current,
                    error.code,
                    error.safe_summary,
                    command.submitted_at,
                )
            return self._checkpoint_product(store, current, product, at=command.submitted_at)
        if current.stage is DeliveryStage.DESIGNING:
            return self._continue_after_product(store, current, None, at=command.submitted_at)
        if current.stage is DeliveryStage.PLANNING:
            return self._continue_after_design(store, current, at=command.submitted_at)
        if current.stage is DeliveryStage.DISPATCHING:
            return self._continue_after_plan(store, current, at=command.submitted_at)
        if current.stage is DeliveryStage.DELIVERING:
            return self._continue_delivery(store, current, at=command.submitted_at)
        raise DeliveryCommandRejected(f"stage {current.stage.value} cannot be resumed")

    def status(self, delivery_id: DeliveryId | str) -> ProjectDeliveryResult:
        _, current = self._current(delivery_id)
        self._backend.reconcile(current)
        return ProjectDeliveryResult(checkpoint=current)

    def _continue_after_product(
        self,
        store: FileProjectDeliveryCheckpointStore,
        current: ProjectDeliveryCheckpoint,
        product: ProductDiscoveryResult | None,
        *,
        at: datetime,
    ) -> ProjectDeliveryResult:
        try:
            designed = self._backend.run_designer(current)
        except DeliveryBackendFailure as error:
            return self._stage_failure(store, current, error.code, error.safe_summary, at)
        if designed.checkpoint is None or designed.technical_design is None:
            return self._stage_failure(
                store,
                current,
                DeliveryFailureCode.INVALID_AGENT_OUTPUT,
                "Designer did not publish a verified planning handoff",
                at,
            )
        current = self._next(
            store,
            current,
            stage=DeliveryStage.PLANNING,
            next_action=DeliveryNextAction.RUN_PLANNER,
            technical_design_id=designed.technical_design.id,
            technical_design_sha256=designed.technical_design.technical_design_sha256,
            attempts=current.stage_attempts.increment(DeliveryStage.DESIGNING),
            at=at,
        )
        return self._continue_after_design(store, current, product=product, at=at)

    def _continue_after_design(
        self,
        store: FileProjectDeliveryCheckpointStore,
        current: ProjectDeliveryCheckpoint,
        product: ProductDiscoveryResult | None = None,
        *,
        at: datetime,
    ) -> ProjectDeliveryResult:
        try:
            planned = self._backend.run_planner(current)
        except DeliveryBackendFailure as error:
            return self._stage_failure(store, current, error.code, error.safe_summary, at)
        current = self._next(
            store,
            current,
            stage=DeliveryStage.DISPATCHING,
            next_action=DeliveryNextAction.COMMIT_DISPATCH,
            request_revision=planned.ready_request_revision.revision,
            execution_plan_id=planned.execution_plan.id,
            execution_plan_sha256=planned.execution_plan.execution_plan_sha256,
            attempts=current.stage_attempts.increment(DeliveryStage.PLANNING),
            at=at,
        )
        return self._continue_after_plan(store, current, product=product, at=at)

    def _continue_after_plan(
        self,
        store: FileProjectDeliveryCheckpointStore,
        current: ProjectDeliveryCheckpoint,
        product: ProductDiscoveryResult | None = None,
        *,
        at: datetime,
    ) -> ProjectDeliveryResult:
        try:
            dispatch = self._backend.commit_dispatch(current)
        except DeliveryBackendFailure as error:
            return self._stage_failure(store, current, error.code, error.safe_summary, at)
        current = self._next(
            store,
            current,
            stage=DeliveryStage.DELIVERING,
            next_action=DeliveryNextAction.RUN_DELIVERY,
            planning_preview_id=dispatch.planning_preview_id,
            planning_preview_sha256=dispatch.planning_preview_sha256,
            dispatch_commit_id=dispatch.id,
            dispatch_commit_sha256=dispatch.dispatch_sha256,
            task_id=dispatch.task_id,
            task_revision=0,
            task_status=TaskStatus.NEW,
            attempts=current.stage_attempts.increment(DeliveryStage.DISPATCHING),
            at=at,
        )
        return self._continue_delivery(store, current, product=product, at=at)

    def _continue_delivery(
        self,
        store: FileProjectDeliveryCheckpointStore,
        current: ProjectDeliveryCheckpoint,
        product: ProductDiscoveryResult | None = None,
        *,
        at: datetime,
    ) -> ProjectDeliveryResult:
        try:
            delivery = self._backend.run_delivery(current)
        except DeliveryBackendFailure as error:
            return self._stage_failure(store, current, error.code, error.safe_summary, at)
        attempts = current.stage_attempts.increment(DeliveryStage.DELIVERING)
        if isinstance(delivery, BlockedResult):
            checkpoint = self._next(
                store,
                current,
                stage=DeliveryStage.BLOCKED,
                next_action=DeliveryNextAction.REQUEST_HUMAN,
                task_revision=len(delivery.event_ids),
                task_status=delivery.task.status,
                attempts=attempts,
                failure_code=DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED,
                failure_summary=delivery.reason,
                at=at,
            )
            return ProjectDeliveryResult(
                checkpoint=checkpoint,
                product=product,
                delivery=delivery,
            )
        assert isinstance(delivery, RetryDeliveryResult)
        checkpoint = self._next(
            store,
            current,
            stage=DeliveryStage.DONE,
            next_action=DeliveryNextAction.NONE,
            task_revision=len(delivery.event_ids),
            task_status=delivery.task.status,
            candidate_revision=delivery.candidate_revision,
            attempts=attempts,
            at=at,
        )
        return ProjectDeliveryResult(
            checkpoint=checkpoint,
            product=product,
            delivery=delivery,
        )

    def _checkpoint_product(
        self,
        store: FileProjectDeliveryCheckpointStore,
        current: ProjectDeliveryCheckpoint,
        product: ProductDiscoveryResult,
        *,
        at: datetime,
    ) -> ProjectDeliveryResult:
        outcomes = {
            ProductDiscoveryOutcome.CLARIFICATION_REQUIRED: (
                DeliveryStage.WAITING_PRODUCT_REPLY,
                DeliveryNextAction.RECORD_PRODUCT_REPLY,
            ),
            ProductDiscoveryOutcome.READY_FOR_APPROVAL: (
                DeliveryStage.WAITING_PRODUCT_APPROVAL,
                DeliveryNextAction.APPROVE_PRODUCT_SPEC,
            ),
        }
        selected = outcomes.get(product.outcome)
        if selected is None:
            code = (
                DeliveryFailureCode.TRANSIENT_PROVIDER_FAILURE
                if product.outcome
                in {
                    ProductDiscoveryOutcome.AGENT_FAILED,
                    ProductDiscoveryOutcome.AGENT_TIMED_OUT,
                }
                else DeliveryFailureCode.INVALID_AGENT_OUTPUT
            )
            return self._stage_failure(
                store,
                current,
                code,
                f"Product stage stopped with {product.outcome.value}",
                at,
                product=product,
            )
        checkpoint = self._next(
            store,
            current,
            stage=selected[0],
            next_action=selected[1],
            product=product,
            at=at,
        )
        return ProjectDeliveryResult(checkpoint=checkpoint, product=product)

    def _stage_failure(
        self,
        store: FileProjectDeliveryCheckpointStore,
        current: ProjectDeliveryCheckpoint,
        code: DeliveryFailureCode,
        summary: str,
        at: datetime,
        *,
        product: ProductDiscoveryResult | None = None,
    ) -> ProjectDeliveryResult:
        checkpoint = self._next(
            store,
            current,
            stage=DeliveryStage.BLOCKED,
            next_action=DeliveryNextAction.REQUEST_HUMAN,
            failure_code=code,
            failure_summary=summary,
            product=product,
            at=at,
        )
        return ProjectDeliveryResult(checkpoint=checkpoint, product=product)

    def _current(
        self, delivery_id: DeliveryId | str
    ) -> tuple[FileProjectDeliveryCheckpointStore, ProjectDeliveryCheckpoint]:
        store = self._catalog.for_delivery(delivery_id)
        return store, store.current(delivery_id)

    @staticmethod
    def _require_expected(current: ProjectDeliveryCheckpoint, digest: str) -> None:
        if current.checkpoint_sha256 != digest:
            raise DeliveryCheckpointStale("command does not reference the current checkpoint")

    @staticmethod
    def _require_same_intake(intake: ProjectDeliveryIntake, command: StartProjectDelivery) -> None:
        if (
            intake.project_root != str(Path(command.project_root).resolve())
            or intake.requirement != command.requirement
            or intake.title != command.title
        ):
            raise ProjectDeliveryCheckpointConflict(
                "delivery ID was started with different business input"
            )

    @staticmethod
    def _start_command(intake: ProjectDeliveryIntake) -> StartProjectDelivery:
        return StartProjectDelivery(
            project_root=intake.project_root,
            requirement=intake.requirement,
            title=intake.title,
            submitted_at=intake.submitted_at,
        )

    @staticmethod
    def _append(
        store: FileProjectDeliveryCheckpointStore,
        *,
        delivery_id: DeliveryId,
        project_id: ProjectId,
        project_root: str,
        stage: DeliveryStage,
        attempts: DeliveryStageAttempts,
        next_action: DeliveryNextAction,
        at: datetime,
        **updates: object,
    ) -> ProjectDeliveryCheckpoint:
        checkpoint = ProjectDeliveryCheckpoint.create(
            delivery_id=delivery_id,
            sequence=1,
            project_id=project_id,
            project_root=project_root,
            stage=stage,
            stage_attempts=attempts,
            next_action=next_action,
            checkpointed_at=at,
            **updates,
        )
        return store.put(checkpoint)

    @staticmethod
    def _next(
        store: FileProjectDeliveryCheckpointStore,
        current: ProjectDeliveryCheckpoint,
        *,
        stage: DeliveryStage,
        next_action: DeliveryNextAction,
        at: datetime,
        attempts: DeliveryStageAttempts | None = None,
        product: ProductDiscoveryResult | None = None,
        **updates: object,
    ) -> ProjectDeliveryCheckpoint:
        inherited: dict[str, object] = dict(current.to_wire())
        for key in (
            "kind",
            "schema_version",
            "sequence",
            "previous_checkpoint_sha256",
            "stage",
            "stage_attempts",
            "next_action",
            "failure_code",
            "failure_summary",
            "checkpointed_at",
            "checkpoint_sha256",
        ):
            inherited.pop(key, None)
        if product is not None:
            inherited.update(
                {
                    "request_id": product.checkpoint.request_id,
                    "request_revision": product.request_revision.revision,
                    "product_checkpoint_sha256": product.checkpoint.checkpoint_sha256,
                }
            )
            if product.product_spec is not None:
                inherited.update(
                    {
                        "product_spec_id": product.product_spec.id,
                        "product_spec_sha256": product.product_spec.product_spec_sha256,
                    }
                )
            if product.approval is not None:
                inherited.update(
                    {
                        "approval_id": product.approval.id,
                        "approval_sha256": product.approval.approval_sha256,
                    }
                )
        inherited.update(updates)
        checkpoint = ProjectDeliveryCheckpoint.create(
            **inherited,
            sequence=current.sequence + 1,
            previous_checkpoint_sha256=current.checkpoint_sha256,
            stage=stage,
            stage_attempts=attempts or current.stage_attempts,
            next_action=next_action,
            checkpointed_at=at,
        )
        return store.put(checkpoint)


def _delivery_id(project_root: str, requirement: str) -> DeliveryId:
    canonical = json.dumps(
        {
            "project_root": str(Path(project_root).resolve()),
            "requirement": requirement,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"delivery_{hashlib.sha256(canonical.encode()).hexdigest()[:32]}"


__all__ = [
    "ApproveProductSpec",
    "DeliveryBackendFailure",
    "DeliveryCatalogError",
    "DeliveryCheckpointStale",
    "DeliveryCommandRejected",
    "ProjectDeliveryBackend",
    "ProjectDeliveryCheckpointCatalog",
    "ProjectDeliveryResult",
    "ReplyToProduct",
    "ResumeProjectDelivery",
    "StartProjectDelivery",
    "UnifiedProjectEntryError",
    "UnifiedProjectEntryService",
]
