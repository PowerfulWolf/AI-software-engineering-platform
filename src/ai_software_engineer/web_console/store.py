"""Operation-store adapters for browser-submitted Project Manager work."""

from __future__ import annotations

import fcntl
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Protocol

from pydantic import TypeAdapter

from ai_software_engineer.company_workspace import _read_regular

from .models import (
    ConsoleCommandResult,
    ConsoleIntent,
    ConsoleOperation,
    ConsoleOperationStatus,
    IdempotencyKey,
    OperationId,
)


class ConsoleOperationError(RuntimeError):
    """Base safe operation-store error."""


class ConsoleOperationConflict(ConsoleOperationError):
    """An idempotency key or delivery is already bound to other active work."""


class ConsoleOperationNotFound(ConsoleOperationError):
    """The requested operation does not exist."""


class ConsoleOperationStore(Protocol):
    def submit(
        self, *, intent: ConsoleIntent, idempotency_key: str, requested_at: datetime
    ) -> ConsoleOperation: ...

    def get(self, operation_id: str) -> ConsoleOperation: ...
    def list_current(self) -> tuple[ConsoleOperation, ...]: ...
    def claim_next(self, *, at: datetime) -> ConsoleOperation | None: ...

    def succeed(
        self, operation_id: str, *, expected: str, result: ConsoleCommandResult, at: datetime
    ) -> ConsoleOperation: ...

    def fail(
        self,
        operation_id: str,
        *,
        expected: str,
        error_code: str,
        error_summary: str,
        at: datetime,
    ) -> ConsoleOperation: ...

    def interrupt_running(self, *, at: datetime) -> tuple[ConsoleOperation, ...]: ...


