"""Append-only execution baseline facts preserve the approved Task and role history."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.artifact import (
    ArtifactId,
    CoderProgressArtifact,
    ImplementationReportArtifact,
    Sha256,
)
from ai_software_engineer.domain.branch import BranchName
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import Task, TaskId

FullGitRevision = Annotated[str, StringConstraints(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")]


class BaselineInputMode(StrEnum):
    PRESERVE_DRAFT = "preserve_draft"
    CODER_REAPPLY = "coder_reapply"


class RetainedExecutionPatch(DomainModel):
    """Reference to complete old execution-base → candidate + dirty mutation bodies.

    Trusted collection must validate the body and URI before this reference is
    published. A digest alone never permits discarding a dirty worktree.
    """

    uri: NonEmptyStr
    sha256: Sha256
    bytes: Annotated[StrictInt, Field(ge=0, le=8_000_000)]


class ExecutionBaselineBinding(DomainModel):
    """One completed source rebind, never a role verdict or a new Product approval."""

    kind: Literal["execution_baseline_binding"] = "execution_baseline_binding"
    schema_version: Literal["v1"] = "v1"
    scope: EngineeringScope
    task_id: TaskId
    task_intent_sha256: Sha256
    sequence: Annotated[StrictInt, Field(ge=1, le=100)]
    previous_binding_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    approved_base_ref: FullGitRevision
    branch_name: BranchName
    worktree_path: NonEmptyStr
    prior_execution_base_ref: FullGitRevision
    prior_source_revision: FullGitRevision
    execution_base_ref: FullGitRevision
    execution_source_revision: FullGitRevision
    input_mode: BaselineInputMode
    superseded_implementation_artifact_id: ArtifactId | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    superseded_progress_artifact_id: ArtifactId | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    source_artifact_ids: tuple[ArtifactId, ...]
    resolved_interruption_receipt_sha256s: tuple[Sha256, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    retained_patch: RetainedExecutionPatch
    authority_source: Literal["organization_engineering_policy", "engineering_operator_decision"]
    authority_sha256: Sha256
    plan_sha256: Sha256
    facts_sha256: Sha256
    prior_task_revision: Annotated[StrictInt, Field(ge=1)]
    before_inventory_sha256: Sha256
    after_inventory_sha256: Sha256
    completed_at: AwareDatetime
    binding_sha256: Sha256

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        ensure_unique(self.source_artifact_ids, "baseline source artifact IDs")
        ensure_unique(
            self.resolved_interruption_receipt_sha256s, "resolved baseline interruption receipts"
        )
        if (self.sequence == 1) != (self.previous_binding_sha256 is None):
            raise ValueError("baseline binding must extend the exact previous record")
        if self.execution_base_ref == self.prior_execution_base_ref:
            raise ValueError("baseline binding must change the execution base")
        if (
            self.input_mode is BaselineInputMode.CODER_REAPPLY
            and self.execution_source_revision != self.execution_base_ref
        ):
            raise ValueError("Coder reapply starts from the clean exact target base")
        for identity in (
            self.superseded_implementation_artifact_id,
            self.superseded_progress_artifact_id,
        ):
            if identity is not None and identity not in self.source_artifact_ids:
                raise ValueError("superseded role input must remain in baseline history")
        return self

    def recompute_sha256(self) -> str:
        payload = self.to_wire()
        payload.pop("binding_sha256")
        return hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        ).hexdigest()

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.recompute_sha256() != self.binding_sha256:
            raise ValueError("execution baseline binding integrity differs")

    @classmethod
    def create(cls, **values: object) -> Self:
        binding = cls.model_validate({**values, "binding_sha256": "0" * 64})
        return binding.model_copy(update={"binding_sha256": binding.recompute_sha256()})

    def require_task(self, task: Task) -> None:
        self.validate_integrity()
        if (
            task.id != self.task_id
            or task.repository != self.scope.repository_root
            or task.base_ref != self.approved_base_ref
            or task.branch_name != self.branch_name
            or task_intent_sha256(task) != self.task_intent_sha256
        ):
            raise ValueError("baseline binding differs from the approved Task intent")

    def require_predecessor(self, previous: ExecutionBaselineBinding | None) -> None:
        self.validate_integrity()
        if previous is None:
            if (
                self.sequence != 1
                or self.previous_binding_sha256 is not None
                or self.prior_execution_base_ref != self.approved_base_ref
            ):
                raise ValueError("first baseline binding has no exact approved predecessor")
            return
        previous.validate_integrity()
        if (
            self.scope != previous.scope
            or self.task_id != previous.task_id
            or self.task_intent_sha256 != previous.task_intent_sha256
            or self.approved_base_ref != previous.approved_base_ref
            or self.branch_name != previous.branch_name
            or self.worktree_path != previous.worktree_path
            or self.sequence != previous.sequence + 1
            or self.previous_binding_sha256 != previous.binding_sha256
            or self.prior_execution_base_ref != previous.execution_base_ref
            or self.completed_at < previous.completed_at
        ):
            raise ValueError("baseline binding changed append-only execution lineage")


@dataclass(frozen=True, slots=True)
class CoderExecutionInput:
    source_revision: str
    execution_base_ref: str
    active_progress: CoderProgressArtifact | None
    baseline: ExecutionBaselineBinding | None


def resolve_coder_execution_input(
    task: Task,
    *,
    implementation: ImplementationReportArtifact | None,
    progress: CoderProgressArtifact | None,
    baseline: ExecutionBaselineBinding | None,
) -> CoderExecutionInput:
    """Resolve one source for runner/boundary/context/Native/worktree composition.

    The old implementation/progress remains immutable. A baseline input cannot
    resurrect it as the active checkpoint; new artifacts supersede it normally.
    Git ancestry, exact workspace inventory and accepted artifact integrity are
    validated by the caller's trusted collector before passing these values.
    """
    for artifact in (implementation, progress):
        if artifact is not None and artifact.task_id != task.id:
            raise ValueError("Coder source artifact belongs to another Task")
    if baseline is None:
        source = implementation.content.commit_sha if implementation is not None else task.base_ref
        if progress is not None and progress.source_revision != source:
            raise ValueError("active progress does not match the current Coder input")
        return CoderExecutionInput(source, task.base_ref, progress, None)
    baseline.require_task(task)
    current_implementation = implementation
    if (
        current_implementation is not None
        and current_implementation.artifact_id == baseline.superseded_implementation_artifact_id
    ):
        current_implementation = None
    source = (
        current_implementation.content.commit_sha
        if current_implementation is not None
        else baseline.execution_source_revision
    )
    active_progress = progress
    if (
        active_progress is not None
        and active_progress.artifact_id == baseline.superseded_progress_artifact_id
    ):
        active_progress = None
    if active_progress is not None and active_progress.source_revision != source:
        raise ValueError("new progress does not match the bound execution source")
    return CoderExecutionInput(source, baseline.execution_base_ref, active_progress, baseline)
