"""Exact baseline plans, source snapshots and real engineering decisions."""

from __future__ import annotations

import hashlib
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
    BaselineContinuationMode,
    BaselineInputMode,
    BaselinePurpose,
    ExecutionBaselineBinding,
    FullGitRevision,
)
from ai_software_engineer.domain.execution_native_rules import NativeRuleChangePlan
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure, ExecutionAttempt
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git.mutation import WorkspaceMutationInventory
from ai_software_engineer.manager.completed_output_checkpoint import (
    CompletedCoderOutputReason,
    CompletedCoderOutputUnavailableProof,
    validate_completed_output_capture,
)
from ai_software_engineer.manager.knowledge_isolation import KnowledgePreparationIsolationProof
from ai_software_engineer.manager.legacy_containment import LegacyExecutionContainment
from ai_software_engineer.manager.rejected_candidate_output import RejectedCandidateOutputProof
from ai_software_engineer.manager.stopped_execution_checkpoint import (
    StoppedCoderExecutionProof,
    validate_stopped_coder_capture,
)
from ai_software_engineer.manager.stopped_failure_checkpoint import (
    StoppedFailureProof,
    validate_stopped_failure_capture,
)
from ai_software_engineer.manager.stopped_provider_checkpoint import (
    StoppedProviderFailureProof,
    validate_stopped_provider_capture,
)
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.recovery.models import digest


