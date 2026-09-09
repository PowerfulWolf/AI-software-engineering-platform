"""Digest-bound intent and per-role admission for candidate verification."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, model_validator

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.domain.agent import AgentDefinition
from ai_software_engineer.domain.artifact import (
    ArtifactId,
    QaReportArtifact,
    ReviewReportArtifact,
    Sha256,
)
from ai_software_engineer.domain.enums import AgentRole, QaReportStatus, ReviewVerdict
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.project_manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.recovery.models import FullCommit, RecoveryScope, _safe_text, digest


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
    prior_run_ids: tuple[RunId, ...] = ()

    @model_validator(mode="after")
    def unique_runs(self) -> Self:
        if len(set(self.prior_run_ids)) != len(self.prior_run_ids):
            raise ValueError("prior verifier run identities must be unique")
        return self


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
    created_at: AwareDatetime
    plan_sha256: Sha256

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


class CandidateVerificationCompletion(DomainModel):
    """Immutable verifier reports; never a replacement Task success event."""

    kind: Literal["candidate_verification_completion"] = "candidate_verification_completion"
    schema_version: Literal["v0.1"] = "v0.1"
    plan_sha256: Sha256
    authorization_sha256: Sha256
    qa_invocation_sha256: Sha256
    reviewer_invocation_sha256: Sha256 | None = None
    qa: QaReportArtifact
    review: ReviewReportArtifact | None = None
    completed_at: AwareDatetime
    completion_sha256: Sha256

    @property
    def verified(self) -> bool:
        return self.review is not None and self.review.content.verdict is ReviewVerdict.APPROVE

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
