"""Operation-store adapters for browser-submitted Manager work."""

from __future__ import annotations

import fcntl
import hashlib
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Literal, Protocol

from pydantic import TypeAdapter

from ai_software_engineer.agents.model_diagnostics import ModelCallDiagnostic
from ai_software_engineer.redaction import source_inspection_scope
from ai_software_engineer.team_workspace import _read_regular

from .models import (
    ConsoleCommandResult,
    ConsoleIntent,
    ConsoleModelCall,
    ConsoleOperation,
    ConsoleOperationStatus,
    IdempotencyKey,
    OperationId,
)
from .requirement_visibility import (
    RequirementOperationVisibility,
    RequirementOperationVisibilityReader,
)
from .summary_models import OperationSummary, OperationSummaryPage, OperationSummaryQuery
from .summary_projection import (
    OperationSummaryCache,
    SummaryProjectionUnavailable,
    build_summary_page,
)

# A Console operation can include an exact baseline plan with two complete
# mutation captures, its prepared patch and the workspace inventory. This is a
# separate storage admission budget, measured after UTF-8 JSON serialization
# (including escaping); it does not enlarge any capture or domain wire limit.
MAX_CONSOLE_OPERATION_BYTES = 16 * 1024 * 1024
_MAX_MODEL_CALL_BYTES = 16_000


class ConsoleOperationError(RuntimeError):
    """Base safe operation-store error."""


class ConsoleOperationConflict(ConsoleOperationError):
    """An idempotency key or delivery is already bound to other active work."""


class ConsoleOperationNotFound(ConsoleOperationError):
    """The requested operation does not exist."""


