"""Typed local administration for Teams, knowledge documents and settings."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Annotated, Protocol

from pydantic import AwareDatetime, Field, StrictBool, StringConstraints

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.knowledge_documents import (
    KnowledgeDocumentManifest,
    TeamKnowledgeDocumentStore,
)
from ai_software_engineer.project_workspace import ProjectName, ProjectWorkspace
from ai_software_engineer.team_workspace import (
    TeamName,
    TeamWorkspace,
    discover_team_workspaces,
)


class AdministrationError(RuntimeError):
    """Stable operator-facing administration failure."""


class TeamSummary(DomainModel):
    team_id: TeamId
    name: TeamName
    active: StrictBool
    created_at: AwareDatetime


class ProjectSummary(DomainModel):
    project_id: ProjectId
    name: ProjectName
    repository_count: int
    requirement_count: int
    created_at: AwareDatetime


class CreateProjectRequest(DomainModel):
    name: ProjectName
    project_id: ProjectId | None = None


class SecretStatus(DomainModel):
    environment_name: Annotated[str, StringConstraints(pattern=r"^[A-Z_][A-Z0-9_]{0,127}$")]
    configured: StrictBool


class SettingsSnapshot(DomainModel):
    config: ProductionConfig
    config_path: NonEmptyStr
    secret_status: Annotated[tuple[SecretStatus, ...], Field(max_length=32)] = ()
    restart_required: StrictBool = False


class UpdateSettingsRequest(DomainModel):
    config: ProductionConfig


class KnowledgeDocumentView(DomainModel):
    manifest: KnowledgeDocumentManifest
    selected: StrictBool


class ConsoleAdministration(Protocol):
    def team(self) -> TeamSummary: ...
    def projects(self) -> tuple[ProjectSummary, ...]: ...
    def create_project(self, request: CreateProjectRequest) -> ProjectSummary: ...
    def knowledge(self) -> tuple[KnowledgeDocumentView, ...]: ...
    def import_document(self, *, filename: str, content: bytes) -> KnowledgeDocumentView: ...
    def settings(self) -> SettingsSnapshot: ...
    def update_settings(self, request: UpdateSettingsRequest) -> SettingsSnapshot: ...


@dataclass
class LocalConsoleAdministration:
    runtime_config: ProductionConfig
    config_path: Path
    environment: Mapping[str, str]
    _saved_config: ProductionConfig = field(init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    def __post_init__(self) -> None:
        self.config_path = self.config_path.expanduser().absolute()
        self._saved_config = self.runtime_config

    def team(self) -> TeamSummary:
        try:
            team = self._team()
            return TeamSummary(
                team_id=team.manifest.team_id,
                name=team.manifest.name,
                active=True,
                created_at=team.manifest.created_at,
            )
        except (OSError, ValueError) as error:
            raise AdministrationError("Team workspace is invalid") from error

    def projects(self) -> tuple[ProjectSummary, ...]:
        try:
            return tuple(
                self._project_summary(project)
                for project in self._team().project_registry().discover()
            )
        except (OSError, ValueError) as error:
            raise AdministrationError("Project catalog is invalid") from error

    def create_project(self, request: CreateProjectRequest) -> ProjectSummary:
        try:
            registry = self._team().project_registry()
            project = (
                registry.create(name=request.name)
                if request.project_id is None
                else registry.register(project_id=request.project_id, name=request.name)
            )
            return self._project_summary(project)
        except (OSError, ValueError) as error:
            raise AdministrationError("Project could not be created safely") from error

    def knowledge(self) -> tuple[KnowledgeDocumentView, ...]:
        team = self._team()
        selected = set(self._saved_config.team_knowledge_paths)
        return tuple(
            KnowledgeDocumentView(
                manifest=manifest,
                selected=manifest.normalized_relative_path in selected,
            )
            for manifest in TeamKnowledgeDocumentStore(team).list()
        )

    def import_document(self, *, filename: str, content: bytes) -> KnowledgeDocumentView:
        team = self._team()
        manifest = TeamKnowledgeDocumentStore(team).import_document(
            filename=filename,
            content=content,
        )
        selected = manifest.normalized_relative_path in self._saved_config.team_knowledge_paths
        return KnowledgeDocumentView(manifest=manifest, selected=selected)

    def settings(self) -> SettingsSnapshot:
        names = {self._saved_config.database.dsn_env}
        names.update(
            route.api_key_env
            for route in self._saved_config.model_routes
            if route.api_key_env is not None
        )
        return SettingsSnapshot(
            config=self._saved_config,
            config_path=str(self.config_path),
            secret_status=tuple(
                SecretStatus(environment_name=name, configured=bool(self.environment.get(name)))
                for name in sorted(names)
            ),
            restart_required=self._saved_config != self.runtime_config,
        )

    def update_settings(self, request: UpdateSettingsRequest) -> SettingsSnapshot:
        config = request.config
        try:
            team = next(
                item
                for item in discover_team_workspaces(config.platform_root)
                if item.manifest.team_id == config.team_id
            )
        except StopIteration as error:
            if config.platform_root == self.runtime_config.platform_root:
                raise AdministrationError(
                    "selected team is not prepared under platform_root"
                ) from error
            if config.team_knowledge_paths:
                raise AdministrationError(
                    "team knowledge must be cleared when starting a new platform_root"
                ) from error
            try:
                team = TeamWorkspace.initialize(
                    config.platform_root,
                    team_id=config.team_id,
                    name=config.team_name,
                )
            except (OSError, ValueError) as initialization_error:
                raise AdministrationError(
                    "selected team could not be prepared under the new platform_root"
                ) from initialization_error
        except (OSError, ValueError) as error:
            raise AdministrationError("configured team workspace is invalid") from error
        if team.manifest.name != config.team_name:
            raise AdministrationError("team name must match its immutable Team record")
        try:
            team.knowledge_sources(config.team_knowledge_paths)
        except (OSError, UnicodeError, ValueError) as error:
            raise AdministrationError("selected team knowledge is invalid") from error
        with self._lock:
            _write_config(self.config_path, config)
            self._saved_config = config
        return self.settings()

    def _team(self) -> TeamWorkspace:
        try:
            teams = discover_team_workspaces(self.runtime_config.platform_root)
            if len(teams) != 1 or teams[0].manifest.team_id != self._saved_config.team_id:
                raise ValueError("configured Team is not the prepared Team")
            return teams[0]
        except StopIteration as error:
            raise AdministrationError("team workspace was not found") from error
        except (OSError, ValueError) as error:
            raise AdministrationError("team workspace is invalid") from error

    @staticmethod
    def _project_summary(project: ProjectWorkspace) -> ProjectSummary:
        return ProjectSummary(
            project_id=project.manifest.project_id,
            name=project.manifest.name,
            repository_count=len(project.repository_registry().discover()),
            requirement_count=sum(
                1
                for path in project.requirements_root.iterdir()
                if path.is_dir() and not path.is_symlink()
            ),
            created_at=project.manifest.created_at,
        )


def _write_config(path: Path, config: ProductionConfig) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise AdministrationError("production configuration path is not a regular file")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".ase-config-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(config.model_dump_json(indent=2))
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
        raise AdministrationError("production configuration could not be saved") from error


__all__ = [
    "AdministrationError",
    "ConsoleAdministration",
    "CreateProjectRequest",
    "KnowledgeDocumentView",
    "LocalConsoleAdministration",
    "ProjectSummary",
    "SecretStatus",
    "SettingsSnapshot",
    "TeamSummary",
    "UpdateSettingsRequest",
]
