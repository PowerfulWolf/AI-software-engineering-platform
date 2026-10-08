"""Exact baseline plans, source snapshots and real engineering decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, Field, StrictBool, model_validator

from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.artifact import ArtifactId, Sha256
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import (
    EngineeringScope,
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.execution_baseline import (
    BaselineInputMode,
    BaselinePurpose,
    ExecutionBaselineBinding,
    FullGitRevision,
)
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure, ExecutionAttempt
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git.mutation import WorkspaceMutationInventory
from ai_software_engineer.manager.legacy_containment import LegacyExecutionContainment
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.recovery.models import digest


class BaselineExecutionReservation(DomainModel):
    """Exact current-call accounting, consumed only by the fenced queue service."""

    current_attempt: ExecutionAttempt
    next_execution_attempt: ExecutionAttempt
    retry_cause: Literal[
        "uninvoked", "local_execution_limit", "provider_transient", "legacy_execution_abandoned"
    ]
    containment_sha256: Sha256 | None = Field(default=None, exclude_if=lambda value: value is None)
    original_run_id: RunId | None = None
    current_invocation_start_sha256: Sha256 | None = None
    current_invocation_outcome_sha256: Sha256 | None = None
    interruption_receipt_sha256: Sha256 | None = None
    retry_failure: DeliveryRetryFailure | None = None
    reservation_already_applied: StrictBool = False

    @model_validator(mode="after")
    def validate_reservation(self) -> Self:
        if self.retry_cause == "uninvoked":
            if (
                any(
                    value is not None
                    for value in (
                        self.original_run_id,
                        self.current_invocation_start_sha256,
                        self.current_invocation_outcome_sha256,
                        self.interruption_receipt_sha256,
                        self.retry_failure,
                        self.containment_sha256,
                    )
                )
                or self.next_execution_attempt != self.current_attempt
            ):
                raise ValueError("uninvoked baseline cannot invent an original call or a retry")
        elif self.retry_cause == "legacy_execution_abandoned":
            if (
                self.original_run_id is None
                or self.current_invocation_start_sha256 is None
                or self.containment_sha256 is None
                or self.next_execution_attempt != self.current_attempt + 1
                or self.current_invocation_outcome_sha256 is not None
                or self.interruption_receipt_sha256 is not None
                or self.retry_failure is not None
                or self.reservation_already_applied
            ):
                raise ValueError(
                    "legacy disposition must consume new work without invented results"
                )
        elif (
            self.original_run_id is None
            or self.current_invocation_start_sha256 is None
            or self.next_execution_attempt != self.current_attempt + 1
            or (
                self.current_invocation_outcome_sha256 is None
                and self.interruption_receipt_sha256 is None
            )
            or (self.retry_cause == "provider_transient") != (self.retry_failure is not None)
            or self.containment_sha256 is not None
        ):
            raise ValueError("baseline retry must bind its exact original invocation and successor")
        if self.retry_failure is not None and (
            self.retry_failure.attempt != self.current_attempt
            or self.retry_failure.run_id != self.original_run_id
        ):
            raise ValueError("baseline provider debit differs from the original execution")
        return self


class BaselineExecutionFacts(DomainModel):
    """Trusted collector output, never accepted from an API/model request body."""

    task: Task
    scope: EngineeringScope
    task_revision: int = Field(ge=1)
    work_item_id: NonEmptyStr
    checkpoint_sequence: int = Field(ge=0)
    quiescence_proof_sha256: Sha256
    runtime_manifest_sha256: Sha256
    source_native_rules_sha256: Sha256
    target_native_rules_sha256: Sha256
    source_artifact_ids: tuple[ArtifactId, ...]
    implementation_artifact_id: ArtifactId | None = None
    progress_artifact_id: ArtifactId | None = None
    resolved_interruption_receipt_sha256s: tuple[Sha256, ...] = ()
    continuation: BaselineExecutionReservation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    legacy_containment: LegacyExecutionContainment | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    permissions: AgentPermissions
    denied_paths: tuple[NonEmptyStr, ...]
    facts_sha256: Sha256

    @model_validator(mode="after")
    def validate_inputs(self) -> Self:
        ensure_unique(self.source_artifact_ids, "baseline source artifacts")
        ensure_unique(self.resolved_interruption_receipt_sha256s, "baseline interruption receipts")
        if self.denied_paths != (
            self.task.constraints.denied_paths if self.task.constraints is not None else ()
        ):
            raise ValueError("baseline facts changed the frozen Task deny list")
        if self.task.repository != self.scope.repository_root:
            raise ValueError("baseline facts changed repository identity")
        for identity in (self.implementation_artifact_id, self.progress_artifact_id):
            if identity is not None and identity not in self.source_artifact_ids:
                raise ValueError("baseline source artifact is absent from complete facts")
        containment, reservation = self.legacy_containment, self.continuation
        if containment is not None:
            containment.validate_integrity()
            request = containment.original_start.request
            if (
                reservation is None
                or reservation.retry_cause != "legacy_execution_abandoned"
                or reservation.containment_sha256 != containment.containment_sha256
                or reservation.original_run_id != request.run_id
                or reservation.current_invocation_start_sha256
                != containment.original_start.start_sha256
                or containment.scope != self.scope
                or containment.task_intent_sha256 != task_intent_sha256(self.task)
                or containment.original_start.work_item_id != self.work_item_id
                or containment.original_start.checkpoint_sequence != self.checkpoint_sequence
                or request.task_id != self.task.id
                or request.permissions != self.permissions
                or request.attempt != reservation.current_attempt
                or request.attempt != self.task.attempts
                or self.implementation_artifact_id is not None
                or self.source_native_rules_sha256 != self.target_native_rules_sha256
                or not set(request.input_artifact_ids).issubset(self.source_artifact_ids)
            ):
                raise ValueError("legacy facts changed exact original invocation or reservation")
        elif reservation is not None and reservation.retry_cause == "legacy_execution_abandoned":
            raise ValueError("legacy reservation requires full trusted containment facts")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.facts_sha256 != digest(self.model_dump(mode="json", exclude={"facts_sha256"})):
            raise ValueError("baseline authoritative facts changed")


class ExecutionBaselinePlan(DomainModel):
    kind: Literal["execution_baseline_plan"] = "execution_baseline_plan"
    schema_version: Literal["v1"] = "v1"
    purpose: BaselinePurpose = Field(
        default=BaselinePurpose.SOURCE_REBIND,
        exclude_if=lambda value: value is BaselinePurpose.SOURCE_REBIND,
    )
    facts: BaselineExecutionFacts
    previous_binding: ExecutionBaselineBinding | None = None
    input_mode: BaselineInputMode
    target_base_ref: FullGitRevision
    prepared_source_revision: FullGitRevision
    prepared_dirty_tree: FullGitRevision
    prepared_dirty_patch: str = Field(max_length=1_000_000)
    dirty_capture: CapturedMutations
    complete_capture: CapturedMutations
    before_inventory: WorkspaceMutationInventory
    conflicted: StrictBool = False
    plan_sha256: Sha256

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        self.facts.validate_integrity()
        CapturedMutations.model_validate(self.dirty_capture.to_wire())
        CapturedMutations.model_validate(self.complete_capture.to_wire())
        task = self.facts.task
        for capture in (self.dirty_capture, self.complete_capture):
            if capture.task_id != task.id or capture.branch_name != task.branch_name:
                raise ValueError("baseline plan changed Task or original branch")
        if (
            self.dirty_capture.source_revision != self.complete_capture.source_revision
            or self.dirty_capture.worktree_path != self.complete_capture.worktree_path
            or self.dirty_capture.base_revision is not None
        ):
            raise ValueError("baseline plan does not bind two exact source captures")
        expected_base = task.base_ref
        if self.previous_binding is not None:
            self.previous_binding.require_task(task)
            expected_base = self.previous_binding.execution_base_ref
        if self.complete_capture.base_revision != expected_base:
            raise ValueError("complete baseline capture omitted the old execution base")
        if self.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
            if (
                self.facts.legacy_containment is None
                or self.target_base_ref != expected_base
                or self.input_mode is not BaselineInputMode.PRESERVE_DRAFT
                or self.prepared_source_revision != self.dirty_capture.source_revision
                or self.dirty_capture.source_revision
                != self.facts.legacy_containment.original_start.request.source_revision
                or self.prepared_dirty_patch != self.dirty_capture.patch
                or self.conflicted
            ):
                raise ValueError("legacy rescue cannot change source, input mode or retained draft")
        elif self.target_base_ref == expected_base or self.facts.legacy_containment is not None:
            raise ValueError(
                "source rebind must select a different base without legacy containment"
            )
        if self.input_mode is BaselineInputMode.CODER_REAPPLY and (
            self.prepared_source_revision != self.target_base_ref
            or self.prepared_dirty_patch
            or self.conflicted
        ):
            raise ValueError("Coder reapply requires a clean exact target and a new plan")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.plan_sha256 != digest(self.model_dump(mode="json", exclude={"plan_sha256"})):
            raise ValueError("baseline plan integrity mismatch")

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "plan_sha256": "0" * 64})
        return value.model_copy(
            update={"plan_sha256": digest(value.model_dump(mode="json", exclude={"plan_sha256"}))}
        )


class BaselineOperatorAuthorization(DomainModel):
    kind: Literal["baseline_operator_authorization"] = "baseline_operator_authorization"
    authorization_source: Literal["engineering_operator_decision"] = "engineering_operator_decision"
    task_id: NonEmptyStr
    task_intent_sha256: Sha256
    plan_sha256: Sha256
    facts_sha256: Sha256
    principal: LocalOperatorPrincipal
    reference: NonEmptyStr = Field(max_length=2000)
    submitted_at: AwareDatetime
    confirm_legacy_containment: Literal[True] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    authorization_sha256: Sha256

    @model_validator(mode="after")
    def require_engineering(self) -> Self:
        self.principal.require_duty(OperatorDuty.ENGINEERING)
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.authorization_sha256 != digest(
            self.model_dump(mode="json", exclude={"authorization_sha256"})
        ):
            raise ValueError("baseline engineering decision changed")

    @classmethod
    def for_plan(
        cls,
        plan: ExecutionBaselinePlan,
        *,
        principal: LocalOperatorPrincipal,
        reference: str,
        submitted_at: datetime,
        confirm_legacy_containment: Literal[True] | None = None,
    ) -> Self:
        plan.validate_integrity()
        if (plan.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE) != (
            confirm_legacy_containment is True
        ):
            raise ValueError("旧执行救援需要明确确认同一本机整机重启、未迁移和可信时间依据")
        value = cls(
            task_id=plan.facts.task.id,
            task_intent_sha256=task_intent_sha256(plan.facts.task),
            plan_sha256=plan.plan_sha256,
            facts_sha256=plan.facts.facts_sha256,
            principal=principal,
            reference=reference,
            submitted_at=submitted_at,
            confirm_legacy_containment=confirm_legacy_containment,
            authorization_sha256="0" * 64,
        )
        return value.model_copy(
            update={
                "authorization_sha256": digest(
                    value.model_dump(mode="json", exclude={"authorization_sha256"})
                )
            }
        )


class BaselineOperationStart(DomainModel):
    kind: Literal["baseline_operation_start"] = "baseline_operation_start"
    plan: ExecutionBaselinePlan
    authority_source: Literal["organization_engineering_policy", "engineering_operator_decision"]
    authority_sha256: Sha256
    started_at: AwareDatetime
    start_sha256: Sha256

    def validate_integrity(self) -> None:
        self.plan.validate_integrity()
        if self.start_sha256 != digest(self.model_dump(mode="json", exclude={"start_sha256"})):
            raise ValueError("baseline operation start changed")