class BaselineExecutionReservation(DomainModel):
    """Exact current-call accounting, consumed only by the fenced queue service."""

    current_attempt: ExecutionAttempt
    next_execution_attempt: ExecutionAttempt
    retry_cause: Literal[
        "uninvoked",
        "knowledge_isolation",
        "local_execution_limit",
        "provider_transient",
        "service_pause",
        "legacy_execution_abandoned",
        "completed_output_unavailable",
        "completed_output_rejected",
        "rejected_candidate_output",
        "provider_prerequisite_repaired",
        "stopped_failure_retry",
        "stopped_execution_unknown",
    ]
    knowledge_isolation_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    stopped_execution_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    rejected_candidate_output_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    completed_output_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    stopped_provider_failure_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    stopped_failure_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    containment_sha256: Sha256 | None = Field(default=None, exclude_if=lambda value: value is None)
    original_run_id: RunId | None = None
    current_invocation_start_sha256: Sha256 | None = None
    current_invocation_outcome_sha256: Sha256 | None = None
    interruption_receipt_sha256: Sha256 | None = None
    retry_failure: DeliveryRetryFailure | None = None
    reservation_already_applied: StrictBool = False

    @model_validator(mode="after")
    def validate_reservation(self) -> Self:
        if (self.retry_cause == "rejected_candidate_output") != (
            self.rejected_candidate_output_sha256 is not None
        ):
            raise ValueError("候选报告拒绝证明不能混入其它工作预留")
        if (self.retry_cause == "knowledge_isolation") != (
            self.knowledge_isolation_sha256 is not None
        ):
            raise ValueError("当前知识隔离证明只能属于独立普通工作预留")
        if self.retry_cause == "knowledge_isolation":
            if (
                self.next_execution_attempt != self.current_attempt + 1
                or self.reservation_already_applied
                or any(
                    value is not None
                    for value in (
                        self.original_run_id,
                        self.current_invocation_start_sha256,
                        self.current_invocation_outcome_sha256,
                        self.interruption_receipt_sha256,
                        self.retry_failure,
                        self.containment_sha256,
                        self.completed_output_sha256,
                        self.stopped_provider_failure_sha256,
                        self.stopped_failure_sha256,
                        self.stopped_execution_sha256,
                    )
                )
            ):
                raise ValueError("当前知识隔离须消费普通工作额度, 不补造主调用或退款")
        elif self.retry_cause == "stopped_execution_unknown":
            if (
                self.original_run_id is None
                or self.current_invocation_start_sha256 is None
                or self.stopped_execution_sha256 is None
                or self.next_execution_attempt != self.current_attempt + 1
                or self.current_invocation_outcome_sha256 is not None
                or self.interruption_receipt_sha256 is not None
                or self.containment_sha256 is not None
                or self.completed_output_sha256 is not None
                or self.stopped_provider_failure_sha256 is not None
                or self.retry_failure is not None
                or self.reservation_already_applied
            ):
                raise ValueError("未知结果停止恢复必须消费普通工作额度, 不得补造结果或退款")
        elif self.retry_cause == "uninvoked":
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
                        self.completed_output_sha256,
                        self.stopped_provider_failure_sha256,
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
                or self.completed_output_sha256 is not None
            ):
                raise ValueError(
                    "legacy disposition must consume new work without invented results"
                )
        elif self.retry_cause == "rejected_candidate_output":
            if (
                self.original_run_id is None
                or self.current_invocation_start_sha256 is None
                or self.current_invocation_outcome_sha256 is None
                or self.next_execution_attempt != self.current_attempt + 1
                or self.reservation_already_applied
                or any(
                    value is not None
                    for value in (
                        self.interruption_receipt_sha256,
                        self.retry_failure,
                        self.containment_sha256,
                        self.completed_output_sha256,
                        self.stopped_provider_failure_sha256,
                        self.stopped_failure_sha256,
                        self.stopped_execution_sha256,
                        self.knowledge_isolation_sha256,
                    )
                )
            ):
                raise ValueError("候选报告恢复必须消费普通工作额度并保留精确原成功结果")
        elif self.retry_cause in {"completed_output_unavailable", "completed_output_rejected"}:
            if (
                self.original_run_id is None
                or self.current_invocation_start_sha256 is None
                or self.current_invocation_outcome_sha256 is None
                or self.completed_output_sha256 is None
                or self.next_execution_attempt != self.current_attempt + 1
                or self.interruption_receipt_sha256 is not None
                or self.containment_sha256 is not None
                or self.retry_failure is not None
                or self.reservation_already_applied
            ):
                raise ValueError("完成但结果未接纳的接续必须消费普通工作额度并保留原结果")
        elif self.retry_cause == "provider_prerequisite_repaired":
            if (
                self.original_run_id is None
                or self.current_invocation_start_sha256 is None
                or self.current_invocation_outcome_sha256 is None
                or self.stopped_provider_failure_sha256 is None
                or self.next_execution_attempt != self.current_attempt + 1
                or self.interruption_receipt_sha256 is not None
                or self.containment_sha256 is not None
                or self.completed_output_sha256 is not None
                or self.retry_failure is not None
                or self.reservation_already_applied
            ):
                raise ValueError("提供方前提修复接续必须消费普通工作额度并保留精确原失败")
        elif self.retry_cause == "stopped_failure_retry":
            if (
                self.original_run_id is None
                or self.current_invocation_start_sha256 is None
                or self.current_invocation_outcome_sha256 is None
                or self.stopped_failure_sha256 is None
                or self.next_execution_attempt != self.current_attempt + 1
                or self.interruption_receipt_sha256 is not None
                or self.containment_sha256 is not None
                or self.completed_output_sha256 is not None
                or self.retry_failure is not None
                or self.reservation_already_applied
            ):
                raise ValueError("原执行失败接续必须消费普通工作额度并保留精确原失败")
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
            or self.completed_output_sha256 is not None
        ):
            raise ValueError("baseline retry must bind its exact original invocation and successor")
        if (self.retry_cause == "stopped_failure_retry") != (
            self.stopped_failure_sha256 is not None
        ):
            raise ValueError("原执行失败证明不能混入其他执行预留")
        if (
            self.retry_cause != "provider_prerequisite_repaired"
            and self.stopped_provider_failure_sha256 is not None
        ):
            raise ValueError("提供方前提失败证明不能混入其他执行预留")
        if (self.retry_cause == "stopped_execution_unknown") != (
            self.stopped_execution_sha256 is not None
        ):
            raise ValueError("未知结果停止证明不能混入其他执行预留")
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
    native_rule_change: NativeRuleChangePlan | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    source_artifact_ids: tuple[ArtifactId, ...]
    implementation_artifact_id: ArtifactId | None = None
    progress_artifact_id: ArtifactId | None = None
    resolved_interruption_receipt_sha256s: tuple[Sha256, ...] = ()
    continuation: BaselineExecutionReservation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    knowledge_isolation: KnowledgePreparationIsolationProof | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    legacy_containment: LegacyExecutionContainment | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    stopped_execution: StoppedCoderExecutionProof | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    rejected_candidate_output: RejectedCandidateOutputProof | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    completed_output: CompletedCoderOutputUnavailableProof | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    stopped_provider_failure: StoppedProviderFailureProof | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    stopped_failure: StoppedFailureProof | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    context_capacity_receipt_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    permissions: AgentPermissions
    denied_paths: tuple[NonEmptyStr, ...]
    facts_sha256: Sha256

    @model_validator(mode="after")
    def validate_inputs(self) -> Self:
        if (
            sum(
                value is not None
                for value in (
                    self.knowledge_isolation,
                    self.rejected_candidate_output,
                    self.stopped_execution,
                    self.completed_output,
                    self.stopped_provider_failure,
                    self.stopped_failure,
                    self.legacy_containment,
                    self.context_capacity_receipt_sha256,
                )
            )
            > 1
        ):
            raise ValueError("不同执行恢复证明不能混用")
        candidate, reservation = self.rejected_candidate_output, self.continuation
        if candidate is not None:
            candidate.validate_integrity()
            request = candidate.request
            if (
                candidate.scope != self.scope
                or candidate.task.to_wire() != self.task.to_wire()
                or candidate.task_revision != self.task_revision
                or candidate.work_item_id != self.work_item_id
                or candidate.checkpoint_sequence != self.checkpoint_sequence
                or request.permissions != self.permissions
                or request.attempt != self.task.attempts
                or self.implementation_artifact_id is not None
                or self.native_rule_change is not None
                or self.source_native_rules_sha256 != self.target_native_rules_sha256
                or not set(request.input_artifact_ids).issubset(self.source_artifact_ids)
                or reservation is None
                or reservation.retry_cause != "rejected_candidate_output"
                or reservation.rejected_candidate_output_sha256 != candidate.proof_sha256
                or reservation.original_run_id != request.run_id
                or reservation.current_attempt != request.attempt
                or reservation.current_invocation_start_sha256
                != candidate.outcome.start.start_sha256
                or reservation.current_invocation_outcome_sha256 != candidate.outcome.outcome_sha256
            ):
                raise ValueError("候选报告恢复事实与原 Task、精确执行或普通工作预留不同")
        elif reservation is not None and reservation.retry_cause == "rejected_candidate_output":
            raise ValueError("候选报告恢复预留缺少完整精确候选证明")
        isolation, reservation = self.knowledge_isolation, self.continuation
        if isolation is not None:
            isolation.validate_integrity()
            if (
                isolation.scope != self.scope
                or isolation.task_id != self.task.id
                or isolation.task_intent_sha256 != task_intent_sha256(self.task)
                or isolation.task_revision != self.task_revision
                or isolation.work_item_id != self.work_item_id
                or isolation.checkpoint_sequence != self.checkpoint_sequence
                or isolation.original_claim.work_item.attempt != self.task.attempts
                or self.implementation_artifact_id is not None
                or self.native_rule_change is not None
                or self.source_native_rules_sha256 != self.target_native_rules_sha256
                or reservation is None
                or reservation.retry_cause != "knowledge_isolation"
                or reservation.current_attempt != self.task.attempts
                or reservation.knowledge_isolation_sha256 != isolation.proof_sha256
            ):
                raise ValueError("当前知识隔离未绑定原 Task、完整进度和普通工作预留")
        elif reservation is not None and reservation.retry_cause == "knowledge_isolation":
            raise ValueError("当前知识隔离预留缺少完整独立工程事实")
        stopped, reservation = self.stopped_execution, self.continuation
        if stopped is not None:
            stopped.validate_integrity()
            invocation = stopped.invocation_start
            start, request = stopped.capture_start, invocation.request
            if (
                reservation is None
                or reservation.retry_cause != "stopped_execution_unknown"
                or reservation.stopped_execution_sha256 != stopped.proof_sha256
                or reservation.original_run_id != request.run_id
                or reservation.current_invocation_start_sha256 != invocation.start_sha256
                or invocation.work_item_id != self.work_item_id
                or invocation.checkpoint_sequence != self.checkpoint_sequence
                or start.task_revision != self.task_revision
                or start.task_intent_sha256 != task_intent_sha256(self.task)
                or (start.scope.team_id, start.scope.project_id, start.scope.repository_id)
                != (self.scope.team_id, self.scope.project_id, self.scope.repository_id)
                or request.task_id != self.task.id
                or request.permissions != self.permissions
                or request.attempt != self.task.attempts
                or reservation.current_attempt != request.attempt
                or self.legacy_containment is not None
                or self.completed_output is not None
                or self.stopped_provider_failure is not None
                or self.context_capacity_receipt_sha256 is not None
                or self.implementation_artifact_id is not None
                or self.native_rule_change is not None
                or self.source_native_rules_sha256 != self.target_native_rules_sha256
                or not set(request.input_artifact_ids).issubset(self.source_artifact_ids)
            ):
                raise ValueError("未知结果停止事实未绑定精确原任务、权限和普通工作预留")
        elif reservation is not None and reservation.retry_cause == "stopped_execution_unknown":
            raise ValueError("未知结果停止预留缺少完整原执行证明")
        change = self.native_rule_change
        if change is not None:
            change.validate_integrity()
            if (
                change.source_native_rules_sha256 != self.source_native_rules_sha256
                or change.target_native_rules_sha256 != self.target_native_rules_sha256
                or change.target.scope != self.scope
                or change.target.task_id != self.task.id
                or not change.changes
                or self.legacy_containment is not None
            ):
                raise ValueError("项目规范更新未绑定当前任务和精确工程输入")
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
        if self.context_capacity_receipt_sha256 is not None and (
            reservation is None
            or reservation.retry_cause != "uninvoked"
            or reservation.current_attempt != self.task.attempts
            or not reservation.reservation_already_applied
            or self.legacy_containment is not None
            or self.completed_output is not None
            or self.stopped_provider_failure is not None
        ):
            raise ValueError("容量恢复必须绑定未调用的当前工作预留, 不退款或新增已执行身份")
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
        completion = self.completed_output
        if completion is not None:
            completion.validate_integrity()
            start, request = completion.capture_start, completion.outcome.start.request
            if (
                reservation is None
                or reservation.retry_cause != completion.reason.value
                or reservation.completed_output_sha256 != completion.proof_sha256
                or reservation.original_run_id != request.run_id
                or reservation.current_invocation_start_sha256
                != completion.outcome.start.start_sha256
                or reservation.current_invocation_outcome_sha256
                != completion.outcome.outcome_sha256
                or (start.scope.team_id, start.scope.project_id, start.scope.repository_id)
                != (self.scope.team_id, self.scope.project_id, self.scope.repository_id)
                or start.task_intent_sha256 != task_intent_sha256(self.task)
                or completion.outcome.start.work_item_id != self.work_item_id
                or completion.outcome.start.checkpoint_sequence != self.checkpoint_sequence
                or start.task_revision != self.task_revision
                or request.task_id != self.task.id
                or request.permissions != self.permissions
                or request.attempt != self.task.attempts
                or reservation.current_attempt != request.attempt
                or containment is not None
                or self.implementation_artifact_id is not None
                or not set(request.input_artifact_ids).issubset(self.source_artifact_ids)
            ):
                raise ValueError("完成但结果未接纳的事实与当前任务、权限或普通工作预留不一致")
        elif reservation is not None and reservation.retry_cause in {
            "completed_output_unavailable",
            "completed_output_rejected",
        }:
            raise ValueError("完成但结果未接纳的预留缺少完整原执行证明")
        provider = self.stopped_provider_failure
        if provider is not None:
            provider.validate_integrity()
            start, request = provider.capture_start, provider.outcome.start.request
            if (
                reservation is None
                or reservation.retry_cause != "provider_prerequisite_repaired"
                or reservation.stopped_provider_failure_sha256 != provider.proof_sha256
                or reservation.original_run_id != request.run_id
                or reservation.current_invocation_start_sha256
                != provider.outcome.start.start_sha256
                or reservation.current_invocation_outcome_sha256 != provider.outcome.outcome_sha256
                or (start.scope.team_id, start.scope.project_id, start.scope.repository_id)
                != (self.scope.team_id, self.scope.project_id, self.scope.repository_id)
                or start.task_intent_sha256 != task_intent_sha256(self.task)
                or provider.outcome.start.work_item_id != self.work_item_id
                or provider.outcome.start.checkpoint_sequence != self.checkpoint_sequence
                or start.task_revision != self.task_revision
                or request.task_id != self.task.id
                or request.permissions != self.permissions
                or request.attempt != self.task.attempts
                or reservation.current_attempt != request.attempt
                or containment is not None
                or completion is not None
                or self.implementation_artifact_id is not None
                or not set(request.input_artifact_ids).issubset(self.source_artifact_ids)
            ):
                raise ValueError("提供方前提失败事实与当前任务、原执行、权限或普通工作预留不一致")
        elif (
            reservation is not None and reservation.retry_cause == "provider_prerequisite_repaired"
        ):
            raise ValueError("提供方前提失败预留缺少完整原执行证明")
        failure = self.stopped_failure
        if failure is not None:
            failure.validate_integrity()
            start, request = failure.capture_start, failure.outcome.start.request
            if (
                reservation is None
                or reservation.retry_cause != "stopped_failure_retry"
                or reservation.stopped_failure_sha256 != failure.proof_sha256
                or reservation.original_run_id != request.run_id
                or reservation.current_invocation_start_sha256 != failure.outcome.start.start_sha256
                or reservation.current_invocation_outcome_sha256 != failure.outcome.outcome_sha256
                or (start.scope.team_id, start.scope.project_id, start.scope.repository_id)
                != (self.scope.team_id, self.scope.project_id, self.scope.repository_id)
                or start.task_intent_sha256 != task_intent_sha256(self.task)
                or failure.outcome.start.work_item_id != self.work_item_id
                or failure.outcome.start.checkpoint_sequence != self.checkpoint_sequence
                or start.task_revision != self.task_revision
                or request.task_id != self.task.id
                or request.permissions != self.permissions
                or request.attempt != self.task.attempts
                or reservation.current_attempt != request.attempt
                or containment is not None
                or completion is not None
                or self.implementation_artifact_id is not None
                or self.native_rule_change is not None
                or self.source_native_rules_sha256 != self.target_native_rules_sha256
                or not set(request.input_artifact_ids).issubset(self.source_artifact_ids)
            ):
                raise ValueError("原执行失败事实与当前任务、原执行、权限或普通工作预留不一致")
        elif reservation is not None and reservation.retry_cause == "stopped_failure_retry":
            raise ValueError("原执行失败预留缺少完整原执行证明")
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
        if (self.purpose is BaselinePurpose.REJECTED_CANDIDATE_RESCUE) != (
            self.facts.rejected_candidate_output is not None
        ):
            raise ValueError("候选报告拒绝证明只能属于独立精确恢复方案")
        candidate = self.facts.rejected_candidate_output
        if candidate is not None and (
            self.complete_capture != candidate.complete_capture
            or self.before_inventory != candidate.inventory
            or self.dirty_capture.source_revision != candidate.candidate_revision
            or self.dirty_capture.to_capture().changed_paths
            or self.dirty_capture.patch
            or self.dirty_capture.index_diff_sha256 != hashlib.sha256(b"").hexdigest()
        ):
            raise ValueError("候选报告恢复方案必须绑定完整原候选及干净现场")
        if self.facts.stopped_execution is not None:
            validate_stopped_coder_capture(
                self.facts.stopped_execution,
                self.dirty_capture,
                self.before_inventory,
                self.facts.permissions,
            )
        if self.facts.completed_output is not None:
            validate_completed_output_capture(
                self.facts.completed_output,
                self.dirty_capture,
                self.before_inventory,
                self.facts.permissions,
            )
        if self.facts.stopped_provider_failure is not None:
            validate_stopped_provider_capture(
                self.facts.stopped_provider_failure,
                self.dirty_capture,
                self.before_inventory,
                self.facts.permissions,
            )
        if self.facts.stopped_failure is not None:
            validate_stopped_failure_capture(
                self.facts.stopped_failure,
                self.dirty_capture,
                self.before_inventory,
                self.facts.permissions,
            )
        if (self.purpose is BaselinePurpose.STOPPED_EXECUTION_RESCUE) != (
            self.facts.stopped_execution is not None
        ):
            raise ValueError("未知结果停止证明只能属于独立恢复方案")
        if (self.purpose is BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION) != (
            self.facts.knowledge_isolation is not None
        ):
            raise ValueError("当前知识隔离只能属于独立精确恢复方案")
        task = self.facts.task
        if (
            self.facts.native_rule_change is not None
            and self.facts.native_rule_change.target.target_base_ref != self.target_base_ref
        ):
            raise ValueError("规范批准方案与目标代码版本不同")
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
        if self.purpose is BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION:
            isolation = self.facts.knowledge_isolation
            if (
                isolation is None
                or self.target_base_ref != expected_base
                or self.input_mode is not BaselineInputMode.PRESERVE_DRAFT
                or self.prepared_source_revision != self.dirty_capture.source_revision
                or self.prepared_dirty_patch != self.dirty_capture.patch
                or self.dirty_capture.source_revision
                != isolation.outcome.intent.binding.source_revision
                or self.dirty_capture.worktree_path != isolation.worktree_surveys[0].worktree_path
                or self.conflicted
            ):
                raise ValueError("当前知识隔离必须保留原基线和完整草稿、进度")
        elif self.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
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
            survey = self.facts.legacy_containment.local_execution_survey
            if survey is not None and survey.worktree_path != self.dirty_capture.worktree_path:
                raise ValueError("本机调查与恢复方案封存的工作区不同")
        elif self.purpose is BaselinePurpose.STOPPED_EXECUTION_RESCUE:
            if (
                self.facts.stopped_execution is None
                or self.target_base_ref != expected_base
                or self.input_mode is not BaselineInputMode.PRESERVE_DRAFT
                or self.prepared_source_revision != self.dirty_capture.source_revision
                or self.prepared_dirty_patch != self.dirty_capture.patch
                or self.conflicted
            ):
                raise ValueError("未知结果停止恢复必须使用原基线和完整合法草稿")
        elif self.purpose is BaselinePurpose.REJECTED_CANDIDATE_RESCUE:
            candidate = self.facts.rejected_candidate_output
            if (
                candidate is None
                or self.target_base_ref != expected_base
                or candidate.candidate_parent_revision != expected_base
                or self.input_mode is not BaselineInputMode.PRESERVE_DRAFT
                or self.prepared_source_revision != candidate.candidate_revision
                or self.prepared_dirty_patch
                or self.conflicted
            ):
                raise ValueError("候选报告恢复必须保留原基线, 仅推进到可信既存候选")
        elif self.purpose is BaselinePurpose.COMPLETED_OUTPUT_RESCUE:
            if (
                self.facts.completed_output is None
                or self.facts.legacy_containment is not None
                or self.facts.native_rule_change is not None
                or self.facts.source_native_rules_sha256 != self.facts.target_native_rules_sha256
                or self.facts.implementation_artifact_id is not None
                or self.target_base_ref != expected_base
                or self.input_mode is not BaselineInputMode.PRESERVE_DRAFT
                or self.prepared_source_revision != self.dirty_capture.source_revision
                or self.prepared_dirty_patch != self.dirty_capture.patch
                or self.conflicted
            ):
                raise ValueError(
                    "已结束执行恢复必须使用原基线和完整合法草稿, 不能更换规范或执行模式"
                )
        elif self.purpose is BaselinePurpose.STOPPED_PROVIDER_RETRY:
            if (
                self.facts.stopped_provider_failure is None
                or self.facts.legacy_containment is not None
                or self.facts.completed_output is not None
                or self.facts.native_rule_change is not None
                or self.facts.source_native_rules_sha256 != self.facts.target_native_rules_sha256
                or self.target_base_ref != expected_base
                or self.input_mode is not BaselineInputMode.PRESERVE_DRAFT
                or self.prepared_source_revision != self.dirty_capture.source_revision
                or self.prepared_dirty_patch != self.dirty_capture.patch
                or self.conflicted
            ):
                raise ValueError(
                    "提供方前提失败恢复必须使用原基线和完整合法草稿, 不能更换规范或执行模式"
                )
        elif self.purpose is BaselinePurpose.STOPPED_FAILURE_RETRY:
            if (
                self.facts.stopped_failure is None
                or self.facts.legacy_containment is not None
                or self.facts.completed_output is not None
                or self.facts.native_rule_change is not None
                or self.facts.source_native_rules_sha256 != self.facts.target_native_rules_sha256
                or self.target_base_ref != expected_base
                or self.input_mode is not BaselineInputMode.PRESERVE_DRAFT
                or self.prepared_source_revision != self.dirty_capture.source_revision
                or self.prepared_dirty_patch != self.dirty_capture.patch
                or self.conflicted
            ):
                raise ValueError(
                    "原执行失败恢复必须使用原基线和完整合法草稿, 不能更换规范或执行模式"
                )
        elif self.purpose is BaselinePurpose.CONTEXT_CAPACITY_RESUME:
            reservation = self.facts.continuation
            if (
                self.facts.context_capacity_receipt_sha256 is None
                or self.facts.legacy_containment is not None
                or self.facts.completed_output is not None
                or self.facts.stopped_provider_failure is not None
                or self.facts.native_rule_change is not None
                or self.facts.source_native_rules_sha256 != self.facts.target_native_rules_sha256
                or self.target_base_ref != expected_base
                or self.input_mode is not BaselineInputMode.PRESERVE_DRAFT
                or self.prepared_source_revision != self.dirty_capture.source_revision
                or self.prepared_dirty_patch != self.dirty_capture.patch
                or self.conflicted
                or reservation is None
                or reservation.retry_cause != "uninvoked"
                or not reservation.reservation_already_applied
                or reservation.current_attempt != task.attempts
                or reservation.next_execution_attempt != task.attempts
            ):
                raise ValueError("容量恢复需要精确未调用记录和原预留, 不能更换代码、规范或进度")
        elif self.facts.legacy_containment is not None:
            raise ValueError("代码基线更新不能混入旧执行隔离证据")
        elif self.target_base_ref == expected_base:
            reservation = self.facts.continuation
            if (
                reservation is None
                or reservation.retry_cause != "service_pause"
                or reservation.current_invocation_outcome_sha256 is None
                or self.facts.native_rule_change is not None
                or self.facts.source_native_rules_sha256 != self.facts.target_native_rules_sha256
                or self.input_mode is not BaselineInputMode.PRESERVE_DRAFT
                or self.prepared_source_revision != self.dirty_capture.source_revision
                or self.prepared_dirty_patch != self.dirty_capture.patch
                or self.conflicted
            ):
                raise ValueError("同基线继续必须绑定精确服务暂停结果, 保留原规范和完整工作现场")
        if (self.purpose is BaselinePurpose.STOPPED_FAILURE_RETRY) != (
            self.facts.stopped_failure is not None
        ):
            raise ValueError("原执行失败恢复只能使用独立同基线方案")
        if self.input_mode is BaselineInputMode.CODER_REAPPLY and (
            self.prepared_source_revision != self.target_base_ref
            or self.prepared_dirty_patch
            or self.conflicted
        ):
            raise ValueError("Coder reapply requires a clean exact target and a new plan")
        return self

    @property
    def preserves_paused_baseline(self) -> bool:
        expected = (
            self.previous_binding.execution_base_ref
            if self.previous_binding
            else self.facts.task.base_ref
        )
        return (
            self.purpose is BaselinePurpose.SOURCE_REBIND
            and self.target_base_ref == expected
            and self.facts.continuation is not None
            and self.facts.continuation.retry_cause == "service_pause"
        )

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


