"""Digest-bound intent and per-role admission for candidate verification."""

from __future__ import annotations

from collections.abc import Set
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, field_validator, model_validator

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.domain.agent import AgentDefinition
from ai_software_engineer.domain.artifact import (
    ArtifactId,
    QaReportArtifact,
    ReviewReportArtifact,
    Sha256,
    classify_qa_failure,
)
from ai_software_engineer.domain.enums import (
    AgentRole,
    QaFailureDisposition,
    QaReportStatus,
    ReviewVerdict,
)
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.execution import CommandResult
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.manager.native_ui import NativeUiCapability, NativeUiResult
from ai_software_engineer.manager.verification_coordination import (
    ManagerVerificationAdvice,
    VerificationFailureReference,
)
from ai_software_engineer.manager.verification_environment import SwiftSandboxCapability
from ai_software_engineer.recovery.models import FullCommit, RecoveryScope, _safe_text, digest


class AcceptedQaReport(DomainModel):
    """One sealed QA PASS selected from the terminal Task event chain."""

    artifact_id: ArtifactId
    artifact_sha256: Sha256


class CandidateVerificationInputs(DomainModel):
    """Exact original facts; a matching digest is not an authorization."""

    task_id: TaskId
    task_revision: StrictInt = Field(ge=1)
    task_sha256: Sha256
    plan_id: ArtifactId
    plan_sha256: Sha256
    implementation_id: ArtifactId
    implementation_sha256: Sha256
    candidate_revision: FullCommit
    accepted_qa: AcceptedQaReport | None = None
    prior_run_ids: tuple[RunId, ...] = ()

    @model_validator(mode="after")
    def unique_runs(self) -> Self:
        if len(set(self.prior_run_ids)) != len(self.prior_run_ids):
            raise ValueError("prior verifier run identities must be unique")
        return self


def verification_inputs_are_current(
    approved: CandidateVerificationInputs,
    current: CandidateVerificationInputs,
    admitted_run_ids: Set[str],
) -> bool:
    """Accept only append-only run facts durably admitted by the exact approved plan."""
    approved_runs, current_runs = set(approved.prior_run_ids), set(current.prior_run_ids)
    return (
        current.model_copy(update={"prior_run_ids": approved.prior_run_ids}) == approved
        and approved_runs <= current_runs
        and current_runs - approved_runs <= set(admitted_run_ids)
    )


class PriorVisualEvidence(DomainModel):
    """Exact QA receipt of the prerequisite completion, not ambient history access."""

    plan_sha256: Sha256
    record_sha256: Sha256


class RetainedVerificationQa(DomainModel):
    """Admitted, sealed standalone QA before an interrupted Reviewer completed."""

    plan_sha256: Sha256
    qa_invocation_sha256: Sha256
    reviewer_invocation_sha256: Sha256 | None = None
    qa: QaReportArtifact


