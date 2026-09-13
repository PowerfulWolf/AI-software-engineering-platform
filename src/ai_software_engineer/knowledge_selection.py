"""Scope-owned, atomically replaceable knowledge selections."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.team_workspace import TeamWorkspace, validate_knowledge_path

Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
KnowledgeScope = Literal["team", "project"]
_MAX_RECORD_BYTES = 64_000


class KnowledgeSelectionError(RuntimeError):
    """Raised when a current knowledge selection cannot be trusted or published."""


class KnowledgeSelection(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    scope: KnowledgeScope
    team_id: TeamId
    project_id: ProjectId | None = None
    selected_paths: Annotated[tuple[NonEmptyStr, ...], Field(max_length=64)] = ()
    selection_sha256: Digest

    @model_validator(mode="after")
    def validate_scope_and_paths(self) -> Self:
        if (self.scope == "project") != (self.project_id is not None):
            raise ValueError("knowledge selection scope and Project identity do not match")
        ensure_unique(self.selected_paths, "knowledge selection paths")
        for path in self.selected_paths:
            validate_knowledge_path(path)
        if tuple(sorted(self.selected_paths)) != self.selected_paths:
            raise ValueError("knowledge selection paths must be sorted")
        return self

    def recompute_digest(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"selection_sha256"},
            exclude_none=True,
        )
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate_integrity(self) -> None:
        if self.selection_sha256 != self.recompute_digest():
            raise KnowledgeSelectionError("knowledge selection digest mismatch")


@dataclass(frozen=True, slots=True)
class TeamKnowledgeSelectionStore:
    team: TeamWorkspace

    @property
    def path(self) -> Path:
        return self.team.root / "knowledge" / "selection.json"

    def load(self) -> KnowledgeSelection | None:
        self.team.validate_current()
        selection = _load(self.path)
        if selection is not None and (
            selection.scope != "team"
            or selection.team_id != self.team.manifest.team_id
            or selection.project_id is not None
        ):
            raise KnowledgeSelectionError("Team knowledge selection identity mismatch")
        return selection

    def save(self, selected_paths: tuple[str, ...]) -> KnowledgeSelection:
        self.team.validate_current()
        paths = tuple(sorted(selected_paths))
        try:
            self.team.knowledge_sources(paths)
        except (OSError, UnicodeError, ValueError) as error:
            raise KnowledgeSelectionError("Team knowledge selection is invalid") from error
        return _save(
            self.path,
            KnowledgeSelection(
                scope="team",
                team_id=self.team.manifest.team_id,
                selected_paths=paths,
                selection_sha256="0" * 64,
            ),
        )


@dataclass(frozen=True, slots=True)
class ProjectKnowledgeSelectionStore:
    project: ProjectWorkspace

    @property
    def path(self) -> Path:
        return self.project.root / "knowledge" / "selection.json"

    def load(self) -> KnowledgeSelection | None:
        self.project.validate_current()
        selection = _load(self.path)
        if selection is not None and (
            selection.scope != "project"
            or selection.team_id != self.project.manifest.team_id
            or selection.project_id != self.project.manifest.project_id
        ):
            raise KnowledgeSelectionError("Project knowledge selection identity mismatch")
        return selection

    def save(self, selected_paths: tuple[str, ...]) -> KnowledgeSelection:
        self.project.validate_current()
        paths = tuple(sorted(selected_paths))
        try:
            self.project.knowledge_sources(paths)
        except (OSError, UnicodeError, ValueError) as error:
            raise KnowledgeSelectionError("Project knowledge selection is invalid") from error
        return _save(
            self.path,
            KnowledgeSelection(
                scope="project",
                team_id=self.project.manifest.team_id,
                project_id=self.project.manifest.project_id,
                selected_paths=paths,
                selection_sha256="0" * 64,
            ),
        )


def _load(path: Path) -> KnowledgeSelection | None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise KnowledgeSelectionError("knowledge selection path is not a regular file")
    if not path.exists():
        return None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise KnowledgeSelectionError("knowledge selection is not a regular file")
            payload = stream.read(_MAX_RECORD_BYTES + 1)
    except OSError as error:
        raise KnowledgeSelectionError("knowledge selection could not be read") from error
    if len(payload) > _MAX_RECORD_BYTES:
        raise KnowledgeSelectionError("knowledge selection exceeds its size limit")
    try:
        selection = KnowledgeSelection.model_validate_json(payload)
    except ValueError as error:
        raise KnowledgeSelectionError("knowledge selection is invalid") from error
    selection.validate_integrity()
    return selection


def _save(path: Path, provisional: KnowledgeSelection) -> KnowledgeSelection:
    selection = provisional.model_copy(update={"selection_sha256": provisional.recompute_digest()})
    current = _load(path)
    if current == selection:
        return current
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise KnowledgeSelectionError("knowledge selection path is not a regular file")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".knowledge-selection-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(selection.model_dump_json(indent=2))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise KnowledgeSelectionError("knowledge selection could not be saved") from error
    return _load(path) or selection


def effective_team_knowledge_paths(
    team: TeamWorkspace,
    fallback: tuple[str, ...] = (),
) -> tuple[str, ...]:
    selection = TeamKnowledgeSelectionStore(team).load()
    return selection.selected_paths if selection is not None else fallback


def effective_project_knowledge_paths(
    project: ProjectWorkspace,
    fallback: tuple[str, ...] = (),
) -> tuple[str, ...]:
    selection = ProjectKnowledgeSelectionStore(project).load()
    return selection.selected_paths if selection is not None else fallback


__all__ = [
    "KnowledgeSelection",
    "KnowledgeSelectionError",
    "ProjectKnowledgeSelectionStore",
    "TeamKnowledgeSelectionStore",
    "effective_project_knowledge_paths",
    "effective_team_knowledge_paths",
]