def require_context_capacity_binding(
    plan: ExecutionBaselinePlan, binding: ExecutionBaselineBinding
) -> None:
    """Bind the runtime-only purpose to the exact trusted plan, never a caller digest."""
    if plan.purpose is not BaselinePurpose.CONTEXT_CAPACITY_RESUME:
        if binding.context_capacity_receipt_sha256 is not None:
            raise ValueError("普通基线绑定不能携带独立容量恢复摘要")
        return
    plan.validate_integrity()
    binding.validate_integrity()
    expected_base = (
        plan.previous_binding.execution_base_ref
        if plan.previous_binding is not None
        else plan.facts.task.base_ref
    )
    if (
        binding.purpose is not plan.purpose
        or binding.task_id != plan.facts.task.id
        or binding.scope != plan.facts.scope
        or binding.plan_sha256 != plan.plan_sha256
        or binding.facts_sha256 != plan.facts.facts_sha256
        or binding.context_capacity_receipt_sha256 != plan.facts.context_capacity_receipt_sha256
        or binding.prior_execution_base_ref != expected_base
        or binding.execution_base_ref != plan.target_base_ref
        or binding.prior_source_revision != plan.dirty_capture.source_revision
        or binding.execution_source_revision != plan.prepared_source_revision
        or binding.worktree_path != plan.dirty_capture.worktree_path
        or binding.source_artifact_ids != plan.facts.source_artifact_ids
        or binding.resolved_interruption_receipt_sha256s
        != plan.facts.resolved_interruption_receipt_sha256s
        or binding.before_inventory_sha256 != plan.before_inventory.sha256
        or binding.after_inventory_sha256 != plan.before_inventory.sha256
        or binding.prior_task_revision != plan.facts.task_revision
    ):
        raise ValueError("容量恢复绑定与原完整方案、未调用记录或保留进度不一致")


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
    continuation_mode: BaselineContinuationMode = Field(
        default=BaselineContinuationMode.RESUME,
        exclude_if=lambda value: value is BaselineContinuationMode.RESUME,
    )
    approved_native_rule_change_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    confirm_current_knowledge_execution_isolated: Literal[True] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    confirm_legacy_containment: Literal[True] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    confirm_local_execution_stopped: Literal[True] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    confirm_provider_prerequisites_repaired: Literal[True] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    confirm_stopped_failure_retry: Literal[True] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    authorization_sha256: Sha256

    @model_validator(mode="after")
    def require_engineering(self) -> Self:
        self.principal.require_duty(OperatorDuty.ENGINEERING)
        if self.confirm_current_knowledge_execution_isolated is not None and (
            self.continuation_mode is not BaselineContinuationMode.PAUSE
            or any(
                value is not None
                for value in (
                    self.confirm_legacy_containment,
                    self.confirm_local_execution_stopped,
                    self.confirm_provider_prerequisites_repaired,
                    self.confirm_stopped_failure_retry,
                    self.approved_native_rule_change_sha256,
                )
            )
        ):
            raise ValueError("当前知识隔离确认必须独立批准并保持暂停")
        if self.confirm_legacy_containment and self.confirm_local_execution_stopped:
            raise ValueError("两种旧执行恢复确认不能同时使用")
        require_stopped_failure_confirmation_shape(
            self.confirm_stopped_failure_retry,
            self.continuation_mode,
            self.confirm_legacy_containment,
            self.confirm_local_execution_stopped,
            self.confirm_provider_prerequisites_repaired,
        )
        require_provider_confirmation_shape(
            self.confirm_provider_prerequisites_repaired,
            self.continuation_mode,
            self.confirm_legacy_containment,
            self.confirm_local_execution_stopped,
        )
        return self

    def require_plan_confirmation(self, plan: ExecutionBaselinePlan) -> None:
        require_knowledge_isolation_confirmation(
            plan, self.confirm_current_knowledge_execution_isolated, self.continuation_mode
        )
        if plan.purpose is BaselinePurpose.CONTEXT_CAPACITY_RESUME and (
            self.continuation_mode is not BaselineContinuationMode.PAUSE
        ):
            raise ValueError("容量恢复需先精确批准并保持暂停, 再单独明确继续")
        require_completed_output_confirmation(plan, self.continuation_mode)
        require_stopped_failure_confirmation(
            plan, self.confirm_stopped_failure_retry, self.continuation_mode
        )
        require_provider_prerequisite_confirmation(
            plan, self.confirm_provider_prerequisites_repaired, self.continuation_mode
        )
        change = plan.facts.native_rule_change
        expected = change.change_sha256 if change is not None else None
        if self.approved_native_rule_change_sha256 != expected:
            raise ValueError("请明确确认当前方案所列项目规范变化; 旧批准不能用于新版本")
        require_rescue_confirmation(
            plan,
            confirm_legacy_containment=self.confirm_legacy_containment,
            confirm_local_execution_stopped=self.confirm_local_execution_stopped,
        )

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
        confirm_current_knowledge_execution_isolated: Literal[True] | None = None,
        confirm_legacy_containment: Literal[True] | None = None,
        confirm_local_execution_stopped: Literal[True] | None = None,
        confirm_provider_prerequisites_repaired: Literal[True] | None = None,
        confirm_stopped_failure_retry: Literal[True] | None = None,
        continuation_mode: BaselineContinuationMode = BaselineContinuationMode.RESUME,
        approved_native_rule_change_sha256: str | None = None,
    ) -> Self:
        plan.validate_integrity()
        require_rescue_confirmation(
            plan,
            confirm_legacy_containment=confirm_legacy_containment,
            confirm_local_execution_stopped=confirm_local_execution_stopped,
        )
        value = cls(
            task_id=plan.facts.task.id,
            task_intent_sha256=task_intent_sha256(plan.facts.task),
            plan_sha256=plan.plan_sha256,
            facts_sha256=plan.facts.facts_sha256,
            principal=principal,
            reference=reference,
            submitted_at=submitted_at,
            continuation_mode=continuation_mode,
            approved_native_rule_change_sha256=approved_native_rule_change_sha256,
            confirm_current_knowledge_execution_isolated=confirm_current_knowledge_execution_isolated,
            confirm_legacy_containment=confirm_legacy_containment,
            confirm_local_execution_stopped=confirm_local_execution_stopped,
            confirm_provider_prerequisites_repaired=confirm_provider_prerequisites_repaired,
            confirm_stopped_failure_retry=confirm_stopped_failure_retry,
            authorization_sha256="0" * 64,
        )
        value.require_plan_confirmation(plan)
        return value.model_copy(
            update={
                "authorization_sha256": digest(
                    value.model_dump(mode="json", exclude={"authorization_sha256"})
                )
            }
        )


