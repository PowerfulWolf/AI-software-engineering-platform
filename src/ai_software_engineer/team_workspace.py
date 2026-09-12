"""The single long-lived Team workspace outside all source checkouts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import AwareDatetime, StringConstraints, TypeAdapter

from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain.identity import TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.redaction import redact_text

if TYPE_CHECKING:
    from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry

TeamName = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
_DIRECTORIES = (
    "agents",
    "knowledge",
    "leases",
    "metrics",
    "model-policies",
    "skills",
    "specs",
    "work-items",
)
MAX_TEAM_KNOWLEDGE_SOURCE_BYTES = 10_000_000
MAX_TEAM_KNOWLEDGE_DOCUMENT_BYTES = 256_000
_MAX_SELECTION_BYTES = 1_000_000


class TeamManifest(DomainModel):
    schema_version: Literal["v0.2"] = "v0.2"
    team_id: TeamId
    name: TeamName
    platform_root: NonEmptyStr
    team_root: NonEmptyStr
    created_at: AwareDatetime
    manifest_sha256: Digest

    def recompute_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate_integrity(self) -> None:
        if self.manifest_sha256 != self.recompute_digest():
            raise ValueError("team manifest digest mismatch")


@dataclass(frozen=True)
class TeamWorkspace:
    manifest: TeamManifest

    @classmethod
    def initialize(
        cls, platform_root: str | Path, *, team_id: str, name: str, read_only: bool = False
    ) -> TeamWorkspace:
        identity = TypeAdapter(TeamId).validate_python(team_id)
        TypeAdapter(TeamName).validate_python(name)
        configured = Path(platform_root).expanduser().absolute()
        _reject_symlinks(configured)
        platform = configured.resolve()
        root = platform / "team"
        _reject_symlinks(root)
        if not root.exists():
            if read_only:
                raise ValueError("team workspace has not been prepared")
            root.parent.mkdir(parents=True, exist_ok=True)
            manifest = TeamManifest(
                team_id=identity,
                name=name,
                platform_root=str(platform),
                team_root=str(root),
                created_at=datetime.now(UTC),
                manifest_sha256="0" * 64,
            )
            manifest = manifest.model_copy(update={"manifest_sha256": manifest.recompute_digest()})
            staging = Path(tempfile.mkdtemp(prefix=".team-", dir=root.parent))
            try:
                for directory in _DIRECTORIES:
                    (staging / directory).mkdir()
                with (staging / "team.json").open("x", encoding="utf-8") as stream:
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
                    (staging / "team.json").unlink(missing_ok=True)
                    for directory in _DIRECTORIES:
                        (staging / directory).rmdir()
                    staging.rmdir()
        _reject_symlinks(root)
        manifest = TeamManifest.model_validate_json(_read_regular(root / "team.json", 16_000))
        manifest.validate_integrity()
        if (
            manifest.team_id != identity
            or manifest.name != name
            or manifest.platform_root != str(platform)
            or manifest.team_root != str(root)
        ):
            raise ValueError("team manifest identity or location differs from configuration")
        for directory in _DIRECTORIES:
            _reject_symlinks(root / directory)
            if not (root / directory).is_dir():
                raise ValueError("team workspace has a missing directory")
        return cls(manifest=manifest)

    @property
    def root(self) -> Path:
        return Path(self.manifest.team_root)

    def directory(self, name: str) -> Path:
        """Resolve one fixed Team-owned directory."""
        if name not in _DIRECTORIES:
            raise ValueError(f"unknown Team directory: {name}")
        return self.root / name

    def validate_current(self) -> None:
        if not self.root.is_dir() or not (self.root / "team.json").is_file():
            raise ValueError("team workspace is missing; restore it before continuing")
        current = self.initialize(
            self.manifest.platform_root,
            team_id=self.manifest.team_id,
            name=self.manifest.name,
        )
        if current.manifest != self.manifest:
            raise ValueError("team workspace identity changed")

    def validate_code_root(self, root: str | Path) -> None:
        target = Path(root).resolve()
        platform = Path(self.manifest.platform_root)
        if target.is_relative_to(platform) or platform.is_relative_to(target):
            raise ValueError("team/platform workspace and code scope overlap")

    def project_registry(self) -> ProjectWorkspaceRegistry:
        """Return the sibling business Project registry without creating a Project."""
        from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry

        self.validate_current()
        return ProjectWorkspaceRegistry(self)

    def knowledge_sources(self, relative_paths: tuple[str, ...]) -> tuple[ContextSource, ...]:
        self.validate_current()
        ensure_unique(relative_paths, "team knowledge selection")
        if len(relative_paths) > 64:
            raise ValueError("team knowledge selection exceeds document budget")
        sources: list[ContextSource] = []
        total = 0
        for relative in sorted(relative_paths):
            validate_knowledge_path(relative)
            path = self.root / "knowledge" / relative
            content = _read_regular(path, MAX_TEAM_KNOWLEDGE_DOCUMENT_BYTES)
            total += len(content)
            if total > _MAX_SELECTION_BYTES:
                raise ValueError("team knowledge selection exceeds byte budget")
            sha = hashlib.sha256(content).hexdigest()
            sources.append(
                ContextSource(
                    source_id="team.knowledge."
                    + hashlib.sha256(relative.encode()).hexdigest()[:16],
                    uri=f"team://{self.manifest.team_id}/knowledge/{relative}#{sha}",
                    content=redact_text(content.decode("utf-8")).text,
                    required=True,
                    priority=15,
                )
            )
        return tuple(sources)


def discover_team_workspaces(platform_root: str | Path) -> tuple[TeamWorkspace, ...]:
    """Return the single prepared Team as a tuple for catalog callers."""
    configured = Path(platform_root).expanduser().absolute()
    _reject_symlinks(configured)
    platform = configured.resolve()
    root = platform / "team"
    _reject_symlinks(root)
    if not root.is_dir():
        return ()
    manifest = TeamManifest.model_validate_json(_read_regular(root / "team.json", 16_000))
    manifest.validate_integrity()
    return (
        TeamWorkspace.initialize(
            configured,
            team_id=manifest.team_id,
            name=manifest.name,
            read_only=True,
        ),
    )


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
        raise ValueError("team knowledge must be an explicit safe relative document path")


def _reject_symlinks(path: Path) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("team workspace cannot traverse a symlink")


def _read_regular(path: Path, limit: int) -> bytes:
    _reject_symlinks(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("team record must be a regular file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("team document exceeds byte budget")
    return data


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
