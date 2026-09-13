"""Typed local administration for Teams, knowledge documents and settings."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal, Protocol

from pydantic import (
    AwareDatetime,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
)

from ai_software_engineer.config import (
    LocalRuntimeEnvironmentStore,
    ProductionConfig,
    RuntimeEnvironmentError,
    runtime_environment_path,
)
from ai_software_engineer.config.production import (
    EnvVarName,
    ModelProviderKind,
    ProviderRouteConfig,
)
from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.knowledge_documents import (
    KnowledgeDocumentId,
    KnowledgeDocumentManifest,
    ProjectKnowledgeDocumentManifest,
    ProjectKnowledgeDocumentStore,
    TeamKnowledgeDocumentStore,
)
from ai_software_engineer.knowledge_selection import (
    KnowledgeSelectionError,
    ProjectKnowledgeSelectionStore,
    TeamKnowledgeSelectionStore,
    effective_project_knowledge_paths,
    effective_team_knowledge_paths,
)
from ai_software_engineer.project_workspace import ProjectName, ProjectWorkspace
from ai_software_engineer.store import StoreError, open_mysql_connection, validate_mysql_dsn
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


RuntimeVariableValue = Annotated[str, StringConstraints(min_length=1, max_length=8_192)]


class RuntimeVariableUpdate(DomainModel):
    environment_name: EnvVarName
    value: RuntimeVariableValue = Field(repr=False)

    @field_validator("value")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("runtime value cannot contain control characters")
        return value


class SettingsSnapshot(DomainModel):
    config: ProductionConfig
    config_path: NonEmptyStr
    config_source: Literal["default", "saved"]
    secret_status: Annotated[tuple[SecretStatus, ...], Field(max_length=32)] = ()
    restart_required: StrictBool = False


class UpdateSettingsRequest(DomainModel):
    config: ProductionConfig
    runtime_variables: Annotated[tuple[RuntimeVariableUpdate, ...], Field(max_length=32)] = ()

    @field_validator("runtime_variables")
    @classmethod
    def require_unique_runtime_variables(
        cls, values: tuple[RuntimeVariableUpdate, ...]
    ) -> tuple[RuntimeVariableUpdate, ...]:
        ensure_unique((value.environment_name for value in values), "runtime environment updates")
        return values


class MySqlConnectionRequest(DomainModel):
    dsn: RuntimeVariableValue | None = Field(default=None, repr=False)

    @field_validator("dsn")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is not None and any(
            ord(character) < 32 or ord(character) == 127 for character in value
        ):
            raise ValueError("MySQL DSN cannot contain control characters")
        return value


class MySqlConnectionResult(DomainModel):
    connected: StrictBool
    message: NonEmptyStr


class DatabaseRuntimeStatus(DomainModel):
    environment_name: EnvVarName
    configured: StrictBool
    source: Literal["runtime.env", "process environment", "missing"]
    connection: Literal["CONNECTED", "UNAVAILABLE", "NOT_CONFIGURED"]


class CodexRuntimeStatus(DomainModel):
    executable: NonEmptyStr
    available: StrictBool
    resolved_path: NonEmptyStr | None = None


class ModelRouteRuntimeStatus(DomainModel):
    provider: NonEmptyStr
    model: NonEmptyStr
    kind: ModelProviderKind
    enabled: StrictBool
    ready: StrictBool
    credential_environment_name: EnvVarName | None = None
    credential_configured: StrictBool | None = None


class RuntimeStatusSnapshot(DomainModel):
    config_path: NonEmptyStr
    config_source: Literal["default", "saved"]
    runtime_environment_path: NonEmptyStr
    restart_required: StrictBool
    delivery_runtime: Literal["READY", "SETUP_REQUIRED"]
    live_model_execution: StrictBool
    database: DatabaseRuntimeStatus
    codex: CodexRuntimeStatus
    team_prepared: StrictBool
    team_knowledge_imported: int
    team_knowledge_selected: int
    model_routes: Annotated[tuple[ModelRouteRuntimeStatus, ...], Field(max_length=16)]


class KnowledgeDocumentView(DomainModel):
    scope: Literal["team", "project"]
    project_id: ProjectId | None = None
    manifest: KnowledgeDocumentManifest | ProjectKnowledgeDocumentManifest
    selected: StrictBool


class UpdateKnowledgeSelectionRequest(DomainModel):
    document_ids: Annotated[tuple[KnowledgeDocumentId, ...], Field(max_length=64)] = ()

    @field_validator("document_ids")
    @classmethod
    def require_unique_document_ids(
        cls, values: tuple[KnowledgeDocumentId, ...]
    ) -> tuple[KnowledgeDocumentId, ...]:
        ensure_unique(values, "knowledge document selection")
        return values


class ConsoleAdministration(Protocol):
    def team(self) -> TeamSummary: ...
    def projects(self) -> tuple[ProjectSummary, ...]: ...
    def create_project(self, request: CreateProjectRequest) -> ProjectSummary: ...
    def knowledge(self) -> tuple[KnowledgeDocumentView, ...]: ...
    def import_document(self, *, filename: str, content: bytes) -> KnowledgeDocumentView: ...
    def update_team_knowledge_selection(
        self, request: UpdateKnowledgeSelectionRequest
    ) -> tuple[KnowledgeDocumentView, ...]: ...
    def project_knowledge(self, project_id: str) -> tuple[KnowledgeDocumentView, ...]: ...
    def import_project_document(
        self, project_id: str, *, filename: str, content: bytes
    ) -> KnowledgeDocumentView: ...
    def update_project_knowledge_selection(
        self, project_id: str, request: UpdateKnowledgeSelectionRequest
    ) -> tuple[KnowledgeDocumentView, ...]: ...
    def settings(self) -> SettingsSnapshot: ...
    def update_settings(self, request: UpdateSettingsRequest) -> SettingsSnapshot: ...
    def test_mysql_connection(self, request: MySqlConnectionRequest) -> MySqlConnectionResult: ...
    def status(self) -> RuntimeStatusSnapshot: ...


def _probe_mysql(dsn: str) -> None:
    connection = open_mysql_connection(dsn)
    connection.close()


@dataclass
class LocalConsoleAdministration:
    runtime_config: ProductionConfig
    config_path: Path
    environment: Mapping[str, str]
    delivery_runtime_ready: bool = True
    mysql_probe: Callable[[str], None] = _probe_mysql
    _saved_config: ProductionConfig = field(init=False)
    _runtime_environment: LocalRuntimeEnvironmentStore = field(init=False)
    _runtime_changed: bool = field(default=False, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    def __post_init__(self) -> None:
        self.config_path = self.config_path.expanduser().absolute()
        self._saved_config = self.runtime_config
        self._runtime_environment = LocalRuntimeEnvironmentStore(
            runtime_environment_path(self.config_path)
        )

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
        selected = set(
            effective_team_knowledge_paths(team, self._saved_config.team_knowledge_paths)
        )
        return tuple(
            KnowledgeDocumentView(
                scope="team",
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
        selected = manifest.normalized_relative_path in effective_team_knowledge_paths(
            team, self._saved_config.team_knowledge_paths
        )
        return KnowledgeDocumentView(scope="team", manifest=manifest, selected=selected)

    def update_team_knowledge_selection(
        self, request: UpdateKnowledgeSelectionRequest
    ) -> tuple[KnowledgeDocumentView, ...]:
        team = self._team()
        manifests = TeamKnowledgeDocumentStore(team).list()
        paths = _selected_document_paths(manifests, request.document_ids)
        try:
            with self._lock:
                TeamKnowledgeSelectionStore(team).save(paths)
        except KnowledgeSelectionError as error:
            raise AdministrationError("Team knowledge selection could not be saved") from error
        return self.knowledge()

    def project_knowledge(self, project_id: str) -> tuple[KnowledgeDocumentView, ...]:
        project = self._project(project_id)
        selected = set(
            effective_project_knowledge_paths(
                project,
                self._legacy_project_knowledge_paths(project),
            )
        )
        return tuple(
            KnowledgeDocumentView(
                scope="project",
                project_id=project.manifest.project_id,
                manifest=manifest,
                selected=manifest.normalized_relative_path in selected,
            )
            for manifest in ProjectKnowledgeDocumentStore(project).list()
        )

    def import_project_document(
        self, project_id: str, *, filename: str, content: bytes
    ) -> KnowledgeDocumentView:
        project = self._project(project_id)
        manifest = ProjectKnowledgeDocumentStore(project).import_document(
            filename=filename,
            content=content,
        )
        selected = manifest.normalized_relative_path in effective_project_knowledge_paths(
            project,
            self._legacy_project_knowledge_paths(project),
        )
        return KnowledgeDocumentView(
            scope="project",
            project_id=project.manifest.project_id,
            manifest=manifest,
            selected=selected,
        )

    def update_project_knowledge_selection(
        self, project_id: str, request: UpdateKnowledgeSelectionRequest
    ) -> tuple[KnowledgeDocumentView, ...]:
        project = self._project(project_id)
        manifests = ProjectKnowledgeDocumentStore(project).list()
        paths = _selected_document_paths(manifests, request.document_ids)
        try:
            with self._lock:
                ProjectKnowledgeSelectionStore(project).save(paths)
        except KnowledgeSelectionError as error:
            raise AdministrationError("Project knowledge selection could not be saved") from error
        return self.project_knowledge(project_id)

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
            config_source="saved" if self.config_path.is_file() else "default",
            secret_status=tuple(
                SecretStatus(
                    environment_name=name,
                    configured=self._runtime_variable(name)[0] is not None,
                )
                for name in sorted(names)
            ),
            restart_required=self._restart_required(),
        )

    def update_settings(self, request: UpdateSettingsRequest) -> SettingsSnapshot:
        config = request.config
        updates = {item.environment_name: item.value for item in request.runtime_variables}
        allowed_names = _runtime_variable_names(config)
        if set(updates) - allowed_names:
            raise AdministrationError(
                "runtime environment update is not referenced by configuration"
            )
        if config.database.dsn_env in updates:
            try:
                validate_mysql_dsn(updates[config.database.dsn_env])
            except StoreError as error:
                raise AdministrationError("MySQL DSN is invalid") from error
        try:
            teams = discover_team_workspaces(config.platform_root)
            team = next(item for item in teams if item.manifest.team_id == config.team_id)
        except StopIteration as error:
            if teams:
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
            try:
                current_runtime = self._runtime_environment.load()
                next_runtime = {
                    name: value for name, value in current_runtime.items() if name in allowed_names
                }
                next_runtime.update(updates)
                if next_runtime != current_runtime:
                    self._runtime_environment.save(next_runtime)
                    self._runtime_changed = True
                _write_config(self.config_path, config)
                self._saved_config = config
            except RuntimeEnvironmentError as error:
                raise AdministrationError("runtime environment could not be saved") from error
        return self.settings()

    def test_mysql_connection(self, request: MySqlConnectionRequest) -> MySqlConnectionResult:
        dsn = request.dsn
        if dsn is None:
            dsn = self._runtime_variable(self._saved_config.database.dsn_env)[0]
        if dsn is None:
            return MySqlConnectionResult(
                connected=False,
                message="MySQL DSN 尚未配置。",
            )
        try:
            validate_mysql_dsn(dsn)
            self.mysql_probe(dsn)
        except (OSError, StoreError, ValueError):
            return MySqlConnectionResult(
                connected=False,
                message="MySQL 连接失败; 请检查地址、账号、密码和数据库。",
            )
        return MySqlConnectionResult(connected=True, message="MySQL 连接成功。")

    def status(self) -> RuntimeStatusSnapshot:
        dsn_name = self._saved_config.database.dsn_env
        dsn, dsn_source = self._runtime_variable(dsn_name)
        if dsn is None:
            database_connection: Literal["CONNECTED", "UNAVAILABLE", "NOT_CONFIGURED"] = (
                "NOT_CONFIGURED"
            )
        else:
            database_connection = (
                "CONNECTED"
                if self.test_mysql_connection(MySqlConnectionRequest()).connected
                else "UNAVAILABLE"
            )
        codex = _codex_status(self._saved_config.codex_executable, self.environment)
        routes = tuple(
            self._model_route_status(route, codex.available)
            for route in self._saved_config.model_routes
        )
        try:
            team = self._team()
            imported = len(TeamKnowledgeDocumentStore(team).list())
            selected = len(
                effective_team_knowledge_paths(team, self._saved_config.team_knowledge_paths)
            )
            team_prepared = True
        except AdministrationError:
            imported = 0
            selected = 0
            team_prepared = False
        except (KnowledgeSelectionError, OSError, ValueError) as error:
            raise AdministrationError("Team knowledge status is unavailable") from error
        return RuntimeStatusSnapshot(
            config_path=str(self.config_path),
            config_source="saved" if self.config_path.is_file() else "default",
            runtime_environment_path=str(self._runtime_environment.path),
            restart_required=self._restart_required(),
            delivery_runtime=("READY" if self.delivery_runtime_ready else "SETUP_REQUIRED"),
            live_model_execution=self._saved_config.live_model_execution,
            database=DatabaseRuntimeStatus(
                environment_name=dsn_name,
                configured=dsn is not None,
                source=dsn_source,
                connection=database_connection,
            ),
            codex=codex,
            team_prepared=team_prepared,
            team_knowledge_imported=imported,
            team_knowledge_selected=selected,
            model_routes=routes,
        )

    def _model_route_status(
        self, route: ProviderRouteConfig, codex_available: bool
    ) -> ModelRouteRuntimeStatus:
        if route.kind is ModelProviderKind.CODEX_CLI:
            return ModelRouteRuntimeStatus(
                provider=route.provider,
                model=route.model,
                kind=route.kind,
                enabled=route.enabled,
                ready=not route.enabled or codex_available,
            )
        assert route.api_key_env is not None
        configured = self._runtime_variable(route.api_key_env)[0] is not None
        return ModelRouteRuntimeStatus(
            provider=route.provider,
            model=route.model,
            kind=route.kind,
            enabled=route.enabled,
            ready=not route.enabled or configured,
            credential_environment_name=route.api_key_env,
            credential_configured=configured,
        )

    def _runtime_variable(
        self, name: str
    ) -> tuple[str | None, Literal["runtime.env", "process environment", "missing"]]:
        try:
            stored = self._runtime_environment.load().get(name)
        except RuntimeEnvironmentError as error:
            raise AdministrationError("runtime environment is invalid") from error
        if stored:
            return stored, "runtime.env"
        process = self.environment.get(name)
        if process:
            return process, "process environment"
        return None, "missing"

    def _restart_required(self) -> bool:
        if self._saved_config != self.runtime_config or self._runtime_changed:
            return True
        try:
            stored = self._runtime_environment.load()
        except RuntimeEnvironmentError as error:
            raise AdministrationError("runtime environment is invalid") from error
        return any(self.environment.get(name) != value for name, value in stored.items())

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

    def _project(self, project_id: str) -> ProjectWorkspace:
        try:
            return self._team().project_registry().open(project_id)
        except (OSError, ValueError) as error:
            raise AdministrationError("Project workspace is invalid") from error

    def _legacy_project_knowledge_paths(self, project: ProjectWorkspace) -> tuple[str, ...]:
        return (
            self._saved_config.project_knowledge_paths
            if self._saved_config.default_project_id == project.manifest.project_id
            else ()
        )

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


def _runtime_variable_names(config: ProductionConfig) -> set[str]:
    names = {config.database.dsn_env}
    names.update(
        route.api_key_env for route in config.model_routes if route.api_key_env is not None
    )
    return names


def _selected_document_paths(
    manifests: tuple[KnowledgeDocumentManifest, ...] | tuple[ProjectKnowledgeDocumentManifest, ...],
    document_ids: tuple[KnowledgeDocumentId, ...],
) -> tuple[str, ...]:
    available = {manifest.document_id: manifest for manifest in manifests}
    unknown = sorted(set(document_ids) - set(available))
    if unknown:
        raise AdministrationError("knowledge selection contains an unknown document")
    return tuple(
        sorted(available[document_id].normalized_relative_path for document_id in document_ids)
    )


def _codex_status(executable: str, environment: Mapping[str, str]) -> CodexRuntimeStatus:
    if "/" in executable:
        candidate = Path(executable).expanduser()
        resolved = (
            str(candidate.absolute())
            if candidate.is_file() and os.access(candidate, os.X_OK)
            else None
        )
    else:
        resolved = shutil.which(executable, path=environment.get("PATH"))
    return CodexRuntimeStatus(
        executable=executable,
        available=resolved is not None,
        resolved_path=resolved,
    )


__all__ = [
    "AdministrationError",
    "CodexRuntimeStatus",
    "ConsoleAdministration",
    "CreateProjectRequest",
    "DatabaseRuntimeStatus",
    "KnowledgeDocumentView",
    "LocalConsoleAdministration",
    "ModelRouteRuntimeStatus",
    "MySqlConnectionRequest",
    "MySqlConnectionResult",
    "ProjectSummary",
    "RuntimeStatusSnapshot",
    "RuntimeVariableUpdate",
    "SecretStatus",
    "SettingsSnapshot",
    "TeamSummary",
    "UpdateKnowledgeSelectionRequest",
    "UpdateSettingsRequest",
]