class BaselineContinueAuthorization(DomainModel):
    """One explicit start decision for the current preserved execution input."""

    kind: Literal["baseline_continue_authorization"] = "baseline_continue_authorization"
    scope: EngineeringScope
    task_id: NonEmptyStr
    task_intent_sha256: Sha256
    task_revision: int = Field(ge=1)
    work_item_id: NonEmptyStr
    execution_baseline_sha256: Sha256
    expected_source_revision: FullGitRevision
    checkpoint_sequence: int = Field(ge=1)
    expected_disposition_sha256: Sha256
    inventory_sha256: Sha256
    principal: LocalOperatorPrincipal
    reference: NonEmptyStr = Field(max_length=2000)
    submitted_at: AwareDatetime
    authorization_sha256: Sha256

    @model_validator(mode="after")
    def engineering_decision(self) -> Self:
        self.principal.require_duty(OperatorDuty.ENGINEERING)
        if self.checkpoint_sequence != self.task_revision:
            raise ValueError("继续决定未绑定精确任务版本")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.authorization_sha256 != digest(
            self.model_dump(mode="json", exclude={"authorization_sha256"})
        ):
            raise ValueError("基线继续决定完整性异常")

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "authorization_sha256": "0" * 64})
        return value.model_copy(
            update={
                "authorization_sha256": digest(
                    value.model_dump(mode="json", exclude={"authorization_sha256"})
                )
            }
        )


