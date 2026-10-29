"""Production-only baseline facts: real process locks, idle queue and sealed calls.

Request bodies select an immutable target and exact plan. They cannot assert that
an executor stopped, grant write paths, or replace original native instructions.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, Field, JsonValue, TypeAdapter, model_validator
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.execution import ExecutionStop, SynchronousToolLoopStop
from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, RouteAttemptOutcome
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentOutputContractError,
    AgentRequest,
    AgentRunStatus,
)
from ai_software_engineer.artifacts import ArtifactStore, artifact_digest
from ai_software_engineer.artifacts.ordering import latest_accepted_artifact
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.artifact import (
    CoderProgressArtifact,
    ImplementationReportArtifact,
    PlanArtifact,
    Sha256,
    validate_current_artifact_version,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import DeliveryResolution
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselineInputMode,
    BaselinePurpose,
    ExecutionBaselineBinding,
    FullGitRevision,
)
from ai_software_engineer.domain.execution_native_rules import (
    MAX_NATIVE_RULE_RAW_TOTAL_BYTES as MAX_NATIVE_RULE_TOTAL_BYTES,
)
from ai_software_engineer.domain.execution_native_rules import (
    MAX_NATIVE_RULE_SOURCE_BYTES as MAX_NATIVE_RULE_BYTES,
)
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.retry_policy import TRANSIENT_CODES, DeliveryRetryFailure
from ai_software_engineer.domain.task import Task, TaskId, task_matches_dispatch
from ai_software_engineer.domain.workforce import RoleAssignment
from ai_software_engineer.git import GitWorktreeManager, WorktreeNotFound
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.git.ports import WorktreeRef, WorktreeSpec
from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import (
    BaselineContinueAuthorization,
    BaselineExecutionFacts,
    BaselineExecutionReservation,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
    require_completed_output_confirmation,
    require_context_capacity_binding,
    require_knowledge_isolation_binding,
    require_knowledge_isolation_confirmation,
    require_provider_confirmation_shape,
    require_provider_prerequisite_confirmation,
    require_rejected_candidate_binding,
    require_rejected_candidate_confirmation,
    require_rescue_confirmation,
    require_stopped_failure_confirmation,
    require_stopped_failure_confirmation_shape,
)
from ai_software_engineer.manager.baseline_native_rules import build_native_rule_change
from ai_software_engineer.manager.capacity_input_reader import (
    CapacityInputReader,
    PriorInvocationFence,
    UninvokedClaimBoundary,
)
from ai_software_engineer.manager.completed_output_checkpoint import (
    CompletedCoderOutputReason,
    CompletedCoderOutputUnavailableProof,
    require_completed_output_workspace,
)
from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.manager.delivery_preflight import (
    DeliveryPreflightCheckpoint,
    DeliveryPreflightReceipt,
)
from ai_software_engineer.manager.dispatch import DeliveryAllocation, RecoveryDispatchRecord
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.manager.knowledge_invocation_proof import (
    KnowledgeNativeStopChecker,
    KnowledgeOnlyClaimProof,
    ReplayGuardedClaimObservation,
    read_capacity_claim_snapshot,
    read_failed_knowledge_claims,
    read_replay_guarded_claims,
    require_no_knowledge_claim_activity,
)
from ai_software_engineer.manager.knowledge_isolation import (
    KnowledgePreparationIsolationProof,
    observe_isolation_boundary,
    read_unknown_knowledge_preparation,
    require_current_isolation_boundary,
)
from ai_software_engineer.manager.legacy_containment import (
    LegacyExecutionContainment,
    LocalBootObservation,
    LocalBootObserver,
    TrustedLocalBootObserver,
)
from ai_software_engineer.manager.legacy_local_execution import (
    LegacyLocalExecutionObserver,
    LegacyRescuePrerequisiteError,
)
from ai_software_engineer.manager.legacy_snapshot import require_complete_legacy_inventory
from ai_software_engineer.manager.local_survey_observation import (
    IsolatedLegacyLocalExecutionObserver,
)
from ai_software_engineer.manager.owned_session_boot_bridge import ScopedNativeStopVerifier
from ai_software_engineer.manager.recovery_input_schedule import (
    RecoveryInputScheduleDecision,
    require_consumed_recovery_input_schedule,
)
from ai_software_engineer.manager.rejected_candidate_output import RejectedCandidateOutputProof
from ai_software_engineer.manager.stopped_execution_checkpoint import (
    StoppedCoderExecutionProof,
    read_stopped_coder_execution,
    require_stopped_coder_workspace,
)
from ai_software_engineer.manager.stopped_failure_checkpoint import (
    StoppedFailureProof,
    require_stopped_failure_workspace,
)
from ai_software_engineer.manager.stopped_provider_checkpoint import (
    StoppedProviderFailureProof,
    require_stopped_provider_workspace,
)
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.capture_reconciliation import validate_capture_stop
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRecordMissing,
    ContinuationScope,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.retry import _active_progress, _latest
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.repository_profile import NativeRuleSource, native_rule_kinds
from ai_software_engineer.safe_files import _reject_symlinks
from ai_software_engineer.spec_compiler import SpecRule
from ai_software_engineer.store import TaskRepository
from ai_software_engineer.work_queue.claim_snapshot import require_claim_snapshot
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.worker import AcceptedArtifactStore, WorkerExecutionGuard


class BaselineProposeCommand(DomainModel):
    purpose: BaselinePurpose = Field(
        default=BaselinePurpose.SOURCE_REBIND,
        exclude_if=lambda value: value is BaselinePurpose.SOURCE_REBIND,
    )
    delivery_id: DeliveryId
    task_id: TaskId
    expected_task_intent_sha256: Sha256
    expected_task_revision: int = Field(ge=1)
    expected_work_item_id: NonEmptyStr
    expected_source_revision: FullGitRevision
    target_base_ref: FullGitRevision | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    input_mode: BaselineInputMode = BaselineInputMode.PRESERVE_DRAFT

    @model_validator(mode="after")
    def distinct_preparation(self) -> Self:
        if self.purpose in {
            BaselinePurpose.COMPLETED_OUTPUT_RESCUE,
            BaselinePurpose.REJECTED_CANDIDATE_RESCUE,
            BaselinePurpose.STOPPED_PROVIDER_RETRY,
            BaselinePurpose.STOPPED_FAILURE_RETRY,
            BaselinePurpose.STOPPED_EXECUTION_RESCUE,
            BaselinePurpose.CONTEXT_CAPACITY_RESUME,
            BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION,
        }:
            if (
                self.target_base_ref is not None
                or self.input_mode is not BaselineInputMode.PRESERVE_DRAFT
            ):
                raise ValueError(
                    "容量恢复由平台核验并固定当前基线, 不能指定目标或重放模式"
                    if self.purpose is BaselinePurpose.CONTEXT_CAPACITY_RESUME
                    else "已结束执行恢复由平台核验并固定原基线, 不能指定目标或重放模式"
                )
        elif self.target_base_ref is None:
            raise ValueError("基线更新或旧执行救援需要精确目标版本")
        return self

    def require_current(
        self, task: Task, revision: int, work_item_id: str, source_revision: str
    ) -> None:
        """Reject stale inputs before the collector publishes original facts."""
        if (
            task.id,
            task_intent_sha256(task),
            revision,
            work_item_id,
            source_revision,
        ) != (
            self.task_id,
            self.expected_task_intent_sha256,
            self.expected_task_revision,
            self.expected_work_item_id,
            self.expected_source_revision,
        ):
            raise ValueError("工程执行基线事实已变化, 请刷新后重新调查")

    def require_plan(self, plan: ExecutionBaselinePlan) -> None:
        plan.validate_integrity()
        facts = plan.facts
        if (
            facts.task.id,
            task_intent_sha256(facts.task),
            facts.task_revision,
            facts.work_item_id,
            (
                facts.rejected_candidate_output.request.source_revision
                if facts.rejected_candidate_output is not None
                else plan.dirty_capture.source_revision
            ),
            plan.target_base_ref,
            plan.input_mode,
            plan.purpose,
        ) != (
            self.task_id,
            self.expected_task_intent_sha256,
            self.expected_task_revision,
            self.expected_work_item_id,
            self.expected_source_revision,
            plan.target_base_ref
            if self.purpose
            in {
                BaselinePurpose.COMPLETED_OUTPUT_RESCUE,
                BaselinePurpose.REJECTED_CANDIDATE_RESCUE,
                BaselinePurpose.STOPPED_PROVIDER_RETRY,
                BaselinePurpose.STOPPED_FAILURE_RETRY,
                BaselinePurpose.STOPPED_EXECUTION_RESCUE,
                BaselinePurpose.CONTEXT_CAPACITY_RESUME,
                BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION,
            }
            else self.target_base_ref,
            self.input_mode,
            self.purpose,
        ):
            raise ValueError("工程执行基线事实已变化, 请刷新后重新调查")


class BaselineExecuteCommand(DomainModel):
    delivery_id: DeliveryId
    task_id: TaskId
    expected_plan_sha256: Sha256
    reference: NonEmptyStr = Field(max_length=2000)
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

    @model_validator(mode="after")
    def current_isolation_confirmation_shape(self) -> Self:
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
        return self

    @model_validator(mode="after")
    def distinct_confirmation(self) -> Self:
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

    def require_plan(self, plan: ExecutionBaselinePlan) -> None:
        require_knowledge_isolation_confirmation(
            plan, self.confirm_current_knowledge_execution_isolated, self.continuation_mode
        )
        plan.validate_integrity()
        require_completed_output_confirmation(plan, self.continuation_mode)
        require_rejected_candidate_confirmation(plan, self.continuation_mode)
        if (
            plan.facts.context_capacity_receipt_sha256 is not None
            and self.continuation_mode is not BaselineContinuationMode.PAUSE
        ):
            raise ValueError("上下文容量恢复需先精确批准保留进度并暂停, 再明确继续原需求")
        if (plan.facts.task.id, plan.plan_sha256) != (self.task_id, self.expected_plan_sha256):
            raise ValueError("工程决定未绑定当前需求和精确执行基线计划")
        change = plan.facts.native_rule_change
        if self.approved_native_rule_change_sha256 != (
            change.change_sha256 if change is not None else None
        ):
            raise ValueError("请明确确认此精确目标版本的项目规范变更")
        require_stopped_failure_confirmation(
            plan, self.confirm_stopped_failure_retry, self.continuation_mode
        )
        require_provider_prerequisite_confirmation(
            plan, self.confirm_provider_prerequisites_repaired, self.continuation_mode
        )
        require_rescue_confirmation(
            plan,
            confirm_legacy_containment=self.confirm_legacy_containment,
            confirm_local_execution_stopped=self.confirm_local_execution_stopped,
        )


class BaselineContinueCommand(DomainModel):
    """A distinct, exact decision to release a preserved execution baseline hold."""

    delivery_id: DeliveryId
    task_id: TaskId
    expected_task_intent_sha256: Sha256
    expected_task_revision: int = Field(ge=1)
    expected_work_item_id: NonEmptyStr
    expected_source_revision: FullGitRevision
    expected_execution_baseline_sha256: Sha256
    expected_disposition_sha256: Sha256
    reference: NonEmptyStr = Field(max_length=2000)


class ReclaimedUninvokedClaimObservation(DomainModel):
    """A queue reclaim fact, never a native stop or model outcome."""

    kind: Literal["reclaimed_uninvoked_claim_observation"] = "reclaimed_uninvoked_claim_observation"
    lease_id: NonEmptyStr
    task_id: TaskId
    work_item_id: NonEmptyStr
    claim_sha256: Sha256
    next_claim_sha256: Sha256
    blocking_start_sha256: Sha256
    dispatch_sequence: int = Field(ge=0)
    claimed_at: AwareDatetime
    expired_at: AwareDatetime
    reclaim_event_sequence: int = Field(ge=1)
    reclaim_event_sha256: Sha256
    observation_sha256: Sha256

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if self.expired_at <= self.claimed_at:
            raise ValueError("回收 claim 的结束时间早于领取时间")
        if self.observation_sha256 != digest(
            self.model_dump(mode="json", exclude={"observation_sha256"})
        ):
            raise ValueError("回收 claim 观察摘要不一致")
        return self

    @classmethod
    def create(
        cls,
        *,
        lease_id: str,
        task_id: str,
        work_item_id: str,
        claim_sha256: str,
        next_claim_sha256: str,
        blocking_start_sha256: str,
        dispatch_sequence: int,
        claimed_at: datetime,
        expired_at: datetime,
        reclaim_event_sequence: int,
        reclaim_event_sha256: str,
    ) -> Self:
        value = cls.model_construct(
            lease_id=lease_id,
            task_id=task_id,
            work_item_id=work_item_id,
            claim_sha256=claim_sha256,
            next_claim_sha256=next_claim_sha256,
            blocking_start_sha256=blocking_start_sha256,
            dispatch_sequence=dispatch_sequence,
            claimed_at=claimed_at,
            expired_at=expired_at,
            reclaim_event_sequence=reclaim_event_sequence,
            reclaim_event_sha256=reclaim_event_sha256,
            observation_sha256="0" * 64,
        )
        return cls.model_validate(
            value.model_copy(
                update={
                    "observation_sha256": digest(
                        value.model_dump(mode="json", exclude={"observation_sha256"})
                    )
                }
            ).to_wire()
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())


class ConsumedPreContextClaimObservation(DomainModel):
    """Consumed engineering no-Context decision, not an execution stop or result."""

    kind: Literal["consumed_pre_context_claim_observation"] = (
        "consumed_pre_context_claim_observation"
    )
    lease_id: NonEmptyStr
    task_id: TaskId
    work_item_id: NonEmptyStr
    claim_sha256: Sha256
    next_claim_sha256: Sha256
    blocking_start_sha256: Sha256
    schedule_sha256: Sha256
    resolution_sha256: Sha256
    wait_event_sequence: int = Field(ge=1)
    wait_event_sha256: Sha256
    resolved_event_sequence: int = Field(ge=1)
    resolved_event_sha256: Sha256
    observation_sha256: Sha256

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if self.wait_event_sequence >= self.resolved_event_sequence:
            raise ValueError("预 Context 原等待决定的事件顺序不一致")
        if self.observation_sha256 != digest(
            self.model_dump(mode="json", exclude={"observation_sha256"})
        ):
            raise ValueError("预 Context 原等待观察摘要不一致")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        body = {"kind": "consumed_pre_context_claim_observation", **values}
        return cls.model_validate({**body, "observation_sha256": digest(body)})

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())


class BaselineInvocationProof(DomainModel):
    work_item_id: NonEmptyStr
    step_sha256: Sha256
    start_sha256: Sha256 | None = None
    outcome_sha256: Sha256 | None = None
    interruption_receipt_sha256: Sha256 | None = None
    preflight_checkpoint_sha256: Sha256 | None = None
    preflight_checkpoint_sha256s: tuple[Sha256, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    context_capacity_receipt_sha256s: tuple[Sha256, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    knowledge_only_claims: tuple[KnowledgeOnlyClaimProof, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    replay_guarded_claims: tuple[ReplayGuardedClaimObservation, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    reclaimed_uninvoked_claims: tuple[ReclaimedUninvokedClaimObservation, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    consumed_pre_context_claims: tuple[ConsumedPreContextClaimObservation, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    legacy_containment: LegacyExecutionContainment | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    legacy_binding_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    knowledge_isolation: KnowledgePreparationIsolationProof | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    knowledge_isolation_binding_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    stopped_execution: StoppedCoderExecutionProof | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    proof_kind: Literal[
        "definitive_outcome",
        "stopped_execution_without_outcome",
        "owned_process_stopped",
        "unclaimed",
        "claimed_preflight",
        "claimed_context_capacity",
        "claimed_knowledge_failure",
        "isolated_knowledge_preparation",
        "legacy_execution_contained",
    ]

    @model_validator(mode="after")
    def validate_legacy(self) -> Self:
        if self.proof_kind == "isolated_knowledge_preparation":
            isolation_proof = self.knowledge_isolation
            if (
                isolation_proof is None
                or isolation_proof.work_item_id != self.work_item_id
                or any(
                    value is not None
                    for value in (
                        self.start_sha256,
                        self.outcome_sha256,
                        self.interruption_receipt_sha256,
                        self.legacy_containment,
                        self.stopped_execution,
                    )
                )
                or self.knowledge_only_claims
                or self.replay_guarded_claims
                or self.reclaimed_uninvoked_claims
                or self.consumed_pre_context_claims
                or self.preflight_checkpoint_sha256s
                or self.context_capacity_receipt_sha256s
            ):
                raise ValueError("当前知识隔离不能冒充主岗位启动、结果或停止事实")
            isolation_proof.validate_integrity()
        elif (
            self.knowledge_isolation is not None
            or self.knowledge_isolation_binding_sha256 is not None
        ):
            raise ValueError("当前知识隔离证明只能覆盖精确原 claim")
        if self.replay_guarded_claims and (
            self.proof_kind
            not in {"stopped_execution_without_outcome", "legacy_execution_contained"}
            or len({value.lease_id for value in self.replay_guarded_claims})
            != len(self.replay_guarded_claims)
        ):
            raise ValueError("重领观察只能覆盖已独立隔离的精确原调用和不同真实 claim")
        for observation in self.replay_guarded_claims:
            observation.validate_integrity()
            if observation.blocking_start_sha256 != self.start_sha256:
                raise ValueError("重领观察没有绑定此精确原调用")
        if self.reclaimed_uninvoked_claims and self.proof_kind != "legacy_execution_contained":
            raise ValueError("回收未调用观察只能附着旧执行隔离事实")
        if len({value.lease_id for value in self.reclaimed_uninvoked_claims}) != len(
            self.reclaimed_uninvoked_claims
        ):
            raise ValueError("回收未调用观察含重复历史 claim")
        for reclaimed_observation in self.reclaimed_uninvoked_claims:
            reclaimed_observation.validate_integrity()
            if (
                reclaimed_observation.work_item_id != self.work_item_id
                or reclaimed_observation.blocking_start_sha256 != self.start_sha256
                or self.legacy_containment is None
                or reclaimed_observation.task_id
                != self.legacy_containment.original_start.request.task_id
                or reclaimed_observation.next_claim_sha256
                != claim_identity_sha256(self.legacy_containment.original_claim)
            ):
                raise ValueError("回收未调用观察未绑定当前原调用及其真实后续 claim")
        if len({value.lease_id for value in self.consumed_pre_context_claims}) != len(
            self.consumed_pre_context_claims
        ):
            raise ValueError("预 Context 原等待观察含重复历史 claim")
        for consumed_observation in self.consumed_pre_context_claims:
            consumed_observation.validate_integrity()
            if (
                consumed_observation.work_item_id != self.work_item_id
                or consumed_observation.blocking_start_sha256 != self.start_sha256
                or self.start_sha256 is None
            ):
                raise ValueError("预 Context 原等待观察未绑定真实后续调用")
        if self.proof_kind == "stopped_execution_without_outcome":
            proof = self.stopped_execution
            if (
                proof is None
                or proof.invocation_start.work_item_id != self.work_item_id
                or proof.invocation_start.start_sha256 != self.start_sha256
                or self.outcome_sha256 is not None
                or self.interruption_receipt_sha256 is not None
            ):
                raise ValueError("未知结果停止证明不能替代原结果或停止收据")
            proof.validate_integrity()
        elif self.stopped_execution is not None:
            raise ValueError("未知结果停止证明只能属于独立停止观察")
        if self.proof_kind == "claimed_knowledge_failure" and (
            not self.knowledge_only_claims
            or self.start_sha256 is not None
            or self.outcome_sha256 is not None
            or self.interruption_receipt_sha256 is not None
        ):
            raise ValueError("知识准备失败证明不能冒充主岗位启动、结果或停止收据")
        if self.proof_kind == "claimed_context_capacity" and (
            not self.context_capacity_receipt_sha256s
            or self.start_sha256 is not None
            or self.outcome_sha256 is not None
            or self.interruption_receipt_sha256 is not None
        ):
            raise ValueError("上下文容量停止证明不能冒充模型启动、结果或停止收据")
        if self.proof_kind == "legacy_execution_contained":
            containment = self.legacy_containment
            if (
                containment is None
                or containment.original_start.work_item_id != self.work_item_id
                or containment.original_start.start_sha256 != self.start_sha256
                or self.outcome_sha256 is not None
                or self.interruption_receipt_sha256 is not None
            ):
                raise ValueError("旧执行观察不能替代原结果或原停止记录")
            containment.validate_integrity()
        elif self.legacy_containment is not None or self.legacy_binding_sha256 is not None:
            raise ValueError("旧执行隔离观察只能属于独立工程救援证明")
        return self


class BaselineQuiescenceProof(DomainModel):
    kind: Literal["baseline_quiescence_v1"] = "baseline_quiescence_v1"
    task_id: TaskId
    task_revision: int
    task_snapshot_sha256: Sha256
    task_events_sha256: Sha256
    allocation_sha256: Sha256
    queue_snapshot_sha256: Sha256
    assignments_sha256: Sha256
    task_process_lock: Literal["held"] = "held"
    queue_authority_and_task_row: Literal["held_no_active_claim"] = "held_no_active_claim"
    invocations: tuple[BaselineInvocationProof, ...]


def native_rules_at_revision(
    git: GitWorktreeManager,
    *,
    repository_id: str,
    revision: str,
) -> tuple[NativeRuleSource, ...]:
    """Discover the entire immutable tree, including newly added instruction files."""
    # Full SHA only; a movable branch cannot become an engineering plan input.
    if git._resolve_revision(revision) != revision:
        raise ValueError("执行基线只接受完整、不可变的 Git 提交")
    records = git._run_git_bytes(("ls-tree", "-r", "-z", revision), cwd=git._repository)
    result: list[NativeRuleSource] = []
    total = 0
    for record in records.split(b"\0"):
        if not record:
            continue
        metadata, separator, path_bytes = record.partition(b"\t")
        if not separator:
            raise ValueError("目标基线 Git 文件清单格式异常")
        relative = path_bytes.decode("utf-8")
        kinds = native_rule_kinds(relative)
        if not kinds:
            continue
        mode, kind, blob = metadata.decode("ascii").split(" ")
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("目标基线的原生规范必须是普通文本文件")
        size = int(git._run_git(("cat-file", "-s", blob), cwd=git._repository))
        total += size
        if size > MAX_NATIVE_RULE_BYTES or total > MAX_NATIVE_RULE_TOTAL_BYTES:
            raise ValueError("目标基线原生规范超过有界读取预算")
        body = git._run_git_bytes(("cat-file", "blob", blob), cwd=git._repository)
        body.decode("utf-8")
        if len(body) != size:
            raise ValueError("目标基线原生规范读取不完整")
        result.append(
            NativeRuleSource(
                uri=f"project://{repository_id}/{relative}",
                relative_path=relative,
                kinds=kinds,
                sha256=hashlib.sha256(body).hexdigest(),
                byte_length=size,
            )
        )
    return tuple(sorted(result, key=lambda item: item.relative_path))


class ProductionBaselineFactCollector:
    """Trusted service composition; no model/API supplied facts are accepted.

    Lock order matches the Worker: Task process lock, queue authority, Task row.
    All ACTIVE claims are excluded even if expired. Git mutations are deliberately
    not part of collect(): the sealed adapter plan owns its exact crash replay.
    """

    def __init__(
        self,
        *,
        allocation: DeliveryAllocation,
        scope: EngineeringScope,
        requirement_id: DeliveryId,
        repository: TaskRepository,
        queue: MySqlRoleQueue,
        artifacts: ArtifactStore,
        git: GitWorktreeManager,
        sidecar_state: Path,
        locks_root: Path,
        permissions: AgentPermissions,
        source_native_rules: tuple[NativeRuleSource, ...],
        runtime_manifest_sha256: str,
        inputs: StoredCoderExecutionInputResolver,
        structured_project_rules: tuple[SpecRule, ...] = (),
        purpose: BaselinePurpose = BaselinePurpose.SOURCE_REBIND,
        observer: LocalBootObserver | None = None,
        local_execution_observer: LegacyLocalExecutionObserver | None = None,
        route_root: Path | None = None,
        knowledge_requirement_id: str | None = None,
        native_stop_verifier: ScopedNativeStopVerifier | None = None,
    ) -> None:
        allocation.validate_integrity()
        self.allocation, self.scope, self.requirement_id = allocation, scope, requirement_id
        self.knowledge_requirement_id = knowledge_requirement_id or requirement_id
        self.repository, self.queue, self.git = repository, queue, git
        self.state, self.locks_root, self.permissions = sidecar_state, locks_root, permissions
        self.native_rules, self.runtime_manifest_sha256, self.inputs = (
            source_native_rules,
            runtime_manifest_sha256,
            inputs,
        )
        self.guard = WorkerExecutionGuard()
        self.structured_project_rules = structured_project_rules
        self.capacity_artifacts = artifacts
        self.artifacts = AcceptedArtifactStore(artifacts, queue, allocation.task_id, self.guard)
        self._scope_held = False
        self._idle_cursor: DictCursor | None = None
        self.purpose = purpose
        self.observer = observer if observer is not None else TrustedLocalBootObserver()
        self.local_execution_observer = (
            local_execution_observer
            if local_execution_observer is not None
            else IsolatedLegacyLocalExecutionObserver()
        )
        self._sealed_legacy_observation: LegacyExecutionContainment | None = None
        self.route_root = route_root
        self._proposal_command: BaselineProposeCommand | None = None
        self.native_stop_verifier = native_stop_verifier

    def _require_stopped(self, stop: ExecutionStop, request: AgentRequest | None = None) -> None:
        verifier = getattr(self, "native_stop_verifier", None)
        if verifier is None:
            NativeCoderContinuation._require_stopped(stop, request)
        else:
            verifier.require_stopped(stop, request)

    def _knowledge_stop_checker(self) -> KnowledgeNativeStopChecker | None:
        verifier = getattr(self, "native_stop_verifier", None)
        return verifier.require_knowledge if verifier is not None else None

    def bind_proposal(self, command: BaselineProposeCommand) -> None:
        """Bind one explicit preparation, never an execute/continue recollection."""
        if self._scope_held:
            raise ValueError("执行基线方案不能在调查期间替换当前命令")
        self._proposal_command = command

    def _collect_proposal_facts(
        self,
        task: Task,
        revision: int,
        step: QueuedRoleStep,
        source_revision: str,
        target_base_ref: str,
    ) -> None:
        if not self._scope_held or self._idle_cursor is None:
            raise ValueError("执行基线事实封存缺少真实任务锁和队列屏障")
        command = self._proposal_command
        if command is None:
            return
        command.require_current(task, revision, step.work_item.id, source_revision)
        if (
            command.delivery_id != self.requirement_id
            or command.purpose is not self.purpose
            or (
                command.purpose
                not in {
                    BaselinePurpose.COMPLETED_OUTPUT_RESCUE,
                    BaselinePurpose.REJECTED_CANDIDATE_RESCUE,
                    BaselinePurpose.STOPPED_PROVIDER_RETRY,
                    BaselinePurpose.STOPPED_FAILURE_RETRY,
                    BaselinePurpose.STOPPED_EXECUTION_RESCUE,
                    BaselinePurpose.CONTEXT_CAPACITY_RESUME,
                    BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION,
                }
                and command.target_base_ref != target_base_ref
            )
        ):
            raise ValueError("工程执行基线事实已变化, 请刷新后重新调查")
        item = self.queue.get(step.work_item.id)
        disposition = item.wait_disposition
        if (
            self.purpose
            not in {
                BaselinePurpose.SOURCE_REBIND,
                BaselinePurpose.COMPLETED_OUTPUT_RESCUE,
                BaselinePurpose.STOPPED_PROVIDER_RETRY,
                BaselinePurpose.STOPPED_FAILURE_RETRY,
            }
            or item.status not in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
            or disposition is None
            or disposition.facts.classification not in {"EXECUTION_UNCERTAIN", "PLATFORM_BUG"}
        ):
            return
        if self.route_root is None:
            raise ValueError("执行基线事实封存缺少原调用路由记录位置")
        collector = DeliveryWaitFactCollector(
            sidecar_state=self.state,
            route_root=self.route_root,
            scope=self.scope,
            expected_continuation_scope=ContinuationScope(
                team_id=self.scope.team_id,
                project_id=self.scope.project_id,
                repository_id=self.scope.repository_id,
                requirement_id=self.requirement_id,
                dispatch_sha256=self.allocation.dispatch_sha256,
            ),
            git=self.git,
            queue=self.queue,
        )
        # execution_scope already owns both boundaries. Collection only appends
        # original outcome/receipt facts; HANDLE would also resolve and resume.
        collector.collect(task, step, self.guard)

    def bind_knowledge_isolation(self, proof: KnowledgePreparationIsolationProof) -> None:
        proof.validate_integrity()
        self._sealed_knowledge_isolation = proof

    def bind_legacy_observation(self, containment: LegacyExecutionContainment) -> None:
        """Pin the approved evidence while collect independently checks it again."""
        containment.validate_integrity()
        if (
            containment.scope != self.scope
            or containment.requirement_id != self.requirement_id
            or containment.dispatch_sha256 != self.allocation.dispatch_sha256
        ):
            raise ValueError("旧执行恢复观察不属于当前精确需求和分配")
        self._sealed_legacy_observation = containment

    def _observe_legacy_boot(self) -> LocalBootObservation:
        try:
            return self.observer.observe()
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            raise LegacyRescuePrerequisiteError(
                code="LEGACY_LOCAL_OBSERVATION_UNAVAILABLE",
                safe_message="平台暂时无法读取可靠的本机身份和启动记录，不能准备旧执行恢复。",  # noqa: RUF001
                next_action="请让平台维护者检查当前系统的只读查询能力和权限，修复后重新检查恢复前提；不要清空工作区。",  # noqa: RUF001
            ) from error

    def _verify_legacy_observation(
        self, containment: LegacyExecutionContainment, *, worktree_root: Path
    ) -> None:
        containment.validate_integrity()
        boot = self._observe_legacy_boot()
        if boot.machine_sha256 != containment.boot.machine_sha256 or (
            not boot.same_boot(containment.boot) and boot.booted_at <= containment.boot.booted_at
        ):
            raise LegacyRescuePrerequisiteError(
                code="LOCAL_IDENTITY_CHANGED",
                safe_message="原执行所在电脑或启动依据已变化, 保留进度并重新准备恢复方案。",
                next_action="由工程授权者核对原执行所在电脑; 确认后重新准备方案。",
            )
        if containment.method == "operator_confirmed_local_stop":
            sealed = containment.local_execution_survey
            assert sealed is not None
            current = self.local_execution_observer.observe(worktree_root=worktree_root, boot=boot)
            current.require_idle()
            # A later real boot is acceptable to an already supplied local stop
            # declaration. It does not replace the immutable observation or stop history.
            if not sealed.same_boundary(
                current, allow_new_boot=not boot.same_boot(containment.boot)
            ):
                raise LegacyRescuePrerequisiteError(
                    code="LOCAL_IDENTITY_CHANGED",
                    safe_message="当前工作区、电脑、账户或检查范围与恢复方案不一致。",
                    next_action="保留原进度, 由工程授权者核对后重新准备恢复方案。",
                )
        if not boot.same_boot(self._observe_legacy_boot()):
            raise LegacyRescuePrerequisiteError(
                code="LOCAL_OBSERVATION_CHANGED",
                safe_message="检查期间电脑启动会话发生变化, 恢复尚未安排。",
                next_action="请等当前服务稳定后重新准备恢复方案。",
            )

    @contextmanager
    def execution_scope(self) -> Iterator[None]:
        if self._scope_held:
            raise ValueError("执行基线调查不允许嵌套执行")
        with self.guard.task_scope(self.locks_root, self.allocation.task_id):
            if getattr(self, "purpose", None) is BaselinePurpose.REJECTED_CANDIDATE_RESCUE:
                if self.inputs.store is None:
                    raise ValueError("原拒绝候选owner收尾缺少可信完整封存位置")

                def collect_current() -> RejectedCandidateOutputProof:
                    task = self.repository.get(self.allocation.task_id)
                    unfinished = tuple(
                        item
                        for item in self.queue.items_for_task(task.id)
                        if item.status is not WorkItemStatus.CLOSED
                    )
                    if len(unfinished) != 1:
                        raise ValueError("原拒绝候选owner收尾缺少唯一未结束工作")
                    item = unfinished[0]
                    step = self.queue.step(item.id)
                    command = self._proposal_command
                    if command is not None:
                        command.require_current(
                            task,
                            self.repository.current_revision(task.id),
                            item.id,
                            step.boundary.source_revision,
                        )
                        if (
                            command.delivery_id != self.requirement_id
                            or command.purpose != self.purpose
                        ):
                            raise ValueError("工程执行基线事实已变化, 请刷新后重新调查")
                    proof = self._rejected_candidate_output(task, item, step)
                    if proof is None:
                        raise ValueError("原拒绝候选owner收尾缺少完整已停止版本拒绝证明")
                    return proof

                self.queue.settle_rejected_candidate_expired_owner(
                    task_id=self.allocation.task_id,
                    task_lock=self.guard,
                    collect_current=collect_current,
                    seal=self.inputs.store.put_expired_owner_settlement,
                )
            with self.queue.idle_task_scope(self.allocation.task_id) as cursor:
                self._scope_held = True
                self._idle_cursor = cursor
                try:
                    yield
                finally:
                    self._scope_held = False
                    self._idle_cursor = None

    def publish_completion(
        self, plan: ExecutionBaselinePlan, binding: ExecutionBaselineBinding
    ) -> None:
        if not self._scope_held or self._idle_cursor is None:
            raise ValueError("基线队列接续缺少原持锁执行范围和 SQL 屏障")
        if binding.task_id != self.allocation.task_id or binding.scope != self.scope:
            raise ValueError("基线队列接续不属于当前需求和原批准范围")
        require_rejected_candidate_binding(plan, binding)
        from ai_software_engineer.work_queue.baseline import consume_baseline

        def validate_new_consumption() -> None:
            if not self._scope_held or self._idle_cursor is None:
                raise ValueError("旧执行救援缺少原持锁执行和队列屏障")
            if (
                plan.facts.stopped_execution is not None
                or plan.facts.legacy_containment is not None
            ):
                if self.inputs.store is None:
                    raise ValueError("恢复消费缺少精确原调查记录")
                original = self.inputs.store.records.get(
                    "baseline-quiescence",
                    plan.facts.quiescence_proof_sha256,
                    BaselineQuiescenceProof,
                )
                if digest(original.to_wire()) != plan.facts.quiescence_proof_sha256:
                    raise ValueError("恢复消费的原调查摘要不一致")
                task = self.repository.get(plan.facts.task.id)
                current = self._invocations(
                    task,
                    self.queue.items_for_task(task.id),
                    self._receipts(task),
                    tuple(
                        assignment
                        for assignment in self.queue.list_assignments()
                        if assignment.task_id == task.id
                    ),
                    legacy=plan.facts.legacy_containment,
                    stopped_execution=plan.facts.stopped_execution,
                )
                if current != original.invocations:
                    raise ValueError("恢复消费前原调用或重领观察事实已变化, 原现场保留")
            if plan.purpose is BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION:
                require_knowledge_isolation_binding(plan, binding)
                isolation_proof = plan.facts.knowledge_isolation
                assert isolation_proof is not None
                self._reread_knowledge_isolation(
                    isolation_proof,
                    self.repository.get(isolation_proof.task_id),
                    self.queue.get(isolation_proof.work_item_id),
                )
                self._verify_knowledge_isolation_boundary(isolation_proof)
                for capture in (plan.dirty_capture, plan.complete_capture):
                    self.git.verify_mutations(
                        capture.to_capture(),
                        plan.facts.permissions,
                        denied_paths=plan.facts.denied_paths,
                    )
                if capture_mutation_inventory(Path(binding.worktree_path)) != plan.before_inventory:
                    raise ValueError("当前知识隔离的完整现场已变化")
            if plan.purpose is BaselinePurpose.CONTEXT_CAPACITY_RESUME:
                require_context_capacity_binding(plan, binding)
                if self.collect(plan.target_base_ref) != plan.facts:
                    raise ValueError("容量恢复的完整原调用或当前队列事实已变化, 原现场保留")
                for capture in (plan.dirty_capture, plan.complete_capture):
                    self.git.verify_mutations(
                        capture.to_capture(),
                        plan.facts.permissions,
                        denied_paths=plan.facts.denied_paths,
                    )
                if (
                    capture_mutation_inventory(Path(plan.dirty_capture.worktree_path))
                    != plan.before_inventory
                ):
                    raise ValueError("容量恢复的完整保留进度已变化, 请重新准备方案")
            if plan.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                containment = plan.facts.legacy_containment
                if (
                    containment is None
                    or binding.legacy_containment_sha256 != containment.containment_sha256
                ):
                    raise ValueError("救援绑定与原精确检查事实不同, 原现场和工程决定保留")
                self._verify_legacy_observation(
                    containment, worktree_root=Path(plan.dirty_capture.worktree_path)
                )
                self.git.verify_mutations(
                    plan.dirty_capture.to_capture(),
                    plan.facts.permissions,
                    denied_paths=plan.facts.denied_paths,
                )
                self.git.verify_mutations(
                    plan.complete_capture.to_capture(),
                    plan.facts.permissions,
                    denied_paths=plan.facts.denied_paths,
                )
                inventory = capture_mutation_inventory(Path(plan.dirty_capture.worktree_path))
                if inventory != plan.before_inventory:
                    raise ValueError("救援封存后工作现场已变化, 保留文件并重新检查工程方案")
                require_complete_legacy_inventory(self.git, plan.dirty_capture, inventory)
                self._verify_legacy_observation(
                    containment, worktree_root=Path(plan.dirty_capture.worktree_path)
                )
            if plan.facts.stopped_execution is not None:
                task = self.repository.get(plan.facts.task.id)
                item = self.queue.get(plan.facts.work_item_id)
                if (
                    self._stopped_execution(task, item, self.queue.step(item.id))
                    != plan.facts.stopped_execution
                ):
                    raise ValueError("未知结果停止恢复的原核验事实已变化")
                inventory = capture_mutation_inventory(Path(binding.worktree_path))
                if (
                    inventory != plan.before_inventory
                    or inventory.sha256 != binding.after_inventory_sha256
                ):
                    raise ValueError("未知结果停止恢复的完整现场已变化")
                for capture in (plan.dirty_capture, plan.complete_capture):
                    self.git.verify_mutations(
                        capture.to_capture(),
                        plan.facts.permissions,
                        denied_paths=plan.facts.denied_paths,
                    )
                require_stopped_coder_workspace(
                    plan.facts.stopped_execution,
                    plan.dirty_capture,
                    inventory,
                    plan.facts.permissions,
                    plan.facts.denied_paths,
                )
            if plan.facts.completed_output is not None:
                task = self.repository.get(plan.facts.task.id)
                item = self.queue.get(plan.facts.work_item_id)
                if (
                    self._completed_output(task, item, self.queue.step(item.id))
                    != plan.facts.completed_output
                ):
                    raise ValueError("已结束执行的原核验事实发生变化, 恢复尚未安排")
                proof = plan.facts.completed_output
                require_completed_output_workspace(
                    proof,
                    plan.dirty_capture,
                    plan.before_inventory,
                    plan.facts.permissions,
                    plan.facts.denied_paths,
                )
                inventory = capture_mutation_inventory(Path(binding.worktree_path))
                if inventory.sha256 != binding.after_inventory_sha256:
                    raise ValueError("未接纳产出接续后的完整现场已变化, 原草稿和失败记录保留")
                if plan.purpose is BaselinePurpose.COMPLETED_OUTPUT_RESCUE:
                    self.git.verify_mutations(
                        plan.dirty_capture.to_capture(),
                        plan.facts.permissions,
                        denied_paths=plan.facts.denied_paths,
                    )
                    self.git.verify_mutations(
                        plan.complete_capture.to_capture(),
                        plan.facts.permissions,
                        denied_paths=plan.facts.denied_paths,
                    )
                    if inventory != plan.before_inventory:
                        raise ValueError("恢复封存后工作现场已变化, 保留文件并重新检查方案")
                else:
                    source_reference = replace(
                        plan.dirty_capture.to_capture().worktree,
                        head_revision=binding.execution_source_revision,
                    )
                    current_capture = self.git.capture_mutations(
                        source_reference,
                        plan.facts.permissions,
                        denied_paths=plan.facts.denied_paths,
                        retained_source_paths=plan.dirty_capture.to_capture().changed_paths,
                    )
                    if (
                        current_capture.worktree.head_revision != binding.execution_source_revision
                        or current_capture.worktree.branch != binding.branch_name
                        or current_capture.patch != plan.prepared_dirty_patch.encode("utf-8")
                        or current_capture.index_diff_sha256 != hashlib.sha256(b"").hexdigest()
                        or capture_mutation_inventory(Path(binding.worktree_path)) != inventory
                    ):
                        raise ValueError("未接纳产出基线更新后的源版本、完整草稿或 index 已变化")

            if plan.facts.rejected_candidate_output is not None:
                task = self.repository.get(plan.facts.task.id)
                item = self.queue.get(plan.facts.work_item_id)
                rejected_proof = plan.facts.rejected_candidate_output
                if (
                    self._rejected_candidate_output(task, item, self.queue.step(item.id))
                    != rejected_proof
                ):
                    raise ValueError("原版本拒绝候选、执行停止或发布事实已变化, 原现场保留")
                for capture in (plan.dirty_capture, plan.complete_capture):
                    self.git.verify_mutations(
                        capture.to_capture(),
                        plan.facts.permissions,
                        denied_paths=plan.facts.denied_paths,
                    )
                inventory = capture_mutation_inventory(Path(binding.worktree_path))
                if (
                    inventory != plan.before_inventory
                    or inventory != rejected_proof.inventory
                    or inventory.sha256 != binding.after_inventory_sha256
                ):
                    raise ValueError("原版本拒绝候选的完整干净现场已变化, 恢复尚未安排")

            if plan.facts.stopped_provider_failure is not None:
                task = self.repository.get(plan.facts.task.id)
                item = self.queue.get(plan.facts.work_item_id)
                if (
                    self._stopped_provider_failure(task, item, self.queue.step(item.id))
                    != plan.facts.stopped_provider_failure
                ):
                    raise ValueError("提供方前提失败的原核验事实已变化, 恢复尚未安排")
                inventory = capture_mutation_inventory(Path(binding.worktree_path))
                if inventory.sha256 != binding.after_inventory_sha256:
                    raise ValueError("提供方前提失败恢复后的完整现场已变化, 保留原文件")
                if plan.purpose is BaselinePurpose.STOPPED_PROVIDER_RETRY:
                    self.git.verify_mutations(
                        plan.dirty_capture.to_capture(),
                        plan.facts.permissions,
                        denied_paths=plan.facts.denied_paths,
                    )
                    self.git.verify_mutations(
                        plan.complete_capture.to_capture(),
                        plan.facts.permissions,
                        denied_paths=plan.facts.denied_paths,
                    )
                    if inventory != plan.before_inventory:
                        raise ValueError("提供方前提失败恢复封存后现场已变化, 请重新准备方案")
                    require_stopped_provider_workspace(
                        plan.facts.stopped_provider_failure,
                        plan.dirty_capture,
                        inventory,
                        plan.facts.permissions,
                        plan.facts.denied_paths,
                    )
                else:
                    reference = self.git.inspect(plan.dirty_capture.to_capture().worktree)
                    if reference.head_revision != binding.execution_source_revision:
                        raise ValueError("提供方前提失败基线更新后的代码版本已变化")

            if plan.facts.stopped_failure is not None:
                task = self.repository.get(plan.facts.task.id)
                item = self.queue.get(plan.facts.work_item_id)
                if (
                    self._stopped_failure(task, item, self.queue.step(item.id))
                    != plan.facts.stopped_failure
                ):
                    raise ValueError("原执行失败的原核验事实已变化, 恢复尚未安排")
                inventory = capture_mutation_inventory(Path(binding.worktree_path))
                if (
                    inventory != plan.before_inventory
                    or inventory.sha256 != binding.after_inventory_sha256
                ):
                    raise ValueError("原执行失败恢复后的完整现场已变化, 保留原文件")
                for capture in (plan.dirty_capture, plan.complete_capture):
                    self.git.verify_mutations(
                        capture.to_capture(),
                        plan.facts.permissions,
                        denied_paths=plan.facts.denied_paths,
                    )
                require_stopped_failure_workspace(
                    plan.facts.stopped_failure,
                    plan.dirty_capture,
                    inventory,
                    plan.facts.permissions,
                    plan.facts.denied_paths,
                )

        consume_baseline(
            self.queue,
            plan,
            binding,
            cursor=self._idle_cursor,
            validate_new_consumption=validate_new_consumption,
        )

    def publish_continuation(
        self, binding: ExecutionBaselineBinding, authority: BaselineContinueAuthorization
    ) -> bool:
        if not self._scope_held or self._idle_cursor is None or self.inputs.store is None:
            raise ValueError("工程继续缺少原持锁执行范围和 SQL 屏障")
        store = self.inputs.store

        def validate_new_release() -> None:
            facts = self.collect(binding.execution_base_ref)
            if (
                facts.task.id,
                facts.task_revision,
                facts.work_item_id,
                facts.checkpoint_sequence,
            ) != (
                authority.task_id,
                authority.task_revision,
                authority.work_item_id,
                authority.checkpoint_sequence,
            ):
                raise ValueError("暂停工作项或任务版本已变化, 请重新查看当前输入")
            worktree = self.source_worktree(facts)
            if (str(worktree.path), worktree.head_revision) != (
                binding.worktree_path,
                binding.execution_source_revision,
            ) or capture_mutation_inventory(worktree.path).sha256 != binding.after_inventory_sha256:
                raise ValueError("保留现场已变化, 不能沿用原继续决定; 文件保持")
            plan = store.plan(binding.plan_sha256)
            for previous in store.bindings_for_task(binding.task_id):
                if previous.purpose is BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION:
                    isolated = store.plan(previous.plan_sha256).facts.knowledge_isolation
                    if isolated is None:
                        raise ValueError("历史知识隔离缺少精确原调查")
                    self._verify_knowledge_isolation_boundary(isolated)
                if previous.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                    saved = store.plan(previous.plan_sha256).facts.legacy_containment
                    if saved is None:
                        raise ValueError("原救援缺少完整实际停止前提, 保留进度")
                    self._verify_legacy_observation(saved, worktree_root=worktree.path)
            if binding.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                self.git.verify_mutations(
                    plan.dirty_capture.to_capture(),
                    facts.permissions,
                    denied_paths=facts.denied_paths,
                )
                self.git.verify_mutations(
                    plan.complete_capture.to_capture(),
                    facts.permissions,
                    denied_paths=facts.denied_paths,
                )
                return
            capture = self.git.capture_mutations(
                worktree,
                facts.permissions,
                denied_paths=facts.denied_paths,
                retained_source_paths=plan.dirty_capture.to_capture().changed_paths,
            )
            if capture.index_diff_sha256 != hashlib.sha256(b"").hexdigest():
                raise ValueError("保留现场暂存区已变化, 不能沿用原继续决定")
            from ai_software_engineer.git.baseline import GitExecutionBaselineAdapter

            adapter = GitExecutionBaselineAdapter(self.git)
            if (
                adapter._tree_for_worktree(
                    worktree.head_revision,
                    worktree.path,
                    facts.permissions,
                    facts.denied_paths,
                    worktree,
                    retained_source_paths=plan.dirty_capture.to_capture().changed_paths,
                )
                != plan.prepared_dirty_tree
            ):
                raise ValueError("保留的完整草稿与获批方案不同, 请重新检查")

        released = self.queue.release_baseline_pause(
            binding,
            authority,
            cursor=self._idle_cursor,
            validate_new_release=validate_new_release,
        )
        if released:
            return True
        if self.queue.pending_baseline_release(binding, authority, cursor=self._idle_cursor):
            validate_new_release()
            return True
        return False

    def collect(self, target_base_ref: str | None) -> BaselineExecutionFacts:
        if not self._scope_held:
            raise ValueError("执行基线调查缺少真实停机锁和队列屏障")
        task = self.repository.get(self.allocation.task_id)
        revision = self.repository.current_revision(task.id)
        if not task_matches_dispatch(task, self.allocation.task) or (
            task.repository != self.scope.repository_root
            or task.metadata.get("repository_id") != self.scope.repository_id
            or (task.engineering_policy is not None and task.engineering_policy.scope != self.scope)
            or task.status is not TaskStatus.IMPLEMENTING
        ):
            raise ValueError("执行基线调查与原批准范围或当前 Coder checkpoint 不一致")
        admission = self.queue.admission(task.id)
        if admission is None or admission.allocation_sha256 != self.allocation.dispatch_sha256:
            raise ValueError("执行基线缺少原分配的真实队列接纳记录")
        items = self.queue.items_for_task(task.id)
        current = tuple(item for item in items if item.status is not WorkItemStatus.CLOSED)
        if len(current) != 1:
            raise ValueError("执行基线必须对应唯一尚未结束的 Coder 工作项")
        item = current[0]
        if (
            self.purpose is BaselinePurpose.REJECTED_CANDIDATE_RESCUE
            and item.status is not WorkItemStatus.RUNNING
        ):
            raise ValueError("原版本拒绝候选恢复需要精确原运行工作项")
        if (
            item.status in {WorkItemStatus.LEASED, WorkItemStatus.RUNNING}
            and not (
                item.status is WorkItemStatus.RUNNING
                and self.purpose is BaselinePurpose.REJECTED_CANDIDATE_RESCUE
            )
        ) or (
            item.task_id,
            item.repository_id,
            item.role,
            item.checkpoint_sequence,
        ) != (task.id, self.scope.repository_id, AgentRole.CODER, revision):
            raise ValueError("Coder 工作项仍在执行或已偏离当前 Task checkpoint")
        step = self.queue.step(item.id)
        self._require_step(item, step)
        artifacts = self.artifacts.list_for_task(task.id)
        plan = _latest(artifacts, PlanArtifact)
        previous_source = self.inputs.current(task, implementation=None, progress=None)
        implementation = latest_accepted_artifact(
            artifacts,
            ImplementationReportArtifact,
            excluded_artifact_ids=previous_source.superseded_artifact_ids,
        )
        progress = latest_accepted_artifact(
            artifacts,
            CoderProgressArtifact,
            excluded_artifact_ids=previous_source.superseded_artifact_ids,
        )
        progress = _active_progress(progress, implementation, artifacts)
        if plan is None:
            raise ValueError("执行基线调查缺少已接纳的原始交付计划")
        for artifact in artifacts:
            if (
                not artifact.integrity.validated
                or artifact_digest(artifact) != artifact.integrity.sha256
            ):
                raise ValueError("执行基线输入产物完整性异常")
        source = self.inputs.current(task, implementation=implementation, progress=progress)
        if step.boundary.source_revision != source.source_revision:
            raise ValueError("Coder 队列源版本与当前已接纳输入不一致")
        if self.purpose in {
            BaselinePurpose.COMPLETED_OUTPUT_RESCUE,
            BaselinePurpose.REJECTED_CANDIDATE_RESCUE,
            BaselinePurpose.STOPPED_PROVIDER_RETRY,
            BaselinePurpose.STOPPED_FAILURE_RETRY,
            BaselinePurpose.STOPPED_EXECUTION_RESCUE,
            BaselinePurpose.CONTEXT_CAPACITY_RESUME,
            BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION,
        }:
            if target_base_ref is not None and target_base_ref != source.execution_base_ref:
                raise ValueError(
                    "容量恢复不能更换当前代码基线"
                    if self.purpose is BaselinePurpose.CONTEXT_CAPACITY_RESUME
                    else "已结束执行恢复不能更换当前代码基线"
                )
            target_base_ref = source.execution_base_ref
            if (
                implementation is not None
                and self.purpose is not BaselinePurpose.CONTEXT_CAPACITY_RESUME
            ):
                raise ValueError("已有接纳候选不能改为未接纳执行恢复")
        elif target_base_ref is None:
            raise ValueError("执行基线调查缺少精确目标版本")
        self._collect_proposal_facts(task, revision, step, source.source_revision, target_base_ref)
        if self.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE and (
            target_base_ref != source.execution_base_ref or implementation is not None
        ):
            raise ValueError("旧执行救援只能保留原代码基线和草稿, 不能覆盖已接纳候选")
        target_rules = native_rules_at_revision(
            self.git, repository_id=self.scope.repository_id, revision=target_base_ref
        )
        epoch = self.inputs.native_rule_epoch(source)
        frozen_rules = tuple(
            sorted(
                epoch.rules if epoch is not None else self.native_rules,
                key=lambda rule: rule.relative_path,
            )
        )
        if self.inputs.store is None:
            raise ValueError("执行基线缺少可信 append-only 事实存储")
        if (
            self.purpose
            in {
                BaselinePurpose.LEGACY_WORKSPACE_RESCUE,
                BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION,
            }
            and target_rules != frozen_rules
        ):
            raise ValueError("旧执行救援不能同时替换原规范, 请先保留进度并暂停")
        change = build_native_rule_change(
            git=self.git,
            records=self.inputs.store.records,
            scope=self.scope,
            task_id=task.id,
            source_revision=source.execution_base_ref,
            target_base_ref=target_base_ref,
            source_rules=frozen_rules,
            target_rules=target_rules,
            structured_project_rules=self.structured_project_rules,
        )
        assignments = tuple(
            assignment
            for assignment in self.queue.list_assignments()
            if assignment.task_id == task.id
        )
        receipts = self._receipts(task)
        rejected_candidate_output = (
            self._rejected_candidate_output(task, item, step)
            if self.purpose is BaselinePurpose.REJECTED_CANDIDATE_RESCUE
            else None
        )
        if (
            self.purpose is BaselinePurpose.REJECTED_CANDIDATE_RESCUE
            and rejected_candidate_output is None
        ):
            raise ValueError("原执行不符合精确已停止且版本拒绝的完整候选恢复前提")
        legacy = (
            self._legacy_containment(task, item)
            if self.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE
            else None
        )
        stopped_execution = (
            self._stopped_execution(task, item, step)
            if self.purpose is BaselinePurpose.STOPPED_EXECUTION_RESCUE
            else None
        )
        if self.purpose is BaselinePurpose.STOPPED_EXECUTION_RESCUE and stopped_execution is None:
            raise ValueError("原执行不符合完整已停止且无结果的精确恢复前提, 原现场保留")
        knowledge_isolation = (
            self._knowledge_isolation(task, item, step)
            if self.purpose is BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION
            else None
        )
        invocation_proofs = self._invocations(
            task,
            items,
            receipts,
            assignments,
            legacy=legacy,
            stopped_execution=stopped_execution,
            knowledge_isolation=knowledge_isolation,
        )
        completed_output = (
            self._completed_output(task, item, step)
            if not any(receipt.original_work_item_id == item.id for receipt in receipts)
            and rejected_candidate_output is None
            else None
        )
        if self.purpose is BaselinePurpose.COMPLETED_OUTPUT_RESCUE and completed_output is None:
            raise ValueError("原执行不符合已结束且报告未接纳的精确恢复前提, 原状态和现场保留")
        stopped_provider_failure = (
            self._stopped_provider_failure(task, item, step)
            if not any(receipt.original_work_item_id == item.id for receipt in receipts)
            and legacy is None
            and completed_output is None
            else None
        )
        if (
            self.purpose is BaselinePurpose.STOPPED_PROVIDER_RETRY
            and stopped_provider_failure is None
        ):
            raise ValueError("原执行不符合已停止的提供方前提失败恢复条件, 原状态和现场保留")
        stopped_failure = (
            self._stopped_failure(task, item, step)
            if self.purpose is BaselinePurpose.STOPPED_FAILURE_RETRY
            and not any(receipt.original_work_item_id == item.id for receipt in receipts)
            and legacy is None
            and completed_output is None
            and stopped_provider_failure is None
            else None
        )
        if self.purpose is BaselinePurpose.STOPPED_FAILURE_RETRY and stopped_failure is None:
            raise ValueError("原执行不符合精确已停止失败恢复条件, 原状态和现场保留")
        reservation = self._reservation(
            task,
            item,
            receipts,
            legacy=legacy,
            completed_output=completed_output,
            rejected_candidate_output=rejected_candidate_output,
            stopped_provider_failure=stopped_provider_failure,
            stopped_failure=stopped_failure,
            stopped_execution=stopped_execution,
            knowledge_isolation=knowledge_isolation,
        )
        current_capacity = self._current_capacity_receipt(task, item, invocation_proofs)
        proof = BaselineQuiescenceProof(
            task_id=task.id,
            task_revision=revision,
            task_snapshot_sha256=digest(task.to_wire()),
            task_events_sha256=digest(
                [event.to_wire() for event in self.repository.list_events(task.id)]
            ),
            allocation_sha256=self.allocation.dispatch_sha256,
            queue_snapshot_sha256=digest([queued.to_wire() for queued in items]),
            assignments_sha256=digest([assignment.to_wire() for assignment in assignments]),
            invocations=invocation_proofs,
        )
        if self.inputs.store is None:
            raise ValueError("执行基线缺少可信 append-only 事实存储")
        self.inputs.store.records.put("baseline-quiescence", digest(proof.to_wire()), proof)
        previous = source.baseline.resolved_interruption_receipt_sha256s if source.baseline else ()
        resolved = tuple(
            dict.fromkeys((*previous, *(receipt.receipt_sha256 for receipt in receipts)))
        )
        values = BaselineExecutionFacts(
            task=task,
            scope=self.scope,
            task_revision=revision,
            work_item_id=item.id,
            checkpoint_sequence=item.checkpoint_sequence,
            quiescence_proof_sha256=digest(proof.to_wire()),
            runtime_manifest_sha256=self.runtime_manifest_sha256,
            source_native_rules_sha256=digest([rule.to_wire() for rule in frozen_rules]),
            target_native_rules_sha256=digest([rule.to_wire() for rule in target_rules]),
            native_rule_change=change,
            source_artifact_ids=tuple(sorted(artifact.artifact_id for artifact in artifacts)),
            implementation_artifact_id=implementation.artifact_id if implementation else None,
            progress_artifact_id=progress.artifact_id if progress else None,
            resolved_interruption_receipt_sha256s=resolved,
            continuation=reservation,
            legacy_containment=legacy,
            knowledge_isolation=knowledge_isolation,
            completed_output=completed_output,
            rejected_candidate_output=rejected_candidate_output,
            stopped_provider_failure=stopped_provider_failure,
            stopped_failure=stopped_failure,
            stopped_execution=stopped_execution,
            context_capacity_receipt_sha256=current_capacity,
            permissions=self.permissions,
            denied_paths=task.constraints.denied_paths if task.constraints else (),
            facts_sha256="0" * 64,
        )
        return values.model_copy(
            update={
                "facts_sha256": digest(values.model_dump(mode="json", exclude={"facts_sha256"}))
            }
        )

    def completed_task(self, binding: ExecutionBaselineBinding) -> Task:
        if (
            not self._scope_held
            or binding.scope != self.scope
            or binding.task_id != self.allocation.task_id
        ):
            raise ValueError("已完成基线未绑定当前持锁需求")
        task = self.repository.get(binding.task_id)
        if not task_matches_dispatch(task, self.allocation.task):
            raise ValueError("已完成基线的原批准范围发生变化")
        binding.require_task(task)
        return task

    def source_worktree(self, facts: BaselineExecutionFacts) -> WorktreeRef:
        if not self._scope_held or facts.task.id != self.allocation.task_id:
            raise ValueError("执行基线工作区不属于当前持锁需求")
        if facts.rejected_candidate_output is not None:
            proof = facts.rejected_candidate_output
            proof.validate_for(
                facts.task,
                self.queue.step(facts.work_item_id),
                self.scope,
                facts.permissions,
                facts.denied_paths,
            )
            reference = self.git.recover(
                WorktreeSpec(
                    task_id=facts.task.id,
                    role=AgentRole.CODER,
                    attempt=1,
                    source_revision=proof.candidate_revision,
                )
            )
            if str(reference.path) != proof.capture_start.worktree_path:
                raise ValueError("原拒绝候选工作区位置已变化")
            return reference
        artifacts = self.artifacts.list_for_task(facts.task.id)
        previous_source = self.inputs.current(facts.task, implementation=None, progress=None)
        implementation = latest_accepted_artifact(
            artifacts,
            ImplementationReportArtifact,
            excluded_artifact_ids=previous_source.superseded_artifact_ids,
        )
        progress = latest_accepted_artifact(
            artifacts,
            CoderProgressArtifact,
            excluded_artifact_ids=previous_source.superseded_artifact_ids,
        )
        progress = _active_progress(progress, implementation, artifacts)
        source = self.inputs.current(facts.task, implementation=implementation, progress=progress)
        spec = WorktreeSpec(
            task_id=facts.task.id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=source.source_revision,
        )
        try:
            return self.git.recover(spec)
        except WorktreeNotFound:
            # Preflight can stop before RoleAwareAgentAdapter creates any checkout.
            # This is the first clean checkout, never reconstruction of lost work.
            invocation_root = self.state / "invocations"
            starts = (
                KnowledgeRecordStore(invocation_root, read_only=True).list(
                    "invocation-starts", DeliveryInvocationStart
                )
                if invocation_root.is_dir()
                else ()
            )
            coder_starts = tuple(
                start
                for start in starts
                if start.request.task_id == facts.task.id and start.request.role is AgentRole.CODER
            )
            confirmed_no_start = bool(coder_starts) and all(
                (
                    outcome := KnowledgeRecordStore(invocation_root, read_only=True).find(
                        "invocation-outcomes", start.work_item_id, DeliveryInvocationOutcome
                    )
                )
                is not None
                and outcome.start == start
                and outcome.service_pause is not None
                and outcome.service_pause.admission_closed
                for start in coder_starts
            )
            if (
                facts.continuation is None
                or facts.continuation.retry_cause not in {"uninvoked", "service_pause"}
                or (facts.continuation.retry_cause == "service_pause" and not confirmed_no_start)
                or implementation is not None
                or progress is not None
                or source.baseline is not None
                or source.source_revision != facts.task.base_ref
                or self._receipts(facts.task)
                or any(
                    start.request.task_id == facts.task.id
                    and start.request.role is AgentRole.CODER
                    and not confirmed_no_start
                    for start in starts
                )
            ):
                raise ValueError("已开始执行的 Coder 工作区缺失, 保留历史并等待工程调查") from None
            # Git.create rejects any surviving branch, unsafe path or registration.
            return self.git.create(spec)

    def _require_step(self, item: QueuedWorkItem, step: QueuedRoleStep) -> None:
        if step.allocation_sha256 != self.allocation.dispatch_sha256 or (
            item.id,
            item.task_id,
            item.repository_id,
            item.role,
            item.attempt,
            item.checkpoint_sequence,
        ) != (
            step.work_item.id,
            step.work_item.task_id,
            step.work_item.repository_id,
            step.boundary.role,
            step.boundary.attempt,
            step.boundary.checkpoint_sequence,
        ):
            raise ValueError("执行基线队列工作项与原分配不一致")

    def _receipts(self, task: Task) -> tuple[ExecutionInterruptionReceipt, ...]:
        root = self.state / "continuations" / task.id
        if not root.exists():
            return ()
        receipts = FileContinuationStore(root, task_id=task.id).receipts_for_task(task.id)
        for receipt in receipts:
            policy = task.interruption_continuation_policy
            if (
                (
                    receipt.scope.team_id,
                    receipt.scope.project_id,
                    receipt.scope.repository_id,
                    receipt.scope.requirement_id,
                    receipt.scope.dispatch_sha256,
                    receipt.task_intent_sha256,
                    receipt.request.permissions,
                )
                != (
                    self.scope.team_id,
                    self.scope.project_id,
                    self.scope.repository_id,
                    self.requirement_id,
                    self.allocation.dispatch_sha256,
                    task_intent_sha256(task),
                    self.permissions,
                )
                or policy is None
                or receipt.policy_sha256 != policy.policy_sha256
            ):
                raise ValueError("原停机记录未绑定原需求、分配和冻结权限")
            self._require_stopped(receipt.process_stop, receipt.request)
        return receipts

    def _reclaimed_uninvoked_claims(
        self,
        task: Task,
        item: QueuedWorkItem,
        claims: tuple[QueueClaim, ...],
        start: DeliveryInvocationStart | None,
        legacy: LegacyExecutionContainment | None,
    ) -> tuple[ReclaimedUninvokedClaimObservation, ...]:
        if not claims or start is None:
            return ()
        next_claim = self.queue.original_claim(start.lease_id)
        if legacy is None:
            historical = self._historical_legacy(task, start, next_claim)
            legacy = historical[0] if historical is not None else None
        if legacy is None or legacy.original_start != start:
            return ()
        cursor = self._idle_cursor
        if not self._scope_held or cursor is None:
            raise ValueError("回收 claim 调查缺少任务锁和队列屏障")
        if (
            next_claim != legacy.original_claim
            or next_claim.work_item.dispatch_sequence != item.dispatch_sequence
            or next_claim.claimed_at > start.started_at
        ):
            raise ValueError("回收 claim 后续调用与真实领取事实不一致")
        result: list[ReclaimedUninvokedClaimObservation] = []
        for claim in claims:
            if claim.lease.id == start.lease_id:
                continue
            if self.queue.original_claim(claim.lease.id) != claim:
                raise ValueError("回收 claim 原始领取事实已变化")
            if (
                claim.work_item.id != item.id
                or claim.work_item.task_id != task.id
                or claim.work_item.role is not item.role
                or claim.work_item.attempt != item.attempt
                or claim.work_item.checkpoint_sequence != item.checkpoint_sequence
                or claim.work_item.dispatch_sequence + 1 != next_claim.work_item.dispatch_sequence
            ):
                continue  # Other preflight/knowledge facts retain their existing gates.
            preflight_root = self.state / "delivery-preflight"
            preflight_receipts: tuple[DeliveryPreflightReceipt, ...] = ()
            if CapacityInputReader._capacity_ledger_exists(preflight_root):
                preflight = KnowledgeRecordStore(preflight_root, read_only=True)
                preflight_receipts = preflight.list("preflight-receipts", DeliveryPreflightReceipt)
                if any(
                    value.lease_id == claim.lease.id
                    for value in preflight.list(
                        "preflight-checkpoints", DeliveryPreflightCheckpoint
                    )
                ) or any(
                    value.lease_id == claim.lease.id
                    for value in preflight.list("context-capacity-receipts", ContextCapacityReceipt)
                ):
                    continue
            step = self.queue.step_for_claim(claim)
            self._require_step(item, step)
            if step.boundary.source_revision != start.request.source_revision:
                raise ValueError("回收 claim 与后续调用源版本不一致")
            cursor.execute(
                "SELECT lease_id,work_item_id,task_id,state,expires_at,ended_at "
                "FROM work_queue_claims WHERE lease_id=%s",
                (claim.lease.id,),
            )
            rows = cursor.fetchall()
            if len(rows) != 1:
                raise ValueError("回收 claim 缺少唯一租约状态")
            row = rows[0]
            ended_at = datetime.fromisoformat(str(row["ended_at"]))
            expires_at = datetime.fromisoformat(str(row["expires_at"]))
            if row["state"] == "RELEASED":
                continue  # An independently consumed wait has its own proof path.
            if (
                row["lease_id"] != claim.lease.id
                or row["work_item_id"] != item.id
                or row["task_id"] != task.id
                or row["state"] != "EXPIRED"
                or ended_at.tzinfo is None
                or expires_at.tzinfo is None
                or not (
                    claim.claimed_at
                    < claim.lease.expires_at
                    <= expires_at
                    <= ended_at
                    < next_claim.claimed_at
                    <= start.started_at
                )
            ):
                raise ValueError("回收 claim 租约结束或后续领取时序不可验证")
            for receipt in preflight_receipts:
                receipt.validate_integrity()
                if (
                    receipt.task_id == task.id
                    and receipt.scope.team_id == self.scope.team_id
                    and receipt.scope.project_id == self.scope.project_id
                    and receipt.scope.repository_id == self.scope.repository_id
                    and receipt.scope.requirement_id == self.requirement_id
                    and receipt.source_revision == start.request.source_revision
                    and claim.claimed_at <= receipt.checked_at <= ended_at
                ):
                    raise ValueError("回收 claim 已有执行前检查收据, 不能证明未调用")
            cursor.execute(
                "SELECT sequence,event_type,work_item_id,lease_id,from_status,to_status,"
                "occurred_at,payload_json FROM work_queue_events "
                "WHERE lease_id=%s AND event_type='LEASE_EXPIRED'",
                (claim.lease.id,),
            )
            events = cursor.fetchall()
            if len(events) != 1:
                raise ValueError("回收 claim 缺少唯一过期事件")
            event = events[0]
            occurred_at = datetime.fromisoformat(str(event["occurred_at"]))
            payload = TypeAdapter(dict[str, JsonValue]).validate_json(str(event["payload_json"]))
            if set(payload) != {"work_item", "detail"} or payload["detail"] != {}:
                raise ValueError("回收 claim 事件载荷不完整")
            requeued = QueuedWorkItem.model_validate(payload["work_item"])
            mutable = {
                "status",
                "dispatch_sequence",
                "wait_reason",
                "wait_disposition",
                "available_at",
                "updated_at",
            }
            if (
                not isinstance(event["sequence"], int)
                or event["sequence"] < 1
                or event["event_type"] != "LEASE_EXPIRED"
                or (event["work_item_id"], event["lease_id"]) != (item.id, claim.lease.id)
                or event["from_status"] not in {"LEASED", "RUNNING"}
                or event["to_status"] != "RETRY_SCHEDULED"
                or occurred_at != ended_at
                or requeued.status is not WorkItemStatus.RETRY_SCHEDULED
                or requeued.dispatch_sequence != claim.work_item.dispatch_sequence + 1
                or requeued.wait_reason != f"lease_expired:{claim.lease.id}"
                or requeued.updated_at != ended_at
                or requeued.available_at is None
                or requeued.available_at <= ended_at
                or requeued.model_dump(exclude=mutable)
                != claim.work_item.model_dump(exclude=mutable)
            ):
                raise ValueError("回收 claim 过期事件与真实队列世代不一致")
            cursor.execute(
                "SELECT sequence FROM work_queue_events WHERE lease_id=%s AND event_type='CLAIMED'",
                (next_claim.lease.id,),
            )
            next_events = cursor.fetchall()
            if len(next_events) != 1 or not (event["sequence"] < next_events[0]["sequence"]):
                raise ValueError("回收 claim 事件未先于后续真实领取")
            require_no_knowledge_claim_activity(
                state=self.state,
                task=task,
                item=item,
                scope=self.scope,
                requirement_id=getattr(self, "knowledge_requirement_id", self.requirement_id),
                lease_id=claim.lease.id,
            )
            self._capacity_input_reader().require_claim_not_started(
                UninvokedClaimBoundary(
                    task_id=task.id,
                    work_item_id=item.id,
                    lease_id=claim.lease.id,
                    role=item.role,
                    attempt=item.attempt,
                    checkpoint_sequence=item.checkpoint_sequence,
                    dispatch_sequence=claim.work_item.dispatch_sequence,
                    observed_at=ended_at,
                    run_id=None,
                    context_manifest_id=None,
                ),
                allow_later_claims=True,
            )
            result.append(
                ReclaimedUninvokedClaimObservation.create(
                    lease_id=claim.lease.id,
                    task_id=task.id,
                    work_item_id=item.id,
                    claim_sha256=claim_identity_sha256(claim),
                    next_claim_sha256=claim_identity_sha256(next_claim),
                    blocking_start_sha256=start.start_sha256,
                    dispatch_sequence=claim.work_item.dispatch_sequence,
                    claimed_at=claim.claimed_at,
                    expired_at=ended_at,
                    reclaim_event_sequence=event["sequence"],
                    reclaim_event_sha256=digest(
                        {
                            key: str(value) if key in {"occurred_at", "payload_json"} else value
                            for key, value in event.items()
                        }
                    ),
                )
            )
        return tuple(sorted(result, key=lambda observation: observation.dispatch_sequence))

    def _consumed_recovery_schedule(
        self, task: Task
    ) -> tuple[RecoveryInputScheduleDecision, DeliveryResolution] | None:
        """Reopen the original approved input decision through its full sealed lineage."""
        if not isinstance(self.allocation, RecoveryDispatchRecord):
            return None
        from ai_software_engineer.recovery.models import RecoveryScope
        from ai_software_engineer.recovery.store import FileRecoveryStore

        decision = self.queue.consumed_recovery_input_resolution(task.id)
        if decision is None:
            return None
        plan_sha256 = task.metadata.get("recovery_plan_sha256")
        if not isinstance(plan_sha256, str):
            raise ValueError("已消费预 Context 决定缺少原恢复计划身份")
        recovery = FileRecoveryStore(
            self.state / f"recovery-{self.requirement_id}",
            scope=RecoveryScope(
                team_id=self.scope.team_id,
                repository_id=self.scope.repository_id,
                delivery_id=self.requirement_id,
                repository_root=self.scope.repository_root,
            ),
        )
        plan = recovery.get_plan(plan_sha256)
        authorization = recovery.get_authorization(plan_sha256)
        sealed = recovery.get_task_record(plan_sha256)
        seed = recovery.get_seed(plan_sha256)
        records = KnowledgeRecordStore(self.state / "delivery-waits", read_only=True)
        schedule = require_consumed_recovery_input_schedule(
            self.queue, records, plan, self.allocation, task
        )
        if schedule is None or (
            schedule.authorization_sha256 != authorization.authorization_sha256
            or schedule.task_record_sha256 != sealed.record_sha256
            or schedule.seed_record_sha256 != seed.record_sha256
        ):
            raise ValueError("已消费预 Context 决定缺少精确封存来源")
        return schedule, decision

    def _consumed_pre_context_claim_observations(
        self,
        task: Task,
        item: QueuedWorkItem,
        claims: tuple[QueueClaim, ...],
        start: DeliveryInvocationStart | None,
    ) -> tuple[ConsumedPreContextClaimObservation, ...]:
        if not claims or start is None:
            return ()
        source = self._consumed_recovery_schedule(task)
        if source is None:
            return ()
        schedule, decision = source
        schedule.validate_integrity()
        decision.validate_integrity()
        if schedule.work_item_id != item.id or decision.work_item_id != item.id:
            return ()
        matched = tuple(claim for claim in claims if claim.lease.id == schedule.original_lease_id)
        if len(matched) != 1:
            raise ValueError("已消费预 Context 原 claim 缺失或重复")
        claim = matched[0]
        next_claim = self.queue.original_claim(start.lease_id)
        if (
            not self._scope_held
            or self._idle_cursor is None
            or self.queue.original_claim(claim.lease.id) != claim
            or digest(claim.to_wire()) != schedule.original_claim_sha256
            or next_claim.work_item.id != item.id
            or next_claim.work_item.dispatch_sequence != claim.work_item.dispatch_sequence + 1
            or next_claim.claimed_at >= start.started_at
            or claim.work_item.task_id != task.id
            or claim.work_item.role is not item.role
            or claim.work_item.attempt != item.attempt
            or claim.work_item.checkpoint_sequence != item.checkpoint_sequence
            or schedule.target_base_revision != start.request.source_revision
        ):
            raise ValueError("已消费预 Context 决定与后续真实 claim 不一致")
        step = self.queue.step_for_claim(claim)
        self._require_step(item, step)
        if step.boundary.source_revision != start.request.source_revision:
            raise ValueError("预 Context 原 claim 与后续调用源版本不一致")
        cursor = self._idle_cursor
        cursor.execute(
            "SELECT lease_id,work_item_id,task_id,state,expires_at,ended_at FROM work_queue_claims "
            "WHERE lease_id=%s",
            (claim.lease.id,),
        )
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise ValueError("预 Context 原 claim 缺少唯一释放状态")
        row = rows[0]
        ended_at = datetime.fromisoformat(str(row["ended_at"]))
        expires_at = datetime.fromisoformat(str(row["expires_at"]))
        if (
            row["lease_id"] != claim.lease.id
            or row["work_item_id"] != item.id
            or row["task_id"] != task.id
            or row["state"] != "RELEASED"
            or ended_at.tzinfo is None
            or expires_at.tzinfo is None
            or not claim.claimed_at < ended_at < expires_at
            or ended_at >= next_claim.claimed_at
        ):
            raise ValueError("预 Context 原 claim 的真实租约未释放")
        cursor.execute(
            "SELECT sequence,event_type,work_item_id,lease_id,from_status,to_status,"
            "occurred_at,payload_json FROM work_queue_events WHERE work_item_id=%s "
            "ORDER BY sequence LIMIT 4097",
            (item.id,),
        )
        events = cursor.fetchall()
        if len(events) > 4096:
            raise ValueError("预 Context 原等待事件超过完整观察上限")
        first_events = tuple(event for event in events if event["lease_id"] == claim.lease.id)
        next_events = tuple(event for event in events if event["lease_id"] == next_claim.lease.id)
        waits = tuple(event for event in first_events if event["event_type"] == "WAITING")
        starts = tuple(event for event in first_events if event["event_type"] == "STARTED")
        claimed = tuple(event for event in first_events if event["event_type"] == "CLAIMED")
        later_claimed = tuple(event for event in next_events if event["event_type"] == "CLAIMED")
        resolutions = tuple(
            event
            for event in events
            if event["event_type"] == "WAIT_RESOLVED"
            and isinstance(event["sequence"], int)
            and claimed
            and later_claimed
            and claimed[0]["sequence"] < event["sequence"] < later_claimed[0]["sequence"]
        )
        if any(len(group) != 1 for group in (claimed, starts, waits, resolutions, later_claimed)):
            raise ValueError("预 Context 原 claim 缺少唯一领取、等待或消费事件")
        begin, started, waited, resolved, resumed = (
            claimed[0],
            starts[0],
            waits[0],
            resolutions[0],
            later_claimed[0],
        )
        waited_at = datetime.fromisoformat(str(waited["occurred_at"]))
        resolved_at = datetime.fromisoformat(str(resolved["occurred_at"]))
        begin_at = datetime.fromisoformat(str(begin["occurred_at"]))
        started_at = datetime.fromisoformat(str(started["occurred_at"]))
        resumed_at = datetime.fromisoformat(str(resumed["occurred_at"]))
        if not (
            begin["sequence"]
            < started["sequence"]
            < waited["sequence"]
            < resolved["sequence"]
            < resumed["sequence"]
            and waited_at == ended_at
            and begin_at == claim.claimed_at
            and claim.claimed_at <= started_at <= ended_at
            and ended_at <= resolved_at < next_claim.claimed_at
            and resumed_at == next_claim.claimed_at
            and all(
                event["work_item_id"] == item.id
                for event in (begin, started, waited, resolved, resumed)
            )
            and begin["from_status"] in {"READY", "RETRY_SCHEDULED"}
            and begin["to_status"] == "LEASED"
            and (started["from_status"], started["to_status"]) == ("LEASED", "RUNNING")
            and (waited["from_status"], waited["to_status"]) == ("RUNNING", "WAITING_DEPENDENCY")
            and (resolved["from_status"], resolved["to_status"]) == ("WAITING_DEPENDENCY", "READY")
            and resolved["lease_id"] is None
            and (resumed["from_status"], resumed["to_status"]) == ("READY", "LEASED")
        ):
            raise ValueError("预 Context 原等待与后续调用的事件顺序不一致")
        begin_payload = TypeAdapter(dict[str, JsonValue]).validate_json(str(begin["payload_json"]))
        started_payload = TypeAdapter(dict[str, JsonValue]).validate_json(
            str(started["payload_json"])
        )
        waited_payload = TypeAdapter(dict[str, JsonValue]).validate_json(
            str(waited["payload_json"])
        )
        resolved_payload = TypeAdapter(dict[str, JsonValue]).validate_json(
            str(resolved["payload_json"])
        )
        resumed_payload = TypeAdapter(dict[str, JsonValue]).validate_json(
            str(resumed["payload_json"])
        )
        if any(
            set(payload) != {"work_item", "detail"}
            for payload in (
                begin_payload,
                started_payload,
                waited_payload,
                resolved_payload,
                resumed_payload,
            )
        ):
            raise ValueError("预 Context 原等待事件缺少完整工作项快照")
        begun_item = QueuedWorkItem.model_validate(begin_payload["work_item"])
        started_item = QueuedWorkItem.model_validate(started_payload["work_item"])
        waited_item = QueuedWorkItem.model_validate(waited_payload["work_item"])
        resolved_item = QueuedWorkItem.model_validate(resolved_payload["work_item"])
        resumed_item = QueuedWorkItem.model_validate(resumed_payload["work_item"])
        detail = resolved_payload["detail"]
        if not isinstance(detail, dict):
            raise ValueError("预 Context 原决定缺少完整事件正文")
        beginning = begin_payload["detail"]
        resuming = resumed_payload["detail"]
        if not isinstance(beginning, dict) or not isinstance(resuming, dict):
            raise ValueError("预 Context 领取事件缺少完整原 claim")
        mutable = {
            "status",
            "dispatch_sequence",
            "wait_reason",
            "wait_disposition",
            "available_at",
            "updated_at",
        }
        actual_decision = type(decision).model_validate(detail.get("resolution"))
        actual_decision.validate_integrity()
        disposition = waited_item.wait_disposition
        if (
            set(beginning) != {"queue_claim"}
            or QueueClaim.model_validate(beginning["queue_claim"]) != claim
            or begun_item != claim.work_item
            or started_payload["detail"] != {}
            or started_item.status is not WorkItemStatus.RUNNING
            or started_item.updated_at != started_at
            or started_item.model_dump(exclude={"status", "updated_at"})
            != begun_item.model_dump(exclude={"status", "updated_at"})
            or waited_payload.get("detail") != {}
            or waited_item.id != item.id
            or waited_item.status is not WorkItemStatus.WAITING_DEPENDENCY
            or waited_item.updated_at != waited_at
            or waited_item.dispatch_sequence != claim.work_item.dispatch_sequence
            or waited_item.checkpoint_sequence != claim.work_item.checkpoint_sequence
            or waited_item.model_dump(exclude=mutable)
            != claim.work_item.model_dump(exclude=mutable)
            or disposition is None
            or disposition.facts.classification != "CONTEXT_CAPACITY"
            or any(
                value.startswith("context-capacity://") for value in disposition.facts.evidence_ids
            )
            or disposition.disposition_sha256 != schedule.disposition_sha256
            or resolved_item.id != item.id
            or resolved_item.status is not WorkItemStatus.READY
            or resolved_item.updated_at != resolved_at
            or resolved_item.dispatch_sequence != next_claim.work_item.dispatch_sequence
            or resolved_item.wait_disposition is not None
            or resolved_item.model_dump(exclude=mutable)
            != claim.work_item.model_dump(exclude=mutable)
            or set(resuming) != {"queue_claim"}
            or QueueClaim.model_validate(resuming["queue_claim"]) != next_claim
            or resumed_item != next_claim.work_item
            or resumed_item.model_dump(exclude=mutable)
            != claim.work_item.model_dump(exclude=mutable)
            or detail.get("resolution_sha256") != decision.resolution_sha256
            or detail.get("next_work_item_id") != item.id
            or detail.get("budget_refund") is not False
            or actual_decision != decision
            or schedule.task_id != task.id
        ):
            raise ValueError("预 Context 原等待决定或队列世代未绑定完整封存事实")
        preflight_root = self.state / "delivery-preflight"
        if CapacityInputReader._capacity_ledger_exists(preflight_root):
            preflight = KnowledgeRecordStore(preflight_root, read_only=True)
            if any(
                value.lease_id == claim.lease.id
                for value in preflight.list("preflight-checkpoints", DeliveryPreflightCheckpoint)
            ) or any(
                value.lease_id == claim.lease.id
                for value in preflight.list("context-capacity-receipts", ContextCapacityReceipt)
            ):
                raise ValueError("预 Context 原 claim 已有执行前或容量收据")
            for receipt in preflight.list("preflight-receipts", DeliveryPreflightReceipt):
                receipt.validate_integrity()
                if (
                    receipt.task_id == task.id
                    and receipt.scope.team_id == self.scope.team_id
                    and receipt.scope.project_id == self.scope.project_id
                    and receipt.scope.repository_id == self.scope.repository_id
                    and receipt.scope.requirement_id == self.requirement_id
                    and receipt.source_revision == start.request.source_revision
                    and claim.claimed_at <= receipt.checked_at <= ended_at
                ):
                    raise ValueError("预 Context 原 claim 已有未完成的执行前检查收据")
        context_root = self.state.parent / "contexts"
        if context_root.exists():
            _reject_symlinks(context_root)
            if not context_root.is_dir():
                raise ValueError("预 Context 原 claim 的 Context 目录不可验证")
            paths = tuple(islice(context_root.glob("*.json"), 4097))
            if len(paths) > 4096:
                raise ValueError("预 Context 原 claim 的 Context 清单超过观察上限")
            contexts = FileContextStore(context_root, read_only=True)
            for path in paths:
                _reject_symlinks(path)
                if not path.is_file() or not path.name.startswith("ctx_"):
                    raise ValueError("预 Context 原 claim 的 Context 文件不可验证")
                context = contexts.get(path.stem)
                if context.task_id != task.id or context.role is not AgentRole.CODER:
                    continue
                sections = tuple(
                    section
                    for section in context.sections
                    if section.name == "source:execution.claim"
                )
                if len(sections) != 1 or sections[0].truncated:
                    raise ValueError("预 Context 同任务 Coder 输入缺少真实 claim 身份")
                section = sections[0]
                identity = TypeAdapter(dict[str, JsonValue]).validate_json(section.content)
                if (
                    section.uri == f"claim://{claim.lease.id}"
                    or identity.get("lease_id") == claim.lease.id
                ):
                    raise ValueError("预 Context 原 claim 已有单独封存的 Coder Context")
        require_no_knowledge_claim_activity(
            state=self.state,
            task=task,
            item=item,
            scope=self.scope,
            requirement_id=getattr(self, "knowledge_requirement_id", self.requirement_id),
            lease_id=claim.lease.id,
        )
        self._capacity_input_reader().require_claim_not_started(
            UninvokedClaimBoundary(
                task_id=task.id,
                work_item_id=item.id,
                lease_id=claim.lease.id,
                role=item.role,
                attempt=item.attempt,
                checkpoint_sequence=item.checkpoint_sequence,
                dispatch_sequence=claim.work_item.dispatch_sequence,
                observed_at=ended_at,
                run_id=None,
                context_manifest_id=None,
            ),
            allow_later_claims=True,
        )
        return (
            ConsumedPreContextClaimObservation.create(
                lease_id=claim.lease.id,
                task_id=task.id,
                work_item_id=item.id,
                claim_sha256=digest(claim.to_wire()),
                next_claim_sha256=claim_identity_sha256(next_claim),
                blocking_start_sha256=start.start_sha256,
                schedule_sha256=schedule.schedule_sha256,
                resolution_sha256=decision.resolution_sha256,
                wait_event_sequence=waited["sequence"],
                wait_event_sha256=digest(waited),
                resolved_event_sequence=resolved["sequence"],
                resolved_event_sha256=digest(resolved),
            ),
        )

    def _invocations(
        self,
        task: Task,
        items: tuple[QueuedWorkItem, ...],
        receipts: tuple[ExecutionInterruptionReceipt, ...],
        assignments: tuple[RoleAssignment, ...],
        *,
        legacy: LegacyExecutionContainment | None = None,
        stopped_execution: StoppedCoderExecutionProof | None = None,
        knowledge_isolation: KnowledgePreparationIsolationProof | None = None,
    ) -> tuple[BaselineInvocationProof, ...]:
        root = self.state / "invocations"
        records = KnowledgeRecordStore(root, read_only=True) if root.is_dir() else None
        starts = (
            tuple(
                start
                for start in records.list("invocation-starts", DeliveryInvocationStart)
                if start.request.task_id == task.id
            )
            if records
            else ()
        )
        outcomes = (
            tuple(
                outcome
                for outcome in records.list("invocation-outcomes", DeliveryInvocationOutcome)
                if outcome.start.request.task_id == task.id
            )
            if records
            else ()
        )
        starts_by_id = {start.work_item_id: start for start in starts}
        outcomes_by_id = {outcome.start.work_item_id: outcome for outcome in outcomes}
        if len(starts_by_id) != len(starts) or len(outcomes_by_id) != len(outcomes):
            raise ValueError("原调用日志含重复执行身份")
        if not {receipt.request.run_id for receipt in receipts}.issubset(
            {start.request.run_id for start in starts}
        ):
            raise ValueError("原停机日志缺少相应调用启动记录")
        item_ids = {item.id for item in items}
        if not set(starts_by_id).issubset(item_ids) or not set(outcomes_by_id).issubset(item_ids):
            raise ValueError("原调用日志含未归属当前 Task 队列的执行")
        historical_isolations = {
            item.id: self._historical_knowledge_isolation(task, item) for item in items
        }
        isolated_lease_ids = frozenset(
            value[0].original_claim.lease.id
            for value in historical_isolations.values()
            if value is not None
        )
        if knowledge_isolation is not None:
            isolated_lease_ids |= frozenset((knowledge_isolation.original_claim.lease.id,))
        result = []
        for item in items:
            start, outcome = starts_by_id.get(item.id), outcomes_by_id.get(item.id)
            claims = self.queue.claims_for_work_item(item.id)
            historical_isolation = historical_isolations[item.id]
            isolation = (
                knowledge_isolation
                if (knowledge_isolation is not None and knowledge_isolation.work_item_id == item.id)
                else (historical_isolation[0] if historical_isolation is not None else None)
            )
            if isolation is not None:
                if start is not None or outcome is not None or len(claims) != 1:
                    raise ValueError("当前知识隔离原工作项出现主调用或不同 claim")
                require_claim_snapshot(isolation.original_claim, claims[0])
                result.append(
                    BaselineInvocationProof(
                        work_item_id=item.id,
                        step_sha256=digest(isolation.original_step.to_wire()),
                        proof_kind="isolated_knowledge_preparation",
                        knowledge_isolation=isolation,
                        knowledge_isolation_binding_sha256=(
                            historical_isolation[1].binding_sha256
                            if historical_isolation is not None
                            and (
                                knowledge_isolation is None
                                or knowledge_isolation.work_item_id != item.id
                            )
                            else None
                        ),
                    )
                )
                continue
            preflight_claims = tuple(
                claim for claim in claims if start is None or claim.lease.id != start.lease_id
            )
            capacity_markers = self._capacity_markers(
                task, item, preflight_claims, isolated_lease_ids=isolated_lease_ids
            )
            capacity_leases = {marker.lease_id for marker in capacity_markers}
            fence = self._prior_invocation_fence(task, start, legacy, stopped_execution)
            replay_markers = (
                read_replay_guarded_claims(
                    state=self.state,
                    task=task,
                    item=item,
                    claims=tuple(
                        claim for claim in preflight_claims if claim.lease.id not in capacity_leases
                    ),
                    scope=self.scope,
                    requirement_id=getattr(self, "knowledge_requirement_id", self.requirement_id),
                    queue=self.queue,
                    require_step=self._require_step,
                    no_start_reader=self._capacity_input_reader(),
                    fence=fence,
                    isolated_lease_ids=isolated_lease_ids,
                    native_stop_checker=self._knowledge_stop_checker(),
                )
                if fence is not None
                else ()
            )
            replay_leases = {marker.lease_id for marker in replay_markers}
            knowledge_markers = self._knowledge_markers(
                task,
                item,
                tuple(
                    claim
                    for claim in preflight_claims
                    if claim.lease.id not in capacity_leases | replay_leases
                ),
                isolated_lease_ids=isolated_lease_ids,
            )
            knowledge_leases = {marker.lease_id for marker in knowledge_markers}
            remaining_claims = tuple(
                claim
                for claim in preflight_claims
                if claim.lease.id not in capacity_leases | knowledge_leases | replay_leases
            )
            consumed = self._consumed_pre_context_claim_observations(
                task, item, remaining_claims, start
            )
            consumed_leases = {value.lease_id for value in consumed}
            reclaimed = self._reclaimed_uninvoked_claims(
                task,
                item,
                tuple(claim for claim in remaining_claims if claim.lease.id not in consumed_leases),
                start,
                legacy,
            )
            reclaimed_leases = {value.lease_id for value in reclaimed}
            markers = self._preflight_markers(
                task,
                item,
                tuple(
                    claim
                    for claim in remaining_claims
                    if claim.lease.id not in reclaimed_leases | consumed_leases
                ),
            )
            step = (
                self.queue.step_for_invocation(item.id, start.request.execution_baseline_sha256)
                if start is not None
                else self.queue.step(item.id)
            )
            self._require_step(item, step)
            receipt = next(
                (
                    entry
                    for entry in receipts
                    if start and entry.request.run_id == start.request.run_id
                ),
                None,
            )
            if start is not None:
                start.validate_integrity()
                if (
                    start.work_item_id,
                    start.checkpoint_sequence,
                    start.request.task_id,
                    start.request.role,
                    start.request.attempt,
                    start.request.source_revision,
                ) != (
                    item.id,
                    item.checkpoint_sequence,
                    task.id,
                    item.role,
                    item.attempt,
                    step.boundary.source_revision,
                ):
                    raise ValueError("原调用未绑定精确队列角色、attempt 和源版本")
                claim = self.queue.original_claim(start.lease_id)
                if claim.lease.id != start.lease_id or (
                    claim.work_item.id,
                    claim.work_item.task_id,
                    claim.work_item.role,
                    claim.work_item.attempt,
                    claim.work_item.checkpoint_sequence,
                ) != (item.id, task.id, item.role, item.attempt, item.checkpoint_sequence):
                    raise ValueError("原调用与真实历史 claim 不一致")
                stopped = (
                    stopped_execution
                    if stopped_execution is not None and stopped_execution.invocation_start == start
                    else None
                )
                if (
                    stopped is None
                    and outcome is None
                    and receipt is None
                    and self.inputs.store is not None
                ):
                    for binding in self.inputs.store.bindings_for_task(task.id):
                        prior = self.inputs.store.plan(binding.plan_sha256).facts.stopped_execution
                        if prior is not None and prior.invocation_start == start:
                            prior.validate_integrity()
                            ledger = FileContinuationStore(
                                self.state / "continuations" / task.id, task_id=task.id
                            )
                            if (
                                ledger.capture_start(start.request.run_id) != prior.capture_start
                                or ledger.capture_stop(start.request.run_id) != prior.capture_stop
                                or self.queue.original_claim(start.lease_id).model_dump(
                                    exclude={"lease": {"expires_at"}}
                                )
                                != prior.capture_start.claim.model_dump(
                                    exclude={"lease": {"expires_at"}}
                                )
                            ):
                                raise ValueError("历史未知结果停止证明与原封存执行不一致")
                            self._require_stopped(prior.capture_stop.process_stop, start.request)
                            stopped = prior
                if outcome is not None:
                    outcome.validate_integrity()
                    if outcome.start != start:
                        raise ValueError("原调用结果未绑定精确启动记录")
                    proof_kind: Literal[
                        "definitive_outcome",
                        "owned_process_stopped",
                        "legacy_execution_contained",
                        "stopped_execution_without_outcome",
                    ] = "definitive_outcome"
                elif stopped is not None:
                    proof_kind = "stopped_execution_without_outcome"
                elif receipt is not None:
                    if (
                        receipt.request != start.request
                        or receipt.original_work_item_id != item.id
                        or receipt.claim_lease_id != start.lease_id
                    ):
                        raise ValueError("停机证明不属于精确原调用")
                    proof_kind = "owned_process_stopped"
                else:
                    historical_legacy = self._historical_legacy(task, start, claim)
                    containment = legacy if legacy and legacy.original_start == start else None
                    if containment is None and historical_legacy is not None:
                        containment = historical_legacy[0]
                    if containment is None or containment.original_claim != claim:
                        raise ValueError("原调用结果或真实停机事实不完整, 保留现场等待工程调查")
                    containment.validate_integrity()
                    proof_kind = "legacy_execution_contained"
                result.append(
                    BaselineInvocationProof(
                        work_item_id=item.id,
                        step_sha256=digest(step.to_wire()),
                        start_sha256=start.start_sha256,
                        outcome_sha256=outcome.outcome_sha256 if outcome else None,
                        interruption_receipt_sha256=receipt.receipt_sha256 if receipt else None,
                        preflight_checkpoint_sha256s=tuple(
                            marker.checkpoint_sha256 for marker in markers
                        ),
                        context_capacity_receipt_sha256s=tuple(
                            marker.receipt_sha256 for marker in capacity_markers
                        ),
                        knowledge_only_claims=knowledge_markers,
                        replay_guarded_claims=replay_markers,
                        reclaimed_uninvoked_claims=reclaimed,
                        consumed_pre_context_claims=consumed,
                        proof_kind=proof_kind,
                        stopped_execution=stopped,
                        legacy_containment=containment
                        if proof_kind == "legacy_execution_contained"
                        else None,
                        # Current rescue facts retain their pre-binding proof
                        # for exact crash replay. Historical traversal binds the
                        # saved authority only after this invocation is superseded.
                        legacy_binding_sha256=historical_legacy[1].binding_sha256
                        if (
                            proof_kind == "legacy_execution_contained"
                            and historical_legacy
                            and (legacy is None or legacy.original_start != start)
                        )
                        else None,
                    )
                )
                continue
            if outcome is not None or receipt is not None:
                raise ValueError("原调用缺少启动记录, 禁止猜测为未执行")
            # Another checkpoint can legitimately reuse the role/attempt. Only
            # this immutable WorkItem's real claims prove it was ever owned.
            result.append(
                BaselineInvocationProof(
                    work_item_id=item.id,
                    step_sha256=digest(step.to_wire()),
                    preflight_checkpoint_sha256=markers[0].checkpoint_sha256
                    if len(markers) == 1
                    else None,
                    preflight_checkpoint_sha256s=tuple(
                        marker.checkpoint_sha256 for marker in markers
                    ),
                    context_capacity_receipt_sha256s=tuple(
                        marker.receipt_sha256 for marker in capacity_markers
                    ),
                    knowledge_only_claims=knowledge_markers,
                    proof_kind="claimed_context_capacity"
                    if capacity_markers
                    else "claimed_preflight"
                    if markers
                    else "claimed_knowledge_failure"
                    if knowledge_markers
                    else "unclaimed",
                )
            )
        return tuple(result)

    def _prior_invocation_fence(
        self,
        task: Task,
        start: DeliveryInvocationStart | None,
        legacy: LegacyExecutionContainment | None,
        stopped: StoppedCoderExecutionProof | None,
    ) -> PriorInvocationFence | None:
        if start is None:
            return None
        if stopped is not None and stopped.invocation_start == start:
            stopped.validate_integrity()
            return PriorInvocationFence(start, stopped.capture_start, stopped.capture_stop)
        if legacy is not None and legacy.original_start == start:
            legacy.validate_integrity()
            return PriorInvocationFence(start)
        store = getattr(getattr(self, "inputs", None), "store", None)
        if store is None:
            return None
        for binding in store.bindings_for_task(task.id):
            plan = store.plan(binding.plan_sha256)
            prior_stopped = plan.facts.stopped_execution
            if prior_stopped is not None and prior_stopped.invocation_start == start:
                prior_stopped.validate_integrity()
                return PriorInvocationFence(
                    start, prior_stopped.capture_start, prior_stopped.capture_stop
                )
            prior_legacy = plan.facts.legacy_containment
            if prior_legacy is not None and prior_legacy.original_start == start:
                prior_legacy.validate_integrity()
                return PriorInvocationFence(start)
        return None

    def _stopped_execution(
        self, task: Task, item: QueuedWorkItem, step: QueuedRoleStep
    ) -> StoppedCoderExecutionProof | None:
        return read_stopped_coder_execution(
            task,
            item,
            step,
            expected_scope=ContinuationScope(
                team_id=self.scope.team_id,
                project_id=self.scope.project_id,
                repository_id=self.scope.repository_id,
                requirement_id=self.requirement_id,
                dispatch_sha256=self.allocation.dispatch_sha256,
            ),
            state=self.state,
            route_root=self.route_root,
            repository=self.repository,
            queue=self.queue,
            artifacts=self.capacity_artifacts,
            permissions=self.permissions,
            task_lock=self.guard,
        )

    def _completed_output(
        self, task: Task, item: QueuedWorkItem, step: QueuedRoleStep
    ) -> CompletedCoderOutputUnavailableProof | None:
        root = self.state / "invocations"
        records = KnowledgeRecordStore(root, read_only=True) if root.is_dir() else None
        outcome = (
            records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome)
            if records
            else None
        )
        if (
            outcome is None
            or outcome.result.status is not AgentRunStatus.FAILED
            or outcome.result.error is None
            or outcome.result.error.code
            not in {AgentErrorCode.WORK_INTERRUPTED, AgentErrorCode.INVALID_OUTPUT}
        ):
            return None
        assert records is not None
        start = records.get("invocation-starts", item.id, DeliveryInvocationStart)
        ledger = FileContinuationStore(self.state / "continuations" / task.id, task_id=task.id)
        capture_start = ledger.capture_start(start.request.run_id)
        capture_stop = ledger.capture_stop(start.request.run_id)
        if capture_stop.process_stop.kind != "completed":
            return None
        proof = CompletedCoderOutputUnavailableProof.create(
            outcome=outcome, capture_start=capture_start, capture_stop=capture_stop
        )
        self._validate_stopped_proof(task, item, step, proof)
        return proof

    def _rejected_candidate_output(
        self, task: Task, item: QueuedWorkItem, step: QueuedRoleStep
    ) -> RejectedCandidateOutputProof | None:
        """Reopen exact original unsupported output; no acceptance or Git mutation."""
        records = KnowledgeRecordStore(self.state / "invocations", read_only=True)
        outcome = records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome)
        if outcome is None or outcome.result.status is not AgentRunStatus.SUCCEEDED:
            return None
        report = outcome.result.artifact
        if not isinstance(report, ImplementationReportArtifact):
            return None
        try:
            validate_current_artifact_version(report)
        except ValueError as error:
            expected_rejection = str(error)
        else:
            return None
        try:
            outcome.result.validate_current_output()
        except AgentOutputContractError as error:
            if str(error) != expected_rejection:
                raise ValueError("原候选输出不是单一精确版本契约拒绝") from error
        else:
            raise ValueError("原候选输出未命中当前精确版本拒绝")
        start = records.get("invocation-starts", item.id, DeliveryInvocationStart)
        ledger = FileContinuationStore(self.state / "continuations" / task.id, task_id=task.id)
        capture_start = ledger.capture_start(start.request.run_id)
        capture_stop = ledger.capture_stop(start.request.run_id)
        reference = self.git.recover(
            WorktreeSpec(
                task_id=task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=report.content.commit_sha,
            )
        )
        if str(reference.path) != capture_start.worktree_path or self.git._run_git_bytes(
            ("status", "--porcelain=v1", "--untracked-files=all", "-z"), cwd=reference.path
        ):
            raise ValueError("原未接纳候选工作区已变化或不是完整干净现场")
        parent = self.git._run_git(
            ("rev-parse", report.content.commit_sha + "^@"), cwd=reference.path
        )
        complete = CapturedMutations.from_capture(
            self.git.capture_mutations(
                reference,
                self.permissions,
                denied_paths=task.constraints.denied_paths if task.constraints else (),
                base_revision=start.request.source_revision,
                include_ignored=True,
            )
        )
        proof = RejectedCandidateOutputProof.create(
            scope=self.scope,
            task=task,
            task_revision=self.repository.current_revision(task.id),
            task_intent_sha256=task_intent_sha256(task),
            step=step,
            outcome=outcome,
            capture_start=capture_start,
            capture_stop=capture_stop,
            candidate_revision=report.content.commit_sha,
            candidate_parent_revision=parent,
            complete_capture=complete,
            inventory=capture_mutation_inventory(reference.path),
            publication_absent=True,
        )
        self._validate_stopped_proof(task, item, step, proof)
        proof.validate_for(
            task,
            step,
            self.scope,
            self.permissions,
            task.constraints.denied_paths if task.constraints else (),
        )
        return proof

    def _validate_rejected_candidate_publications(
        self, task: Task, proof: RejectedCandidateOutputProof
    ) -> None:
        request, start = proof.request, proof.outcome.start
        if proof.capture_start.scope != ContinuationScope(
            team_id=self.scope.team_id,
            project_id=self.scope.project_id,
            repository_id=self.scope.repository_id,
            requirement_id=self.requirement_id,
            dispatch_sha256=self.allocation.dispatch_sha256,
        ) or any(
            artifact.producer.run_id == request.run_id
            for artifact in self.capacity_artifacts.list_for_task(task.id)
        ):
            raise ValueError("原拒绝候选已有发布产物或不属于精确需求分配")
        if any(
            accepted.work_item_id == start.work_item_id
            or accepted.checkpoint_sequence >= start.checkpoint_sequence
            for accepted in self.queue.accepted(task.id)
        ) or any(
            event.artifact_ids
            for event in self.repository.list_events(task.id)[proof.capture_start.task_revision :]
        ):
            raise ValueError("原拒绝候选之后已有产物接纳, 不能覆盖交付历史")
        if any(receipt.request.run_id == request.run_id for receipt in self._receipts(task)):
            raise ValueError("原拒绝候选已有中断接续收据, 不能混用恢复路径")

    def _stopped_provider_failure(
        self, task: Task, item: QueuedWorkItem, step: QueuedRoleStep
    ) -> StoppedProviderFailureProof | None:
        root = self.state / "invocations"
        records = KnowledgeRecordStore(root, read_only=True) if root.is_dir() else None
        outcome = (
            records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome)
            if records
            else None
        )
        if (
            outcome is None
            or outcome.result.status is not AgentRunStatus.FAILED
            or outcome.result.error is None
            or outcome.result.error.code is not AgentErrorCode.AUTHENTICATION_ERROR
        ):
            return None
        assert records is not None
        start = records.get("invocation-starts", item.id, DeliveryInvocationStart)
        ledger = FileContinuationStore(self.state / "continuations" / task.id, task_id=task.id)
        proof = StoppedProviderFailureProof.create(
            outcome=outcome,
            capture_start=ledger.capture_start(start.request.run_id),
            capture_stop=ledger.capture_stop(start.request.run_id),
        )
        self._validate_stopped_proof(task, item, step, proof)
        return proof

    def _stopped_failure(
        self, task: Task, item: QueuedWorkItem, step: QueuedRoleStep
    ) -> StoppedFailureProof | None:
        root = self.state / "invocations"
        records = KnowledgeRecordStore(root, read_only=True) if root.is_dir() else None
        outcome = (
            records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome)
            if records
            else None
        )
        if (
            outcome is None
            or outcome.result.status is not AgentRunStatus.FAILED
            or outcome.result.error is None
            or outcome.result.error.code is not AgentErrorCode.PROVIDER_UNAVAILABLE
            or outcome.result.error.transient
        ):
            return None
        assert records is not None
        start = records.get("invocation-starts", item.id, DeliveryInvocationStart)
        ledger = FileContinuationStore(self.state / "continuations" / task.id, task_id=task.id)
        proof = StoppedFailureProof.create(
            outcome=outcome,
            capture_start=ledger.capture_start(start.request.run_id),
            capture_stop=ledger.capture_stop(start.request.run_id),
        )
        self._validate_stopped_proof(task, item, step, proof)
        self._validate_stopped_failure_publications(task, proof)

        return proof

    def _validate_stopped_failure_publications(
        self, task: Task, proof: StoppedFailureProof
    ) -> None:
        """Fail closed on late raw output, receipts or inconsistent sealed native routes."""
        request = proof.outcome.start.request
        ledger = FileContinuationStore(self.state / "continuations" / task.id, task_id=task.id)
        if any(
            receipt.request.run_id == request.run_id
            for receipt in ledger.receipts_for_task(task.id)
        ):
            raise ValueError("原执行失败已有中断收据, 不能覆盖原事实")
        if any(
            artifact.producer.run_id == request.run_id
            for artifact in self.capacity_artifacts.list_for_task(task.id)
        ):
            raise ValueError("原执行失败已有封存产物, 不能覆盖原输出")
        if self.route_root is None or not self.route_root.is_dir():
            raise ValueError("原执行失败缺少完整原生调用路由事实")
        routes = FileModelRouteAttemptStore(self.route_root, read_only=True).list_for_run(
            request.run_id
        )
        if not routes:
            raise ValueError("原执行失败缺少完整原生调用路由事实")
        for ordinal, route in enumerate(routes, start=1):
            route.validate_integrity()
            if route.route_index != ordinal or route.request_sha256 != digest(request.to_wire()):
                raise ValueError("原执行失败路由未绑定精确原调用")
            if route.task_id != task.id or route.role is not AgentRole.CODER:
                raise ValueError("原执行失败路由身份不一致")
            if ordinal < len(routes) and route.outcome is not RouteAttemptOutcome.FALLBACK:
                raise ValueError("原执行失败路由链包含竞争终结结果")
        final = routes[-1]
        if (
            final.outcome is not RouteAttemptOutcome.FAILED
            or final.route_kind != "codex_cli"
            or final.result != proof.outcome.result
        ):
            raise ValueError("原执行失败最终原生路由与原结果不一致")

    def _validate_stopped_proof(
        self,
        task: Task,
        item: QueuedWorkItem,
        step: QueuedRoleStep,
        proof: CompletedCoderOutputUnavailableProof
        | StoppedProviderFailureProof
        | StoppedFailureProof
        | RejectedCandidateOutputProof,
    ) -> None:
        proof.validate_integrity()
        outcome, capture_start, capture_stop = (
            proof.outcome,
            proof.capture_start,
            proof.capture_stop,
        )
        records = KnowledgeRecordStore(self.state / "invocations", read_only=True)
        start = records.get("invocation-starts", item.id, DeliveryInvocationStart)
        ledger = FileContinuationStore(self.state / "continuations" / task.id, task_id=task.id)
        expected_scope = ContinuationScope(
            team_id=self.scope.team_id,
            project_id=self.scope.project_id,
            repository_id=self.scope.repository_id,
            requirement_id=self.requirement_id,
            dispatch_sha256=self.allocation.dispatch_sha256,
        )
        if capture_start.scope != expected_scope or start != outcome.start:
            raise ValueError("完成但结果未接纳的原执行不属于当前需求和分配")

        def validate_inputs(request: AgentRequest) -> None:
            if isinstance(proof, StoppedFailureProof):
                self._validate_stopped_failure_publications(task, proof)
            if isinstance(proof, RejectedCandidateOutputProof):
                self._validate_rejected_candidate_publications(task, proof)
            if (
                request != start.request
                or request.permissions != self.permissions
                or request.source_revision != step.boundary.source_revision
                or self.queue.get(item.id) != item
                or self.queue.step(item.id) != step
                or records.get("invocation-starts", item.id, DeliveryInvocationStart) != start
                or records.get("invocation-outcomes", item.id, DeliveryInvocationOutcome) != outcome
                or ledger.capture_start(request.run_id) != capture_start
                or ledger.capture_stop(request.run_id) != capture_stop
            ):
                raise ValueError("完成但结果未接纳的原执行或当前队列事实已变化")
            retired = self.queue.rejected_output_artifact_ids(task.id)
            if any(
                accepted.work_item_id == item.id
                or (
                    accepted.checkpoint_sequence >= start.checkpoint_sequence
                    and accepted.receipt.artifact_id not in retired
                )
                for accepted in self.queue.accepted(task.id)
            ) or any(
                event.artifact_ids
                for event in self.repository.list_events(task.id)[capture_start.task_revision :]
            ):
                raise ValueError("原执行之后已有产物发布或交付采纳, 不能覆盖原结果")

        validate_capture_stop(
            start=capture_start,
            stop=capture_stop,
            task=task,
            task_revision=self.repository.current_revision(task.id),
            historical_claim=self.queue.original_claim(start.lease_id),
            task_lock=self.guard,
            validate_inputs=validate_inputs,
            stop_checker=self._require_stopped,
        )

    def _reservation(
        self,
        task: Task,
        item: QueuedWorkItem,
        receipts: tuple[ExecutionInterruptionReceipt, ...],
        *,
        legacy: LegacyExecutionContainment | None = None,
        completed_output: CompletedCoderOutputUnavailableProof | None = None,
        rejected_candidate_output: RejectedCandidateOutputProof | None = None,
        stopped_provider_failure: StoppedProviderFailureProof | None = None,
        stopped_failure: StoppedFailureProof | None = None,
        stopped_execution: StoppedCoderExecutionProof | None = None,
        knowledge_isolation: KnowledgePreparationIsolationProof | None = None,
    ) -> BaselineExecutionReservation:
        if (
            sum(
                value is not None
                for value in (
                    legacy,
                    completed_output,
                    rejected_candidate_output,
                    stopped_provider_failure,
                    stopped_failure,
                    stopped_execution,
                    knowledge_isolation,
                )
            )
            > 1
        ):
            raise ValueError("不同原执行恢复证明不能混用")
        if knowledge_isolation is not None:
            if (
                task.attempts != item.attempt
                or task.work_budget_exhausted
                or task.attempts >= task.max_attempts
            ):
                raise ValueError("当前知识隔离没有剩余普通工作额度或精确原执行身份")
            return BaselineExecutionReservation(
                current_attempt=item.attempt,
                next_execution_attempt=item.attempt + 1,
                retry_cause="knowledge_isolation",
                knowledge_isolation_sha256=knowledge_isolation.proof_sha256,
            )
        root = self.state / "invocations"
        records = KnowledgeRecordStore(root, read_only=True) if root.is_dir() else None
        start = (
            records.find("invocation-starts", item.id, DeliveryInvocationStart) if records else None
        )
        if start is None:
            if any(
                value is not None
                for value in (
                    legacy,
                    completed_output,
                    rejected_candidate_output,
                    stopped_provider_failure,
                    stopped_failure,
                    stopped_execution,
                )
            ):
                raise ValueError("原执行恢复预留缺少真实调用开始记录")
            if item.attempt not in {max(task.attempts, 1), task.attempts + 1}:
                raise ValueError("未调用的工作项没有精确当前或下一执行预留")
            if item.attempt > task.attempts and (
                task.work_budget_exhausted or item.attempt > task.max_attempts
            ):
                raise ValueError("代码基线更新不补充原工作额度")
            return BaselineExecutionReservation(
                current_attempt=item.attempt,
                next_execution_attempt=item.attempt,
                retry_cause="uninvoked",
                reservation_already_applied=item.attempt == task.attempts,
            )
        outcome = (
            records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome)
            if records
            else None
        )
        receipt = next(
            (entry for entry in receipts if entry.request.run_id == start.request.run_id), None
        )
        if (
            outcome is not None
            and outcome.result.status is AgentRunStatus.SUCCEEDED
            and rejected_candidate_output is None
        ):
            raise ValueError("原调用已有成功结果, 需要先接纳封存结果, 不能用基线更新覆盖")
        failure = None
        if rejected_candidate_output is not None:
            rejected_candidate_output.validate_integrity()
            if (
                self.purpose is not BaselinePurpose.REJECTED_CANDIDATE_RESCUE
                or rejected_candidate_output.task != task
                or rejected_candidate_output.work_item_id != item.id
                or rejected_candidate_output.request.attempt != item.attempt
                or rejected_candidate_output.outcome != outcome
                or rejected_candidate_output.outcome.start != start
                or receipt is not None
                or task.attempts != start.request.attempt
                or task.work_budget_exhausted
                or start.request.attempt + 1 > task.max_attempts
            ):
                raise ValueError("原拒绝候选恢复没有剩余普通工作额度或精确原调用身份")
            return BaselineExecutionReservation(
                current_attempt=start.request.attempt,
                next_execution_attempt=start.request.attempt + 1,
                retry_cause="rejected_candidate_output",
                original_run_id=start.request.run_id,
                current_invocation_start_sha256=start.start_sha256,
                current_invocation_outcome_sha256=outcome.outcome_sha256,
                rejected_candidate_output_sha256=rejected_candidate_output.proof_sha256,
            )
        if stopped_execution is not None:
            stopped_execution.validate_integrity()
            if (
                stopped_execution.invocation_start != start
                or outcome is not None
                or receipt is not None
                or task.attempts != start.request.attempt
            ):
                raise ValueError("未知结果停止恢复没有精确原执行身份")
            successor = start.request.attempt + 1
            if task.work_budget_exhausted or successor > task.max_attempts:
                raise ValueError("未知结果停止恢复不补充原工作额度")
            return BaselineExecutionReservation(
                current_attempt=start.request.attempt,
                next_execution_attempt=successor,
                retry_cause="stopped_execution_unknown",
                original_run_id=start.request.run_id,
                current_invocation_start_sha256=start.start_sha256,
                stopped_execution_sha256=stopped_execution.proof_sha256,
            )
        if stopped_provider_failure is not None:
            stopped_provider_failure.validate_integrity()
            if (
                stopped_provider_failure.outcome != outcome
                or stopped_provider_failure.outcome.start != start
                or receipt is not None
                or legacy is not None
                or completed_output is not None
                or task.attempts != start.request.attempt
                or task.work_budget_exhausted
                or start.request.attempt + 1 > task.max_attempts
            ):
                raise ValueError("提供方前提失败接续没有剩余普通工作额度或精确原执行")
            return BaselineExecutionReservation(
                current_attempt=start.request.attempt,
                next_execution_attempt=start.request.attempt + 1,
                retry_cause="provider_prerequisite_repaired",
                original_run_id=start.request.run_id,
                current_invocation_start_sha256=start.start_sha256,
                current_invocation_outcome_sha256=stopped_provider_failure.outcome.outcome_sha256,
                stopped_provider_failure_sha256=stopped_provider_failure.proof_sha256,
            )
        if stopped_failure is not None:
            stopped_failure.validate_integrity()
            if (
                stopped_failure.outcome != outcome
                or stopped_failure.outcome.start != start
                or receipt is not None
                or legacy is not None
                or completed_output is not None
                or task.attempts != start.request.attempt
                or task.work_budget_exhausted
                or start.request.attempt + 1 > task.max_attempts
            ):
                raise ValueError("原执行失败接续没有剩余普通工作额度或精确原执行")
            return BaselineExecutionReservation(
                current_attempt=start.request.attempt,
                next_execution_attempt=start.request.attempt + 1,
                retry_cause="stopped_failure_retry",
                original_run_id=start.request.run_id,
                current_invocation_start_sha256=start.start_sha256,
                current_invocation_outcome_sha256=stopped_failure.outcome.outcome_sha256,
                stopped_failure_sha256=stopped_failure.proof_sha256,
            )
        if completed_output is not None:
            completed_output.validate_integrity()
            if (
                completed_output.outcome != outcome
                or completed_output.outcome.start != start
                or receipt is not None
                or legacy is not None
                or task.attempts != start.request.attempt
                or task.work_budget_exhausted
                or start.request.attempt + 1 > task.max_attempts
            ):
                raise ValueError("完成但结果未接纳的接续没有剩余工作额度或精确原执行")
            return BaselineExecutionReservation(
                current_attempt=start.request.attempt,
                next_execution_attempt=start.request.attempt + 1,
                retry_cause=(
                    "completed_output_rejected"
                    if completed_output.reason is CompletedCoderOutputReason.REJECTED
                    else "completed_output_unavailable"
                ),
                original_run_id=start.request.run_id,
                current_invocation_start_sha256=start.start_sha256,
                current_invocation_outcome_sha256=outcome.outcome_sha256,
                completed_output_sha256=completed_output.proof_sha256,
            )
        if legacy is not None:
            legacy.validate_integrity()
            if (
                outcome is not None
                or receipt is not None
                or legacy.original_start != start
                or task.attempts != start.request.attempt
                or task.work_budget_exhausted
                or start.request.attempt + 1 > task.max_attempts
            ):
                raise ValueError("旧执行救援不补充工作额度, 需要精确原执行和下一次工作预留")
            return BaselineExecutionReservation(
                current_attempt=start.request.attempt,
                next_execution_attempt=start.request.attempt + 1,
                retry_cause="legacy_execution_abandoned",
                original_run_id=start.request.run_id,
                current_invocation_start_sha256=start.start_sha256,
                containment_sha256=legacy.containment_sha256,
            )
        if receipt is not None:
            cause = receipt.cause
            error_code = receipt.original_error_code.value
        elif (
            outcome is not None
            and outcome.service_pause is not None
            and (
                outcome.service_pause.admission_closed
                or (
                    isinstance(outcome.service_pause.process_stop, SynchronousToolLoopStop)
                    and bool(outcome.service_pause.process_stop.completed_operation_ids)
                    and all(
                        operation.startswith("model-route.")
                        for operation in outcome.service_pause.process_stop.completed_operation_ids
                    )
                )
            )
            and outcome.start == start
            and outcome.result.error is not None
            and outcome.result.error.code is AgentErrorCode.SERVICE_PAUSED
        ):
            outcome.validate_integrity()
            cause = "service_pause"
            error_code = AgentErrorCode.SERVICE_PAUSED.value
        elif (
            outcome is not None
            and outcome.result.error is not None
            and outcome.result.error.transient
            and outcome.result.error.code.value in TRANSIENT_CODES
        ):
            cause = "provider_transient"
            error_code = outcome.result.error.code.value
        else:
            raise ValueError("基线更新没有明确、可预算的原调用终结事实")
        successor = start.request.attempt + 1
        if cause == "provider_transient":
            failure = DeliveryRetryFailure.model_validate(
                {
                    "role": "coder",
                    "attempt": start.request.attempt,
                    "run_id": start.request.run_id,
                    "code": error_code,
                }
            )
            reserved = task.with_retry_failure(failure)
            if reserved.attempts != successor:
                raise ValueError("基线接续没有剩余的服务故障额度")
            already = reserved == task
        else:
            already = task.attempts == successor
            if not already and (
                task.attempts != start.request.attempt
                or task.work_budget_exhausted
                or successor > task.max_attempts
            ):
                raise ValueError("基线接续没有剩余的工作额度或精确原执行身份")
        return BaselineExecutionReservation(
            current_attempt=start.request.attempt,
            next_execution_attempt=successor,
            retry_cause=cause,
            original_run_id=start.request.run_id,
            current_invocation_start_sha256=start.start_sha256,
            current_invocation_outcome_sha256=outcome.outcome_sha256 if outcome else None,
            interruption_receipt_sha256=receipt.receipt_sha256 if receipt else None,
            retry_failure=failure,
            reservation_already_applied=already,
        )

    def _reread_knowledge_isolation(
        self, proof: KnowledgePreparationIsolationProof, task: Task, item: QueuedWorkItem
    ) -> None:
        proof.validate_integrity()
        outcome, claim, step, context_sha256 = read_unknown_knowledge_preparation(
            state=self.state,
            task=task,
            item=item,
            scope=self.scope,
            requirement_id=getattr(self, "knowledge_requirement_id", self.requirement_id),
            queue=self.queue,
            require_step=self._require_step,
            no_start_reader=self._capacity_input_reader(),
        )
        if (
            outcome != proof.outcome
            or step != proof.original_step
            or context_sha256 != proof.context_sha256
            or proof.scope != self.scope
            or proof.task_id != task.id
            or proof.task_intent_sha256 != task_intent_sha256(task)
            or proof.requirement_id != self.requirement_id
            or proof.dispatch_sha256 != self.allocation.dispatch_sha256
        ):
            raise ValueError("当前知识隔离的原知识输入、claim 或工程范围已变化")
        require_claim_snapshot(proof.original_claim, claim)

    def _verify_knowledge_isolation_boundary(
        self, proof: KnowledgePreparationIsolationProof
    ) -> None:
        boot = self._observe_legacy_boot()
        require_current_isolation_boundary(
            proof,
            observer=self.local_execution_observer,
            boot=boot,
            repository_root=Path(self.scope.repository_root),
            worktree_root=Path(proof.worktree_surveys[0].worktree_path),
        )
        if self._observe_legacy_boot() != boot:
            raise ValueError("当前知识隔离检查期间电脑启动会话发生变化")

    def _knowledge_isolation(
        self, task: Task, item: QueuedWorkItem, step: QueuedRoleStep
    ) -> KnowledgePreparationIsolationProof:
        disposition = item.wait_disposition
        if (
            item.status not in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
            or disposition is None
            or disposition.facts.classification != "SERVICE_PAUSED"
            or disposition.facts.task_intent_sha256 != task_intent_sha256(task)
            or disposition.facts.checkpoint_sequence != item.checkpoint_sequence
            or disposition.facts.source_revision != step.boundary.source_revision
            or len(self.queue.claims_for_work_item(item.id)) != 1
        ):
            raise ValueError("当前知识隔离只处理精确旧知识准备导致的 Coder 暂停等待")
        outcome, claim, original_step, context_sha256 = read_unknown_knowledge_preparation(
            state=self.state,
            task=task,
            item=item,
            scope=self.scope,
            requirement_id=getattr(self, "knowledge_requirement_id", self.requirement_id),
            queue=self.queue,
            require_step=self._require_step,
            no_start_reader=self._capacity_input_reader(),
        )
        sealed: KnowledgePreparationIsolationProof | None = getattr(
            self, "_sealed_knowledge_isolation", None
        )
        if sealed is not None:
            self._reread_knowledge_isolation(sealed, task, item)
            self._verify_knowledge_isolation_boundary(sealed)
            return sealed
        worktree = self.git.recover(
            WorktreeSpec(
                task_id=task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=step.boundary.source_revision,
            )
        )
        boot = self._observe_legacy_boot()
        repository_surveys, worktree_surveys = observe_isolation_boundary(
            observer=self.local_execution_observer,
            boot=boot,
            repository_root=Path(self.scope.repository_root),
            worktree_root=worktree.path,
        )
        if self._observe_legacy_boot() != boot:
            raise ValueError("当前知识隔离检查期间电脑启动会话发生变化")
        proof = KnowledgePreparationIsolationProof.create(
            scope=self.scope,
            requirement_id=self.requirement_id,
            knowledge_requirement_id=outcome.intent.binding.requirement_id,
            dispatch_sha256=self.allocation.dispatch_sha256,
            task_id=task.id,
            task_intent_sha256=task_intent_sha256(task),
            task_revision=self.repository.current_revision(task.id),
            work_item_id=item.id,
            checkpoint_sequence=item.checkpoint_sequence,
            original_claim=claim,
            original_step=original_step,
            outcome=outcome,
            context_sha256=context_sha256,
            boot=boot,
            repository_surveys=repository_surveys,
            worktree_surveys=worktree_surveys,
        )
        self._sealed_knowledge_isolation = proof
        return proof

    def _historical_knowledge_isolation(
        self, task: Task, item: QueuedWorkItem
    ) -> tuple[KnowledgePreparationIsolationProof, ExecutionBaselineBinding] | None:
        if getattr(self, "inputs", None) is None or self.inputs.store is None:
            return None
        for binding in self.inputs.store.bindings_for_task(task.id):
            if binding.purpose is not BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION:
                continue
            plan = self.inputs.store.plan(binding.plan_sha256)
            proof = plan.facts.knowledge_isolation
            if proof is None or proof.work_item_id != item.id:
                continue
            authority = self.inputs.store.records.get(
                "baseline-authorities", binding.plan_sha256, BaselineOperatorAuthorization
            )
            require_knowledge_isolation_binding(plan, binding)
            authority.validate_integrity()
            authority.require_plan_confirmation(plan)
            if (
                authority.authorization_sha256 != binding.authority_sha256
                or authority.plan_sha256 != plan.plan_sha256
                or authority.facts_sha256 != plan.facts.facts_sha256
                or authority.task_id != task.id
                or authority.task_intent_sha256 != task_intent_sha256(task)
            ):
                raise ValueError("历史知识隔离缺少精确真实 ENGINEERING 决定")
            self._reread_knowledge_isolation(proof, task, item)
            return proof, binding
        return None

    def _legacy_containment(self, task: Task, item: QueuedWorkItem) -> LegacyExecutionContainment:
        disposition = item.wait_disposition
        if (
            item.status not in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
            or disposition is None
            or disposition.facts.classification not in {"EXECUTION_UNCERTAIN", "PLATFORM_BUG"}
            or disposition.facts.task_intent_sha256 != task_intent_sha256(task)
            or disposition.facts.checkpoint_sequence != item.checkpoint_sequence
        ):
            raise ValueError("旧执行救援只处理当前尚未确认结果的 Coder 等待")
        root = self.state / "invocations"
        if not root.is_dir():
            raise ValueError("旧执行救援缺少真实原调用启动记录")
        records = KnowledgeRecordStore(root, read_only=True)
        start = records.get("invocation-starts", item.id, DeliveryInvocationStart)
        start.validate_integrity()
        if (
            start.request.task_id != task.id
            or start.request.role is not AgentRole.CODER
            or start.request.permissions != self.permissions
            or start.request.source_revision != disposition.facts.source_revision
            or start.checkpoint_sequence != item.checkpoint_sequence
        ):
            raise ValueError("旧执行救援启动记录与当前原权限和等待版本不一致")
        if records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome) is not None:
            raise ValueError("原调用结果已存在, 请先让平台处理原结果, 无需旧执行救援")
        claim = self.queue.original_claim(start.lease_id)
        capture_root = self.state / "continuations" / task.id
        if any(
            (capture_root / name).exists() or (capture_root / name).is_symlink()
            for name in (
                f"capture-stop-{start.request.run_id}.json",
                f"receipt-{start.request.run_id}.json",
            )
        ):
            raise ValueError("原执行已有现场或停止记录, 请使用原执行记录处理路径")
        self._require_legacy_capture_start(task, start, claim, capture_root)
        self._require_legacy_routes(start)
        # Resolve only the original manager-owned checkout. A missing checkout is
        # not rebuilt, and HTTP cannot select a process-survey root.
        boot = self._observe_legacy_boot()
        sealed: LegacyExecutionContainment | None = getattr(
            self, "_sealed_legacy_observation", None
        )
        if sealed is not None:
            if sealed.original_start != start or sealed.original_claim != claim:
                raise ValueError("恢复方案的原调用或历史领取记录已变化")
            worktree_path = Path(self.scope.repository_root)
            if sealed.method == "operator_confirmed_local_stop":
                worktree_path = self.git.recover(
                    WorktreeSpec(
                        task_id=task.id,
                        role=AgentRole.CODER,
                        attempt=1,
                        source_revision=start.request.source_revision,
                    )
                ).path
            self._verify_legacy_observation(sealed, worktree_root=worktree_path)
            return sealed
        survey = None
        method: Literal["os_reboot", "operator_confirmed_local_stop"] = "os_reboot"
        if boot.booted_at <= start.started_at:
            worktree = self.git.recover(
                WorktreeSpec(
                    task_id=task.id,
                    role=AgentRole.CODER,
                    attempt=1,
                    source_revision=start.request.source_revision,
                )
            )
            survey = self.local_execution_observer.observe(worktree_root=worktree.path, boot=boot)
            survey.require_idle()
            if not boot.same_boot(self._observe_legacy_boot()):
                raise LegacyRescuePrerequisiteError(
                    code="LOCAL_OBSERVATION_CHANGED",
                    safe_message="检查期间电脑启动会话发生变化, 恢复尚未安排。",
                    next_action="请等当前服务稳定后重新准备恢复方案。",
                )
            method = "operator_confirmed_local_stop"
        containment = LegacyExecutionContainment.create(
            scope=self.scope,
            requirement_id=self.requirement_id,
            dispatch_sha256=self.allocation.dispatch_sha256,
            task_intent_sha256=task_intent_sha256(task),
            original_start=start,
            original_claim=claim,
            boot=boot,
            method=method,
            local_execution_survey=survey,
        )
        self._sealed_legacy_observation = containment
        return containment

    def _require_legacy_capture_start(
        self, task: Task, start: DeliveryInvocationStart, claim: QueueClaim, root: Path
    ) -> None:
        """A start-only ledger is retained input, never evidence that execution stopped."""
        if not root.exists() and not root.is_symlink():
            return
        try:
            capture = FileContinuationStore(root, task_id=task.id).capture_start(
                start.request.run_id
            )
        except ContinuationRecordMissing:
            return
        recorded, policy = capture.claim, task.interruption_continuation_policy
        if (
            capture.request != start.request
            or capture.scope
            != ContinuationScope(
                team_id=self.scope.team_id,
                project_id=self.scope.project_id,
                repository_id=self.scope.repository_id,
                requirement_id=self.requirement_id,
                dispatch_sha256=self.allocation.dispatch_sha256,
            )
            or capture.task_intent_sha256 != task_intent_sha256(task)
            or capture.task_revision != start.checkpoint_sequence
            or policy is None
            or capture.policy_sha256 != policy.policy_sha256
            or capture.started_at < start.started_at
            or recorded.assignment != claim.assignment
            or recorded.model_selection != claim.model_selection
            # Heartbeats can extend the original lease after capture-start.
            or recorded.lease.model_dump(exclude={"expires_at"})
            != claim.lease.model_dump(exclude={"expires_at"})
            or recorded.work_item != claim.work_item
            or recorded.worker_id != claim.worker_id
            or recorded.claimed_at != claim.claimed_at
        ):
            raise ValueError("启动现场记录与当前需求事实不一致, 原记录与草稿保留")
        worktree = self.git.recover(
            WorktreeSpec(
                task_id=task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=start.request.source_revision,
            )
        )
        if capture.worktree_path != str(worktree.path):
            raise ValueError("启动现场记录与当前需求事实不一致, 原记录与草稿保留")

    def _require_legacy_routes(self, start: DeliveryInvocationStart) -> None:
        root = self.route_root
        if root is None or not root.is_dir():
            return
        routes = FileModelRouteAttemptStore(root, read_only=True).list_for_run(start.request.run_id)
        for ordinal, route in enumerate(routes, start=1):
            route.validate_integrity()
            if route.route_index != ordinal or route.request_sha256 != digest(
                start.request.to_wire()
            ):
                raise ValueError("原模型路由记录与完整原调用不一致")
            if route.outcome is not RouteAttemptOutcome.FALLBACK:
                raise ValueError("原模型已有封存最终结果, 请先处理原结果")
            if route.route_kind != "codex_cli":
                raise ValueError("旧执行救援只支持可由原电脑整机重启隔离的本机执行")
        if routes:
            # A sealed fallback describes the completed previous route, not the
            # route which was entered afterwards. Missing next-route facts cannot
            # be interpreted as a local native invocation.
            raise ValueError("原执行发生过模型切换但后续路由尚未封存, 不能确认本机救援边界")

    def _historical_legacy(
        self, task: Task, start: DeliveryInvocationStart, claim: QueueClaim
    ) -> tuple[LegacyExecutionContainment, ExecutionBaselineBinding] | None:
        store = getattr(getattr(self, "inputs", None), "store", None)
        if store is None:
            return None
        matches: list[tuple[LegacyExecutionContainment, ExecutionBaselineBinding]] = []
        for binding in store.bindings_for_task(task.id):
            if binding.purpose is not BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                continue
            plan = store.plan(binding.plan_sha256)
            containment = plan.facts.legacy_containment
            if containment is None or containment.original_start != start:
                continue
            authority = store.records.get(
                "baseline-authorities", plan.plan_sha256, BaselineOperatorAuthorization
            )
            authority.validate_integrity()
            authority.require_plan_confirmation(plan)
            containment.validate_integrity()
            if (
                containment.original_claim != claim
                or containment.scope != self.scope
                or containment.requirement_id != self.requirement_id
                or containment.dispatch_sha256 != self.allocation.dispatch_sha256
                or containment.task_intent_sha256 != task_intent_sha256(task)
                or containment.original_start.request.permissions != self.permissions
                or binding.legacy_containment_sha256 != containment.containment_sha256
                or binding.authority_source != "engineering_operator_decision"
                or binding.authority_sha256 != authority.authorization_sha256
                or authority.plan_sha256 != plan.plan_sha256
                or authority.facts_sha256 != plan.facts.facts_sha256
                or authority.task_id != task.id
                or authority.task_intent_sha256 != task_intent_sha256(task)
            ):
                raise ValueError("旧执行历史隔离记录缺少精确原事实和工程确认")
            matches.append((containment, binding))
        if len(matches) > 1:
            raise ValueError("同一旧执行存在重复救援记录, 禁止重复预留")
        return matches[0] if matches else None

    def _knowledge_markers(
        self,
        task: Task,
        item: QueuedWorkItem,
        claims: tuple[QueueClaim, ...],
        *,
        isolated_lease_ids: frozenset[str] = frozenset(),
    ) -> tuple[KnowledgeOnlyClaimProof, ...]:
        root = self.state.parent / "knowledge" / "runs" / "invocations"
        if not claims or not CapacityInputReader._capacity_ledger_exists(root):
            return ()
        if not self._scope_held:
            raise ValueError("知识准备调查缺少真实任务锁和队列屏障")
        return read_failed_knowledge_claims(
            state=self.state,
            task=task,
            item=item,
            claims=claims,
            scope=self.scope,
            requirement_id=getattr(self, "knowledge_requirement_id", self.requirement_id),
            queue=self.queue,
            require_step=self._require_step,
            no_start_reader=self._capacity_input_reader(),
            isolated_lease_ids=isolated_lease_ids,
            native_stop_checker=self._knowledge_stop_checker(),
        )

    def _preflight_markers(
        self, task: Task, item: QueuedWorkItem, claims: tuple[QueueClaim, ...]
    ) -> tuple[DeliveryPreflightCheckpoint, ...]:
        if not claims:
            return ()
        root = self.state / "delivery-preflight"
        if not root.is_dir():
            raise ValueError("历史 claim 没有可验证的调用或执行前停止记录")
        records = KnowledgeRecordStore(root, read_only=True)
        claims_by_lease = {claim.lease.id: claim for claim in claims}
        if len(claims_by_lease) != len(claims):
            raise ValueError("执行前停止调查含重复的历史 claim")
        matches: dict[str, DeliveryPreflightCheckpoint] = {}
        for marker in records.list("preflight-checkpoints", DeliveryPreflightCheckpoint):
            if marker.work_item_id != item.id or marker.lease_id not in claims_by_lease:
                continue
            marker.validate_integrity()
            prior = records.get(
                "preflight-receipts", marker.receipt_sha256, DeliveryPreflightReceipt
            )
            prior.validate_integrity()
            claim = claims_by_lease[marker.lease_id]
            step = self.queue.step_for_claim(claim)
            self._require_step(item, step)
            if (
                marker.task_id,
                marker.checkpoint_sequence,
                marker.source_revision,
                prior.task_id,
                prior.scope.repository_id,
                prior.scope.team_id,
                prior.scope.project_id,
                prior.scope.requirement_id,
                prior.source_revision,
                claim.work_item.id,
                claim.work_item.task_id,
                claim.work_item.role,
                claim.work_item.attempt,
                claim.work_item.checkpoint_sequence,
            ) != (
                task.id,
                item.checkpoint_sequence,
                step.boundary.source_revision,
                task.id,
                self.scope.repository_id,
                self.scope.team_id,
                self.scope.project_id,
                self.requirement_id,
                step.boundary.source_revision,
                item.id,
                task.id,
                item.role,
                item.attempt,
                item.checkpoint_sequence,
            ) or prior.status != "WAIT_ENGINEERING":
                raise ValueError("执行前停止记录与真实原 claim 不一致")
            if marker.lease_id in matches:
                raise ValueError("同一历史 claim 有多个执行前停止记录, 无法证明精确调用边界")
            matches[marker.lease_id] = marker
        if set(matches) != set(claims_by_lease):
            raise ValueError("历史 claim 没有可验证的调用或执行前停止记录")
        return tuple(matches[identity] for identity in sorted(matches))

    def _current_capacity_receipt(
        self, task: Task, item: QueuedWorkItem, proofs: tuple[BaselineInvocationProof, ...]
    ) -> str | None:
        disposition = item.wait_disposition
        if disposition is None or disposition.facts.classification != "CONTEXT_CAPACITY":
            return None
        proof = next(value for value in proofs if value.work_item_id == item.id)
        records = KnowledgeRecordStore(self.state / "delivery-preflight", read_only=True)
        markers = tuple(
            records.get("context-capacity-receipts", identity, ContextCapacityReceipt)
            for identity in proof.context_capacity_receipt_sha256s
        )
        current = tuple(
            marker for marker in markers if marker.dispatch_sequence == item.dispatch_sequence
        )
        if len(current) != 1:
            raise ValueError("当前容量等待缺少唯一精确未调用记录, 原进度和历史保留")
        marker = current[0]
        if (
            marker.task_sha256 != digest(task.to_wire())
            or marker.task_revision != self.repository.current_revision(task.id)
            or disposition.facts.source_revision != marker.source_revision
            or disposition.facts.evidence_ids != ("context-capacity://" + marker.receipt_sha256,)
            or proof.proof_kind != "claimed_context_capacity"
        ):
            raise ValueError("当前容量等待与原 Task、输入或未调用证明不一致")
        return marker.receipt_sha256

    def _capacity_markers(
        self,
        task: Task,
        item: QueuedWorkItem,
        claims: tuple[QueueClaim, ...],
        *,
        isolated_lease_ids: frozenset[str] = frozenset(),
    ) -> tuple[ContextCapacityReceipt, ...]:
        """Cover actual historical claims using independently sealed no-start facts."""
        root = self.state / "delivery-preflight"
        if not claims or not self._capacity_ledger_exists(root):
            return ()
        claims_by_lease = {claim.lease.id: claim for claim in claims}
        if len(claims_by_lease) != len(claims):
            raise ValueError("容量停止调查含重复历史 claim")
        records = KnowledgeRecordStore(root, read_only=True)
        markers = tuple(
            marker
            for marker in records.list("context-capacity-receipts", ContextCapacityReceipt)
            if marker.work_item_id == item.id and marker.lease_id in claims_by_lease
        )
        if not markers:
            return ()
        if not self._scope_held:
            raise ValueError("容量停止调查缺少真实任务锁和队列屏障")
        matched: dict[str, ContextCapacityReceipt] = {}
        for marker in markers:
            marker.validate_integrity()
            claim = claims_by_lease[marker.lease_id]
            step = self.queue.step_for_claim(claim)
            self._require_step(item, step)
            self._require_capacity_identity(
                task, marker, claim, step, isolated_lease_ids=isolated_lease_ids
            )
            self._require_capacity_context(task, marker, claim)
            self._require_capacity_not_started(marker)
            if marker.lease_id in matched:
                raise ValueError("同一历史 claim 存在多个容量停止记录, 不能推断调用边界")
            matched[marker.lease_id] = marker
        return tuple(sorted(matched.values(), key=lambda marker: marker.dispatch_sequence))

    def _capacity_input_reader(
        self, *, isolated_lease_ids: frozenset[str] = frozenset()
    ) -> CapacityInputReader:
        return CapacityInputReader(
            state=self.state,
            queue=self.queue,
            artifacts=self.capacity_artifacts,
            route_root=self.route_root,
            baselines=self.inputs.store,
            permissions=self.permissions,
            legacy_claim_snapshot=lambda task, marker, claim, step: (
                self._legacy_capacity_claim_snapshot(
                    task, marker, claim, step, isolated_lease_ids=isolated_lease_ids
                )
            ),
        )

    def _legacy_capacity_claim_snapshot(
        self,
        task: Task,
        marker: ContextCapacityReceipt,
        claim: QueueClaim,
        step: QueuedRoleStep,
        *,
        isolated_lease_ids: frozenset[str] = frozenset(),
    ) -> QueueClaim:
        self._require_step(claim.work_item, step)
        return read_capacity_claim_snapshot(
            state=self.state,
            task=task,
            marker=marker,
            historical=claim,
            scope=self.scope,
            requirement_id=getattr(self, "knowledge_requirement_id", self.requirement_id),
            queue=self.queue,
            require_step=self._require_step,
            isolated_lease_ids=isolated_lease_ids,
            native_stop_checker=self._knowledge_stop_checker(),
        )

    def _require_capacity_identity(
        self,
        task: Task,
        marker: ContextCapacityReceipt,
        claim: QueueClaim,
        step: QueuedRoleStep,
        *,
        isolated_lease_ids: frozenset[str] = frozenset(),
    ) -> None:
        self._capacity_input_reader(isolated_lease_ids=isolated_lease_ids).require_identity(
            task, marker, claim, step
        )

    def _require_capacity_context(
        self, task: Task, marker: ContextCapacityReceipt, claim: QueueClaim
    ) -> None:
        self._capacity_input_reader().require_context(task, marker, claim)

    def _require_capacity_not_started(self, marker: ContextCapacityReceipt) -> None:
        self._capacity_input_reader().require_not_started(marker, allow_later_claims=True)

    _capacity_ledger_exists = staticmethod(CapacityInputReader._capacity_ledger_exists)
