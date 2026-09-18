"""Durable recovery intent and human decisions; no Task or execution mutation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from ai_software_engineer.domain import AgentPermissions, AgentRole
from ai_software_engineer.domain.identity import ContextId, RepositoryId, RunId, TeamId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.git.capture import (
    MAX_CAPTURE_BYTES,
    MAX_CAPTURE_FILES,
    WorktreeChangeCapture,
)
from ai_software_engineer.git.ports import AttemptNumber, WorktreeRef
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.redaction import redact_text


class RecoveryRejected(RuntimeError):
    """A recovery fact, decision or current-fact gate cannot be trusted."""


class RecoveryConflict(RecoveryRejected):
    """A durable identity was reused with changed input."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _absolute(value: str) -> str:
    if (
        not value.startswith("/")
        or any(part in (".", "..") for part in value.split("/"))
        or str(Path(value)) != value
    ):
        raise ValueError("recovery paths must be canonical absolute paths")
    return value


def _relative(value: str) -> str:
    if (
        PurePosixPath(value).is_absolute()
        or any(p in ("", ".", "..", ".git") for p in value.split("/"))
        or any(c in value for c in "\\*?[")
    ):
        raise ValueError("capture requires canonical relative file paths")
    return value


def _safe_text(value: str) -> str:
    if redact_text(value).occurrences:
        raise ValueError("recovery text contains sensitive content")
    return value


AbsolutePath = Annotated[
    str,
    StringConstraints(pattern=r"^/[^\x00-\x1f]*$"),
    AfterValidator(_absolute),
    AfterValidator(_safe_text),
]
RelativePath = Annotated[
    str,
    StringConstraints(min_length=1, pattern=r"^[^\x00-\x1f]+$"),
    AfterValidator(_relative),
    AfterValidator(_safe_text),
]
FullCommit = Annotated[str, StringConstraints(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")]
SafeText = Annotated[
    str, StringConstraints(min_length=1, max_length=2000), AfterValidator(_safe_text)
]

RecoveryInputMode = Literal["coder_reapply"]
RecoveryPathRebindingReason = Literal["missing_source_path_unique_match"]


class CapturedFile(DomainModel):
    path: RelativePath
    sha256: StageSha256


class CapturedChanges(DomainModel):
    task_id: TaskId
    attempt: AttemptNumber
    source_revision: FullCommit
    worktree_path: AbsolutePath
    patch: Annotated[str, StringConstraints(max_length=MAX_CAPTURE_BYTES)]
    index_diff_sha256: StageSha256
    files: tuple[CapturedFile, ...] = Field(max_length=MAX_CAPTURE_FILES)
    capture_sha256: StageSha256
    base_revision: FullCommit | None = None

    @classmethod
    def from_capture(cls, capture: WorktreeChangeCapture) -> CapturedChanges:
        if capture.worktree.role is not AgentRole.CODER or capture.worktree.detached:
            raise RecoveryRejected("recovery requires an assigned Coder capture")
        result = cls(
            task_id=capture.worktree.task_id,
            attempt=capture.worktree.attempt,
            source_revision=capture.worktree.head_revision,
            worktree_path=str(capture.worktree.path),
            patch=capture.patch.decode("utf-8"),
            index_diff_sha256=capture.index_diff_sha256,
            files=tuple(CapturedFile(path=p, sha256=s) for p, s in capture.file_sha256s),
            capture_sha256=capture.capture_sha256,
            base_revision=capture.base_revision,
        )
        if result.to_capture() != capture:
            raise RecoveryRejected("capture has a noncanonical Coder identity")
        return result

    def to_capture(self) -> WorktreeChangeCapture:
        return WorktreeChangeCapture(
            worktree=WorktreeRef(
                task_id=self.task_id,
                role=AgentRole.CODER,
                attempt=self.attempt,
                path=Path(self.worktree_path),
                head_revision=self.source_revision,
                branch=f"ai/{self.task_id}/attempt-{self.attempt}",
                detached=False,
            ),
            patch=self.patch.encode("utf-8"),
            index_diff_sha256=self.index_diff_sha256,
            file_sha256s=tuple((f.path, f.sha256) for f in self.files),
            base_revision=self.base_revision,
        )

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        paths = tuple(f.path for f in self.files)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("captured paths must be sorted and unique")
        if (
            len(self.patch.encode("utf-8")) > MAX_CAPTURE_BYTES
            or "\0" in self.patch
            or "GIT binary patch" in self.patch
        ):
            raise ValueError("recovery patch must be bounded UTF-8 text")
        _safe_text(self.patch)
        if self.to_capture().capture_sha256 != self.capture_sha256:
            raise ValueError("capture digest does not match content")
        return self


class RecoveryScope(DomainModel):
    team_id: TeamId
    repository_id: RepositoryId
    delivery_id: DeliveryId
    repository_root: AbsolutePath


class RecoverySource(DomainModel):
    """Exact references; a trusted facts port must resolve and verify their origin."""

    scope: RecoveryScope
    task_id: TaskId
    task_status: Literal["BLOCKED"] = "BLOCKED"
    task_revision: Annotated[StrictInt, Field(ge=1)]
    task_sha256: StageSha256
    checkpoint_sha256: StageSha256
    dispatch_sha256: StageSha256
    preparation_sha256: StageSha256
    product_spec_sha256: StageSha256
    approval_sha256: StageSha256
    technical_design_sha256: StageSha256
    execution_plan_sha256: StageSha256
    failed_run_id: RunId
    failed_context_id: ContextId
    base_revision: FullCommit
    parent_delivery_id: DeliveryId | None = None
    parent_checkpoint_sha256: StageSha256 | None = None

    @model_validator(mode="after")
    def parent_pair(self) -> Self:
        if (self.parent_delivery_id is None) != (self.parent_checkpoint_sha256 is None):
            raise ValueError("parent identity and digest must appear together")
        return self


class RecoveryScopeSupplement(DomainModel):
    """Deterministic request to approve exact changed paths missing from Coder policy."""

    kind: Literal["recovery_scope_supplement"] = "recovery_scope_supplement"
    schema_version: Literal["v0.1"] = "v0.1"
    scope: RecoveryScope
    task_id: TaskId
    task_revision: Annotated[StrictInt, Field(ge=1)]
    checkpoint_sha256: StageSha256
    base_revision: FullCommit
    permissions_sha256: StageSha256
    denied_paths_sha256: StageSha256
    paths: tuple[RelativePath, ...] = Field(min_length=1, max_length=MAX_CAPTURE_FILES)
    supplement_sha256: StageSha256

    @classmethod
    def create(cls, **values: object) -> RecoveryScopeSupplement:
        provisional = cls.model_validate({**values, "supplement_sha256": "0" * 64})
        return provisional.model_copy(update={"supplement_sha256": provisional.recompute_sha256()})

    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        if self.paths != tuple(sorted(set(self.paths))):
            raise ValueError("recovery scope supplement paths must be sorted and unique")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"supplement_sha256"}))

    def validate_integrity(self) -> None:
        RecoveryScopeSupplement.model_validate(self.to_wire())
        if self.supplement_sha256 != self.recompute_sha256():
            raise RecoveryRejected("recovery scope supplement integrity mismatch")


