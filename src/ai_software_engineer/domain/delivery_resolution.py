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
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.enums import TaskStatus
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


RESULT_REPLAY_REJECTED_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        "INVALID_OUTPUT",
        "POLICY_VIOLATION",
        "PLATFORM_BUG",
        "REQUIREMENT_AMBIGUITY",
        "BUDGET_EXHAUSTED",
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
    interruption_receipt_sha256: DispositionSha256 | None = None
    process_stop_sha256: DispositionSha256 | None = None
    workspace_inventory_sha256: DispositionSha256 | None = None
    prerequisite_receipt_sha256: DispositionSha256 | None = None
    prerequisite_facts_sha256: DispositionSha256 | None = None
    original_authority: OriginalInvocationAuthority | None = None
    verification_retry: VerificationRetryEvidence | None = None
    verifier_preparation: VerifierPreparationEvidence | None = None
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
