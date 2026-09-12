"""Company-owned knowledge and project modules outside all source checkouts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import AwareDatetime, StringConstraints, TypeAdapter

from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.project_workspace import ProjectWorkspace, ProjectWorkspaceRegistry
from ai_software_engineer.redaction import redact_text

CompanyId = Annotated[str, StringConstraints(pattern=r"^company_[a-z0-9][a-z0-9_-]{1,63}$")]
CompanyName = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
_DIRECTORIES = ("knowledge", "projects", "requests")
MAX_COMPANY_KNOWLEDGE_SOURCE_BYTES = 10_000_000
MAX_COMPANY_KNOWLEDGE_DOCUMENT_BYTES = 256_000
_MAX_SELECTION_BYTES = 1_000_000


class CompanyManifest(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    company_id: CompanyId
    name: CompanyName
    platform_root: NonEmptyStr
    company_root: NonEmptyStr
    created_at: AwareDatetime
    manifest_sha256: Digest

    def recompute_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate_integrity(self) -> None:
        if self.manifest_sha256 != self.recompute_digest():
            raise ValueError("company manifest digest mismatch")


@dataclass(frozen=True)
class CompanyWorkspace:
    manifest: CompanyManifest

    @classmethod
    def initialize(
        cls, platform_root: str | Path, *, company_id: str, name: str, read_only: bool = False
    ) -> CompanyWorkspace:
        identity = TypeAdapter(CompanyId).validate_python(company_id)
        TypeAdapter(CompanyName).validate_python(name)
        configured = Path(platform_root).expanduser().absolute()
        _reject_symlinks(configured)
        platform = configured.resolve()
        root = platform / "companies" / identity
        _reject_symlinks(root)
        if not root.exists():
            if read_only:
                raise ValueError("company workspace has not been prepared")
            root.parent.mkdir(parents=True, exist_ok=True)
            manifest = CompanyManifest(
                company_id=identity,
                name=name,
                platform_root=str(platform),
                company_root=str(root),
                created_at=datetime.now(UTC),
                manifest_sha256="0" * 64,
            )
            manifest = manifest.model_copy(update={"manifest_sha256": manifest.recompute_digest()})
            staging = Path(tempfile.mkdtemp(prefix=".company-", dir=root.parent))
            try:
                for directory in _DIRECTORIES:
                    (staging / directory).mkdir()
                with (staging / "company.json").open("x", encoding="utf-8") as stream:
                    stream.write(manifest.model_dump_json(indent=2))
                    stream.flush()
                    os.fsync(stream.fileno())
                _sync_directory(staging)
                try:
                    staging.rename(root)
                except OSError:
                    if not root.exists():
                        raise
                _sync_directory(root.parent)
            finally:
                if staging.exists():
                    (staging / "company.json").unlink(missing_ok=True)
                    for directory in _DIRECTORIES:
                        (staging / directory).rmdir()
                    staging.rmdir()
        _reject_symlinks(root)
        manifest = CompanyManifest.model_validate_json(_read_regular(root / "company.json", 16_000))
        manifest.validate_integrity()
        if (
            manifest.company_id != identity
            or manifest.name != name
            or manifest.platform_root != str(platform)
            or manifest.company_root != str(root)
        ):
            raise ValueError("company manifest identity or location differs from configuration")
        for directory in _DIRECTORIES:
            _reject_symlinks(root / directory)
            if not (root / directory).is_dir():
                raise ValueError("company workspace has a missing directory")
        return cls(manifest=manifest)

    @property
    def root(self) -> Path:
        return Path(self.manifest.company_root)

    @property
    def requests_root(self) -> Path:
        return self.root / "requests"

    def validate_current(self) -> None:
        if not self.root.is_dir() or not (self.root / "company.json").is_file():
            raise ValueError("company workspace is missing; restore it before continuing")
        current = self.initialize(
            self.manifest.platform_root,
            company_id=self.manifest.company_id,
            name=self.manifest.name,
        )
        if current.manifest != self.manifest:
            raise ValueError("company workspace identity changed")

    def validate_code_root(self, root: str | Path) -> None:
        target = Path(root).resolve()
        platform = Path(self.manifest.platform_root)
        if target.is_relative_to(platform) or platform.is_relative_to(target):
            raise ValueError("company/platform workspace and code scope overlap")

    def project_registry(self) -> ProjectWorkspaceRegistry:
        self.validate_current()
        return _CompanyProjectRegistry(self)

    def knowledge_sources(self, relative_paths: tuple[str, ...]) -> tuple[ContextSource, ...]:
        self.validate_current()
        ensure_unique(relative_paths, "company knowledge selection")
        if len(relative_paths) > 64:
            raise ValueError("company knowledge selection exceeds document budget")
        sources: list[ContextSource] = []
        total = 0
        for relative in sorted(relative_paths):
            validate_knowledge_path(relative)
            path = self.root / "knowledge" / relative
            content = _read_regular(path, MAX_COMPANY_KNOWLEDGE_DOCUMENT_BYTES)
            total += len(content)
            if total > _MAX_SELECTION_BYTES:
                raise ValueError("company knowledge selection exceeds byte budget")
            sha = hashlib.sha256(content).hexdigest()
            sources.append(
                ContextSource(
                    source_id="company.knowledge."
                    + hashlib.sha256(relative.encode()).hexdigest()[:16],
                    uri=f"company://{self.manifest.company_id}/knowledge/{relative}#{sha}",
                    content=redact_text(content.decode("utf-8")).text,
                    required=True,
                    priority=15,
                )
            )
        return tuple(sources)


def discover_company_workspaces(platform_root: str | Path) -> tuple[CompanyWorkspace, ...]:
    """Read and validate every prepared Company without creating platform state."""
    configured = Path(platform_root).expanduser().absolute()
    _reject_symlinks(configured)
    companies_root = configured.resolve() / "companies"
    _reject_symlinks(companies_root)
    if not companies_root.is_dir():
        return ()
    companies: list[CompanyWorkspace] = []
    for directory in sorted(companies_root.iterdir(), key=lambda path: path.name):
        if directory.is_symlink():
            raise ValueError("company workspace cannot traverse a symlink")
        manifest_path = directory / "company.json"
        if not directory.is_dir() or not directory.name.startswith("company_"):
            continue
        if not manifest_path.is_file():
            raise ValueError("company workspace has a missing manifest")
        manifest = CompanyManifest.model_validate_json(_read_regular(manifest_path, 16_000))
        manifest.validate_integrity()
        if directory.name != manifest.company_id:
            raise ValueError("company workspace directory does not match its manifest")
        companies.append(
            CompanyWorkspace.initialize(
                configured,
                company_id=manifest.company_id,
                name=manifest.name,
                read_only=True,
            )
        )
    return tuple(companies)


class _CompanyProjectRegistry(ProjectWorkspaceRegistry):
    def __init__(self, company: CompanyWorkspace) -> None:
        super().__init__(company.root / "projects")
        self._company = company

    def register(
        self, project_root: str | Path, *, project_id: ProjectId | str | None = None
    ) -> ProjectWorkspace:
        self._company.validate_current()
        self._company.validate_code_root(project_root)
        root = Path(project_root).resolve()
        identity = (
            "project_"
            + hashlib.sha256(
                (self._company.manifest.company_id + "\n" + str(root)).encode()
            ).hexdigest()[:40]
        )
        if project_id is not None and project_id != identity:
            raise ValueError("project ID is not bound to this company and code root")
        return super().register(project_root, project_id=identity)


def validate_knowledge_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or any(ord(c) < 32 for c in value)
        or any(p in {"", ".", "..", ".git"} or p.startswith(".") for p in value.split("/"))
        or any(c in value for c in "*?[")
        or path.suffix.lower() not in {".md", ".txt", ".json", ".yaml", ".yml", ".toml"}
        or path.stem.lower() in {"credentials", "secrets", "id_rsa", "id_ed25519"}
    ):
        raise ValueError("company knowledge must be an explicit safe relative document path")


def _reject_symlinks(path: Path) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("company workspace cannot traverse a symlink")


def _read_regular(path: Path, limit: int) -> bytes:
    _reject_symlinks(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("company record must be a regular file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("company document exceeds byte budget")
    return data


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
