"""Immutable v2 full mutation bodies; no candidate, approval or replay authority."""

import hashlib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.branch import BranchName
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.git.capture import MAX_CAPTURE_BYTES, MAX_CAPTURE_FILES
from ai_software_engineer.git.mutation_capture import (
    MAX_MUTATION_BODY_BYTES,
    FileMutationCapture,
    MutationTextBody,
    RegularMode,
    WorktreeMutationCapture,
)
from ai_software_engineer.git.ports import WorktreeRef
from ai_software_engineer.recovery.models import AbsolutePath, FullCommit, RelativePath
from ai_software_engineer.redaction import patch_secret_occurrences


class CapturedMutationBody(DomainModel):
    text: Annotated[str, StringConstraints(max_length=MAX_CAPTURE_BYTES)]
    sha256: StageSha256
    mode: RegularMode
    size: Annotated[StrictInt, Field(ge=0, le=MAX_CAPTURE_BYTES)]

    @classmethod
    def from_body(cls, body: MutationTextBody) -> Self:
        return cls(text=body.text, sha256=body.sha256, mode=body.mode, size=body.size)

    def to_body(self, *, source_path: str) -> MutationTextBody:
        return MutationTextBody(self.text, self.mode, source_path=source_path)

    @model_validator(mode="after")
    def validate_body(self) -> Self:
        # The containing mutation owns the validated relative path and checks
        # source sensitivity. This body checks only structural byte identity.
        payload = self.text.encode("utf-8")
        if b"\0" in payload or len(payload) > MAX_CAPTURE_BYTES:
            raise ValueError("mutation body must be bounded regular UTF-8 text")
        if hashlib.sha256(payload).hexdigest() != self.sha256 or len(payload) != self.size:
            raise ValueError("mutation body bytes, digest and size must match")
        return self


class CapturedMutation(DomainModel):
    path: RelativePath
    before: CapturedMutationBody | None = None
    after: CapturedMutationBody | None = None

    @model_validator(mode="after")
    def validate_mutation(self) -> Self:
        if (self.before is None and self.after is None) or self.before == self.after:
            raise ValueError("mutation must bind changed before/after file facts")
        for body in (self.before, self.after):
            if body is not None:
                body.to_body(source_path=self.path)
        return self


class CapturedMutations(DomainModel):
    kind: Literal["captured_mutations"] = "captured_mutations"
    schema_version: Literal["v2"] = "v2"
    task_id: TaskId
    attempt: Literal[1] = 1
    source_revision: FullCommit
    worktree_path: AbsolutePath
    patch: Annotated[str, StringConstraints(max_length=MAX_CAPTURE_BYTES)]
    index_diff_sha256: StageSha256
    mutations: tuple[CapturedMutation, ...] = Field(max_length=MAX_CAPTURE_FILES)
    capture_sha256: StageSha256
    base_revision: FullCommit | None = None
    branch_name: BranchName | None = Field(default=None, exclude_if=lambda value: value is None)

    @classmethod
    def from_capture(cls, capture: WorktreeMutationCapture) -> Self:
        if (
            capture.worktree.role is not AgentRole.CODER
            or capture.worktree.detached
            or capture.worktree.attempt != 1
        ):
            raise ValueError("mutation capture requires the original assigned Coder checkout")
        result = cls(
            task_id=capture.worktree.task_id,
            source_revision=capture.worktree.head_revision,
            worktree_path=str(capture.worktree.path),
            patch=capture.patch.decode("utf-8"),
            index_diff_sha256=capture.index_diff_sha256,
            mutations=tuple(
                CapturedMutation(
                    path=item.path,
                    before=CapturedMutationBody.from_body(item.before)
                    if item.before is not None
                    else None,
                    after=CapturedMutationBody.from_body(item.after)
                    if item.after is not None
                    else None,
                )
                for item in capture.mutations
            ),
            capture_sha256=capture.capture_sha256,
            base_revision=capture.base_revision,
            branch_name=(
                None
                if capture.worktree.branch == f"ai/{capture.worktree.task_id}/attempt-1"
                else capture.worktree.branch
            ),
        )
        if result.to_capture() != capture:
            raise ValueError("mutation capture has a noncanonical Coder identity")
        return result

    def to_capture(self) -> WorktreeMutationCapture:
        return WorktreeMutationCapture(
            worktree=WorktreeRef(
                task_id=self.task_id,
                role=AgentRole.CODER,
                attempt=1,
                path=Path(self.worktree_path),
                head_revision=self.source_revision,
                branch=self.branch_name or f"ai/{self.task_id}/attempt-1",
                detached=False,
            ),
            patch=self.patch.encode("utf-8"),
            index_diff_sha256=self.index_diff_sha256,
            mutations=tuple(
                FileMutationCapture(
                    path=item.path,
                    before=item.before.to_body(source_path=item.path)
                    if item.before is not None
                    else None,
                    after=item.after.to_body(source_path=item.path)
                    if item.after is not None
                    else None,
                )
                for item in self.mutations
            ),
            base_revision=self.base_revision,
        )

    @model_validator(mode="after")
    def validate_capture(self) -> Self:
        paths = tuple(item.path for item in self.mutations)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("mutation paths must be sorted and unique")
        if (
            len(self.patch.encode("utf-8")) > MAX_CAPTURE_BYTES
            or "\0" in self.patch
            or "GIT binary patch" in self.patch
            or patch_secret_occurrences(self.patch)
            or sum(
                body.size
                for item in self.mutations
                for body in (item.before, item.after)
                if body is not None
            )
            > MAX_MUTATION_BODY_BYTES
        ):
            raise ValueError("mutation bodies and complete patch must be bounded nonsensitive text")
        if self.to_capture().capture_sha256 != self.capture_sha256:
            raise ValueError("mutation capture digest must bind the complete mutation facts")
        return self
