"""Atomic, immutable filesystem ArtifactStore implementation."""

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.artifacts.ports import ArtifactRef
from ai_software_engineer.domain.artifact import (
    Artifact,
    ArtifactId,
    ArtifactIntegrity,
    Sha256,
    validate_artifact,
)
from ai_software_engineer.domain.enums import ArtifactKind
from ai_software_engineer.domain.model import WirePayload

SUPPORTED_SCHEMA_VERSION: Final = "v0.1"
_ARTIFACT_ID_ADAPTER: Final[TypeAdapter[ArtifactId]] = TypeAdapter(ArtifactId)


class ArtifactStoreError(RuntimeError):
    """Base class for stable ArtifactStore failures."""


class ArtifactNotFound(ArtifactStoreError):
    """Raised when an Artifact ID has no persisted file."""


class ArtifactValidationError(ArtifactStoreError):
    """Raised when a typed Artifact payload fails its contract."""


class ArtifactIntegrityError(ArtifactStoreError):
    """Raised when an Artifact is unsealed or its digest does not match."""


class ArtifactAlreadyExists(ArtifactStoreError):
    """Raised when an existing Artifact ID has different immutable content."""


class ArtifactParentError(ArtifactStoreError):
    """Raised when Artifact lineage is missing or crosses Task/kind boundaries."""


class ArtifactCorruption(ArtifactStoreError):
    """Raised when a persisted Artifact cannot be trusted or decoded."""


class SchemaVersionError(ArtifactStoreError):
    """Raised when a store receives a schema version it does not understand."""


def artifact_digest(artifact: Artifact) -> Sha256:
    """Return the canonical SHA-256 digest, excluding integrity to avoid circularity."""
    payload = artifact.to_wire()
    payload.pop("integrity", None)
    try:
        encoded = _canonical_json(payload).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ArtifactValidationError("Artifact is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()


def seal_artifact(artifact: Artifact, *, validated_at: datetime) -> Artifact:
    """Return an immutable copy sealed with its canonical digest and validation time."""
    integrity = ArtifactIntegrity(
        sha256=artifact_digest(artifact),
        validated=True,
        validated_at=validated_at,
    )
    return artifact.model_copy(update={"integrity": integrity})


class FileArtifactStore:
    """Persist each Artifact as one canonical JSON file under a controlled root."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ArtifactStoreError(f"cannot initialize ArtifactStore at {self._root}") from error

    def put(self, artifact: Artifact) -> ArtifactRef:
        """Validate, lineage-check, and atomically persist one immutable Artifact."""
        self._validate_for_put(artifact)
        target = self._path(artifact.artifact_id)
        if target.exists():
            existing = self.get(artifact.artifact_id)
            if existing.to_wire() == artifact.to_wire():
                return self._ref(existing, target)
            raise ArtifactAlreadyExists(artifact.artifact_id)
        self._validate_lineage(artifact)

        _atomic_write(target, _canonical_json(artifact.to_wire()))
        return self._ref(artifact, target)

    def get(self, artifact_id: ArtifactId) -> Artifact:
        """Read, validate, and integrity-check one persisted Artifact."""
        target = self._path(artifact_id)
        if not target.is_file():
            raise ArtifactNotFound(artifact_id)
        try:
            payload: object = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ArtifactCorruption(f"cannot decode Artifact {artifact_id}") from error
        if not isinstance(payload, dict):
            raise ArtifactCorruption(f"Artifact {artifact_id} is not a JSON object")
        if payload.get("artifact_id") != artifact_id:
            raise ArtifactCorruption(f"Artifact ID mismatch for {artifact_id}")
        try:
            kind = ArtifactKind(payload["kind"])
            artifact = validate_artifact(payload, kind)
            self._validate_for_put(artifact)
        except (KeyError, TypeError, ValueError, ValidationError, ArtifactStoreError) as error:
            if isinstance(error, ArtifactCorruption):
                raise
            raise ArtifactCorruption(f"Artifact {artifact_id} violates its contract") from error
        return artifact

    def _validate_for_put(self, artifact: Artifact) -> None:
        if artifact.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"unsupported Artifact schema version: {artifact.schema_version}"
            )
        try:
            validate_artifact(artifact.to_wire(), artifact.kind)
        except (ValueError, ValidationError) as error:
            raise ArtifactValidationError(f"invalid {artifact.kind} Artifact") from error
        if not artifact.integrity.validated:
            raise ArtifactIntegrityError(f"Artifact {artifact.artifact_id} is not sealed")
        digest = artifact_digest(artifact)
        if artifact.integrity.sha256 != digest:
            raise ArtifactIntegrityError(f"Artifact {artifact.artifact_id} digest mismatch")

    def _validate_lineage(self, artifact: Artifact) -> None:
        for parent_id in artifact.parent_artifact_ids:
            parent = self._load_parent(artifact.artifact_id, parent_id)
            if parent.task_id != artifact.task_id:
                raise ArtifactParentError(f"parent {parent_id} belongs to another Task")
        if artifact.supersedes is not None:
            superseded = self._load_parent(artifact.artifact_id, artifact.supersedes)
            if superseded.task_id != artifact.task_id:
                raise ArtifactParentError(
                    f"superseded {artifact.supersedes} belongs to another Task"
                )
            if superseded.kind is not artifact.kind:
                raise ArtifactParentError("supersedes must reference the same Artifact kind")

    def _load_parent(self, artifact_id: ArtifactId, parent_id: ArtifactId) -> Artifact:
        try:
            return self.get(parent_id)
        except ArtifactNotFound as error:
            raise ArtifactParentError(
                f"Artifact {artifact_id} references missing {parent_id}"
            ) from error

    def _path(self, artifact_id: ArtifactId) -> Path:
        try:
            validated_id = _ARTIFACT_ID_ADAPTER.validate_python(artifact_id)
        except ValidationError as error:
            raise ArtifactNotFound(artifact_id) from error
        return self._root / f"{validated_id}.json"

    @staticmethod
    def _ref(artifact: Artifact, path: Path) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=artifact.artifact_id,
            task_id=artifact.task_id,
            kind=artifact.kind,
            sha256=artifact.integrity.sha256,
            path=path,
        )


def _canonical_json(payload: WirePayload) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _atomic_write(target: Path, content: str) -> None:
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
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    except OSError as error:
        raise ArtifactStoreError(f"failed to atomically write {target.name}") from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