class InMemoryConsoleOperationStore:
    def __init__(self, company_id: str) -> None:
        self.company_id = company_id
        self._histories: dict[str, list[ConsoleOperation]] = {}
        self._lock = Lock()

    def submit(
        self, *, intent: ConsoleIntent, idempotency_key: str, requested_at: datetime
    ) -> ConsoleOperation:
        operation = ConsoleOperation.queued(
            company_id=self.company_id,
            idempotency_key=idempotency_key,
            intent=intent,
            requested_at=requested_at,
        )
        with self._lock:
            existing = self._histories.get(operation.operation_id)
            if existing is not None:
                return _same_submission(existing[-1], operation)
            self._require_available(operation)
            self._histories[operation.operation_id] = [operation]
            return operation

    def get(self, operation_id: str) -> ConsoleOperation:
        TypeAdapter(OperationId).validate_python(operation_id)
        with self._lock:
            try:
                return self._histories[operation_id][-1]
            except KeyError as error:
                raise ConsoleOperationNotFound("console operation not found") from error

    def list_current(self) -> tuple[ConsoleOperation, ...]:
        with self._lock:
            return tuple(history[-1] for _, history in sorted(self._histories.items()))

    def claim_next(self, *, at: datetime) -> ConsoleOperation | None:
        with self._lock:
            queued = sorted(
                (
                    history[-1]
                    for history in self._histories.values()
                    if history[-1].status is ConsoleOperationStatus.QUEUED
                ),
                key=lambda item: (item.requested_at, item.operation_id),
            )
            if not queued:
                return None
            claimed = queued[0].transition(ConsoleOperationStatus.RUNNING, updated_at=at)
            self._histories[claimed.operation_id].append(claimed)
            return claimed

    def succeed(
        self, operation_id: str, *, expected: str, result: ConsoleCommandResult, at: datetime
    ) -> ConsoleOperation:
        return self._finish(
            operation_id,
            expected=expected,
            status=ConsoleOperationStatus.SUCCEEDED,
            at=at,
            result=result,
        )

    def fail(
        self,
        operation_id: str,
        *,
        expected: str,
        error_code: str,
        error_summary: str,
        at: datetime,
    ) -> ConsoleOperation:
        return self._finish(
            operation_id,
            expected=expected,
            status=ConsoleOperationStatus.FAILED,
            at=at,
            error_code=error_code,
            error_summary=error_summary,
        )

    def interrupt_running(self, *, at: datetime) -> tuple[ConsoleOperation, ...]:
        with self._lock:
            interrupted: list[ConsoleOperation] = []
            for operation_id, history in sorted(self._histories.items()):
                current = history[-1]
                if current.status is not ConsoleOperationStatus.RUNNING:
                    continue
                item = current.transition(
                    ConsoleOperationStatus.INTERRUPTED,
                    updated_at=at,
                    error_code="HOST_INTERRUPTED",
                    error_summary="The console host stopped before the operation completed.",
                )
                self._histories[operation_id].append(item)
                interrupted.append(item)
            return tuple(interrupted)

    def _finish(
        self,
        operation_id: str,
        *,
        expected: str,
        status: ConsoleOperationStatus,
        at: datetime,
        result: ConsoleCommandResult | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> ConsoleOperation:
        with self._lock:
            try:
                current = self._histories[operation_id][-1]
            except KeyError as error:
                raise ConsoleOperationNotFound("console operation not found") from error
            if current.operation_sha256 != expected:
                raise ConsoleOperationConflict("console operation changed")
            item = current.transition(
                status,
                updated_at=at,
                result=result,
                error_code=error_code,
                error_summary=error_summary,
            )
            self._histories[operation_id].append(item)
            return item

    def _require_available(self, proposed: ConsoleOperation) -> None:
        if proposed.delivery_id is None:
            return
        if any(
            current.delivery_id == proposed.delivery_id and not current.terminal
            for current in (history[-1] for history in self._histories.values())
        ):
            raise ConsoleOperationConflict("delivery already has an active console operation")


class FileConsoleOperationStore:
    """Append-only company-sidecar adapter with process-safe admission."""

    def __init__(self, root: Path, *, company_id: str) -> None:
        self.root = root.absolute()
        self.company_id = company_id
        _reject_symlinks(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def submit(
        self, *, intent: ConsoleIntent, idempotency_key: str, requested_at: datetime
    ) -> ConsoleOperation:
        TypeAdapter(IdempotencyKey).validate_python(idempotency_key)
        proposed = ConsoleOperation.queued(
            company_id=self.company_id,
            idempotency_key=idempotency_key,
            intent=intent,
            requested_at=requested_at,
        )
        with self._locked():
            existing = self._current(proposed.operation_id)
            if existing is not None:
                return _same_submission(existing, proposed)
            if proposed.delivery_id is not None and any(
                item.delivery_id == proposed.delivery_id and not item.terminal
                for item in self._list_current()
            ):
                raise ConsoleOperationConflict("delivery already has an active console operation")
            self._append(proposed, expected=None)
        return proposed

    def get(self, operation_id: str) -> ConsoleOperation:
        TypeAdapter(OperationId).validate_python(operation_id)
        with self._locked(shared=True):
            current = self._current(operation_id)
        if current is None:
            raise ConsoleOperationNotFound("console operation not found")
        return current

    def list_current(self) -> tuple[ConsoleOperation, ...]:
        with self._locked(shared=True):
            return self._list_current()

    def claim_next(self, *, at: datetime) -> ConsoleOperation | None:
        with self._locked():
            queued = sorted(
                (
                    item
                    for item in self._list_current()
                    if item.status is ConsoleOperationStatus.QUEUED
                ),
                key=lambda item: (item.requested_at, item.operation_id),
            )
            if not queued:
                return None
            claimed = queued[0].transition(ConsoleOperationStatus.RUNNING, updated_at=at)
            self._append(claimed, expected=queued[0].operation_sha256)
            return claimed

    def succeed(
        self, operation_id: str, *, expected: str, result: ConsoleCommandResult, at: datetime
    ) -> ConsoleOperation:
        return self._finish(
            operation_id,
            expected=expected,
            status=ConsoleOperationStatus.SUCCEEDED,
            at=at,
            result=result,
        )

    def fail(
        self,
        operation_id: str,
        *,
        expected: str,
        error_code: str,
        error_summary: str,
        at: datetime,
    ) -> ConsoleOperation:
        return self._finish(
            operation_id,
            expected=expected,
            status=ConsoleOperationStatus.FAILED,
            at=at,
            error_code=error_code,
            error_summary=error_summary,
        )

    def interrupt_running(self, *, at: datetime) -> tuple[ConsoleOperation, ...]:
        with self._locked():
            interrupted: list[ConsoleOperation] = []
            for current in self._list_current():
                if current.status is not ConsoleOperationStatus.RUNNING:
                    continue
                item = current.transition(
                    ConsoleOperationStatus.INTERRUPTED,
                    updated_at=at,
                    error_code="HOST_INTERRUPTED",
                    error_summary="The console host stopped before the operation completed.",
                )
                self._append(item, expected=current.operation_sha256)
                interrupted.append(item)
            return tuple(interrupted)

    def _finish(
        self,
        operation_id: str,
        *,
        expected: str,
        status: ConsoleOperationStatus,
        at: datetime,
        result: ConsoleCommandResult | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> ConsoleOperation:
        with self._locked():
            current = self._current(operation_id)
            if current is None:
                raise ConsoleOperationNotFound("console operation not found")
            if current.operation_sha256 != expected:
                raise ConsoleOperationConflict("console operation changed")
            item = current.transition(
                status,
                updated_at=at,
                result=result,
                error_code=error_code,
                error_summary=error_summary,
            )
            self._append(item, expected=expected)
            return item

    @contextmanager
    def _locked(self, *, shared: bool = False) -> Iterator[None]:
        _reject_symlinks(self.root)
        descriptor = os.open(
            self.root / "console.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def _list_current(self) -> tuple[ConsoleOperation, ...]:
        return tuple(
            item
            for path in sorted(self.root.glob("operation_*"))
            if path.is_dir() and (item := self._current(path.name)) is not None
        )

    def _current(self, operation_id: str) -> ConsoleOperation | None:
        TypeAdapter(OperationId).validate_python(operation_id)
        directory = self.root / operation_id
        _reject_symlinks(directory)
        if not directory.exists():
            return None
        previous: ConsoleOperation | None = None
        for path in sorted(directory.glob("*.json")):
            _reject_symlinks(path)
            item = ConsoleOperation.model_validate_json(_read_regular(path, 256_000))
            item.validate_integrity()
            if path.name != f"{item.sequence:06d}.json" or item.operation_id != operation_id:
                raise ConsoleOperationConflict("console operation identity mismatch")
            _validate_successor(previous, item)
            previous = item
        return previous

    def _append(self, operation: ConsoleOperation, *, expected: str | None) -> None:
        operation.validate_integrity()
        current = self._current(operation.operation_id)
        if (current.operation_sha256 if current else None) != expected:
            raise ConsoleOperationConflict("console operation changed")
        _validate_successor(current, operation)
        directory = self.root / operation.operation_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{operation.sequence:06d}.json"
        descriptor, temporary_name = tempfile.mkstemp(prefix=".operation-", dir=directory)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(operation.model_dump_json(indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError as error:
                raise ConsoleOperationConflict(
                    "console operation was concurrently updated"
                ) from error
            directory_descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            temporary.unlink(missing_ok=True)


def _same_submission(current: ConsoleOperation, proposed: ConsoleOperation) -> ConsoleOperation:
    if (
        current.company_id != proposed.company_id
        or current.idempotency_key != proposed.idempotency_key
        or current.intent_sha256 != proposed.intent_sha256
        or current.intent != proposed.intent
    ):
        raise ConsoleOperationConflict("idempotency key belongs to another console intent")
    return current


def _validate_successor(previous: ConsoleOperation | None, operation: ConsoleOperation) -> None:
    if previous is None:
        if operation.sequence != 1 or operation.previous_operation_sha256 is not None:
            raise ConsoleOperationConflict("console operation has no valid initial record")
        return
    if (
        operation.sequence != previous.sequence + 1
        or operation.previous_operation_sha256 != previous.operation_sha256
    ):
        raise ConsoleOperationConflict("console operation hash chain is broken")
    allowed = {
        ConsoleOperationStatus.QUEUED: {ConsoleOperationStatus.RUNNING},
        ConsoleOperationStatus.RUNNING: {
            ConsoleOperationStatus.SUCCEEDED,
            ConsoleOperationStatus.FAILED,
            ConsoleOperationStatus.INTERRUPTED,
        },
    }
    if operation.status not in allowed.get(previous.status, set()):
        raise ConsoleOperationConflict("console operation transition is invalid")
    for field in (
        "operation_id",
        "company_id",
        "idempotency_key",
        "intent",
        "intent_sha256",
        "requested_at",
    ):
        if getattr(operation, field) != getattr(previous, field):
            raise ConsoleOperationConflict("console operation intent is immutable")


def _reject_symlinks(path: Path) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ConsoleOperationConflict("console operation store cannot traverse symlinks")


__all__ = [
    "ConsoleOperationConflict",
    "ConsoleOperationError",
    "ConsoleOperationNotFound",
    "ConsoleOperationStore",
    "FileConsoleOperationStore",
    "InMemoryConsoleOperationStore",
]
