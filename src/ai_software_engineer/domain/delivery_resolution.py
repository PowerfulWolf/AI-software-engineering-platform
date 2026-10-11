"""Exact engineering investigation and decisions for a nonterminal delivery wait."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator

from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.artifact import ArtifactId
from ai_software_engineer.domain.continuation import ContinuationCause
from ai_software_engineer.domain.delivery_disposition import DeliveryDisposition, DispositionSha256
from ai_software_engineer.domain.engineering_authority import (
    EngineeringAdmission,
    EngineeringCapability,
    EngineeringScope,
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.execution_baseline import FullGitRevision
from ai_software_engineer.domain.identity import ContextId, RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.domain.workforce import ModelSelection, RoleAssignment, TaskLease


class DeliveryResolutionKind(StrEnum):
    RETRY_FROM_CHECKPOINT = "RETRY_FROM_CHECKPOINT"
    REPLAY_RECORDED_RESULT = "REPLAY_RECORDED_RESULT"
    RESUME_UNINVOKED = "RESUME_UNINVOKED"
    REVERIFY_CANDIDATE = "REVERIFY_CANDIDATE"
    RETRY_VERIFIER_PREPARATION = "RETRY_VERIFIER_PREPARATION"
    RETRY_KNOWLEDGE_PREPARATION = "RETRY_KNOWLEDGE_PREPARATION"
    RETRY_REJECTED_CODER_OUTPUT = "RETRY_REJECTED_CODER_OUTPUT"


class DeliveryProofMissing(StrEnum):
    TASK_PROCESS_LIVE = "TASK_PROCESS_LIVE"
    INVOCATION_UNRECORDED = "INVOCATION_UNRECORDED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    OUTCOME_REJECTED = "OUTCOME_REJECTED"
    STOP_UNRECORDED = "STOP_UNRECORDED"
    PROCESS_LIVE_OR_UNKNOWN = "PROCESS_LIVE_OR_UNKNOWN"
    CHECKPOINT_UNAVAILABLE = "CHECKPOINT_UNAVAILABLE"
    CHECKPOINT_DRIFT = "CHECKPOINT_DRIFT"
    PREREQUISITES_UNVERIFIED = "PREREQUISITES_UNVERIFIED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ORIGINAL_CLAIM_UNAVAILABLE = "ORIGINAL_CLAIM_UNAVAILABLE"
    VERIFICATION_EVIDENCE_UNAVAILABLE = "VERIFICATION_EVIDENCE_UNAVAILABLE"
    VERIFIER_PREPARATION_UNAVAILABLE = "VERIFIER_PREPARATION_UNAVAILABLE"
    NATIVE_EXECUTION_UNCERTAIN = "NATIVE_EXECUTION_UNCERTAIN"
    KNOWLEDGE_PREPARATION_UNAVAILABLE = "KNOWLEDGE_PREPARATION_UNAVAILABLE"
    KNOWLEDGE_WINDOW_EXHAUSTED = "KNOWLEDGE_WINDOW_EXHAUSTED"


class DeliveryWaitCollectionFailure(StrEnum):
    """Safe bounded diagnosis; no rejected body, path or exception text."""

    WORKSPACE_CAPTURE_REJECTED = "WORKSPACE_CAPTURE_REJECTED"


RESULT_REPLAY_REJECTED_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        "INVALID_OUTPUT",
        "POLICY_VIOLATION",
        "PLATFORM_BUG",
        "REQUIREMENT_AMBIGUITY",
        "BUDGET_EXHAUSTED",
        "NONTRANSIENT_INFRA",
    }
)


class VerificationRetryEvidence(DomainModel):
    """A real inconclusive QA result on a retained candidate, never a code defect."""

    candidate_revision: FullGitRevision
    previous_qa_artifact_id: ArtifactId
    previous_qa_sha256: DispositionSha256
    previous_run_id: RunId
    previous_context_manifest_id: ContextId
    invocation_outcome_sha256: DispositionSha256
    prerequisite_facts_sha256: DispositionSha256
    budget_source: Literal["frozen_work_attempt"] = "frozen_work_attempt"


class VerifierPreparationEvidence(DomainModel):
    """Exact pre-model native execution facts, never an inferred provider failure."""

    candidate_revision: FullGitRevision
    preparation_checkpoint_sha256: DispositionSha256
    previous_run_id: RunId
    previous_context_manifest_id: ContextId
    request_sha256: DispositionSha256
    native_execution_state: Literal["NOT_STARTED", "FINISHED"]
    native_binding_plan_sha256: DispositionSha256 | None = None
    native_started_sha256: DispositionSha256 | None = None
    native_finished_sha256: DispositionSha256 | None = None
    native_failure_code: NonEmptyStr | None = None
    prerequisite_facts_sha256: DispositionSha256
    budget_source: Literal["frozen_work_attempt"] | None = None

    @model_validator(mode="after")
    def validate_exact_native_state(self) -> Self:
        finished = self.native_execution_state == "FINISHED"
        if finished != (self.budget_source == "frozen_work_attempt"):
            raise ValueError("only a finished native preparation consumes frozen work allowance")
        if finished and (
            self.native_binding_plan_sha256 is None
            or self.native_started_sha256 is None
            or self.native_finished_sha256 is None
        ):
            raise ValueError("native preparation retry requires a real sealed final execution")
        if not finished and (
            self.native_started_sha256 is not None
            or self.native_finished_sha256 is not None
            or self.native_failure_code is not None
        ):
            raise ValueError("unstarted native preparation cannot claim execution or failure")
        return self


class OriginalInvocationAuthority(DomainModel):
    """Original producer identity from a real historical claim, never request text."""

    kind: Literal["original_invocation_authority"] = "original_invocation_authority"
    work_item_id: NonEmptyStr
    checkpoint_sequence: Annotated[StrictInt, Field(ge=0)]
    assignment: RoleAssignment
    lease: TaskLease
    model_selection: ModelSelection
    request_permissions: AgentPermissions
    run_id: RunId
    context_manifest_id: ContextId
    source_revision: NonEmptyStr
    request_sha256: DispositionSha256

    @model_validator(mode="after")
    def validate_original_claim(self) -> Self:
        if (
            self.assignment.lease_id,
            self.assignment.id,
            self.assignment.task_id,
            self.assignment.agent_id,
        ) != (self.lease.id, self.lease.assignment_id, self.lease.task_id, self.lease.agent_id):
            raise ValueError("original invocation authority has mismatched assignment and lease")
        return self


class KnowledgePreparationRetryEvidence(DomainModel):
    """Exact stopped knowledge preparation and its finite, frozen next window."""

    scope: EngineeringScope
    requirement_id: NonEmptyStr
    delivery_requirement_id: NonEmptyStr | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    task_id: TaskId
    role: AgentRole
    work_item_id: NonEmptyStr
    original_lease_id: NonEmptyStr
    original_claim_sha256: DispositionSha256
    original_attempt: Annotated[StrictInt, Field(ge=1)]
    original_dispatch_sequence: Annotated[StrictInt, Field(ge=0)]
    checkpoint_sequence: Annotated[StrictInt, Field(ge=0)]
    previous_run_id: RunId
    previous_context_manifest_id: ContextId
    source_revision: NonEmptyStr
    snapshot_sha256: DispositionSha256
    phase: Literal["intent", "assessment"]
    intent_sha256: DispositionSha256
    outcome_sha256: DispositionSha256
    request_sha256: DispositionSha256
    execution_record_sha256s: Annotated[
        tuple[DispositionSha256, ...], Field(min_length=2, max_length=32)
    ]
    root_intent_sha256: DispositionSha256
    initial_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=86_400)]
    current_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=86_400)]
    next_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=86_400)]
    maximum_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=86_400)]
    expansion_number: Annotated[StrictInt, Field(ge=1, le=2)]
    budget_source: Literal["frozen_work_attempt"] = "frozen_work_attempt"

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        ensure_unique(self.execution_record_sha256s, "knowledge execution receipts")
        maximum = min(self.initial_timeout_seconds * 4, 86_400)
        current = min(self.initial_timeout_seconds * (2 ** (self.expansion_number - 1)), maximum)
        if (
            self.role not in {AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER}
            or self.maximum_timeout_seconds != maximum
            or self.current_timeout_seconds != current
            or self.next_timeout_seconds != min(current * 2, maximum)
            or self.next_timeout_seconds <= current
            or (self.expansion_number == 1 and self.root_intent_sha256 != self.intent_sha256)
        ):
            raise ValueError("knowledge retry requires its exact finite doubled execution window")
        return self


class RejectedCoderOutputEvidence(DomainModel):
    """A stopped rejected progress report, never an interruption or a candidate."""

    scope: EngineeringScope
    requirement_id: NonEmptyStr
    task_id: TaskId
    work_item_id: NonEmptyStr
    original_lease_id: NonEmptyStr
    original_claim_sha256: DispositionSha256
    original_attempt: Annotated[StrictInt, Field(ge=1)]
    original_dispatch_sequence: Annotated[StrictInt, Field(ge=0)]
    checkpoint_sequence: Annotated[StrictInt, Field(ge=1)]
    previous_run_id: RunId
    previous_context_manifest_id: ContextId
    source_revision: NonEmptyStr
    invocation_start_sha256: DispositionSha256
    invocation_outcome_sha256: DispositionSha256
    rejected_artifact_id: ArtifactId
    rejected_artifact_sha256: DispositionSha256
    rejection_code: Literal["PROGRESS_SEQUENCE_MISMATCH"] = "PROGRESS_SEQUENCE_MISMATCH"
    expected_sequence: Annotated[StrictInt, Field(ge=1)]
    reported_sequence: Annotated[StrictInt, Field(ge=1)]
    process_stop_sha256: DispositionSha256
    capture_sha256: DispositionSha256
    workspace_inventory_sha256: DispositionSha256
    checkpoint_sha256: DispositionSha256
    budget_source: Literal["frozen_work_attempt"] = "frozen_work_attempt"

    @model_validator(mode="after")
    def require_real_rejection(self) -> Self:
        if (
            self.expected_sequence != self.original_attempt
            or self.reported_sequence == self.expected_sequence
        ):
            raise ValueError("rejected progress proof requires a real run sequence mismatch")
        return self


class InspectDeliveryWait(DomainModel):
    work_item_id: NonEmptyStr
    expected_disposition_sha256: DispositionSha256
    expected_task_intent_sha256: DispositionSha256
    expected_source_revision: NonEmptyStr
    expected_checkpoint_sequence: Annotated[StrictInt, Field(ge=0)]


class ResolveDeliveryWait(InspectDeliveryWait):
    resolution_kind: DeliveryResolutionKind
    proof_sha256: DispositionSha256
    submitted_at: AwareDatetime


class HandleDeliveryWait(InspectDeliveryWait):
    """Request one bounded platform handling, never assert execution facts."""


class DeliveryWaitInvestigation(DomainModel):
    """Trusted collector observation. Request fields cannot assert stop or readiness."""

    kind: Literal["delivery_wait_investigation"] = "delivery_wait_investigation"
    schema_version: Literal["v1"] = "v1"
    task_id: TaskId
    work_item_id: NonEmptyStr
    disposition: DeliveryDisposition
    disposition_sha256: DispositionSha256
    task_intent_sha256: DispositionSha256
    task_revision: Annotated[StrictInt, Field(ge=0)]
    task_snapshot_sha256: DispositionSha256
    source_revision: NonEmptyStr
    checkpoint_sequence: Annotated[StrictInt, Field(ge=0)]
    step_sha256: DispositionSha256
    original_run_id: RunId | None = None
    invocation_start_sha256: DispositionSha256 | None = None
    invocation_outcome_sha256: DispositionSha256 | None = None
    provider_failure_code: Literal["AUTHENTICATION_ERROR"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    interruption_receipt_sha256: DispositionSha256 | None = None
    process_stop_sha256: DispositionSha256 | None = None
    workspace_inventory_sha256: DispositionSha256 | None = None
    prerequisite_receipt_sha256: DispositionSha256 | None = None
    prerequisite_facts_sha256: DispositionSha256 | None = None
    original_authority: OriginalInvocationAuthority | None = None
    verification_retry: VerificationRetryEvidence | None = None
    verifier_preparation: VerifierPreparationEvidence | None = None
    knowledge_preparation: KnowledgePreparationRetryEvidence | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    rejected_output: RejectedCoderOutputEvidence | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    retry_cause: ContinuationCause | None = None
    permitted_resolutions: tuple[DeliveryResolutionKind, ...] = ()
    missing: tuple[DeliveryProofMissing, ...] = ()
    next_action: NonEmptyStr
    inspected_at: AwareDatetime
    proof_sha256: DispositionSha256

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        facts = self.disposition.facts
        if self.disposition_sha256 != self.disposition.disposition_sha256 or (
            facts.task_id,
            facts.work_item_id,
            facts.task_intent_sha256,
            facts.source_revision,
            facts.checkpoint_sequence,
        ) != (
            self.task_id,
            self.work_item_id,
            self.task_intent_sha256,
            self.source_revision,
            self.checkpoint_sequence,
        ):
            raise ValueError("engineering investigation changed its exact waiting facts")
        if self.provider_failure_code is not None and (
            facts.role is not AgentRole.CODER
            or self.invocation_start_sha256 is None
            or self.invocation_outcome_sha256 is None
            or self.original_run_id is None
            or self.permitted_resolutions
        ):
            raise ValueError("提供方前提失败提示只能绑定原 Coder 失败, 不能授予恢复或执行权限")
        ensure_unique(self.missing, "missing engineering proof")
        ensure_unique(self.permitted_resolutions, "permitted engineering resolutions")
        if self.permitted_resolutions and self.missing:
            raise ValueError("incomplete engineering proof cannot authorize a resolution")
        if (
            DeliveryResolutionKind.REPLAY_RECORDED_RESULT in self.permitted_resolutions
            and facts.classification in RESULT_REPLAY_REJECTED_CLASSIFICATIONS
        ):
            raise ValueError("a durably rejected outcome cannot authorize result replay")
        if (
            DeliveryResolutionKind.REPLAY_RECORDED_RESULT in self.permitted_resolutions
            and self.original_authority is None
        ):
            raise ValueError("recorded result replay requires its original producer authority")
        if (
            DeliveryResolutionKind.REVERIFY_CANDIDATE in self.permitted_resolutions
            and self.verification_retry is None
        ):
            raise ValueError("fresh candidate verification requires exact accepted QA evidence")
        if self.verification_retry is not None and (
            self.verification_retry.candidate_revision != self.source_revision
            or self.verification_retry.invocation_outcome_sha256 != self.invocation_outcome_sha256
            or self.verification_retry.prerequisite_facts_sha256 != self.prerequisite_facts_sha256
        ):
            raise ValueError("fresh candidate verification changed its exact candidate or facts")
        if DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION in self.permitted_resolutions and (
            self.verifier_preparation is None
            or self.verifier_preparation.native_execution_state != "FINISHED"
        ):
            raise ValueError("native preparation retry requires sealed final execution evidence")
        if self.verifier_preparation is not None and (
            self.verifier_preparation.candidate_revision != self.source_revision
            or self.verifier_preparation.prerequisite_facts_sha256 != self.prerequisite_facts_sha256
            or self.verifier_preparation.previous_run_id != self.original_run_id
            or self.invocation_start_sha256 is not None
            or self.invocation_outcome_sha256 is not None
        ):
            raise ValueError("native preparation proof changed its exact pre-model facts")
        if DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION in self.permitted_resolutions and (
            self.knowledge_preparation is None
        ):
            raise ValueError("knowledge preparation retry requires exact sealed native stop facts")
        if self.knowledge_preparation is not None and (
            self.knowledge_preparation.task_id != self.task_id
            or self.knowledge_preparation.work_item_id != self.work_item_id
            or self.knowledge_preparation.role is not facts.role
            or self.knowledge_preparation.source_revision != self.source_revision
            or self.knowledge_preparation.checkpoint_sequence != self.checkpoint_sequence
            or self.knowledge_preparation.previous_run_id != self.original_run_id
            or self.invocation_start_sha256 is not None
            or self.invocation_outcome_sha256 is not None
            or facts.classification != "KNOWLEDGE_PREPARATION_LIMIT"
            or facts.evidence_ids
            != ("knowledge-preparation://" + self.knowledge_preparation.outcome_sha256,)
            or self.permitted_resolutions
            not in ((), (DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION,))
            or self.original_authority is not None
            or self.verification_retry is not None
            or self.verifier_preparation is not None
        ):
            raise ValueError("knowledge preparation proof changed its exact pre-model facts")
        if (
            DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT in self.permitted_resolutions
            and self.rejected_output is None
        ):
            raise ValueError("rejected Coder retry requires its exact stopped checkpoint")
        rejected = self.rejected_output
        if rejected is not None and (
            rejected.task_id != self.task_id
            or rejected.work_item_id != self.work_item_id
            or facts.role is not AgentRole.CODER
            or facts.classification not in {"PLATFORM_BUG", "INVALID_OUTPUT"}
            or rejected.source_revision != self.source_revision
            or rejected.checkpoint_sequence != self.checkpoint_sequence
            or rejected.previous_run_id != self.original_run_id
            or rejected.invocation_start_sha256 != self.invocation_start_sha256
            or rejected.invocation_outcome_sha256 != self.invocation_outcome_sha256
            or rejected.process_stop_sha256 != self.process_stop_sha256
            or rejected.workspace_inventory_sha256 != self.workspace_inventory_sha256
            or self.retry_cause is not None
            or self.interruption_receipt_sha256 is not None
            or self.original_authority is not None
            or self.knowledge_preparation is not None
            or self.verification_retry is not None
            or self.verifier_preparation is not None
            or self.permitted_resolutions
            not in ((), (DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT,))
        ):
            raise ValueError("rejected Coder proof changed its exact stopped execution")
        return self

    def recompute_sha256(self) -> str:
        return _digest(self.model_dump(mode="json", exclude_none=True, exclude={"proof_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.proof_sha256 != self.recompute_sha256():
            raise ValueError("engineering investigation digest mismatch")


class DeliveryResolution(DomainModel):
    """A real engineering decision, sealed before queue consumption and never a verdict."""

    kind: Literal["delivery_wait_resolution"] = "delivery_wait_resolution"
    schema_version: Literal["v1"] = "v1"
    task_id: TaskId
    work_item_id: NonEmptyStr
    expected_disposition_sha256: DispositionSha256
    expected_task_intent_sha256: DispositionSha256
    expected_source_revision: NonEmptyStr
    expected_checkpoint_sequence: Annotated[StrictInt, Field(ge=0)]
    task_revision: Annotated[StrictInt, Field(ge=0)]
    task_snapshot_sha256: DispositionSha256
    step_sha256: DispositionSha256
    resolution_kind: DeliveryResolutionKind
    proof_sha256: DispositionSha256
    authorization_source: Literal[
        "engineering_operator_decision", "organization_engineering_policy"
    ] = "engineering_operator_decision"
    operator_principal: LocalOperatorPrincipal | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    engineering_admission: EngineeringAdmission | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    submitted_at: AwareDatetime
    resolution_sha256: DispositionSha256
    retry_failure: DeliveryRetryFailure | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    retry_cause: ContinuationCause | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    original_authority: OriginalInvocationAuthority | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    verification_retry: VerificationRetryEvidence | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    verifier_preparation: VerifierPreparationEvidence | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    knowledge_preparation: KnowledgePreparationRetryEvidence | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    rejected_output: RejectedCoderOutputEvidence | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def require_engineering_actor(self) -> Self:
        if self.authorization_source == "engineering_operator_decision":
            if self.operator_principal is None or self.engineering_admission is not None:
                raise ValueError("operator decision requires only its real engineering actor")
            self.operator_principal.require_duty(OperatorDuty.ENGINEERING)
        else:
            admission = self.engineering_admission
            if self.operator_principal is not None or admission is None:
                raise ValueError("policy resolution requires an admission, never an operator")
            admission.validate_integrity()
            if (
                admission.task_id != self.task_id
                or admission.task_intent_sha256 != self.expected_task_intent_sha256
                or admission.facts_sha256 != self.proof_sha256
                or admission.plan_sha256
                != delivery_wait_resolution_plan_sha256(self.proof_sha256, self.resolution_kind)
                or admission.capabilities != (EngineeringCapability.DELIVERY_WAIT_RESOLUTION,)
                or admission.admitted_at > self.submitted_at
            ):
                raise ValueError("policy resolution changed its exact engineering admission")
        retry = self.resolution_kind is DeliveryResolutionKind.RETRY_FROM_CHECKPOINT
        if retry != (self.retry_cause is not None):
            raise ValueError("checkpoint retry requires its sealed exact cause")
        if (retry and self.retry_cause == "provider_transient") != (self.retry_failure is not None):
            raise ValueError("only provider transient retry consumes a transient failure fact")
        if (self.resolution_kind is DeliveryResolutionKind.REPLAY_RECORDED_RESULT) != (
            self.original_authority is not None
        ):
            raise ValueError(
                "only recorded result replay uses the sealed original producer authority"
            )
        if (self.resolution_kind is DeliveryResolutionKind.REVERIFY_CANDIDATE) != (
            self.verification_retry is not None
        ):
            raise ValueError("only fresh candidate verification uses exact accepted QA evidence")
        if self.verification_retry is not None and (
            self.verification_retry.candidate_revision != self.expected_source_revision
        ):
            raise ValueError("fresh candidate verification changed the retained candidate")
        if self.resolution_kind is DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION and (
            self.verifier_preparation is None
            or self.verifier_preparation.native_execution_state != "FINISHED"
        ):
            raise ValueError("native preparation retry requires exact final execution evidence")
        if self.verifier_preparation is not None:
            expected_kind = (
                DeliveryResolutionKind.RESUME_UNINVOKED
                if self.verifier_preparation.native_execution_state == "NOT_STARTED"
                else DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION
            )
            if (
                self.resolution_kind is not expected_kind
                or self.verifier_preparation.candidate_revision != self.expected_source_revision
            ):
                raise ValueError(
                    "native preparation decision changed the retained candidate or action"
                )
        if (self.resolution_kind is DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION) != (
            self.knowledge_preparation is not None
        ):
            raise ValueError("only knowledge preparation retry uses sealed knowledge stop facts")
        if self.knowledge_preparation is not None and (
            self.knowledge_preparation.task_id != self.task_id
            or self.knowledge_preparation.work_item_id != self.work_item_id
            or self.knowledge_preparation.source_revision != self.expected_source_revision
            or self.knowledge_preparation.checkpoint_sequence != self.expected_checkpoint_sequence
        ):
            raise ValueError("knowledge preparation decision changed its exact task or source")
        if (self.resolution_kind is DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT) != (
            self.rejected_output is not None
        ):
            raise ValueError("only rejected Coder retry uses its independent checkpoint")
        if self.rejected_output is not None and (
            self.rejected_output.task_id != self.task_id
            or self.rejected_output.work_item_id != self.work_item_id
            or self.rejected_output.source_revision != self.expected_source_revision
            or self.rejected_output.checkpoint_sequence != self.expected_checkpoint_sequence
        ):
            raise ValueError("rejected Coder decision changed its exact task or source")
        return self

    def recompute_sha256(self) -> str:
        return _digest(
            self.model_dump(mode="json", exclude_none=True, exclude={"resolution_sha256"})
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.resolution_sha256 != self.recompute_sha256():
            raise ValueError("engineering resolution digest mismatch")


def delivery_wait_resolution_plan_sha256(proof_sha256: str, kind: DeliveryResolutionKind) -> str:
    """One deterministic, exact use of wait authority; not a new execution plan."""
    return _digest(
        {
            "kind": "delivery_wait_resolution_plan",
            "proof_sha256": proof_sha256,
            "resolution_kind": kind.value,
        }
    )


DeliveryWaitHandlingStatus = Literal[
    "RESOLVED",
    "WAITING_EXECUTION",
    "NEEDS_AUTHORIZATION",
    "PLATFORM_ATTENTION",
    "WAITING_PREREQUISITES",
    "BUDGET_EXHAUSTED",
]


class DeliveryWaitHandling(DomainModel):
    """Immutable platform handling report, separate from execution and verdict."""

    kind: Literal["delivery_wait_handling"] = "delivery_wait_handling"
    schema_version: Literal["v1"] = "v1"
    task_id: TaskId
    work_item_id: NonEmptyStr
    disposition_sha256: DispositionSha256
    task_intent_sha256: DispositionSha256
    source_revision: NonEmptyStr
    checkpoint_sequence: Annotated[StrictInt, Field(ge=0)]
    investigation: DeliveryWaitInvestigation
    resolution: DeliveryResolution | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    status: DeliveryWaitHandlingStatus
    summary: NonEmptyStr
    user_action: NonEmptyStr
    recheck_when: NonEmptyStr
    manual_resolution_allowed: StrictBool
    collection_failed: StrictBool = Field(default=False, exclude_if=lambda value: value is False)
    collection_failure: DeliveryWaitCollectionFailure | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    budget_settlement_sha256: DispositionSha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    handled_at: AwareDatetime
    handling_sha256: DispositionSha256

    @model_validator(mode="after")
    def validate_handling(self) -> Self:
        proof = self.investigation
        proof.validate_integrity()
        if (
            self.task_id,
            self.work_item_id,
            self.disposition_sha256,
            self.task_intent_sha256,
            self.source_revision,
            self.checkpoint_sequence,
        ) != (
            proof.task_id,
            proof.work_item_id,
            proof.disposition_sha256,
            proof.task_intent_sha256,
            proof.source_revision,
            proof.checkpoint_sequence,
        ):
            raise ValueError("platform handling changed its exact waiting facts")
        if (self.status == "RESOLVED") != (self.resolution is not None):
            raise ValueError("resolved handling requires its sealed resolution")
        if self.budget_settlement_sha256 is not None and (
            self.status != "BUDGET_EXHAUSTED"
            or self.resolution is not None
            or self.collection_failed
            or self.collection_failure is not None
            or proof.permitted_resolutions
        ):
            raise ValueError("budget settlement cannot authorize further execution")
        if self.collection_failure is not None and (
            not self.collection_failed
            or self.status != "PLATFORM_ATTENTION"
            or self.resolution is not None
            or proof.process_stop_sha256 is None
            or DeliveryProofMissing.STOP_UNRECORDED in proof.missing
            or DeliveryProofMissing.CHECKPOINT_UNAVAILABLE not in proof.missing
            or proof.permitted_resolutions
        ):
            raise ValueError(
                "capture refusal requires a verified stop and an unavailable checkpoint"
            )
        if self.resolution is not None:
            decision = self.resolution
            decision.validate_integrity()
            if (
                proof.missing
                or decision.proof_sha256 != proof.proof_sha256
                or decision.resolution_kind not in proof.permitted_resolutions
                or decision.task_revision != proof.task_revision
                or decision.task_snapshot_sha256 != proof.task_snapshot_sha256
                or decision.step_sha256 != proof.step_sha256
                or decision.knowledge_preparation != proof.knowledge_preparation
                or decision.rejected_output != proof.rejected_output
                or (
                    decision.task_id,
                    decision.work_item_id,
                    decision.expected_disposition_sha256,
                    decision.expected_task_intent_sha256,
                    decision.expected_source_revision,
                    decision.expected_checkpoint_sequence,
                )
                != (
                    self.task_id,
                    self.work_item_id,
                    self.disposition_sha256,
                    self.task_intent_sha256,
                    self.source_revision,
                    self.checkpoint_sequence,
                )
            ):
                raise ValueError("platform handling resolution does not match its proof")
        return self

    def recompute_sha256(self) -> str:
        return _digest(self.model_dump(mode="json", exclude_none=True, exclude={"handling_sha256"}))

    @property
    def record_key(self) -> str:
        return delivery_wait_handling_record_key(
            InspectDeliveryWait(
                work_item_id=self.work_item_id,
                expected_disposition_sha256=self.disposition_sha256,
                expected_task_intent_sha256=self.task_intent_sha256,
                expected_source_revision=self.source_revision,
                expected_checkpoint_sequence=self.checkpoint_sequence,
            ),
            self.investigation,
            manual_resolution_allowed=self.manual_resolution_allowed,
            collection_failed=self.collection_failed,
            collection_failure=self.collection_failure,
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.handling_sha256 != self.recompute_sha256():
            raise ValueError("platform handling digest mismatch")


def delivery_wait_handling_record_key(
    command: InspectDeliveryWait,
    proof: DeliveryWaitInvestigation,
    *,
    manual_resolution_allowed: bool,
    collection_failed: bool = False,
    collection_failure: DeliveryWaitCollectionFailure | None = None,
) -> str:
    return _digest(
        {
            "binding": command.to_wire(),
            "facts": proof.model_dump(
                mode="json",
                exclude={
                    "proof_sha256",
                    "inspected_at",
                    "prerequisite_receipt_sha256",
                },
            ),
            "manual_resolution_allowed": manual_resolution_allowed,
            "collection_failed": collection_failed,
            **({"collection_failure": collection_failure.value} if collection_failure else {}),
        }
    )


class EngineeringDispositionRecord(DomainModel):
    """Durable compatibility decision; it never reopens an original terminal Task."""

    kind: Literal["engineering_disposition_record"] = "engineering_disposition_record"
    schema_version: Literal["v1"] = "v1"
    compatibility_mode: Literal["terminal_recovery"] = "terminal_recovery"
    delivery_id: NonEmptyStr
    native_checkpoint_sha256: DispositionSha256
    source_task_id: TaskId
    source_task_status: Literal[TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.DONE]
    source_task_snapshot_sha256: DispositionSha256
    repository_root: NonEmptyStr
    plan_sha256: DispositionSha256
    rejection_code: Literal[
        "LEGACY_AUTHORITY",
        "FROZEN_INPUT_CHANGED",
        "CAPABILITY_UNAVAILABLE",
        "BUDGET_EXHAUSTED",
        "SCOPE_CHANGE",
        "VERIFICATION_EXECUTION_BLOCKED",
        "UNVERIFIED_RECOVERY_FACTS",
    ]
    source_diagnostic: NonEmptyStr | None = None
    disposition: DeliveryDisposition
    recorded_at: AwareDatetime
    record_sha256: DispositionSha256

    @model_validator(mode="after")
    def validate_terminal_binding(self) -> Self:
        if self.disposition.facts.task_id != self.source_task_id:
            raise ValueError("terminal engineering disposition belongs to another Task")
        if self.disposition.facts.work_item_id is not None:
            raise ValueError("terminal compatibility disposition cannot invent a queue wait")
        return self

    def recompute_sha256(self) -> str:
        return _digest(self.model_dump(mode="json", exclude_none=True, exclude={"record_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.record_sha256 != self.recompute_sha256():
            raise ValueError("terminal engineering disposition digest mismatch")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
