"""Immutable filesystem stores for evidence records and sealed run manifests."""

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.domain.artifact import EvidenceId
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.evidence.models import (
    EvidenceRecord,
    RunEvidenceManifest,
    validate_evidence_record,
)

_EVIDENCE_ID: Final[TypeAdapter[EvidenceId]] = TypeAdapter(EvidenceId)
_RUN_ID: Final[TypeAdapter[RunId]] = TypeAdapter(RunId)


class EvidenceStoreError(RuntimeError):
    """Base error for durable evidence persistence."""


class EvidenceNotFound(EvidenceStoreError):
    pass


class EvidenceConflict(EvidenceStoreError):
    pass


class EvidenceCorruption(EvidenceStoreError):
    pass


class RunEvidenceNotFound(EvidenceStoreError):
    pass


class RunEvidenceConflict(EvidenceStoreError):
    pass


class FileEvidenceStore:
    """Store one immutable JSON record per evidence fact and Agent Run."""

    def __init__(self, evidence_root: str | Path, runs_root: str | Path) -> None:
        self._evidence_root = _prepare_root(evidence_root, "evidence")
        self._runs_root = _prepare_root(runs_root, "run evidence")
        if _paths_overlap(self._evidence_root, self._runs_root):
            raise EvidenceStoreError("evidence and runs roots must not overlap")

    def put(self, record: EvidenceRecord) -> EvidenceRecord:
        target = self._evidence_path(record.evidence_id)
        try:
            record.validate_integrity()
        except ValueError as error:
            raise EvidenceCorruption(
                f"evidence record is not sealed: {record.evidence_id}"
            ) from error
        if target.exists():
            existing = self.get(record.evidence_id)
            if existing == record:
                return existing
            raise EvidenceConflict(record.evidence_id)
        _atomic_write(target, record.to_wire())
        return self.get(record.evidence_id)

    def get(self, evidence_id: EvidenceId | str) -> EvidenceRecord:
        target = self._evidence_path(evidence_id)
        if not target.is_file():
            raise EvidenceNotFound(str(evidence_id))
        try:
            record = validate_evidence_record(json.loads(target.read_text(encoding="utf-8")))
            record.validate_integrity()
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
            raise EvidenceCorruption(f"evidence record is invalid: {evidence_id}") from error
        if record.evidence_id != evidence_id:
            raise EvidenceCorruption(f"evidence filename identity mismatch: {evidence_id}")
        return record

    def find(self, evidence_id: EvidenceId | str) -> EvidenceRecord | None:
        try:
            return self.get(evidence_id)
        except EvidenceNotFound:
            return None

    def list_for_run(self, run_id: RunId | str) -> tuple[EvidenceRecord, ...]:
        validated = _RUN_ID.validate_python(run_id)
        try:
            records = tuple(
                self.get(path.stem) for path in sorted(self._evidence_root.glob("ev_*.json"))
            )
        except OSError as error:
            raise EvidenceStoreError("cannot list evidence records") from error
        return tuple(
            sorted(
                (record for record in records if record.identity.run_id == validated),
                key=lambda record: (record.captured_at, record.evidence_id),
            )
        )

    def seal_run(self, manifest: RunEvidenceManifest) -> RunEvidenceManifest:
        try:
            manifest.validate_integrity()
        except ValueError as error:
            raise RunEvidenceConflict("run evidence manifest is not sealed") from error
        records = self.list_for_run(manifest.identity.run_id)
        if tuple(record.evidence_id for record in records) != manifest.evidence_ids:
            raise RunEvidenceConflict("manifest evidence IDs do not match persisted run evidence")
        if any(record.identity != manifest.identity for record in records):
            raise RunEvidenceConflict("manifest identity does not match persisted evidence")
        target = self._run_path(manifest.identity.run_id)
        if target.exists():
            existing = self.get_run(manifest.identity.run_id)
            if existing == manifest:
                return existing
            raise RunEvidenceConflict(manifest.identity.run_id)
        _atomic_write(target, manifest.to_wire())
        return self.get_run(manifest.identity.run_id)

    def get_run(self, run_id: RunId | str) -> RunEvidenceManifest:
        target = self._run_path(run_id)
        if not target.is_file():
            raise RunEvidenceNotFound(str(run_id))
        try:
            manifest = RunEvidenceManifest.model_validate(
                json.loads(target.read_text(encoding="utf-8"))
            )
            manifest.validate_integrity()
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
            raise EvidenceCorruption(f"run evidence manifest is invalid: {run_id}") from error
        if manifest.identity.run_id != run_id:
            raise EvidenceCorruption(f"run manifest filename identity mismatch: {run_id}")
        records = self.list_for_run(manifest.identity.run_id)
        if tuple(record.evidence_id for record in records) != manifest.evidence_ids:
            raise EvidenceCorruption("run manifest references changed or missing evidence")
        if any(record.identity != manifest.identity for record in records):
            raise EvidenceCorruption("run evidence identity no longer matches manifest")
        return manifest

    def _evidence_path(self, evidence_id: EvidenceId | str) -> Path:
        try:
            validated = _EVIDENCE_ID.validate_python(evidence_id)
        except ValidationError as error:
            raise EvidenceNotFound(str(evidence_id)) from error
        return self._evidence_root / f"{validated}.json"

    def _run_path(self, run_id: RunId | str) -> Path:
        try:
            validated = _RUN_ID.validate_python(run_id)
        except ValidationError as error:
            raise RunEvidenceNotFound(str(run_id)) from error
        return self._runs_root / f"{validated}.json"


def _prepare_root(root: str | Path, label: str) -> Path:
    configured = Path(root).expanduser()
    if configured.is_symlink():
        raise EvidenceStoreError(f"{label} root cannot be a symlink")
    resolved = configured.resolve(strict=False)
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise EvidenceStoreError(f"cannot initialize {label} root") from error
    return resolved


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _atomic_write(target: Path, payload: WirePayload) -> None:
    temporary_path: Path | None = None
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
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
        raise EvidenceStoreError(f"cannot atomically write {target.name}") from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


__all__ = [
    "EvidenceConflict",
    "EvidenceCorruption",
    "EvidenceNotFound",
    "EvidenceStoreError",
    "FileEvidenceStore",
    "RunEvidenceConflict",
    "RunEvidenceNotFound",
]