class RecoveryPathRebinding(DomainModel):
    """Exact stale-to-current write path replacement requiring human approval."""

    source_path: RelativePath
    target_path: RelativePath
    reason: RecoveryPathRebindingReason = "missing_source_path_unique_match"

    @model_validator(mode="after")
    def validate_rebinding(self) -> Self:
        if self.source_path == self.target_path:
            raise ValueError("recovery path rebinding must change the path")
        return self


class RecoveryPlan(DomainModel):
    kind: Literal["recovery_plan"] = "recovery_plan"
    schema_version: Literal["v0.1"] = "v0.1"
    # None is omitted from wire/digest, preserving historical strict-seed approvals.
    input_mode: RecoveryInputMode | None = None
    source: RecoverySource
    capture: CapturedChanges
    target_base_revision: FullCommit
    target_preparation_sha256: StageSha256
    # Source permissions prove the captured historical worktree. They may contain
    # only the original policy plus a digest-bound, explicitly approved supplement.
    scope_supplement: RecoveryScopeSupplement | None = None
    scope_approval_reference: SafeText | None = None
    permissions: AgentPermissions
    target_permissions: AgentPermissions | None = None
    # None is omitted from wire/digest so historical plans retain their identity.
    path_rebindings: tuple[RecoveryPathRebinding, ...] | None = None
    denied_paths: tuple[str, ...]
    created_at: AwareDatetime
    plan_sha256: StageSha256

    @model_validator(mode="after")
    def validate_scope_approval(self) -> Self:
        if (self.scope_supplement is None) != (self.scope_approval_reference is None):
            raise ValueError("recovery scope supplement and approval must appear together")
        supplement = self.scope_supplement
        if supplement is None:
            return self
        if supplement.supplement_sha256 != supplement.recompute_sha256():
            raise ValueError("recovery scope supplement integrity mismatch")
        source = self.source
        if (
            supplement.scope != source.scope
            or supplement.task_id != source.task_id
            or supplement.task_revision != source.task_revision
            or supplement.checkpoint_sha256 != source.checkpoint_sha256
            or supplement.base_revision != source.base_revision
            or supplement.denied_paths_sha256 != digest(self.denied_paths)
            or any(path not in self.permissions.read_paths for path in supplement.paths)
            or any(path not in self.permissions.write_paths for path in supplement.paths)
        ):
            raise ValueError("recovery scope approval does not bind this plan")
        return self

    @classmethod
    def create(cls, **values: object) -> RecoveryPlan:
        provisional = cls.model_validate({**values, "plan_sha256": "0" * 64})
        return provisional.model_copy(update={"plan_sha256": provisional.recompute_sha256()})

    @property
    def new_task_id(self) -> TaskId:
        return "task_recovery_" + self.plan_sha256[:32]

    @property
    def effective_target_permissions(self) -> AgentPermissions:
        """Return the approved target policy, preserving legacy plan semantics."""
        return self.target_permissions or self.permissions

    @property
    def effective_path_rebindings(self) -> tuple[RecoveryPathRebinding, ...]:
        return self.path_rebindings or ()

    def rebound_write_paths(self, source_paths: tuple[str, ...]) -> tuple[str, ...]:
        replacements = {
            item.source_path: item.target_path for item in self.effective_path_rebindings
        }
        return tuple(replacements.get(path, path) for path in source_paths)

    @model_validator(mode="after")
    def validate_lineage(self) -> Self:
        if (
            self.capture.task_id != self.source.task_id
            or self.capture.to_capture().effective_base_revision != self.source.base_revision
        ):
            raise ValueError("capture must belong to the failed Task and base")
        target = self.effective_target_permissions
        if (
            self.permissions.can_change_state
            or self.permissions.can_merge
            or target.can_change_state
            or target.can_merge
        ):
            raise ValueError("recovery cannot grant Coder state or merge authority")
        rebindings = self.effective_path_rebindings
        source_rebindings = tuple(item.source_path for item in rebindings)
        target_rebindings = tuple(item.target_path for item in rebindings)
        if len(set(source_rebindings)) != len(source_rebindings) or len(
            set(target_rebindings)
        ) != len(target_rebindings):
            raise ValueError("recovery path rebindings must be one-to-one")
        if not set(source_rebindings).issubset(self.permissions.write_paths):
            raise ValueError("recovery path rebinding must replace an approved source path")
        permitted_target_writes = set(self.permissions.write_paths) | set(target_rebindings)
        if self.target_permissions is not None and (
            not set(target.read_paths).issubset(self.permissions.read_paths)
            or not set(target.write_paths).issubset(permitted_target_writes)
            or not set(target.commands).issubset(self.permissions.commands)
            or target.network is not self.permissions.network
        ):
            raise ValueError(
                "recovery target permissions may only narrow source permissions or use exact "
                "approved path rebindings"
            )
        if rebindings and set(target.write_paths) != set(
            self.rebound_write_paths(self.permissions.write_paths)
        ):
            raise ValueError("recovery target permissions do not match path rebindings")
        for value in (
            *self.permissions.read_paths,
            *self.permissions.write_paths,
            *self.permissions.commands,
            *target.read_paths,
            *target.write_paths,
            *target.commands,
            *self.denied_paths,
        ):
            _safe_text(value)
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude_none=True, exclude={"plan_sha256"}))

    def validate_integrity(self) -> None:
        RecoveryPlan.model_validate(self.to_wire())
        if self.plan_sha256 != self.recompute_sha256() or self.new_task_id == self.source.task_id:
            raise RecoveryRejected("recovery plan integrity mismatch")