class CandidateVerificationPlan(DomainModel):
    kind: Literal["candidate_verification_plan"] = "candidate_verification_plan"
    schema_version: Literal["v0.1"] = "v0.1"
    scope: RecoveryScope
    inputs: CandidateVerificationInputs
    execution_task_id: TaskId = "task_candidate_verification"
    native_checkpoint_sha256: Sha256
    dispatch_sha256: Sha256
    approved_stage_chain_sha256: Sha256
    current_policy_sha256: Sha256
    parent_delivery_id: DeliveryId | None = None
    parent_checkpoint_sha256: Sha256 | None = None
    definitions: tuple[AgentDefinition, ...]
    executor_capability: SwiftSandboxCapability | None = None
    native_ui: NativeUiCapability | None = None
    prerequisite_incident_sha256: Sha256 | None = None
    prior_visual_evidence: PriorVisualEvidence | None = None
    retained_qa: RetainedVerificationQa | None = None
    manager_advice: ManagerVerificationAdvice | None = None
    created_at: AwareDatetime
    plan_sha256: Sha256

    @property
    def reused_qa(self) -> AcceptedQaReport | None:
        if self.retained_qa is not None:
            return AcceptedQaReport(
                artifact_id=self.retained_qa.qa.artifact_id,
                artifact_sha256=self.retained_qa.qa.integrity.sha256,
            )
        return self.inputs.accepted_qa

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_validate({**values, "plan_sha256": "0" * 64})
        return provisional.model_copy(update={"plan_sha256": provisional.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude_none=True, exclude={"plan_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.plan_sha256 != self.recompute_sha256():
            raise ValueError("candidate verification plan digest mismatch")

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.retained_qa is not None and self.inputs.accepted_qa is not None:
            raise ValueError("native and standalone QA reuse are mutually exclusive")
        if self.prior_visual_evidence is not None and (
            self.prerequisite_incident_sha256 is None or self.native_ui is None
        ):
            raise ValueError("prior visual evidence requires a prerequisite and native UI plan")
        if self.manager_advice is not None:
            self.manager_advice.validate_integrity()
            if (
                self.manager_advice.scope_sha256 != digest(self.scope.to_wire())
                or self.manager_advice.candidate_revision != self.inputs.candidate_revision
                or self.native_ui is None
                or self.manager_advice.draft.native_ui_scenario != self.native_ui.scenario
            ):
                raise ValueError("verification plan does not bind the exact Manager UI proposal")
        if self.native_ui is not None and self.executor_capability is None:
            raise ValueError("native UI requires an approved isolated Swift build capability")
        if self.execution_task_id == self.inputs.task_id:
            raise ValueError("verification execution must not reuse the terminal Task identity")
        if (self.parent_delivery_id is None) != (self.parent_checkpoint_sha256 is None):
            raise ValueError("parent identity and checkpoint must be paired")
        if len(self.definitions) != len(AgentRole) or {d.role for d in self.definitions} != set(
            AgentRole
        ):
            raise ValueError("verification plan must bind the complete role definitions")
        if len({d.id for d in self.definitions}) != len(self.definitions):
            raise ValueError("role identities must be independent")
        for definition in self.definitions:
            if definition.role in (AgentRole.QA, AgentRole.REVIEWER) and (
                definition.permissions.can_merge or definition.permissions.can_change_state
            ):
                raise ValueError("verifiers cannot merge or change Task state")
            for value in (
                *definition.permissions.read_paths,
                *definition.permissions.write_paths,
                *definition.permissions.commands,
            ):
                _safe_text(value)
        return self


class CandidateVerificationInvocation(DomainModel):
    kind: Literal["candidate_verification_invocation"] = "candidate_verification_invocation"
    schema_version: Literal["v0.1"] = "v0.1"
    plan_sha256: Sha256
    authorization_sha256: Sha256
    request: AgentRequest
    admitted_at: AwareDatetime
    invocation_sha256: Sha256

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_validate({**values, "invocation_sha256": "0" * 64})
        return provisional.model_copy(update={"invocation_sha256": provisional.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return digest(
            self.model_dump(mode="json", exclude_none=True, exclude={"invocation_sha256"})
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.invocation_sha256 != self.recompute_sha256():
            raise ValueError("verification invocation digest mismatch")

    @model_validator(mode="after")
    def only_verifiers(self) -> Self:
        if self.request.role not in (AgentRole.QA, AgentRole.REVIEWER):
            raise ValueError("candidate verification cannot admit Coder or Planner")
        return self


VerificationExecutionFailure = Literal[
    "COMMAND_TIMEOUT", "COMMAND_START_FAILED", "NATIVE_UI_UNAVAILABLE", "NATIVE_UI_SESSION_LOCKED"
]


def native_ui_failure_code(
    results: tuple[NativeUiResult, ...] | None,
) -> VerificationExecutionFailure | None:
    error = results[-1].output.error if results else None
    if error == "SESSION_LOCKED":
        return "NATIVE_UI_SESSION_LOCKED"
    return "NATIVE_UI_UNAVAILABLE" if error is not None else None


class VerificationExecutionRecord(DomainModel):
    """At-most-once controlled execution, separate from every model's verdict."""

    kind: Literal["verification_execution"] = "verification_execution"
    phase: Literal["STARTED", "COMPLETED", "BLOCKED"]
    plan_sha256: Sha256
    invocation_sha256: Sha256
    authorization_sha256: Sha256
    candidate_revision: FullCommit
    role: Literal[AgentRole.QA, AgentRole.REVIEWER]
    capability: SwiftSandboxCapability
    native_ui: NativeUiCapability | None = None
    ui_results: tuple[NativeUiResult, ...] | None = None
    source_root: str
    scratch_root: str
    results: tuple[CommandResult, ...] = ()
    failure_code: VerificationExecutionFailure | None = None
    recorded_at: AwareDatetime
    record_sha256: Sha256

    @property
    def effective_failure_code(self) -> VerificationExecutionFailure | None:
        """Interpret old partial UI receipts without rewriting their recorded phase/hash."""
        return self.failure_code or native_ui_failure_code(self.ui_results)

    @field_validator("source_root", "scratch_root")
    @classmethod
    def safe_execution_path(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in value):
            raise ValueError("execution paths must be safe absolute paths")
        return value

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_validate({**values, "record_sha256": "0" * 64})
        return provisional.model_copy(update={"record_sha256": provisional.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude_none=True, exclude={"record_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.record_sha256 != self.recompute_sha256():
            raise ValueError("verification execution record digest mismatch")

    @model_validator(mode="after")
    def validate_execution_shape(self) -> Self:
        source, scratch = Path(self.source_root), Path(self.scratch_root)
        if scratch.is_relative_to(source) or source.is_relative_to(scratch):
            raise ValueError("execution scratch must not overlap source")
        if (self.phase == "BLOCKED") != (self.failure_code is not None):
            raise ValueError("blocked execution requires exactly one typed failure")
        if len(self.results) > 2:
            raise ValueError("controlled execution has only two commands")
        if self.ui_results is not None:
            if self.native_ui is None or self.phase == "STARTED":
                raise ValueError(
                    "native UI evidence requires approved capability and final receipt"
                )
            if not self.ui_results or len(self.ui_results) > len(self.native_ui.scenario.steps):
                raise ValueError("native UI receipt has no steps or exceeds approved sequence")
            if (
                tuple(result.step for result in self.ui_results)
                != self.native_ui.scenario.steps[: len(self.ui_results)]
                or any(result.output.error is not None for result in self.ui_results[:-1])
                or len({result.output.pid for result in self.ui_results}) != 1
                or any(result.output.action != result.step.action for result in self.ui_results)
                or (
                    self.ui_results[-1].output.error is None
                    and len(self.ui_results) != len(self.native_ui.scenario.steps)
                )
            ):
                raise ValueError("native UI results must be a complete sequence or stop at failure")
            for result in self.ui_results:
                diagnostic = result.output.diagnostics
                if diagnostic is not None and diagnostic.launch_argv is not None:
                    binary, argument = diagnostic.launch_argv
                    path = Path(binary)
                    if (
                        not path.is_absolute()
                        or ".." in path.parts
                        or not path.is_relative_to(scratch / "build")
                        or path.name != self.native_ui.scenario.product
                        or argument != self.native_ui.scenario.mock_argument
                        or diagnostic.process_running != (diagnostic.process_returncode is None)
                    ):
                        raise ValueError("UI launch diagnostic differs from the approved child")
        if (self.phase == "STARTED" and self.results) or (
            self.phase == "COMPLETED" and len(self.results) != 2
        ):
            raise ValueError("execution phase and command results differ")
        return self


class CandidateVerificationDisposition(StrEnum):
    """Typed next route for one sealed candidate verification completion."""

    VERIFIED = "VERIFIED"
    RETRY_VERIFICATION = "RETRY_VERIFICATION"
    REMEDIATE_CANDIDATE = "REMEDIATE_CANDIDATE"


class CandidateExecutorPrerequisite(DomainModel):
    """A sealed executor observation, explicitly NOT a verification completion or verdict."""

    kind: Literal["candidate_executor_prerequisite"] = "candidate_executor_prerequisite"
    plan_sha256: Sha256
    source_task_id: TaskId
    candidate_revision: FullCommit
    execution_failure: VerificationFailureReference
    observed_at: AwareDatetime
    observation_sha256: Sha256

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "observation_sha256": "0" * 64})
        return value.model_copy(update={"observation_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"observation_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if (
            self.observation_sha256 != self.recompute_sha256()
            or self.execution_failure.plan_sha256 != self.plan_sha256
        ):
            raise ValueError("executor prerequisite identity mismatch")

    @property
    def verified(self) -> bool:
        return False

    @property
    def evidence_sha256(self) -> str:
        return self.observation_sha256

    @property
    def evidence_at(self) -> AwareDatetime:
        return self.observed_at


class CandidateVerificationCompletion(DomainModel):
    """Immutable verifier reports; never a replacement Task success event."""

    kind: Literal["candidate_verification_completion"] = "candidate_verification_completion"
    schema_version: Literal["v0.1"] = "v0.1"
    plan_sha256: Sha256
    authorization_sha256: Sha256
    qa_invocation_sha256: Sha256 | None = None
    reviewer_invocation_sha256: Sha256 | None = None
    qa: QaReportArtifact
    review: ReviewReportArtifact | None = None
    completed_at: AwareDatetime
    completion_sha256: Sha256

    @property
    def evidence_sha256(self) -> str:
        return self.completion_sha256

    @property
    def evidence_at(self) -> AwareDatetime:
        return self.completed_at

    @property
    def verified(self) -> bool:
        return self.review is not None and self.review.content.verdict is ReviewVerdict.APPROVE

    @property
    def disposition(self) -> CandidateVerificationDisposition:
        if self.verified:
            return CandidateVerificationDisposition.VERIFIED
        if self.review is not None:
            return CandidateVerificationDisposition.REMEDIATE_CANDIDATE
        if classify_qa_failure(self.qa.content) is QaFailureDisposition.RETRY_VERIFICATION:
            return CandidateVerificationDisposition.RETRY_VERIFICATION
        return CandidateVerificationDisposition.REMEDIATE_CANDIDATE

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_validate({**values, "completion_sha256": "0" * 64})
        return provisional.model_copy(update={"completion_sha256": provisional.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return digest(
            self.model_dump(mode="json", exclude_none=True, exclude={"completion_sha256"})
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.completion_sha256 != self.recompute_sha256():
            raise ValueError("verification completion digest mismatch")

    @model_validator(mode="after")
    def validate_verdict_chain(self) -> Self:
        if (self.review is None) != (self.reviewer_invocation_sha256 is None):
            raise ValueError("Reviewer report and invocation must be paired")
        if (self.qa.content.status is QaReportStatus.PASS) != (self.review is not None):
            raise ValueError("completion requires Review exactly when QA passed")
        return self


CandidateRemediationEvidence = CandidateVerificationCompletion | CandidateExecutorPrerequisite
