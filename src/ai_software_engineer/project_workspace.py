"""Project workspaces stored beside the Team and above code Repositories.

A Project is a durable product/business context. It owns reusable Project knowledge, a
Repository catalog and Requirement records, but never owns or copies the Team's Agents.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import AwareDatetime, StringConstraints, TypeAdapter

from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain.identity import ProjectId, RepositoryId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.repository_workspace import (
    RepositoryWorkspace,
    RepositoryWorkspaceManifest,
    RepositoryWorkspaceRegistry,
)
from ai_software_engineer.team_workspace import TeamWorkspace

ProjectName = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
_DIRECTORIES = ("knowledge", "repositories", "requirements", "specs")
_MAX_PROJECT_KNOWLEDGE_DOCUMENT_BYTES = 256_000
_MAX_PROJECT_KNOWLEDGE_SELECTION_BYTES = 1_000_000
_SAFE_SLUG = re.compile(r"[^a-z0-9_-]+")


class ProjectManifest(DomainModel):
    """Immutable identity of one Project within one Team."""

    schema_version: Literal["v0.2"] = "v0.2"
    team_id: TeamId
    team_manifest_sha256: Digest
    project_id: ProjectId
    name: ProjectName
    project_root: NonEmptyStr
    created_at: AwareDatetime
    manifest_sha256: Digest

    def recompute_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate_integrity(self) -> None:
        if self.manifest_sha256 != self.recompute_digest():
            raise ValueError("Project manifest digest mismatch")


@dataclass(frozen=True, slots=True)
class ProjectWorkspace:
    """Validated Project handle used by administration and runtime composition."""

    team: TeamWorkspace
    manifest: ProjectManifest

    @property
    def root(self) -> Path:
        return Path(self.manifest.project_root)

    @property
    def requirements_root(self) -> Path:
        return self.root / "requirements"

    def repository_registry(self) -> _ProjectRepositoryRegistry:
        self.validate_current()
        return _ProjectRepositoryRegistry(self)

    def knowledge_sources(self, relative_paths: tuple[str, ...]) -> tuple[ContextSource, ...]:
        self.validate_current()
        ensure_unique(relative_paths, "Project knowledge selection")
        if len(relative_paths) > 64:
            raise ValueError("Project knowledge selection exceeds document budget")
        sources: list[ContextSource] = []
        total = 0
        for relative in sorted(relative_paths):
            _validate_knowledge_path(relative)
            content = _read_regular(
                self.root / "knowledge" / relative,
                _MAX_PROJECT_KNOWLEDGE_DOCUMENT_BYTES,
            )
            total += len(content)
            if total > _MAX_PROJECT_KNOWLEDGE_SELECTION_BYTES:
                raise ValueError("Project knowledge selection exceeds byte budget")
            sha = hashlib.sha256(content).hexdigest()
            sources.append(
                ContextSource(
                    source_id="project.knowledge."
                    + hashlib.sha256(relative.encode()).hexdigest()[:16],
                    uri=f"project://{self.manifest.project_id}/knowledge/{relative}#{sha}",
                    content=redact_text(content.decode("utf-8")).text,
                    required=True,
                    priority=16,
                )
            )
        return tuple(sources)

    def validate_current(self) -> None:
        self.team.validate_current()
        current = ProjectWorkspaceRegistry(self.team).open(self.manifest.project_id)
        if current.manifest != self.manifest:
            raise ValueError("Project workspace identity changed")


class ProjectWorkspaceRegistry:
    """Create, discover and reopen Projects served by the platform's Team."""

    def __init__(self, team: TeamWorkspace) -> None:
        self._team = team
        self._root = Path(team.manifest.platform_root) / "projects"

    def register(self, *, project_id: str, name: str) -> ProjectWorkspace:
        self._team.validate_current()
        identity = TypeAdapter(ProjectId).validate_python(project_id)
        TypeAdapter(ProjectName).validate_python(name)
        root = self._root / identity
        _reject_symlinks(root)
        if root.exists():
            project = self.open(identity)
            if project.manifest.name != name:
                raise ValueError("Project name differs from its immutable manifest")
            return project
        root.parent.mkdir(parents=True, exist_ok=True)
        provisional = ProjectManifest(
            team_id=self._team.manifest.team_id,
            team_manifest_sha256=self._team.manifest.manifest_sha256,
            project_id=identity,
            name=name,
            project_root=str(root),
            created_at=datetime.now(UTC),
            manifest_sha256="0" * 64,
        )
        manifest = provisional.model_copy(
            update={"manifest_sha256": provisional.recompute_digest()}
        )
        staging = Path(tempfile.mkdtemp(prefix=f".{identity}.", dir=root.parent))
        try:
            for directory in _DIRECTORIES:
                (staging / directory).mkdir()
            _write_new(staging / "project.json", manifest.model_dump_json(indent=2).encode())
            _sync_directory(staging)
            try:
                staging.rename(root)
            except OSError:
                if not root.exists():
                    raise
            _sync_directory(root.parent)
        finally:
            if staging.exists():
                (staging / "project.json").unlink(missing_ok=True)
                for directory in _DIRECTORIES:
                    (staging / directory).rmdir()
                staging.rmdir()
        project = self.open(identity)
        if project.manifest != manifest:
            raise ValueError("Project publication raced with a different manifest")
        return project

    def create(self, *, name: str) -> ProjectWorkspace:
        """Create or reopen the deterministic Project identity for a display name."""
        TypeAdapter(ProjectName).validate_python(name)
        slug = _SAFE_SLUG.sub("-", name.casefold()).strip("-_") or "project"
        slug = slug[:30].rstrip("-_") or "project"
        suffix = hashlib.sha256(f"{self._team.manifest.team_id}\n{name}".encode()).hexdigest()[:12]
        identity = TypeAdapter(ProjectId).validate_python(f"project_{slug}_{suffix}")
        return self.register(project_id=identity, name=name)

    def open(self, project_id: ProjectId | str) -> ProjectWorkspace:
        identity = TypeAdapter(ProjectId).validate_python(project_id)
        root = self._root / identity
        _reject_symlinks(root)
        manifest = ProjectManifest.model_validate_json(_read_regular(root / "project.json", 32_000))
        manifest.validate_integrity()
        if (
            manifest.project_id != identity
            or manifest.team_id != self._team.manifest.team_id
            or manifest.team_manifest_sha256 != self._team.manifest.manifest_sha256
            or Path(manifest.project_root) != root
        ):
            raise ValueError("Project manifest identity or location differs from Team")
        for directory in _DIRECTORIES:
            path = root / directory
            _reject_symlinks(path)
            if not path.is_dir():
                raise ValueError("Project workspace has a missing directory")
        return ProjectWorkspace(team=self._team, manifest=manifest)

    def discover(self) -> tuple[ProjectWorkspace, ...]:
        self._team.validate_current()
        if not self._root.is_dir():
            return ()
        projects: list[ProjectWorkspace] = []
        for path in sorted(self._root.iterdir(), key=lambda item: item.name):
            if path.is_symlink():
                raise ValueError("Project workspace cannot traverse a symlink")
            if path.is_dir() and path.name.startswith("project_"):
                projects.append(self.open(path.name))
        return tuple(projects)

    def locate_repository(
        self, repository_id: RepositoryId | str
    ) -> tuple[ProjectWorkspace, RepositoryWorkspace]:
        """Resolve one Repository through its owning Project without guessing paths."""
        identity = TypeAdapter(RepositoryId).validate_python(repository_id)
        matches: list[tuple[ProjectWorkspace, RepositoryWorkspace]] = []
        for project in self.discover():
            for repository in project.repository_registry().discover():
                if repository.repository_id == identity:
                    matches.append((project, repository))
        if len(matches) != 1:
            raise ValueError("Repository is missing or ambiguous across Projects")
        return matches[0]