class RecoveryApprovalCommand(DomainModel):
    operation_id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{2,127}$")]
    plan_sha256: StageSha256
    approval_reference: SafeText
    submitted_at: AwareDatetime


class VerifiedRecoveryDecision(DomainModel):
    plan_sha256: StageSha256
    approval_reference: SafeText
    approved: StrictBool
    operator_id: SafeText
    rationale: SafeText
    decided_at: AwareDatetime


class RecoveryAuthorization(DomainModel):
    kind: Literal["recovery_authorization"] = "recovery_authorization"
    schema_version: Literal["v0.1"] = "v0.1"
    command: RecoveryApprovalCommand
    decision: VerifiedRecoveryDecision
    authorization_sha256: StageSha256

    @classmethod
    def create(
        cls, command: RecoveryApprovalCommand, decision: VerifiedRecoveryDecision
    ) -> RecoveryAuthorization:
        provisional = cls(command=command, decision=decision, authorization_sha256="0" * 64)
        return provisional.model_copy(
            update={"authorization_sha256": provisional.recompute_sha256()}
        )

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if (
            self.command.plan_sha256 != self.decision.plan_sha256
            or self.command.approval_reference != self.decision.approval_reference
            or self.decision.decided_at < self.command.submitted_at
        ):
            raise ValueError("verified decision does not match recovery command")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"authorization_sha256"}))

    def validate_integrity(self) -> None:
        RecoveryAuthorization.model_validate(self.to_wire())
        if self.authorization_sha256 != self.recompute_sha256():
            raise RecoveryRejected("recovery authorization integrity mismatch")