def require_rescue_confirmation(
    plan: ExecutionBaselinePlan,
    *,
    confirm_legacy_containment: Literal[True] | None,
    confirm_local_execution_stopped: Literal[True] | None,
) -> None:
    """Keep human provenance declarations distinct from machine observations."""
    containment = plan.facts.legacy_containment
    if plan.purpose is not BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
        if confirm_legacy_containment is not None or confirm_local_execution_stopped is not None:
            raise ValueError("旧执行救援确认只能用于对应的精确救援方案")
        return
    if containment is None:
        raise ValueError("旧执行救援缺少完整的原调用和当前检查记录")
    if containment.method == "operator_confirmed_local_stop":
        if confirm_local_execution_stopped is not True or confirm_legacy_containment is not None:
            raise ValueError(
                "请明确确认原调用及全部派生工具已在同机同账户本地结束, "
                "不会再修改现场; 接受原结果未知并批准保留进度另行执行。"
            )
    elif confirm_legacy_containment is not True or confirm_local_execution_stopped is not None:
        raise ValueError("旧执行救援需要明确确认同一本机整机重启、未迁移和可信时间依据")


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


def require_completed_output_confirmation(
    plan: ExecutionBaselinePlan, continuation_mode: BaselineContinuationMode
) -> None:
    """Rejected output is reproduced under exact human PAUSE, never auto-adopted."""
    require_rejected_candidate_confirmation(plan, continuation_mode)
    proof = plan.facts.completed_output
    if (
        plan.purpose
        in {BaselinePurpose.COMPLETED_OUTPUT_RESCUE, BaselinePurpose.STOPPED_EXECUTION_RESCUE}
        or (proof is not None and proof.reason is CompletedCoderOutputReason.REJECTED)
    ) and continuation_mode is not BaselineContinuationMode.PAUSE:
        raise ValueError("已结束执行恢复批准后必须保持暂停, 再明确继续原需求")


