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

from ai_software_engineer.agents.continuation import same_continuation_inputs
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationAdmission,
    ContinuationConflict,
    ContinuationRecordMissing,
    ContinuationRejected,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.recovery.models import canonical_bytes, digest
from ai_software_engineer.redaction import source_inspection_scope

MAX_CONTINUATION_RECORD_BYTES = 8_000_000
type _Record = (
    ExecutionInterruptionReceipt
    | ContinuationAdmission
    | ExecutionCaptureStart
    | ExecutionCaptureStop
)


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
    """Read-only open; v1 fixed files and v2 per-Run append-only records."""

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

    @source_inspection_scope()
    def put_receipt(self, receipt: ExecutionInterruptionReceipt) -> ExecutionInterruptionReceipt:
        receipt.validate_integrity()
        self._validate_receipt(receipt)
        self._validate_predecessor(receipt)
        records = self.receipts_for_task(self._task_id)
        for prior in records:
            if prior.schema_version != receipt.schema_version:
                raise ContinuationConflict(
                    "Task continuation ledger cannot change authority version"
                )
            if (
                prior.request.attempt == receipt.request.attempt
                and prior.request.run_id != receipt.request.run_id
            ):
                raise ContinuationConflict("execution attempt already has another interruption Run")
        name = (
            "receipt.json"
            if receipt.schema_version == "v1"
            else f"receipt-{receipt.request.run_id}.json"
        )
        return self._put(name, receipt, ExecutionInterruptionReceipt)

    def put_capture_start(self, record: ExecutionCaptureStart) -> ExecutionCaptureStart:
        record.validate_integrity()
        self._require_task(record.request.task_id)
        return self._put(
            f"capture-start-{self._checked_run(record.request.run_id)}.json",
            record,
            ExecutionCaptureStart,
        )

    def capture_start(self, run_id: str) -> ExecutionCaptureStart:
        record = self._get(f"capture-start-{self._checked_run(run_id)}.json", ExecutionCaptureStart)
        self._require_task(record.request.task_id)
        if record.request.run_id != run_id:
            raise ContinuationRejected("capture start belongs to another Run")
        return record

    def put_capture_stop(self, record: ExecutionCaptureStop) -> ExecutionCaptureStop:
        record.validate_integrity()
        self._require_task(record.task_id)
        start = self.capture_start(record.run_id)
        if record.capture_start_sha256 != start.start_sha256 or (
            record.process_stop.stopped_at < start.started_at
        ):
            raise ContinuationRejected("capture stop changed its original invocation")
        return self._put(
            f"capture-stop-{self._checked_run(record.run_id)}.json", record, ExecutionCaptureStop
        )

    def capture_stop(self, run_id: str) -> ExecutionCaptureStop:
        record = self._get(f"capture-stop-{self._checked_run(run_id)}.json", ExecutionCaptureStop)
        self._require_task(record.task_id)
        start = self.capture_start(run_id)
        if record.run_id != run_id or record.capture_start_sha256 != start.start_sha256:
            raise ContinuationRejected("capture stop changed its original invocation")
        return record

    @source_inspection_scope()
    def get_receipt(self, run_id: str) -> ExecutionInterruptionReceipt:
        checked_run = self._checked_run(run_id)
        try:
            record = self._get(f"receipt-{checked_run}.json", ExecutionInterruptionReceipt)
            if record.schema_version != "v2":
                raise ContinuationRejected("per-Run receipt requires v2 authority")
        except ContinuationRecordMissing:
            record = self._get("receipt.json", ExecutionInterruptionReceipt)
            if record.schema_version != "v1":
                raise ContinuationRejected("legacy receipt requires v1 authority") from None
        self._validate_receipt(record)
        if record.request.run_id != checked_run:
            raise ContinuationRejected("interruption receipt belongs to another Run")
        self._validate_predecessor(record)
        return record

    @source_inspection_scope()
    def receipts_for_task(self, task_id: str) -> tuple[ExecutionInterruptionReceipt, ...]:
        self._require_task(task_id)
        records = []
        for name in self._record_names("receipt"):
            record = self._get(name, ExecutionInterruptionReceipt)
            self._validate_receipt(record)
            expected = (
                "receipt.json"
                if record.schema_version == "v1"
                else f"receipt-{record.request.run_id}.json"
            )
            if name != expected:
                raise ContinuationRejected("receipt filename does not match its version and Run")
            records.append(record)
        if (
            len({record.schema_version for record in records}) > 1
            or len({record.request.run_id for record in records}) != len(records)
            or len({record.request.attempt for record in records}) != len(records)
        ):
            raise ContinuationRejected("Task interruption ledger contains conflicting identities")
        for record in records:
            self._validate_predecessor(record)
        return tuple(
            sorted(records, key=lambda record: (record.request.attempt, record.request.run_id))
        )

    def receipt_for_task(self, task_id: str) -> ExecutionInterruptionReceipt | None:
        records = self.receipts_for_task(task_id)
        return records[-1] if records else None

    def put_admission(self, record: ContinuationAdmission) -> ContinuationAdmission:
        record.validate_integrity()
        self._validate_admission(record)
        for prior in self.admissions_for_task(self._task_id):
            if prior.schema_version != record.schema_version:
                raise ContinuationConflict(
                    "Task continuation ledger cannot change authority version"
                )
            if (
                prior.interrupted_run_id == record.interrupted_run_id
                or prior.new_request.attempt == record.new_request.attempt
            ) and prior.to_wire() != record.to_wire():
                raise ContinuationConflict("interruption already has a different one-use successor")
        name = (
            "admission.json"
            if record.schema_version == "v1"
            else f"admission-{record.new_request.run_id}.json"
        )
        return self._put(name, record, ContinuationAdmission)

    def admission_for_run(self, run_id: str) -> ContinuationAdmission | None:
        checked_run = self._checked_run(run_id)
        try:
            record = self._get(f"admission-{checked_run}.json", ContinuationAdmission)
            if record.schema_version != "v2":
                raise ContinuationRejected("per-Run admission requires v2 authority")
        except ContinuationRecordMissing:
            try:
                record = self._get("admission.json", ContinuationAdmission)
            except ContinuationRecordMissing:
                return None
            if record.schema_version != "v1":
                raise ContinuationRejected("legacy admission requires v1 authority") from None
            if record.new_request.run_id != checked_run:
                return None
        if record.new_request.run_id != checked_run:
            raise ContinuationRejected("admission belongs to another replacement Run")
        self._validate_admission(record)
        return record

    def admissions_for_task(self, task_id: str) -> tuple[ContinuationAdmission, ...]:
        self._require_task(task_id)
        records = []
        for name in self._record_names("admission"):
            record = self._get(name, ContinuationAdmission)
            self._validate_admission(record)
            expected = (
                "admission.json"
                if record.schema_version == "v1"
                else f"admission-{record.new_request.run_id}.json"
            )
            if name != expected:
                raise ContinuationRejected("admission filename does not match its version and Run")
            records.append(record)
        if (
            len({record.schema_version for record in records}) > 1
            or len({record.new_request.run_id for record in records}) != len(records)
            or len({record.interrupted_run_id for record in records}) != len(records)
            or len({record.new_request.attempt for record in records}) != len(records)
        ):
            raise ContinuationRejected("Task admission ledger contains conflicting successors")
        return tuple(
            sorted(
                records, key=lambda record: (record.new_request.attempt, record.new_request.run_id)
            )
        )

    def get_admission(self, task_id: str) -> ContinuationAdmission:
        records = self.admissions_for_task(task_id)
        if not records:
            raise ContinuationRecordMissing("continuation admission is missing")
        return records[-1]

    @staticmethod
    def _checked_run(run_id: str) -> RunId:
        try:
            return TypeAdapter(RunId).validate_python(run_id)
        except ValueError as error:
            raise ContinuationRejected("invalid continuation Run identity") from error

    def _record_names(self, prefix: Literal["receipt", "admission"]) -> tuple[str, ...]:
        with self._directory() as directory:
            names = tuple(sorted(name for name in os.listdir(directory) if name.startswith(prefix)))
        for name in names:
            if name == f"{prefix}.json":
                continue
            if not name.startswith(f"{prefix}-") or not name.endswith(".json"):
                raise ContinuationRejected("unknown continuation record filename")
            self._checked_run(name[len(prefix) + 1 : -5])
        return names

    def _validate_predecessor(self, record: ExecutionInterruptionReceipt) -> None:
        if record.schema_version == "v1":
            return
        prior = self.admission_for_run(record.request.run_id)
        if record.previous_admission_sha256 is None:
            if prior is not None:
                raise ContinuationRejected("replacement interruption must bind its admission")
            return
        if (
            prior is None
            or prior.schema_version != record.schema_version
            or prior.admission_sha256 != record.previous_admission_sha256
            or prior.new_request != record.request
            or prior.next_work_item_id != record.original_work_item_id
            or prior.next_lease_id != record.claim_lease_id
            or prior.created_at > record.created_at
        ):
            raise ContinuationRejected("interruption does not bind the exact preceding admission")

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
            or record.schema_version != receipt.schema_version
            or record.receipt_sha256 != receipt.receipt_sha256
            or record.policy_sha256 != receipt.policy_sha256
            or record.created_at < receipt.created_at
            or record.new_request.context_manifest_id == receipt.request.context_manifest_id
            or record.next_work_item_id == receipt.original_work_item_id
            or record.next_lease_id == receipt.claim_lease_id
            or not same_continuation_inputs(
                record.new_request, receipt.request, cause=receipt.cause
            )
            or (
                record.schema_version == "v2"
                and record.interrupted_attempt != receipt.request.attempt
            )
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

    def _put[R: _Record](self, name: str, record: R, model: type[R]) -> R:
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
