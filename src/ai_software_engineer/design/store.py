"""Append-only sidecar store for TechnicalDesign and Designer run receipts."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path
from typing import Final, Protocol, TypeVar

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.design.models import (
    DesignCommitCheckpoint,
    DesignRecordError,
    DesignRecordIntegrityError,
    DesignRunRecord,
)
from ai_software_engineer.domain import TechnicalDesign
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel, WirePayload
from ai_software_engineer.domain.project_delivery import TechnicalDesignId

_DESIGN_ID: Final[TypeAdapter[TechnicalDesignId]] = TypeAdapter(TechnicalDesignId)
_RUN_ID: Final[TypeAdapter[RunId]] = TypeAdapter(RunId)
_RecordT = TypeVar("_RecordT", bound=DomainModel)


class DesignRecordNotFound(DesignRecordError):
    """Raised when an exact immutable Designer record is absent."""


class DesignRecordConflict(DesignRecordError):
    """Raised when an immutable identity is reused with changed content."""


class DesignRecordCorruption(DesignRecordError):
    """Raised when persisted Designer bytes cannot be trusted."""


class DesignRecordPathError(DesignRecordError):
    """Raised when a Designer store path is no longer sidecar-contained."""


class DesignRecordStore(Protocol):
    def put_design(self, design: TechnicalDesign) -> TechnicalDesign: ...

    def get_design(self, design_id: TechnicalDesignId | str) -> TechnicalDesign: ...

    def find_design(self, design_id: TechnicalDesignId | str) -> TechnicalDesign | None: ...

    def put_run(self, record: DesignRunRecord) -> DesignRunRecord: ...

    def get_run(self, run_id: RunId | str) -> DesignRunRecord: ...

    def find_run(self, run_id: RunId | str) -> DesignRunRecord | None: ...

    def put_checkpoint(self, checkpoint: DesignCommitCheckpoint) -> DesignCommitCheckpoint: ...

    def get_checkpoint(self, run_id: RunId | str) -> DesignCommitCheckpoint: ...

    def find_checkpoint(self, run_id: RunId | str) -> DesignCommitCheckpoint | None: ...


class FileDesignRecordStore:
    """Persist records below an external project sidecar with exclusive publish."""

    def __init__(self, root: str | Path) -> None:
        configured = Path(root).expanduser()
        if configured.is_symlink():
            raise DesignRecordPathError("Designer store root cannot be a symlink")
        self._root = configured.resolve(strict=False)
        self._root.mkdir(parents=True, exist_ok=True)
        self._require_root()
        root_stat = self._root.lstat()
        self._root_identity = (root_stat.st_dev, root_stat.st_ino)

    def put_design(self, design: TechnicalDesign) -> TechnicalDesign:
        _validate_record(design)
        return self._put(self._path("designs", design.id), design, TechnicalDesign)

    def get_design(self, design_id: TechnicalDesignId | str) -> TechnicalDesign:
        identity = _identity(_DESIGN_ID, design_id, "TechnicalDesign")
        record = self._read(self._path("designs", identity, create=False), TechnicalDesign)
        if record.id != identity:
            raise DesignRecordCorruption("TechnicalDesign filename identity mismatch")
        return record

    def find_design(self, design_id: TechnicalDesignId | str) -> TechnicalDesign | None:
        try:
            return self.get_design(design_id)
        except DesignRecordNotFound:
            return None

    def put_run(self, record: DesignRunRecord) -> DesignRunRecord:
        _validate_record(record)
        return self._put(self._path("runs", record.run_id), record, DesignRunRecord)

    def get_run(self, run_id: RunId | str) -> DesignRunRecord:
        identity = _identity(_RUN_ID, run_id, "Designer run")
        record = self._read(self._path("runs", identity, create=False), DesignRunRecord)
        if record.run_id != identity:
            raise DesignRecordCorruption("DesignRunRecord filename identity mismatch")
        return record

    def find_run(self, run_id: RunId | str) -> DesignRunRecord | None:
        try:
            return self.get_run(run_id)
        except DesignRecordNotFound:
            return None

    def put_checkpoint(self, checkpoint: DesignCommitCheckpoint) -> DesignCommitCheckpoint:
        _validate_record(checkpoint)
        return self._put(
            self._path("checkpoints", checkpoint.run_id),
            checkpoint,
            DesignCommitCheckpoint,
        )

    def get_checkpoint(self, run_id: RunId | str) -> DesignCommitCheckpoint:
        identity = _identity(_RUN_ID, run_id, "Designer run")
        record = self._read(
            self._path("checkpoints", identity, create=False), DesignCommitCheckpoint
        )
        if record.run_id != identity:
            raise DesignRecordCorruption("DesignCommitCheckpoint filename identity mismatch")
        return record

    def find_checkpoint(self, run_id: RunId | str) -> DesignCommitCheckpoint | None:
        try:
            return self.get_checkpoint(run_id)
        except DesignRecordNotFound:
            return None

    def _put(self, target: Path, record: _RecordT, model: type[_RecordT]) -> _RecordT:
        if target.exists() or target.is_symlink():
            existing = self._read(target, model)
            if existing.to_wire() == record.to_wire():
                return existing
            raise DesignRecordConflict(
                f"Designer record already exists with different content: {target.name}"
            )
        payload = record.to_wire()
        envelope: WirePayload = {"record": payload, "sha256": _digest(payload)}
        if not _publish_exclusive(
            self._root,
            self._root_identity,
            target,
            envelope,
        ):
            existing = self._read(target, model)
            if existing.to_wire() == record.to_wire():
                return existing
            raise DesignRecordConflict(
                f"Designer record concurrently created with different content: {target.name}"
            )
        return self._read(target, model)

    def _read(self, target: Path, model: type[_RecordT]) -> _RecordT:
        self._require_path(target)
        if not target.exists():
            raise DesignRecordNotFound(f"Designer record not found: {target.stem}")
        if target.is_symlink() or not target.is_file():
            raise DesignRecordPathError(f"untrusted Designer record path: {target}")
        try:
            payload: object = json.loads(
                _read_trusted_text(self._root, self._root_identity, target),
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON value: {value}")
                ),
            )
            if not isinstance(payload, dict) or set(payload) != {"record", "sha256"}:
                raise DesignRecordCorruption("Designer record envelope is invalid")
            wire = payload["record"]
            digest = payload["sha256"]
            if not isinstance(wire, dict) or not isinstance(digest, str):
                raise DesignRecordCorruption("Designer record envelope is incomplete")
            if digest != _digest(wire):
                raise DesignRecordCorruption("Designer record envelope digest mismatch")
            record = model.model_validate(wire)
            _validate_record(record)
            return record
        except DesignRecordCorruption:
            raise
        except DesignRecordIntegrityError as error:
            raise DesignRecordCorruption("Designer record inner digest mismatch") from error
        except (OSError, UnicodeError, ValueError, ValidationError) as error:
            raise DesignRecordCorruption("cannot decode Designer record") from error

    def _path(self, category: str, identity: str, *, create: bool = True) -> Path:
        if category not in {"designs", "runs", "checkpoints"}:
            raise DesignRecordPathError(f"unknown Designer record category: {category}")
        self._require_root()
        directory = self._root / category
        if create:
            directory.mkdir(exist_ok=True)
        if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
            raise DesignRecordPathError(f"untrusted Designer record directory: {directory}")
        self._require_path(directory)
        return directory / f"{identity}.json"

    def _require_root(self) -> None:
        if (
            self._root.is_symlink()
            or not self._root.is_dir()
            or self._root.resolve(strict=False) != self._root
        ):
            raise DesignRecordPathError("Designer store root is no longer trusted")
        if hasattr(self, "_root_identity"):
            current = self._root.lstat()
            if (current.st_dev, current.st_ino) != self._root_identity:
                raise DesignRecordPathError("Designer store root identity changed")

    def _require_path(self, path: Path) -> None:
        self._require_root()
        try:
            path.resolve(strict=False).relative_to(self._root)
        except ValueError as error:
            raise DesignRecordPathError("Designer record path escapes store root") from error


def _validate_record(record: DomainModel) -> None:
    validator = getattr(record, "validate_integrity", None)
    if validator is None or not callable(validator):
        raise DesignRecordIntegrityError("record has no integrity contract")
    try:
        validator()
    except DesignRecordIntegrityError:
        raise
    except (RuntimeError, ValueError) as error:
        raise DesignRecordIntegrityError(f"{type(record).__name__} integrity is invalid") from error


def _identity[IdentityT](
    adapter: TypeAdapter[IdentityT], value: IdentityT | str, label: str
) -> IdentityT:
    try:
        return adapter.validate_python(value)
    except ValidationError as error:
        raise DesignRecordNotFound(f"invalid {label} identity: {value}") from error


def _publish_exclusive(
    root: Path,
    root_identity: tuple[int, int],
    target: Path,
    payload: WirePayload,
) -> bool:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    relative = _relative_target(root, target)
    directory_fd = _open_directory_chain(root, root_identity, relative.parent.parts)
    temporary_name = f".{target.name}.{secrets.token_hex(12)}.tmp"
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        try:
            offset = 0
            while offset < len(encoded):
                written = os.write(descriptor, encoded[offset:])
                if written == 0:
                    raise OSError("Designer record write made no progress")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(
                temporary_name,
                target.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except OSError as error:
            if error.errno == errno.EEXIST:
                return False
            raise
        os.fsync(directory_fd)
        if not _directory_fd_matches_path(directory_fd, target.parent):
            with suppress(OSError):
                os.unlink(target.name, dir_fd=directory_fd)
            raise DesignRecordPathError("Designer directory changed during publication")
        return True
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name, dir_fd=directory_fd)
        os.close(directory_fd)


def _relative_target(root: Path, target: Path) -> Path:
    try:
        return target.relative_to(root)
    except ValueError as error:
        raise DesignRecordPathError("Designer record path escapes store root") from error


def _open_directory_chain(
    root: Path,
    root_identity: tuple[int, int],
    parts: tuple[str, ...],
) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags)
    try:
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != root_identity:
            raise DesignRecordPathError("Designer store root identity changed")
        for part in parts:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _directory_fd_matches_path(descriptor: int, path: Path) -> bool:
    try:
        by_path = path.lstat()
        by_fd = os.fstat(descriptor)
    except OSError:
        return False
    return (
        stat.S_ISDIR(by_path.st_mode)
        and by_path.st_dev == by_fd.st_dev
        and by_path.st_ino == by_fd.st_ino
    )


def _read_trusted_text(
    root: Path,
    root_identity: tuple[int, int],
    target: Path,
) -> str:
    relative = _relative_target(root, target)
    directory_fd: int | None = None
    record_fd: int | None = None
    try:
        directory_fd = _open_directory_chain(root, root_identity, relative.parent.parts)
        if not _directory_fd_matches_path(directory_fd, target.parent):
            raise DesignRecordPathError("Designer record directory changed before read")
        record_fd = os.open(
            relative.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        before = os.fstat(record_fd)
        if not stat.S_ISREG(before.st_mode):
            raise DesignRecordPathError("Designer record is not a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(record_fd, 64 * 1024):
            chunks.append(chunk)
        after = os.fstat(record_fd)
        if not _same_file(before, after) or not _directory_fd_matches_path(
            directory_fd, target.parent
        ):
            raise DesignRecordPathError("Designer record changed during read")
        return b"".join(chunks).decode("utf-8")
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise DesignRecordPathError("Designer record path is untrusted") from error
        raise
    finally:
        if record_fd is not None:
            os.close(record_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _same_file(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        stat.S_ISREG(after.st_mode)
        and before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ctime_ns == after.st_ctime_ns
    )


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DesignRecordConflict",
    "DesignRecordCorruption",
    "DesignRecordNotFound",
    "DesignRecordPathError",
    "DesignRecordStore",
    "FileDesignRecordStore",
]