def require_provider_prerequisite_confirmation(
    plan: ExecutionBaselinePlan,
    confirmation: Literal[True] | None,
    continuation_mode: BaselineContinuationMode,
) -> None:
    """A user checks original prerequisites; the platform asserts no provider health."""
    if plan.facts.stopped_provider_failure is None:
        if confirmation is not None:
            raise ValueError("提供方前提确认只能用于对应的精确失败恢复方案")
        return
    if confirmation is not True:
        raise ValueError("请明确确认原执行的提供方或本机调用前提已检查并修复")
    if continuation_mode is not BaselineContinuationMode.PAUSE:
        raise ValueError("提供方前提失败恢复批准后必须保持暂停, 再明确继续原需求")


def require_provider_confirmation_shape(
    confirmation: Literal[True] | None,
    continuation_mode: BaselineContinuationMode,
    legacy_confirmation: Literal[True] | None,
    local_stop_confirmation: Literal[True] | None,
) -> None:
    if confirmation is not None:
        if legacy_confirmation is not None or local_stop_confirmation is not None:
            raise ValueError("提供方前提确认不能混用其他旧执行恢复确认")
        if continuation_mode is not BaselineContinuationMode.PAUSE:
            raise ValueError("提供方前提失败恢复批准后必须保持暂停, 再明确继续原需求")


