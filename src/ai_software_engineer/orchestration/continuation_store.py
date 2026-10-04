"""Private append-only interruption/admission files outside target code worktrees."""

import json
import os
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Literal, cast

from pydantic import TypeAdapter

from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationAdmission,
    ContinuationConflict,
    ContinuationRecordMissing,
    ContinuationRejected,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.recovery.models import canonical_bytes, digest

MAX_CONTINUATION_RECORD_BYTES = 8_000_000
type _Record = ExecutionInterruptionReceipt | ContinuationAdmission


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate continuation JSON key")
        result[key] = value
    return result


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _open_directory(path: Path) -> int:
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as error:
        os.close(descriptor)
        raise ContinuationRejected("continuation directory is missing or unsafe") from error


class FileContinuationStore:
    """Read-only open; each Task has exactly one immutable receipt and admission."""

    def __init__(self, root: str | Path, *, task_id: str) -> None:
        self._root, self._task_id = self._placement(root, task_id)
        descriptor = _open_directory(self._root)
        try:
            metadata = os.fstat(descriptor)
            if metadata.st_mode & 0o077:
                raise ContinuationRejected("continuation directory must be private")
            self._root_identity = _identity(metadata)
        finally:
            os.close(descriptor)

    @classmethod
    def initialize(cls, root: str | Path, *, task_id: str) -> "FileContinuationStore":
        """Create the named Task child only; its trusted sidecar parent must exist."""
        target, checked_task = cls._placement(root, task_id)
        parent = _open_directory(target.parent)
        try:
            with suppress(FileExistsError):
                os.mkdir(target.name, 0o700, dir_fd=parent)
            os.fsync(parent)
            current_parent = _open_directory(target.parent)
            try:
                if _identity(os.fstat(current_parent)) != _identity(os.fstat(parent)):
                    raise ContinuationRejected("continuation parent identity changed")
            finally:
                os.close(current_parent)
        except OSError as error:
            raise ContinuationRejected("cannot initialize continuation directory") from error
        finally:
            os.close(parent)
        return cls(target, task_id=checked_task)

    @staticmethod
    def _placement(root: str | Path, task_id: str) -> tuple[Path, TaskId]:
        try:
            checked_task = TypeAdapter(TaskId).validate_python(task_id)
        except ValueError as error:
            raise ContinuationRejected("invalid continuation Task identity") from error
        target = Path(root)
        if (
            not target.is_absolute()
            or target.name != checked_task
            or ".." in target.parts
            or any(ord(character) < 32 for character in str(target))
        ):
            raise ContinuationRejected("continuation root must be an absolute exact Task directory")
        return target, checked_task

    def put_receipt(self, receipt: ExecutionInterruptionReceipt) -> ExecutionInterruptionReceipt:
        receipt.validate_integrity()
        self._validate_receipt(receipt)
        return self._put("receipt.json", receipt, ExecutionInterruptionReceipt)

    def get_receipt(self, run_id: str) -> ExecutionInterruptionReceipt:
        try:
            checked_run = TypeAdapter(RunId).validate_python(run_id)
        except ValueError as error:
            raise ContinuationRejected("invalid interruption Run identity") from error
        record = self._get("receipt.json", ExecutionInterruptionReceipt)
        self._validate_receipt(record)
        if record.request.run_id != checked_run:
            raise ContinuationRejected("interruption receipt belongs to another Run")
        return record

    def receipt_for_task(self, task_id: str) -> ExecutionInterruptionReceipt | None:
        self._require_task(task_id)
        try:
            record = self._get("receipt.json", ExecutionInterruptionReceipt)
        except ContinuationRecordMissing:
            return None
        self._validate_receipt(record)
        return record

    def put_admission(self, record: ContinuationAdmission) -> ContinuationAdmission:
        record.validate_integrity()
        self._validate_admission(record)
        return self._put("admission.json", record, ContinuationAdmission)

    def get_admission(self, task_id: str) -> ContinuationAdmission:
        self._require_task(task_id)
        record = self._get("admission.json", ContinuationAdmission)
        self._validate_admission(record)
        return record

    def _require_task(self, task_id: str) -> None:
        if task_id != self._task_id:
            raise ContinuationRejected("continuation store belongs to another Task")

    def _validate_receipt(self, record: ExecutionInterruptionReceipt) -> None:
        self._require_task(record.request.task_id)
        workspace = Path(record.capture.worktree_path).resolve()
        root = self._root.resolve()
        if root.is_relative_to(workspace) or workspace.is_relative_to(root):
            raise ContinuationRejected("continuation storage must not overlap the Coder worktree")

    def _validate_admission(self, record: ContinuationAdmission) -> None:
        self._require_task(record.task_id)
        receipt = self.get_receipt(record.interrupted_run_id)
        if (
            record.scope != receipt.scope
            or record.receipt_sha256 != receipt.receipt_sha256
            or record.policy_sha256 != receipt.policy_sha256
            or record.created_at < receipt.created_at
        ):
            raise ContinuationRejected(
                "continuation admission does not reference the exact receipt"
            )

    @contextmanager
    def _directory(self) -> Iterator[int]:
        descriptor = _open_directory(self._root)
        try:
            self._check_directory(descriptor)
            yield descriptor
            self._check_directory(descriptor)
        finally:
            os.close(descriptor)

    def _check_directory(self, descriptor: int) -> None:
        current = _open_directory(self._root)
        try:
            if (
                os.fstat(descriptor).st_mode & 0o077
                or os.fstat(current).st_mode & 0o077
                or _identity(os.fstat(descriptor)) != self._root_identity
                or _identity(os.fstat(current)) != self._root_identity
            ):
                raise ContinuationRejected("continuation root identity or privacy changed")
        finally:
            os.close(current)

    def _get[R: _Record](self, name: str, model: type[R]) -> R:
        with self._directory() as directory:
            try:
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
                )
            except FileNotFoundError as error:
                raise ContinuationRecordMissing("continuation record is missing") from error
            except OSError as error:
                raise ContinuationRejected("continuation record path is unsafe") from error
            try:
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_mode & 0o077
                    or before.st_size > MAX_CONTINUATION_RECORD_BYTES
                ):
                    raise ContinuationRejected("continuation record is not private bounded data")
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    content = stream.read(MAX_CONTINUATION_RECORD_BYTES + 1)
                after = os.fstat(descriptor)
                named = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (
                    len(content) > MAX_CONTINUATION_RECORD_BYTES
                    or _identity(named) != _identity(before)
                    or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                ):
                    raise ContinuationRejected("continuation record changed during read")
                envelope: object = json.loads(content, object_pairs_hook=_unique_object)
                if not isinstance(envelope, dict) or set(envelope) != {"record", "sha256"}:
                    raise ContinuationRejected("invalid continuation record envelope")
                decoded = cast(dict[str, object], envelope)
                if decoded["sha256"] != digest(decoded["record"]):
                    raise ContinuationRejected("continuation envelope integrity mismatch")
                record = model.model_validate(decoded["record"])
                record.validate_integrity()
                return cast(R, record)
            except (OSError, ValueError) as error:
                raise ContinuationRejected("cannot decode trusted continuation record") from error
            finally:
                os.close(descriptor)

    def _put[R: _Record](
        self, name: Literal["receipt.json", "admission.json"], record: R, model: type[R]
    ) -> R:
        wire = record.to_wire()
        try:
            existing = self._get(name, model)
        except ContinuationRecordMissing:
            pass
        else:
            if existing.to_wire() != wire:
                raise ContinuationConflict("continuation identity already has different content")
            return existing
        payload = canonical_bytes({"record": wire, "sha256": digest(wire)})
        if len(payload) > MAX_CONTINUATION_RECORD_BYTES:
            raise ContinuationRejected("continuation record exceeds its byte limit")
        temporary = ".pending-" + uuid.uuid4().hex
        with self._directory() as directory:
            try:
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
                try:
                    remaining = memoryview(payload)
                    while remaining:
                        written = os.write(descriptor, remaining)
                        if written <= 0:
                            raise OSError("short continuation record write")
                        remaining = remaining[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                self._check_directory(directory)
                with suppress(FileExistsError):
                    os.link(
                        temporary,
                        name,
                        src_dir_fd=directory,
                        dst_dir_fd=directory,
                        follow_symlinks=False,
                    )
                os.fsync(directory)
            except OSError as error:
                raise ContinuationRejected("cannot publish continuation record") from error
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=directory)
        existing = self._get(name, model)
        if existing.to_wire() != wire:
            raise ContinuationConflict("continuation identity already has different content")
        return existing
