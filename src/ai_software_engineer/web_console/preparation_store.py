"""Independent, bounded and immutable storage for preparation observations."""

from __future__ import annotations

import fcntl
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Protocol

from pydantic import TypeAdapter

from ai_software_engineer.recovery.preparation_progress import (
    PREPARATION_MILESTONES,
    PreparationProgressScope,
    PreparationProgressView,
    PreparationRecord,
)
from ai_software_engineer.team_workspace import _read_regular, _reject_symlinks

from .store import ConsoleOperationConflict, _publish_json

MAX_PREPARATION_RECORD_BYTES = 8192
MAX_PREPARATION_PROGRESS_BYTES = 5 * MAX_PREPARATION_RECORD_BYTES
_RECORD: TypeAdapter[PreparationRecord] = TypeAdapter(PreparationRecord)
_LOGGER = logging.getLogger(__name__)


class PreparationProgressError(RuntimeError):
    """Observation records could not be read or published safely."""


class PreparationProgressStore(Protocol):
    def append(self, record: PreparationRecord) -> None: ...
    def read(self, scope: PreparationProgressScope) -> PreparationProgressView: ...


class _UnavailablePreparationProgressStore:
    def append(self, record: PreparationRecord) -> None:
        raise PreparationProgressError("preparation observation storage is unavailable")

    def read(self, scope: PreparationProgressScope) -> PreparationProgressView:
        raise PreparationProgressError("preparation observation storage is unavailable")


def open_preparation_progress_store(root: Path) -> PreparationProgressStore:
    """A diagnostic sidecar failure must not stop the production composition."""
    try:
        return FilePreparationProgressStore(root)
    except Exception:
        _LOGGER.error("PREPARATION_OBSERVATION_STORE_SETUP_FAILED")
        return _UnavailablePreparationProgressStore()


def _validate_record(record: PreparationRecord) -> PreparationRecord:
    value = _RECORD.validate_python(record.to_wire())
    PreparationProgressView(scope=value.scope, records=(value,))
    if len(value.model_dump_json(indent=2).encode("utf-8")) > MAX_PREPARATION_RECORD_BYTES:
        raise PreparationProgressError("preparation observation exceeds byte budget")
    return value


def _compatible(existing: PreparationRecord, proposed: PreparationRecord) -> None:
    # Retain the first timestamp: repeated verified reads of the same milestone
    # do not create a new progress event or overwrite immutable observation bytes.
    if (
        existing.scope != proposed.scope
        or existing.kind != proposed.kind
        or existing.evidence != proposed.evidence
    ):
        raise PreparationProgressError("preparation observation is immutable")


class InMemoryPreparationProgressStore:
    def __init__(self) -> None:
        self._records: dict[str, tuple[PreparationRecord, ...]] = {}
        self._lock = Lock()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if not self._lock.acquire(blocking=False):
            raise PreparationProgressError("preparation observations are busy")
        try:
            yield
        finally:
            self._lock.release()

    def append(self, record: PreparationRecord) -> None:
        try:
            value = _validate_record(record)
            with self._locked():
                current = self._read(value.scope)
                if existing := next((r for r in current.records if r.kind == value.kind), None):
                    _compatible(existing, value)
                    return
                combined = PreparationProgressView(
                    scope=value.scope, records=(*current.records, value)
                )
                self._records[value.scope.operation_id] = combined.records
        except (ValueError, OSError) as error:
            raise PreparationProgressError("preparation observation could not be stored") from error

    def _read(self, scope: PreparationProgressScope) -> PreparationProgressView:
        records = self._records.get(scope.operation_id, ())
        return PreparationProgressView(
            scope=scope,
            records=tuple(sorted(records, key=lambda r: PREPARATION_MILESTONES.index(r.kind))),
        )

    def read(self, scope: PreparationProgressScope) -> PreparationProgressView:
        try:
            with self._locked():
                return self._read(scope)
        except (ValueError, OSError) as error:
            raise PreparationProgressError("preparation observations could not be read") from error


class FilePreparationProgressStore:
    """A separate sidecar and nonblocking lock, never the Operation hash chain."""

    def __init__(self, root: Path, *, read_only: bool = False) -> None:
        self.root = root.absolute()
        self.read_only = read_only
        try:
            _reject_symlinks(self.root)
            if not read_only:
                self.root.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(
                    self.root / "preparation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
                )
                os.close(descriptor)
        except (ValueError, OSError) as error:
            raise PreparationProgressError("preparation store could not be opened") from error

    @contextmanager
    def _locked(self, *, shared: bool) -> Iterator[None]:
        _reject_symlinks(self.root)
        _read_regular(self.root / "preparation.lock", 0)
        descriptor = os.open(self.root / "preparation.lock", os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(descriptor, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            yield
        finally:
            os.close(descriptor)

    def append(self, record: PreparationRecord) -> None:
        if self.read_only:
            raise PreparationProgressError("preparation store is read only")
        try:
            value = _validate_record(record)
            with self._locked(shared=False):
                current = self._read(value.scope)
                if existing := next((r for r in current.records if r.kind == value.kind), None):
                    _compatible(existing, value)
                    return
                PreparationProgressView(scope=value.scope, records=(*current.records, value))
                directory = self.root / value.scope.operation_id
                _reject_symlinks(directory)
                directory.mkdir(exist_ok=True)
                _publish_json(
                    directory / f"{value.kind}.json", value.model_dump_json(indent=2).encode()
                )
        except (ValueError, OSError, ConsoleOperationConflict) as error:
            raise PreparationProgressError("preparation observation could not be stored") from error

    def _read(self, scope: PreparationProgressScope) -> PreparationProgressView:
        directory = self.root / scope.operation_id
        _reject_symlinks(directory)
        if not directory.exists():
            return PreparationProgressView(scope=scope)
        if not directory.is_dir():
            raise PreparationProgressError("preparation observations require a directory")
        records: list[PreparationRecord] = []
        total = 0
        for index, path in enumerate(directory.iterdir()):
            if index >= len(PREPARATION_MILESTONES):
                raise PreparationProgressError("preparation observation count exceeds budget")
            if path.name not in {f"{kind}.json" for kind in PREPARATION_MILESTONES}:
                raise PreparationProgressError("preparation observation filename is invalid")
            payload = _read_regular(path, MAX_PREPARATION_RECORD_BYTES)
            total += len(payload)
            if total > MAX_PREPARATION_PROGRESS_BYTES:
                raise PreparationProgressError("preparation observations exceed byte budget")
            record = _RECORD.validate_json(payload)
            if path.stem != record.kind:
                raise PreparationProgressError("preparation observation identity mismatch")
            records.append(record)
        return PreparationProgressView(
            scope=scope,
            records=tuple(sorted(records, key=lambda r: PREPARATION_MILESTONES.index(r.kind))),
        )

    def read(self, scope: PreparationProgressScope) -> PreparationProgressView:
        try:
            _reject_symlinks(self.root)
            if not self.root.exists():
                return PreparationProgressView(scope=scope)
            with self._locked(shared=True):
                return self._read(scope)
        except (ValueError, OSError) as error:
            raise PreparationProgressError("preparation observations could not be read") from error