def require_stopped_failure_confirmation(
    plan: ExecutionBaselinePlan,
    confirmation: Literal[True] | None,
    continuation_mode: BaselineContinuationMode,
) -> None:
    """Accept one ordinary work cost; no assertion that the unknown cause is repaired."""
    if plan.facts.stopped_failure is None:
        if confirmation is not None:
            raise ValueError("原执行失败重试确认只能用于对应的精确恢复方案")
        return
    if confirmation is not True:
        raise ValueError("请明确接受原执行失败原因未知并消费一次普通工作额度重新执行")
    if continuation_mode is not BaselineContinuationMode.PAUSE:
        raise ValueError("原执行失败恢复批准后必须保持暂停, 再明确继续原需求")


def require_stopped_failure_confirmation_shape(
    confirmation: Literal[True] | None,
    continuation_mode: BaselineContinuationMode,
    legacy_confirmation: Literal[True] | None,
    local_stop_confirmation: Literal[True] | None,
    provider_confirmation: Literal[True] | None,
) -> None:
    if confirmation is not None:
        if any(
            value is not None
            for value in (
                legacy_confirmation,
                local_stop_confirmation,
                provider_confirmation,
            )
        ):
            raise ValueError("原执行失败重试确认不能混用其他恢复确认")
        if continuation_mode is not BaselineContinuationMode.PAUSE:
            raise ValueError("原执行失败恢复批准后必须保持暂停, 再明确继续原需求")


