"""Immutable persistence for Project Manager stage checkpoints.

The target repository is never a persistence root for these stores. Composition passes
the project sidecar ``policy/`` directory (or an isolated test directory), and every
record is keyed by a validated project identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Final, Protocol

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.domain.project_delivery import ProjectPreparation, StageIntegrityError

_PROJECT_ID_ADAPTER: Final[TypeAdapter[ProjectId]] = TypeAdapter(ProjectId)
_RECORD_KEYS: Final = frozenset(("preparation", "sha256"))


class ProjectPreparationStoreError(RuntimeError):
    """Base class for stable ProjectPreparation persistence failures."""


class ProjectPreparationNotFound(ProjectPreparationStoreError):
    """Raised when a ProjectPreparation identity is absent or invalid."""


class ProjectPreparationConflict(ProjectPreparationStoreError):
    """Raised when an existing project identity is replayed with changed content."""


class ProjectPreparationIntegrityError(ProjectPreparationStoreError):
    """Raised when an in-memory ProjectPreparation is not correctly sealed."""


class ProjectPreparationCorruption(ProjectPreparationStoreError):
    """Raised when a persisted ProjectPreparation can no longer be trusted."""


class ProjectPreparationPathError(ProjectPreparationStoreError):
    """Raised when a configured root or record path could escape the sidecar."""


class ProjectPreparationStore(Protocol):
    """Port exposed to Project Manager application services, never directly to an Agent."""

    def put(self, preparation: ProjectPreparation) -> ProjectPreparation:
        """Append one immutable preparation or return its exact persisted replay."""
        ...

    def get(self, project_id: ProjectId | str) -> ProjectPreparation:
        """Return one trusted preparation or raise a typed failure."""
        ...

    def find(self, project_id: ProjectId | str) -> ProjectPreparation | None:
        """Return one trusted preparation, or ``None`` only when it is absent."""
        ...


class FileProjectPreparationStore:
    """Persist one canonical, append-once preparation record per project."""

    def __init__(self, root: str | Path) -> None:
        configured = Path(root).expanduser()
        if configured.is_symlink():
            raise ProjectPreparationPathError("ProjectPreparation store root cannot be a symlink")
        self._root = configured.resolve(strict=False)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ProjectPreparationStoreError(
                f"cannot initialize ProjectPreparation store at {self._root}"
            ) from error
        if not self._root.is_dir():
            raise ProjectPreparationPathError(
                f"ProjectPreparation store root is not a directory: {self._root}"
            )

    def put(self, preparation: ProjectPreparation) -> ProjectPreparation:
        """Validate and atomically publish one immutable preparation record."""
        _validate_preparation(preparation, ProjectPreparationIntegrityError)
        target = self._path(preparation.project_id)
        if target.exists() or target.is_symlink():
            existing = self.get(preparation.project_id)
            if existing.to_wire() == preparation.to_wire():
                return existing
            raise ProjectPreparationConflict(
                "ProjectPreparation already exists with different content: "
                f"{preparation.project_id}"
            )

        preparation_payload = preparation.to_wire()
        record: WirePayload = {
            "preparation": preparation_payload,
            "sha256": _digest(preparation_payload),
        }
        if not _atomic_write(target, record):
            existing = self.get(preparation.project_id)
            if existing.to_wire() == preparation.to_wire():
                return existing
            raise ProjectPreparationConflict(
                "ProjectPreparation was concurrently created with different content: "
                f"{preparation.project_id}"
            )
        return self.get(preparation.project_id)

    def get(self, project_id: ProjectId | str) -> ProjectPreparation:
        """Read and revalidate both the record envelope and stage document digest."""
        target = self._path(project_id)
        if target.is_symlink():
            raise ProjectPreparationPathError(
                f"ProjectPreparation record cannot be a symlink: {project_id}"
            )
        if not target.is_file():
            if target.exists():
                raise ProjectPreparationPathError(
                    f"ProjectPreparation record path is not a file: {project_id}"
                )
            raise ProjectPreparationNotFound(str(project_id))
        try:
            payload: object = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != _RECORD_KEYS:
                raise ProjectPreparationCorruption(
                    f"ProjectPreparation record has an invalid envelope: {project_id}"
                )
            preparation_payload = payload.get("preparation")
            digest = payload.get("sha256")
            if not isinstance(preparation_payload, dict) or not isinstance(digest, str):
                raise ProjectPreparationCorruption(
                    f"ProjectPreparation record is incomplete: {project_id}"
                )
            if digest != _digest(preparation_payload):
                raise ProjectPreparationCorruption(
                    f"ProjectPreparation record digest mismatch: {project_id}"
                )
            preparation = ProjectPreparation.model_validate(preparation_payload)
            _validate_preparation(preparation, ProjectPreparationCorruption)
        except ProjectPreparationCorruption:
            raise
        except (OSError, UnicodeError, ValueError, ValidationError) as error:
            raise ProjectPreparationCorruption(
                f"cannot decode ProjectPreparation record: {project_id}"
            ) from error
        if preparation.project_id != project_id:
            raise ProjectPreparationCorruption(
                f"ProjectPreparation filename identity mismatch: {project_id}"
            )
        return preparation

    def find(self, project_id: ProjectId | str) -> ProjectPreparation | None:
        """Return ``None`` for absence while preserving every corruption failure."""
        try:
            return self.get(project_id)
        except ProjectPreparationNotFound:
            return None

    def _path(self, project_id: ProjectId | str) -> Path:
        try:
            validated_id = _PROJECT_ID_ADAPTER.validate_python(project_id)
        except ValidationError as error:
            raise ProjectPreparationNotFound(str(project_id)) from error
        if (
            self._root.is_symlink()
            or not self._root.is_dir()
            or self._root.resolve(strict=False) != self._root
        ):
            raise ProjectPreparationPathError(
                f"ProjectPreparation store root is no longer trusted: {self._root}"
            )
        target = self._root / f"project-preparation-{validated_id}.json"
        if target.parent != self._root:
            raise ProjectPreparationPathError("ProjectPreparation record escapes its store root")
        return target


def _validate_preparation(
    preparation: ProjectPreparation,
    error_type: type[ProjectPreparationStoreError],
) -> None:
    try:
        preparation.validate_integrity()
    except (StageIntegrityError, ValueError) as error:
        raise error_type(f"ProjectPreparation digest mismatch: {preparation.project_id}") from error


def _canonical_json(payload: WirePayload) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(payload: WirePayload) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _atomic_write(target: Path, payload: WirePayload) -> bool:
    """Publish by exclusive hard link so a concurrent writer can never be overwritten."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(_canonical_json(payload))
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.link(temporary_path, target)
        except FileExistsError:
            return False
        _fsync_directory(target.parent)
        return True
    except OSError as error:
        raise ProjectPreparationStoreError(
            f"cannot atomically write ProjectPreparation record: {target.name}"
        ) from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "FileProjectPreparationStore",
    "ProjectPreparationConflict",
    "ProjectPreparationCorruption",
    "ProjectPreparationIntegrityError",
    "ProjectPreparationNotFound",
    "ProjectPreparationPathError",
    "ProjectPreparationStore",
    "ProjectPreparationStoreError",
]
