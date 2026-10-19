"""Positive pre-admission knowledge pause evidence, never an inferred process stop."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.identity import ContextId, RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import TaskId


class KnowledgePreparationPauseEvidence(DomainModel):
    scope: EngineeringScope
    requirement_id: NonEmptyStr
    delivery_requirement_id: NonEmptyStr
    task_id: TaskId
    role: Literal[AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER]
    work_item_id: NonEmptyStr
    original_lease_id: NonEmptyStr
    original_claim_sha256: Sha256
    original_attempt: Annotated[StrictInt, Field(ge=1)]
    original_dispatch_sequence: Annotated[StrictInt, Field(ge=0)]
    checkpoint_sequence: Annotated[StrictInt, Field(ge=0)]
    previous_run_id: RunId
    previous_context_manifest_id: ContextId
    source_revision: NonEmptyStr
    snapshot_sha256: Sha256
    phase: Literal["intent", "assessment"]
    intent_sha256: Sha256
    outcome_sha256: Sha256
    request_sha256: Sha256
    proof_mode: Literal["pre_admission_refusal", "native_admission_closed"]
    pre_admission_pause_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    execution_record_sha256s: tuple[Sha256, ...]

    @model_validator(mode="after")
    def require_positive_refusal(self) -> Self:
        ensure_unique(self.execution_record_sha256s, "knowledge pause execution records")
        if self.proof_mode == "pre_admission_refusal":
            if self.pre_admission_pause_sha256 is None or self.execution_record_sha256s:
                raise ValueError("pre-admission pause needs its positive independent refusal")
        elif self.pre_admission_pause_sha256 is not None or len(self.execution_record_sha256s) != 2:
            raise ValueError("native admission closure needs its exact admission and refusal pair")
        return self