def require_knowledge_isolation_confirmation(
    plan: ExecutionBaselinePlan,
    confirmation: Literal[True] | None,
    continuation_mode: BaselineContinuationMode,
) -> None:
    if plan.purpose is BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION:
        if confirmation is not True or continuation_mode is not BaselineContinuationMode.PAUSE:
            raise ValueError(
                "请由 ENGINEERING 主体明确批准当前隔离决定并保持暂停; "
                "旧知识执行仍为 UNKNOWN, 不宣称历史未启动或已停止"
            )
    elif confirmation is not None:
        raise ValueError("当前知识隔离确认只能用于精确独立隔离方案")


def require_knowledge_isolation_binding(
    plan: ExecutionBaselinePlan, binding: ExecutionBaselineBinding
) -> None:
    proof, reservation = plan.facts.knowledge_isolation, plan.facts.continuation
    if plan.purpose is not BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION:
        if proof is not None or binding.knowledge_isolation_sha256 is not None:
            raise ValueError("当前知识隔离证明不能混入其他执行绑定")
        return
    if (
        proof is None
        or reservation is None
        or reservation.retry_cause != "knowledge_isolation"
        or reservation.knowledge_isolation_sha256 != proof.proof_sha256
        or binding.knowledge_isolation_sha256 != proof.proof_sha256
        or binding.purpose is not BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION
        or binding.plan_sha256 != plan.plan_sha256
        or binding.facts_sha256 != plan.facts.facts_sha256
        or binding.authority_source != "engineering_operator_decision"
        or binding.continuation_mode is not BaselineContinuationMode.PAUSE
        or binding.execution_base_ref != binding.prior_execution_base_ref
        or binding.execution_source_revision != binding.prior_source_revision
        or binding.before_inventory_sha256 != binding.after_inventory_sha256
        or binding.superseded_progress_artifact_id is not None
        or binding.superseded_implementation_artifact_id is not None
        or reservation.reservation_already_applied
        or reservation.retry_failure is not None
        or reservation.current_attempt != proof.original_claim.work_item.attempt
        or reservation.next_execution_attempt != reservation.current_attempt + 1
    ):
        raise ValueError("当前知识隔离绑定必须保持完整原现场、人工批准暂停和普通工作接续")
    proof.validate_integrity()


def require_rejected_candidate_confirmation(
    plan: ExecutionBaselinePlan,
    continuation_mode: BaselineContinuationMode,
) -> None:
    if plan.facts.rejected_candidate_output is not None and (
        continuation_mode is not BaselineContinuationMode.PAUSE
    ):
        raise ValueError("候选报告恢复需要精确工程确认后保持暂停, 再明确继续")


def require_rejected_candidate_binding(
    plan: ExecutionBaselinePlan,
    binding: ExecutionBaselineBinding,
) -> None:
    proof = plan.facts.rejected_candidate_output
    if proof is None:
        if binding.rejected_candidate_output_sha256 is not None:
            raise ValueError("候选报告恢复绑定缺少原证明")
        return
    plan.validate_integrity()
    binding.validate_integrity()
    proof.validate_integrity()
    binding.require_task(plan.facts.task)
    previous = plan.previous_binding
    binding.require_predecessor(previous)
    if (
        plan.purpose is not BaselinePurpose.REJECTED_CANDIDATE_RESCUE
        or binding.purpose is not plan.purpose
        or binding.scope != plan.facts.scope
        or binding.sequence != (previous.sequence + 1 if previous else 1)
        or binding.previous_binding_sha256 != (previous.binding_sha256 if previous else None)
        or binding.worktree_path != proof.complete_capture.worktree_path
        or binding.branch_name != proof.complete_capture.branch_name
        or binding.input_mode is not plan.input_mode
        or binding.source_artifact_ids != plan.facts.source_artifact_ids
        or binding.resolved_interruption_receipt_sha256s
        != plan.facts.resolved_interruption_receipt_sha256s
        or binding.prior_task_revision != plan.facts.task_revision
        or binding.superseded_progress_artifact_id != plan.facts.progress_artifact_id
        or binding.superseded_implementation_artifact_id is not None
        or binding.rejected_candidate_output_sha256 != proof.proof_sha256
        or binding.execution_source_revision != proof.candidate_revision
        or binding.prior_source_revision != proof.request.source_revision
        or binding.execution_base_ref != proof.candidate_parent_revision
        or binding.prior_execution_base_ref != binding.execution_base_ref
        or binding.before_inventory_sha256 != proof.inventory.sha256
        or binding.after_inventory_sha256 != binding.before_inventory_sha256
        or binding.native_rule_epoch_sha256
        != (plan.previous_binding.native_rule_epoch_sha256 if plan.previous_binding else None)
        or binding.plan_sha256 != plan.plan_sha256
        or binding.facts_sha256 != plan.facts.facts_sha256
        or binding.continuation_mode is not BaselineContinuationMode.PAUSE
        or binding.authority_source != "engineering_operator_decision"
    ):
        raise ValueError("候选报告恢复绑定偏离精确候选、原基线或工程确认")
