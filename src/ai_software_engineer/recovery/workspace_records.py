"""Immutable terminal workspace observations, independent of recovery plan models."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    Field,
    StrictInt,
    StringConstraints,
    model_validator,
)

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.identity import ContextId, ProjectId, RepositoryId, RunId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.git.mutation import (
    MAX_INVENTORY_BYTES,
    MAX_INVENTORY_FILE_BYTES,
    MAX_INVENTORY_FILES,
    WorkspaceMutationInventory,
)


def workspace_record_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _relative(value: str) -> str:
    if (
        PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or "\\" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("workspace observation requires canonical relative paths")
    return value


def _absolute(value: str) -> str:
    if str(Path(value)) != value or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError("workspace observation requires a canonical absolute root")
    return value


_Relative = Annotated[
    str,
    StringConstraints(min_length=1, pattern=r"^[^\x00-\x1f]+$"),
    AfterValidator(_relative),
]
_Absolute = Annotated[
    str,
    StringConstraints(pattern=r"^/[^\x00-\x1f]*$"),
    AfterValidator(_absolute),
]
_Commit = Annotated[str, StringConstraints(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")]


class RecoveryWorkspaceScope(DomainModel):
    team_id: TeamId
    project_id: ProjectId
    repository_id: RepositoryId
    requirement_id: NonEmptyStr
    dispatch_sha256: Sha256


class RecoveryExcludedPath(DomainModel):
    """No-follow metadata only; an excluded environment entry is never replayed."""

    path: _Relative
    kind: Literal["file", "symlink"]
    sha256: Sha256
    mode: Annotated[StrictInt, Field(ge=0, le=0o7777)]
    size: Annotated[StrictInt, Field(ge=0, le=MAX_INVENTORY_FILE_BYTES)]

    @model_validator(mode="after")
    def environment_only(self) -> Self:
        if not self.path.startswith(".venv/"):
            raise ValueError("only newly created environment entries can be retained separately")
        return self


class RecoveryWorkspaceSnapshot(DomainModel):
    """A stopped terminal workspace audit, not progress, a verdict, or retry authority."""

    kind: Literal["recovery_workspace_snapshot"] = "recovery_workspace_snapshot"
    schema_version: Literal["v1"] = "v1"
    scope: RecoveryWorkspaceScope
    task_id: TaskId
    task_revision: Annotated[StrictInt, Field(ge=1)]
    task_sha256: Sha256
    task_intent_sha256: Sha256
    run_id: RunId
    context_manifest_id: ContextId
    worktree_path: _Absolute
    source_revision: _Commit
    effective_capture_base: _Commit
    execution_baseline_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    capture_sha256: Sha256
    capture_start_sha256: Sha256
    capture_stop_sha256: Sha256
    invocation_start_sha256: Sha256
    invocation_outcome_sha256: Sha256
    claim_sha256: Sha256
    step_sha256: Sha256
    routes_sha256: Sha256
    inventory_before_sha256: Sha256
    inventory_after: WorkspaceMutationInventory
    inventory_after_sha256: Sha256
    excluded_paths: tuple[RecoveryExcludedPath, ...] = Field(max_length=MAX_INVENTORY_FILES)
    stopped_at: AwareDatetime
    blocked_at: AwareDatetime
    created_at: AwareDatetime
    snapshot_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def strict_inventory_wire(cls, value: object) -> object:
        if isinstance(value, Mapping):
            inventory = value.get("inventory_after")
            if isinstance(inventory, WorkspaceMutationInventory):
                return value
            if not isinstance(inventory, dict) or set(inventory) != {"files"}:
                raise ValueError("workspace snapshot requires the exact inventory wire contract")
            files = inventory["files"]
            if not isinstance(files, (list, tuple)):
                raise ValueError("workspace snapshot inventory must be an array")
            for item in files:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"path", "kind", "sha256", "mode", "size"}
                    or any(type(item[key]) is not str for key in ("path", "kind", "sha256"))
                    or any(type(item[key]) is not int for key in ("mode", "size"))
                ):
                    raise ValueError("workspace snapshot inventory metadata must be strict")
        return value

    @model_validator(mode="after")
    def complete_sorted_inventory(self) -> Self:
        files = self.inventory_after.files
        paths = tuple(item.path for item in files)
        if (
            paths != tuple(sorted(set(paths)))
            or len(files) > MAX_INVENTORY_FILES
            or sum(item.size for item in files) > MAX_INVENTORY_BYTES
            or self.inventory_after.sha256 != self.inventory_after_sha256
        ):
            raise ValueError("workspace snapshot requires complete bounded canonical inventory")
        observed = {item.path: item for item in files}
        for item in files:
            _relative(item.path)
            if (
                (item.kind == "git_directory" and item.path.casefold() != ".git")
                or (
                    any(part.casefold() == ".git" for part in item.path.split("/"))
                    and item.path.casefold() != ".git"
                )
                or type(item.mode) is not int
                or type(item.size) is not int
                or not 0 <= item.mode <= 0o7777
                or not 0 <= item.size <= MAX_INVENTORY_FILE_BYTES
                or len(item.sha256) != 64
                or any(c not in "0123456789abcdef" for c in item.sha256)
            ):
                raise ValueError("workspace snapshot inventory metadata is invalid")
        excluded = tuple(item.path for item in self.excluded_paths)
        if excluded != tuple(sorted(set(excluded))):
            raise ValueError("excluded environment entries must be sorted and unique")
        for excluded_item in self.excluded_paths:
            actual = observed.get(excluded_item.path)
            if actual is None or (actual.kind, actual.sha256, actual.mode, actual.size) != (
                excluded_item.kind,
                excluded_item.sha256,
                excluded_item.mode,
                excluded_item.size,
            ):
                raise ValueError("excluded entry must match complete final inventory")
        if self.blocked_at < self.stopped_at or self.created_at < self.blocked_at:
            raise ValueError("snapshot must follow real stop and terminal event")
        return self

    def recompute_sha256(self) -> str:
        return workspace_record_digest(self.model_dump(mode="json", exclude={"snapshot_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.snapshot_sha256 != self.recompute_sha256():
            raise ValueError("terminal workspace snapshot digest mismatch")

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_validate({**values, "snapshot_sha256": "0" * 64})
        return provisional.model_copy(update={"snapshot_sha256": provisional.recompute_sha256()})
