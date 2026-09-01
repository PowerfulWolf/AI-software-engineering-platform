"""External per-project AI workspace registry.

The target repository remains the source of truth for project code.  This module only
creates a sidecar directory for platform-owned state, prompts, profiles, artifacts,
evidence, and run metadata; it never copies or modifies the target repository.
"""

import hashlib
import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import (
    AwareDatetime,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr

ProjectId = Annotated[str, StringConstraints(pattern=r"^project_[a-z0-9][a-z0-9_-]{2,63}$")]
ManifestSha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
WorkspaceDirectory = Literal[
    "profile",
    "agents",
    "knowledge",
    "policy",
    "state",
    "artifacts",
    "contexts",
    "evidence",
    "evaluations",
    "handoffs",
    "runs",
    "locks",
    "logs",
    "spec-conflicts",
]

SUPPORTED_SCHEMA_VERSION: Final = "v0.1"
WORKSPACE_MANIFEST_NAME: Final = "workspace.json"
WORKSPACE_DIRECTORIES: Final[tuple[WorkspaceDirectory, ...]] = (
    "profile",
    "agents",
    "knowledge",
    "policy",
    "state",
    "artifacts",
    "contexts",
    "evidence",
    "evaluations",
    "handoffs",
    "runs",
    "locks",
    "logs",
    "spec-conflicts",
)
_PROJECT_ID_ADAPTER: Final[TypeAdapter[ProjectId]] = TypeAdapter(ProjectId)
_SAFE_SLUG = re.compile(r"[^a-z0-9_-]+")


class ProjectWorkspaceError(RuntimeError):
    """Base class for project sidecar workspace failures."""


class ProjectRootNotFound(ProjectWorkspaceError):
    """Raised when the requested target project is not an existing directory."""


class WorkspaceRootError(ProjectWorkspaceError):
    """Raised when the configured registry root cannot be used safely."""


class WorkspacePlacementError(ProjectWorkspaceError):
    """Raised when AI state could overlap the target project or escape its registry root."""


class ProjectWorkspaceConflict(ProjectWorkspaceError):
    """Raised when a project ID is already bound to a different project."""


class ProjectWorkspaceCorruption(ProjectWorkspaceError):
    """Raised when a previously created sidecar manifest or layout is untrusted."""


class WorkspaceLayout(DomainModel):
    """Stable relative directory names inside one AI sidecar workspace."""

    profile: NonEmptyStr = "profile"
    agents: NonEmptyStr = "agents"
    knowledge: NonEmptyStr = "knowledge"
    policy: NonEmptyStr = "policy"
    state: NonEmptyStr = "state"
    artifacts: NonEmptyStr = "artifacts"
    contexts: NonEmptyStr = "contexts"
    evidence: NonEmptyStr = "evidence"
    evaluations: NonEmptyStr = "evaluations"
    handoffs: NonEmptyStr = "handoffs"
    runs: NonEmptyStr = "runs"
    locks: NonEmptyStr = "locks"
    logs: NonEmptyStr = "logs"
    spec_conflicts: NonEmptyStr = "spec-conflicts"

    @classmethod
    def default(cls) -> "WorkspaceLayout":
        """Return the only v0.1 layout accepted by the registry."""
        return cls()

    def as_mapping(self) -> dict[WorkspaceDirectory, str]:
        """Return typed directory names for filesystem initialization."""
        return {
            "profile": self.profile,
            "agents": self.agents,
            "knowledge": self.knowledge,
            "policy": self.policy,
            "state": self.state,
            "artifacts": self.artifacts,
            "contexts": self.contexts,
            "evidence": self.evidence,
            "evaluations": self.evaluations,
            "handoffs": self.handoffs,
            "runs": self.runs,
            "locks": self.locks,
            "logs": self.logs,
            "spec-conflicts": self.spec_conflicts,
        }

    def validate_v01(self) -> None:
        """Reject layout changes that could make stores or visualizers ambiguous."""
        values = tuple(self.as_mapping().values())
        if values != WORKSPACE_DIRECTORIES:
            raise ProjectWorkspaceCorruption("sidecar layout does not match the v0.1 contract")


class ProjectWorkspaceManifest(DomainModel):
    """Persisted binding between a target code root and an external AI workspace."""

    schema_version: Literal["v0.1"] = SUPPORTED_SCHEMA_VERSION
    layout_version: Literal["v0.1"] = SUPPORTED_SCHEMA_VERSION
    project_id: ProjectId
    project_root: NonEmptyStr
    ai_workspace_root: NonEmptyStr
    layout: WorkspaceLayout = Field(default_factory=WorkspaceLayout.default)
    created_at: AwareDatetime
    manifest_sha256: ManifestSha256

    @field_validator("project_root", "ai_workspace_root")
    @classmethod
    def require_absolute_paths(cls, value: str) -> str:
        """Keep persisted bindings independent from the process working directory."""
        if any(ord(character) < 32 for character in value) or not Path(value).is_absolute():
            raise ValueError("project workspace paths must be absolute and contain no controls")
        return value

    @classmethod
    def create(
        cls,
        *,
        project_id: ProjectId,
        project_root: Path,
        ai_workspace_root: Path,
        created_at: datetime | None = None,
    ) -> "ProjectWorkspaceManifest":
        """Build a canonical manifest from already-resolved paths."""
        manifest = cls(
            project_id=project_id,
            project_root=str(project_root),
            ai_workspace_root=str(ai_workspace_root),
            created_at=created_at or datetime.now(UTC),
            manifest_sha256="0" * 64,
        )
        return manifest.model_copy(update={"manifest_sha256": _manifest_digest(manifest)})

    def validate_binding(self, expected_workspace_root: Path) -> None:
        """Validate paths, identity, and the fixed directory layout from disk."""
        if self.manifest_sha256 != _manifest_digest(self):
            raise ProjectWorkspaceCorruption("workspace manifest digest does not match content")
        self.layout.validate_v01()
        project_root = _resolved_path(self.project_root)
        workspace_root = _resolved_path(self.ai_workspace_root)
        expected = expected_workspace_root.resolve(strict=False)
        if workspace_root != expected:
            raise ProjectWorkspaceCorruption(
                "manifest AI workspace root does not match registry path"
            )
        if not project_root.is_dir():
            raise ProjectRootNotFound(str(project_root))
        if workspace_root == project_root or workspace_root.is_relative_to(project_root):
            raise WorkspacePlacementError("AI workspace must be outside the target project")
        if not workspace_root.is_relative_to(expected.parent):
            raise WorkspacePlacementError("AI workspace escapes its registry root")


@dataclass(frozen=True, slots=True)
class ProjectWorkspace:
    """Immutable handle used by later runtime/context composition layers."""

    manifest: ProjectWorkspaceManifest

    @property
    def project_id(self) -> ProjectId:
        return self.manifest.project_id

    @property
    def project_root(self) -> Path:
        return Path(self.manifest.project_root)

    @property
    def root(self) -> Path:
        return Path(self.manifest.ai_workspace_root)

    def directory(self, name: WorkspaceDirectory) -> Path:
        """Resolve one known sidecar directory without accepting arbitrary traversal."""
        relative = self.manifest.layout.as_mapping()[name]
        return self.root / relative

    @property
    def manifest_path(self) -> Path:
        return self.root / WORKSPACE_MANIFEST_NAME


class ProjectWorkspaceRegistry:
    """Create and reopen external, per-project AI workspaces idempotently."""

    def __init__(self, registry_root: str | Path) -> None:
        self._configured_registry_root = Path(registry_root).expanduser()
        self._registry_root = self._configured_registry_root.resolve(strict=False)

    @property
    def registry_root(self) -> Path:
        """Return the configured parent for all sidecar workspaces."""
        return self._registry_root

    def register(
        self,
        project_root: str | Path,
        *,
        project_id: ProjectId | str | None = None,
    ) -> ProjectWorkspace:
        """Register a target project without writing any file inside its code root."""
        target_root = _canonical_project_root(project_root)
        self._validate_registry_placement(target_root)
        self._ensure_registry_root()
        selected_id = _validate_or_derive_project_id(project_id, target_root)
        workspace_root = self._registry_root / selected_id
        self._validate_workspace_placement(target_root, workspace_root)

        if workspace_root.exists() or workspace_root.is_symlink():
            return self._open_existing(selected_id, target_root, workspace_root)

        manifest = ProjectWorkspaceManifest.create(
            project_id=selected_id,
            project_root=target_root,
            ai_workspace_root=workspace_root,
        )
        staging = Path(tempfile.mkdtemp(prefix=f".{selected_id}.", dir=self._registry_root))
        pending_staging: Path | None = staging
        try:
            for directory in manifest.layout.as_mapping().values():
                (staging / directory).mkdir(parents=True, exist_ok=False)
            _write_manifest(staging / WORKSPACE_MANIFEST_NAME, manifest)
            try:
                staging.rename(workspace_root)
            except OSError:
                if workspace_root.exists() or workspace_root.is_symlink():
                    return self._open_existing(selected_id, target_root, workspace_root)
                raise
            pending_staging = None
        except OSError as error:
            raise ProjectWorkspaceError(
                f"cannot initialize sidecar workspace: {workspace_root}"
            ) from error
        finally:
            if pending_staging is not None:
                with suppress(OSError):
                    _remove_staging_tree(pending_staging)
        manifest.validate_binding(workspace_root)
        return ProjectWorkspace(manifest=manifest)

    def _open_existing(
        self,
        project_id: ProjectId,
        project_root: Path,
        workspace_root: Path,
    ) -> ProjectWorkspace:
        if workspace_root.is_symlink() or not workspace_root.is_dir():
            raise ProjectWorkspaceConflict(
                f"workspace path is not a sidecar directory: {workspace_root}"
            )
        manifest_path = workspace_root / WORKSPACE_MANIFEST_NAME
        if not manifest_path.is_file():
            raise ProjectWorkspaceCorruption(f"workspace manifest is missing: {manifest_path}")
        try:
            payload: object = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = ProjectWorkspaceManifest.model_validate(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
            raise ProjectWorkspaceCorruption(
                f"workspace manifest is invalid: {manifest_path}"
            ) from error
        if (
            manifest.project_id != project_id
            or _resolved_path(manifest.project_root) != project_root
        ):
            raise ProjectWorkspaceConflict(
                f"project ID {project_id} is already bound to another project"
            )
        if _resolved_path(manifest.ai_workspace_root) != workspace_root.resolve(strict=False):
            raise ProjectWorkspaceCorruption("workspace manifest path does not match its directory")
        manifest.validate_binding(workspace_root)
        for directory in manifest.layout.as_mapping().values():
            if not (workspace_root / directory).is_dir():
                raise ProjectWorkspaceCorruption(
                    f"workspace layout directory is missing: {workspace_root / directory}"
                )
        return ProjectWorkspace(manifest=manifest)

    def _ensure_registry_root(self) -> None:
        if self._configured_registry_root.is_symlink():
            raise WorkspaceRootError(
                f"workspace registry cannot be a symlink: {self._configured_registry_root}"
            )
        try:
            self._registry_root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise WorkspaceRootError(
                f"cannot initialize workspace registry: {self._registry_root}"
            ) from error
        if not self._registry_root.is_dir() or self._registry_root.is_symlink():
            raise WorkspaceRootError(
                f"workspace registry is not a directory: {self._registry_root}"
            )

    def _validate_registry_placement(self, project_root: Path) -> None:
        if self._registry_root == project_root or self._registry_root.is_relative_to(project_root):
            raise WorkspacePlacementError("workspace registry must be outside the target project")

    def _validate_workspace_placement(self, project_root: Path, workspace_root: Path) -> None:
        resolved_workspace = workspace_root.resolve(strict=False)
        if (
            resolved_workspace == project_root
            or resolved_workspace.is_relative_to(project_root)
            or project_root.is_relative_to(resolved_workspace)
            or not resolved_workspace.is_relative_to(self._registry_root)
        ):
            raise WorkspacePlacementError("sidecar workspace overlaps or escapes its boundaries")


def project_id_for_root(project_root: str | Path) -> ProjectId:
    """Return the deterministic ID used when no operator-provided ID is supplied."""
    canonical = _canonical_project_root(project_root)
    return _validate_or_derive_project_id(None, canonical)


def _validate_or_derive_project_id(
    project_id: ProjectId | str | None, project_root: Path
) -> ProjectId:
    if project_id is not None:
        try:
            return _PROJECT_ID_ADAPTER.validate_python(project_id)
        except ValidationError as error:
            raise ProjectWorkspaceError(f"invalid project ID: {project_id!r}") from error
    raw_slug = _SAFE_SLUG.sub("-", project_root.name.lower()).strip("-_") or "project"
    slug = raw_slug[:38].rstrip("-_") or "project"
    digest = hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()[:12]
    return _PROJECT_ID_ADAPTER.validate_python(f"project_{slug}_{digest}")


def _canonical_project_root(project_root: str | Path) -> Path:
    candidate = Path(project_root).expanduser().resolve(strict=False)
    if not candidate.is_dir():
        raise ProjectRootNotFound(str(candidate))
    return candidate


def _resolved_path(value: str) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def _write_manifest(path: Path, manifest: ProjectWorkspaceManifest) -> None:
    encoded = json.dumps(
        manifest.to_wire(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    with path.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _manifest_digest(manifest: ProjectWorkspaceManifest) -> ManifestSha256:
    payload = manifest.to_wire()
    payload.pop("manifest_sha256")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _remove_staging_tree(path: Path) -> None:
    """Remove only an uncommitted staging directory created by this registry."""
    if not path.name.startswith(".") or not path.is_dir():
        return
    _remove_directory_tree(path)


def _remove_directory_tree(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            _remove_directory_tree(child)
        else:
            child.unlink(missing_ok=True)
    path.rmdir()


__all__ = [
    "SUPPORTED_SCHEMA_VERSION",
    "WORKSPACE_DIRECTORIES",
    "WORKSPACE_MANIFEST_NAME",
    "ManifestSha256",
    "ProjectId",
    "ProjectRootNotFound",
    "ProjectWorkspace",
    "ProjectWorkspaceConflict",
    "ProjectWorkspaceCorruption",
    "ProjectWorkspaceError",
    "ProjectWorkspaceManifest",
    "ProjectWorkspaceRegistry",
    "WorkspaceDirectory",
    "WorkspaceLayout",
    "WorkspacePlacementError",
    "WorkspaceRootError",
    "project_id_for_root",
]