class _ProjectRepositoryRegistry(RepositoryWorkspaceRegistry):
    def __init__(self, project: ProjectWorkspace) -> None:
        super().__init__(
            project.root / "repositories",
            project_id=project.manifest.project_id,
            project_manifest_sha256=project.manifest.manifest_sha256,
        )
        self._project = project

    def register(
        self,
        repository_root: str | Path,
        *,
        repository_id: RepositoryId | str | None = None,
    ) -> RepositoryWorkspace:
        self._project.validate_current()
        configured = Path(repository_root).expanduser().absolute()
        if configured.is_symlink():
            raise ValueError("Repository root cannot be a symlink")
        self._project.team.validate_code_root(repository_root)
        root = Path(repository_root).resolve()
        identity = TypeAdapter(RepositoryId).validate_python(
            "repository_"
            + hashlib.sha256(
                (
                    self._project.manifest.team_id
                    + "\n"
                    + self._project.manifest.project_id
                    + "\n"
                    + str(root)
                ).encode()
            ).hexdigest()[:40]
        )
        if repository_id is not None and repository_id != identity:
            raise ValueError("Repository ID is not bound to this Team, Project and code root")
        return super().register(repository_root, repository_id=identity)

    def discover(self) -> tuple[RepositoryWorkspace, ...]:
        """Return every Repository registered to this Project in stable ID order."""
        self._project.validate_current()
        if not self.registry_root.is_dir():
            return ()
        repositories: list[RepositoryWorkspace] = []
        for path in sorted(self.registry_root.iterdir(), key=lambda item: item.name):
            if path.is_symlink():
                raise ValueError("Repository workspace cannot traverse a symlink")
            if not path.is_dir() or not path.name.startswith("repository_"):
                continue
            manifest = RepositoryWorkspaceManifest.model_validate_json(
                _read_regular(path / "workspace.json", 64_000)
            )
            repositories.append(
                self._open_existing(
                    manifest.repository_id,
                    Path(manifest.repository_root).resolve(),
                    path,
                )
            )
        return tuple(repositories)


def _validate_knowledge_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or any(ord(character) < 32 for character in value)
        or any(part in {"", ".", "..", ".git"} or part.startswith(".") for part in value.split("/"))
        or any(character in value for character in "*?[")
        or path.suffix.lower() not in {".md", ".txt", ".json", ".yaml", ".yml", ".toml"}
    ):
        raise ValueError("Project knowledge must be an explicit safe relative document path")


def _reject_symlinks(path: Path) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Project workspace cannot traverse a symlink")


def _read_regular(path: Path, limit: int) -> bytes:
    _reject_symlinks(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Project record must be a regular file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Project document exceeds byte budget")
    return data


def _write_new(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "ProjectId",
    "ProjectManifest",
    "ProjectName",
    "ProjectWorkspace",
    "ProjectWorkspaceRegistry",
]
