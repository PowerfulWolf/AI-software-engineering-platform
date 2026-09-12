"""Typed local administration for Companies, knowledge documents and settings."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Annotated, Protocol

from pydantic import AwareDatetime, Field, StrictBool, StringConstraints

from ai_software_engineer.company_workspace import (
    CompanyId,
    CompanyName,
    CompanyWorkspace,
    discover_company_workspaces,
)
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.knowledge_documents import (
    CompanyKnowledgeDocumentStore,
    KnowledgeDocumentManifest,
)


class AdministrationError(RuntimeError):
    """Stable operator-facing administration failure."""


class CompanySummary(DomainModel):
    company_id: CompanyId
    name: CompanyName
    active: StrictBool
    created_at: AwareDatetime


class CreateCompanyRequest(DomainModel):
    company_id: CompanyId
    name: CompanyName


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
    def companies(self) -> tuple[CompanySummary, ...]: ...
    def create_company(self, request: CreateCompanyRequest) -> CompanySummary: ...
    def knowledge(self, company_id: str) -> tuple[KnowledgeDocumentView, ...]: ...
    def import_document(
        self, *, company_id: str, filename: str, content: bytes
    ) -> KnowledgeDocumentView: ...
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

    def companies(self) -> tuple[CompanySummary, ...]:
        try:
            return tuple(
                CompanySummary(
                    company_id=company.manifest.company_id,
                    name=company.manifest.name,
                    active=company.manifest.company_id == self._saved_config.company_id,
                    created_at=company.manifest.created_at,
                )
                for company in discover_company_workspaces(self.runtime_config.platform_root)
            )
        except (OSError, ValueError) as error:
            raise AdministrationError("company catalog is invalid") from error

    def create_company(self, request: CreateCompanyRequest) -> CompanySummary:
        try:
            company = CompanyWorkspace.initialize(
                self.runtime_config.platform_root,
                company_id=request.company_id,
                name=request.name,
            )
        except (OSError, ValueError) as error:
            raise AdministrationError("company could not be created or reopened safely") from error
        return CompanySummary(
            company_id=company.manifest.company_id,
            name=company.manifest.name,
            active=company.manifest.company_id == self._saved_config.company_id,
            created_at=company.manifest.created_at,
        )

    def knowledge(self, company_id: str) -> tuple[KnowledgeDocumentView, ...]:
        company = self._company(company_id)
        selected = (
            set(self._saved_config.company_knowledge_paths)
            if company_id == self._saved_config.company_id
            else set()
        )
        return tuple(
            KnowledgeDocumentView(
                manifest=manifest,
                selected=manifest.normalized_relative_path in selected,
            )
            for manifest in CompanyKnowledgeDocumentStore(company).list()
        )

    def import_document(
        self, *, company_id: str, filename: str, content: bytes
    ) -> KnowledgeDocumentView:
        company = self._company(company_id)
        manifest = CompanyKnowledgeDocumentStore(company).import_document(
            filename=filename,
            content=content,
        )
        selected = (
            company_id == self._saved_config.company_id
            and manifest.normalized_relative_path in self._saved_config.company_knowledge_paths
        )
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
            company = next(
                item
                for item in discover_company_workspaces(config.platform_root)
                if item.manifest.company_id == config.company_id
            )
        except StopIteration as error:
            if config.platform_root == self.runtime_config.platform_root:
                raise AdministrationError(
                    "selected company is not prepared under platform_root"
                ) from error
            if config.company_knowledge_paths:
                raise AdministrationError(
                    "company knowledge must be cleared when starting a new platform_root"
                ) from error
            try:
                company = CompanyWorkspace.initialize(
                    config.platform_root,
                    company_id=config.company_id,
                    name=config.company_name,
                )
            except (OSError, ValueError) as initialization_error:
                raise AdministrationError(
                    "selected company could not be prepared under the new platform_root"
                ) from initialization_error
        except (OSError, ValueError) as error:
            raise AdministrationError("configured company workspace is invalid") from error
        if company.manifest.name != config.company_name:
            raise AdministrationError("company name must match its immutable Company record")
        try:
            company.knowledge_sources(config.company_knowledge_paths)
        except (OSError, UnicodeError, ValueError) as error:
            raise AdministrationError("selected company knowledge is invalid") from error
        with self._lock:
            _write_config(self.config_path, config)
            self._saved_config = config
        return self.settings()

    def _company(self, company_id: str) -> CompanyWorkspace:
        try:
            return next(
                company
                for company in discover_company_workspaces(self.runtime_config.platform_root)
                if company.manifest.company_id == company_id
            )
        except StopIteration as error:
            raise AdministrationError("company workspace was not found") from error
        except (OSError, ValueError) as error:
            raise AdministrationError("company workspace is invalid") from error


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
    "CompanySummary",
    "ConsoleAdministration",
    "CreateCompanyRequest",
    "KnowledgeDocumentView",
    "LocalConsoleAdministration",
    "SecretStatus",
    "SettingsSnapshot",
    "UpdateSettingsRequest",
]