class ConsoleOperationStore(Protocol):
    def record_model_call(self, operation_id: str, call: ModelCallDiagnostic) -> None: ...
    def model_calls(self, operation_id: str) -> tuple[ModelCallDiagnostic, ...]: ...

    def submit(
        self, *, intent: ConsoleIntent, idempotency_key: str, requested_at: datetime
    ) -> ConsoleOperation: ...

    def get(self, operation_id: str) -> ConsoleOperation: ...
    def list_current(self) -> tuple[ConsoleOperation, ...]: ...
    def summary_page(self, query: OperationSummaryQuery) -> OperationSummaryPage: ...
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
    def __init__(self, team_id: str) -> None:
        self.team_id = team_id
        self._histories: dict[str, list[ConsoleOperation]] = {}
        self._model_calls: dict[str, list[ModelCallDiagnostic]] = {}
        self._lock = Lock()

    def record_model_call(self, operation_id: str, call: ModelCallDiagnostic) -> None:
        with self._lock:
            history = self._histories.get(operation_id)
            if not history:
                raise ConsoleOperationNotFound("console operation not found")
            if history[-1].status is not ConsoleOperationStatus.RUNNING:
                raise ConsoleOperationConflict("model call requires a running operation")
            calls = self._model_calls.setdefault(operation_id, [])
            if call not in calls:
                if len(calls) >= 2048:
                    raise ConsoleOperationConflict("model call diagnostic limit reached")
                calls.append(call)

    def model_calls(self, operation_id: str) -> tuple[ModelCallDiagnostic, ...]:
        self.get(operation_id)
        with self._lock:
            return tuple(self._model_calls.get(operation_id, ()))

    def submit(
        self, *, intent: ConsoleIntent, idempotency_key: str, requested_at: datetime
    ) -> ConsoleOperation:
        operation = ConsoleOperation.queued(
            team_id=self.team_id,
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

    def summary_page(self, query: OperationSummaryQuery) -> OperationSummaryPage:
        with self._lock:
            versions = tuple(
                item for _, history in sorted(self._histories.items()) for item in history
            )
            for item in versions:
                item.validate_integrity()
            inventory = hashlib.sha256(
                "".join(item.operation_sha256 for item in versions).encode()
            ).hexdigest()
            summaries = tuple(
                OperationSummary.from_operation(history[-1])
                for _, history in sorted(self._histories.items())
            )
            try:
                return build_summary_page(
                    summaries=summaries,
                    inventory_sha256=inventory,
                    query=query,
                    team_id=self.team_id,
                )
            except SummaryProjectionUnavailable as error:
                raise ConsoleOperationConflict(
                    "operation summaries cannot be read safely"
                ) from error

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
    """Append-only team-sidecar adapter with process-safe admission."""

    def __init__(
        self,
        root: Path,
        *,
        team_id: str,
        read_only: bool = False,
        visibility: RequirementOperationVisibilityReader | None = None,
    ) -> None:
        self.root = root.absolute()
        self.read_only = read_only
        self._visibility = visibility
        self.team_id = team_id
        self._idle_inventory_sha256: str | None = None
        self._summary_cache = OperationSummaryCache()
        self._summary_cache_lock = Lock()
        self._deleted_completions: dict[str, tuple[float, ConsoleOperation]] = {}
        _reject_symlinks(self.root)
        if not read_only:
            self.root.mkdir(parents=True, exist_ok=True)

    def record_model_call(self, operation_id: str, call: ModelCallDiagnostic) -> None:
        record = ConsoleModelCall(operation_id=operation_id, call=call)
        payload = _bounded_json_bytes(record.model_dump_json(indent=2), _MAX_MODEL_CALL_BYTES)
        with self._locked():
            operation = self._current(operation_id)
            if operation is None:
                raise ConsoleOperationNotFound("console operation not found")
            if operation.status is not ConsoleOperationStatus.RUNNING:
                raise ConsoleOperationConflict("model call requires a running operation")
            directory = self.root / operation_id / "model-calls"
            _reject_symlinks(directory)
            directory.mkdir(exist_ok=True)
            target = directory / f"{record.record_sha256}.json"
            _reject_symlinks(target)
            if target.exists():
                if _read_regular(target, _MAX_MODEL_CALL_BYTES) != payload:
                    raise ConsoleOperationConflict("model call diagnostic changed")
                return
            if len(tuple(directory.glob("*.json"))) >= 2048:
                raise ConsoleOperationConflict("model call diagnostic limit reached")
            _publish_json(target, payload)

    def model_calls(self, operation_id: str) -> tuple[ModelCallDiagnostic, ...]:
        with self._locked(shared=True):
            if self._current(operation_id) is None:
                raise ConsoleOperationNotFound("console operation not found")
            directory = self.root / operation_id / "model-calls"
            _reject_symlinks(directory)
            if directory.exists() and not directory.is_dir():
                raise ConsoleOperationConflict("model call diagnostics require a directory")
            paths = sorted(directory.glob("*.json"))
            if len(paths) > 2048:
                raise ConsoleOperationConflict("model call diagnostic limit reached")
            calls = []
            for path in paths:
                _reject_symlinks(path)
                record = ConsoleModelCall.model_validate_json(
                    _read_regular(path, _MAX_MODEL_CALL_BYTES)
                )
                if record.operation_id != operation_id or path.stem != record.record_sha256:
                    raise ConsoleOperationConflict("model call diagnostic identity mismatch")
                calls.append(record.call)
            return tuple(
                sorted(
                    calls, key=lambda call: (call.started_at, call.invocation_id, call.route_index)
                )
            )

    def submit(
        self, *, intent: ConsoleIntent, idempotency_key: str, requested_at: datetime
    ) -> ConsoleOperation:
        TypeAdapter(IdempotencyKey).validate_python(idempotency_key)
        proposed = ConsoleOperation.queued(
            team_id=self.team_id,
            idempotency_key=idempotency_key,
            intent=intent,
            requested_at=requested_at,
        )
        with self._locked():
            summary = OperationSummary.from_operation(proposed)
            if (
                proposed.intent.action != "DELETE_REQUIREMENT"
                and not self._read_visibility().visible(summary.project_id, summary.delivery_id)
            ):
                raise ConsoleOperationConflict("Requirement has been deleted or replaced")
            existing = self._current(proposed.operation_id)
            self._expire_deleted_completions()
            if existing is None and proposed.operation_id in self._deleted_completions:
                existing = self._deleted_completions[proposed.operation_id][1]
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
            self._expire_deleted_completions()
            if current is None and operation_id in self._deleted_completions:
                current = self._deleted_completions[operation_id][1]
        if current is None:
            raise ConsoleOperationNotFound("console operation not found")
        return current

    def list_current(self) -> tuple[ConsoleOperation, ...]:
        with self._locked(shared=True):
            complete = self._list_current()
            visibility = self._read_visibility()
            return tuple(
                item
                for item in complete
                if visibility.visible(
                    OperationSummary.from_operation(item).project_id,
                    OperationSummary.from_operation(item).delivery_id,
                )
            )

    def _read_visibility(self) -> RequirementOperationVisibility:
        return (
            self._visibility.read()
            if self._visibility is not None
            else RequirementOperationVisibility()
        )

    def summary_page(self, query: OperationSummaryQuery) -> OperationSummaryPage:
        # Separate lock serializes this tiny cache, not authoritative store reads.
        with self._summary_cache_lock, self._locked(shared=True), source_inspection_scope():
            inventory, operations = self._summary_inventory()
            self._summary_cache.discard_absent({operation_id for operation_id, _ in operations})
            summaries = []
            for operation_id, digest in operations:

                def read_current(
                    operation_id: str = operation_id, digest: str = digest
                ) -> ConsoleOperation | None:
                    operation = self._current(operation_id)
                    # Never associate a projection with bytes that drifted during replay.
                    if self._summary_directory_digest(self.root / operation_id) != digest:
                        raise ConsoleOperationConflict("operation changed during summary replay")
                    return operation

                summary = self._summary_cache.project(operation_id, digest, read_current)
                if summary is not None:
                    summaries.append(summary)
            visibility = self._read_visibility()
            if self._visibility is not None:
                inventory = hashlib.sha256(
                    bytes.fromhex(inventory) + bytes.fromhex(visibility.sha256)
                ).hexdigest()
            try:
                return build_summary_page(
                    summaries=tuple(
                        item
                        for item in summaries
                        if visibility.visible(item.project_id, item.delivery_id)
                    ),
                    inventory_sha256=inventory,
                    query=query,
                    team_id=self.team_id,
                )
            except SummaryProjectionUnavailable as error:
                raise ConsoleOperationConflict(
                    "operation summaries cannot be read safely"
                ) from error

    def _summary_inventory(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        inventory = hashlib.sha256()
        operations = []
        for directory in sorted(
            {
                *self.root.glob("operation_*"),
                *(self.root / key for key in self._pending_operations()),
            }
        ):
            _reject_symlinks(directory)
            if not directory.is_dir() and directory.name not in self._pending_operations():
                continue
            TypeAdapter(OperationId).validate_python(directory.name)
            digest = self._summary_directory_digest(directory)
            name = directory.name.encode()
            inventory.update(len(name).to_bytes(8, "big"))
            inventory.update(name)
            inventory.update(bytes.fromhex(digest))
            operations.append((directory.name, digest))
        return inventory.hexdigest(), tuple(operations)

    def _summary_directory_digest(self, directory: Path) -> str:
        _reject_symlinks(directory)
        pending = self._pending_operations().get(directory.name)
        if pending is not None:
            return pending[0]
        inventory = hashlib.sha256()
        for path in sorted(directory.glob("*.json")):
            _reject_symlinks(path)
            name = path.name.encode()
            body = _read_regular(path, MAX_CONSOLE_OPERATION_BYTES)
            inventory.update(len(name).to_bytes(8, "big"))
            inventory.update(name)
            inventory.update(hashlib.sha256(body).digest())
        return inventory.hexdigest()

    def claim_next(self, *, at: datetime) -> ConsoleOperation | None:
        with self._locked():
            inventory = self._operation_inventory_sha256()
            if self._idle_inventory_sha256 == inventory:
                return None
            queued = sorted(
                (
                    item
                    for item in self._list_current()
                    if item.status is ConsoleOperationStatus.QUEUED
                ),
                key=lambda item: (item.requested_at, item.operation_id),
            )
            if not queued:
                # Only reuse a fully validated no-QUEUED conclusion for exactly
                # the same complete bytes, not mtime or a retained model object.
                self._idle_inventory_sha256 = (
                    inventory if inventory == self._operation_inventory_sha256() else None
                )
                return None
            self._idle_inventory_sha256 = None
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
            if (
                status is ConsoleOperationStatus.SUCCEEDED
                and current.intent.action == "DELETE_REQUIREMENT"
                and result is not None
                and result.stage == "REQUIREMENT_DELETED"
            ):
                self._remove_deleted_operations(current, item)
            else:
                self._append(item, expected=expected)
            return item

    def _expire_deleted_completions(self) -> None:
        now = monotonic()
        self._deleted_completions = {
            key: value for key, value in self._deleted_completions.items() if value[0] > now
        }

    def _remove_deleted_operations(
        self, current: ConsoleOperation, completed: ConsoleOperation
    ) -> None:
        owner = OperationSummary.from_operation(current)
        selected = tuple(
            item
            for item in self._list_current()
            if OperationSummary.from_operation(item).project_id == owner.project_id
            and OperationSummary.from_operation(item).delivery_id == owner.delivery_id
        )
        if any(
            not item.terminal and item.operation_id != current.operation_id for item in selected
        ):
            raise ConsoleOperationConflict("deleted requirement has another active operation")
        if len(completed.model_dump_json().encode()) > 16_000:
            raise ConsoleOperationConflict("delete acknowledgement exceeds byte budget")
        from .preparation_store import FilePreparationProgressStore

        with FilePreparationProgressStore(
            self.root.parent / "console-preparation-progress"
        )._locked(shared=False):
            for operation in sorted(
                selected, key=lambda item: item.operation_id == current.operation_id
            ):
                self._cleanup_operations((operation,))
        self._expire_deleted_completions()
        while len(self._deleted_completions) >= 64:
            self._deleted_completions.pop(next(iter(self._deleted_completions)))
        self._deleted_completions[current.operation_id] = (monotonic() + 120, completed)

    def remove_terminal_operations(self, operation_ids: set[str]) -> None:
        """Caller holds both Operation and preparation fences for its verified plan."""
        selected = tuple(
            item for item in self._list_current() if item.operation_id in operation_ids
        )
        if any(not item.terminal for item in selected):
            raise ConsoleOperationConflict("Requirement history has an active Operation")
        # One admitted Operation fits its independent sealed pending budget.
        # Parent/native identity groups and large aggregate histories are safe.
        for item in selected:
            self._cleanup_operations((item,))

    def _cleanup_operations(self, selected: tuple[ConsoleOperation, ...]) -> None:
        from ai_software_engineer.multi_directory.purge import PurgeFile, _file_sha, _regular_files

        from .deletion_cleanup import MAX_CLEANUP_BYTES, ConsoleDeletionCleanup, execute_cleanup

        prep_root = self.root.parent / "console-preparation-progress"
        # The parent Requirement purger may already hold this preparation fence.
        # Its caller uses this helper only after releasing that nested fence.
        inventory: list[PurgeFile] = []
        directories: list[tuple[Literal["operations", "preparations"], str]] = []
        bases: tuple[tuple[Literal["operations", "preparations"], Path], ...] = (
            ("operations", self.root),
            ("preparations", prep_root),
        )
        for operation in selected:
            for scope, base in bases:
                directory = base / operation.operation_id
                _reject_symlinks(directory)
                if not directory.exists():
                    continue
                for path in _regular_files(directory):
                    size, sha = _file_sha(path)
                    inventory.append(
                        PurgeFile(
                            scope=scope,
                            path=path.relative_to(base).as_posix(),
                            size=size,
                            sha256=sha,
                        )
                    )
                directories.extend(
                    (scope, path.relative_to(base).as_posix())
                    for path in directory.rglob("*")
                    if path.is_dir()
                )
                directories.append((scope, operation.operation_id))
        record = ConsoleDeletionCleanup(
            team_id=self.team_id,
            operations=selected,
            files=tuple(inventory),
            directories=tuple(directories),
            cleanup_sha256="0" * 64,
        )
        record = record.model_copy(update={"cleanup_sha256": record.recompute_sha256()})
        record.validate_integrity()
        directory = self.root.parent / "console-deletion-pending"
        _reject_symlinks(directory)
        directory.mkdir(exist_ok=True)
        payload = _bounded_json_bytes(record.model_dump_json(indent=2), MAX_CLEANUP_BYTES)
        _publish_json(directory / (record.cleanup_sha256 + ".json"), payload)
        execute_cleanup(self.root, record)
        self._idle_inventory_sha256 = None

    def _pending_operations(self) -> dict[str, tuple[str, ConsoleOperation]]:
        from .deletion_cleanup import pending_cleanups

        return {
            item.operation_id: (record.cleanup_sha256, item)
            for record in pending_cleanups(self.root, self.team_id)
            for item in record.operations
        }

    def _recover_deleted_operations(self) -> None:
        from .deletion_cleanup import execute_cleanup, pending_cleanups
        from .preparation_store import FilePreparationProgressStore

        records = pending_cleanups(self.root, self.team_id)
        if records:
            with FilePreparationProgressStore(
                self.root.parent / "console-preparation-progress"
            )._locked(shared=False):
                for record in records:
                    execute_cleanup(self.root, record)
            self._idle_inventory_sha256 = None

    @contextmanager
    def _locked(self, *, shared: bool = False) -> Iterator[None]:
        if self.read_only and not shared:
            raise ConsoleOperationConflict("console operation store is read only")
        _reject_symlinks(self.root)
        if self.read_only and not self.root.exists():
            yield
            if self.root.exists():
                raise ConsoleOperationConflict("console operation store appeared during read")
            return
        if self.read_only:
            _read_regular(self.root / "console.lock", 0)
        flags = os.O_RDONLY if self.read_only else os.O_CREAT | os.O_RDWR
        descriptor = os.open(self.root / "console.lock", flags | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            if not shared:
                self._recover_deleted_operations()
            yield
        finally:
            os.close(descriptor)

    def _list_current(self) -> tuple[ConsoleOperation, ...]:
        with source_inspection_scope():
            return tuple(
                item
                for key in sorted(
                    {
                        *(path.name for path in self.root.glob("operation_*") if path.is_dir()),
                        *self._pending_operations(),
                    }
                )
                if (item := self._current(key)) is not None
            )

    def _operation_inventory_sha256(self) -> str:
        """Recheck every relevant complete file under the existing dispatch lock."""
        inventory = hashlib.sha256()
        for directory in sorted(self.root.glob("operation_*")):
            _reject_symlinks(directory)
            if not directory.is_dir():
                continue
            # Include empty directories, so newly admitted identities cannot
            # inherit a prior idle conclusion before their first record appears.
            name = directory.name.encode("utf-8")
            inventory.update(len(name).to_bytes(8, "big"))
            inventory.update(name)
            for path in sorted(directory.glob("*.json")):
                _reject_symlinks(path)
                name = path.name.encode("utf-8")
                body = _read_regular(path, MAX_CONSOLE_OPERATION_BYTES)
                inventory.update(len(name).to_bytes(8, "big"))
                inventory.update(name)
                inventory.update(hashlib.sha256(body).digest())
        return inventory.hexdigest()

    def _current(self, operation_id: str) -> ConsoleOperation | None:
        with source_inspection_scope():
            return self._read_current(operation_id)

    def _read_current(self, operation_id: str) -> ConsoleOperation | None:
        TypeAdapter(OperationId).validate_python(operation_id)
        pending = self._pending_operations().get(operation_id)
        if pending is not None:
            return pending[1]
        directory = self.root / operation_id
        _reject_symlinks(directory)
        if not directory.exists():
            return None
        previous: ConsoleOperation | None = None
        for path in sorted(directory.glob("*.json")):
            _reject_symlinks(path)
            item = ConsoleOperation.model_validate_json(
                _read_regular(path, MAX_CONSOLE_OPERATION_BYTES)
            )
            item.validate_integrity()
            if path.name != f"{item.sequence:06d}.json" or item.operation_id != operation_id:
                raise ConsoleOperationConflict("console operation identity mismatch")
            _validate_successor(previous, item)
            previous = item
        return previous

    def _append(self, operation: ConsoleOperation, *, expected: str | None) -> None:
        self._idle_inventory_sha256 = None
        operation.validate_integrity()
        payload = _bounded_json_bytes(
            operation.model_dump_json(indent=2), MAX_CONSOLE_OPERATION_BYTES
        )
        current = self._current(operation.operation_id)
        if (current.operation_sha256 if current else None) != expected:
            raise ConsoleOperationConflict("console operation changed")
        _validate_successor(current, operation)
        directory = self.root / operation.operation_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{operation.sequence:06d}.json"
        _publish_json(target, payload)


def _bounded_json_bytes(content: str, maximum_bytes: int) -> bytes:
    payload = content.encode("utf-8")
    if len(payload) > maximum_bytes:
        raise ConsoleOperationConflict("console record exceeds byte budget")
    return payload


def _publish_json(target: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".operation-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            raise ConsoleOperationConflict("console operation was concurrently updated") from error
        directory_descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _same_submission(current: ConsoleOperation, proposed: ConsoleOperation) -> ConsoleOperation:
    if (
        current.team_id != proposed.team_id
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
        "team_id",
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
    "MAX_CONSOLE_OPERATION_BYTES",
    "ConsoleOperationConflict",
    "ConsoleOperationError",
    "ConsoleOperationNotFound",
    "ConsoleOperationStore",
    "FileConsoleOperationStore",
    "InMemoryConsoleOperationStore",
]
