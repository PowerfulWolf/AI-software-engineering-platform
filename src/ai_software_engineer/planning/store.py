"""Append-only durable ExecutionPlan store for project sidecars."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import JsonValue
from ai_software_engineer.domain.project_delivery import (
    ExecutionPlan,
    ExecutionPlanId,
    StageContractError,
)
from ai_software_engineer.planning.models import PlannerCommitCheckpoint, PlannerRunRecord

_PLAN_ID = TypeAdapter(ExecutionPlanId)
_RUN_ID = TypeAdapter(RunId)
_RecordT = TypeVar("_RecordT", PlannerRunRecord, PlannerCommitCheckpoint)


class ExecutionPlanStoreError(RuntimeError):
    """Base error for durable ExecutionPlan records."""


class ExecutionPlanNotFound(ExecutionPlanStoreError):
    """Raised when an exact plan identity is absent."""


class ExecutionPlanConflict(ExecutionPlanStoreError):
    """Raised when one immutable plan identity is reused with changed content."""


class ExecutionPlanCorruption(ExecutionPlanStoreError):
    """Raised when persisted plan bytes or integrity cannot be trusted."""


class ExecutionPlanPathError(ExecutionPlanStoreError):
    """Raised when the plan store path leaves its trusted sidecar root."""


class ExecutionPlanStore(Protocol):
    def put_execution_plan(self, plan: ExecutionPlan) -> ExecutionPlan: ...

    def get_execution_plan(self, plan_id: ExecutionPlanId | str) -> ExecutionPlan: ...

    def find_for_request(self, request_id: str) -> ExecutionPlan | None: ...

    def put_run(self, record: PlannerRunRecord) -> PlannerRunRecord: ...

    def get_run(self, run_id: RunId | str) -> PlannerRunRecord: ...

    def find_run(self, run_id: RunId | str) -> PlannerRunRecord | None: ...

    def put_checkpoint(self, checkpoint: PlannerCommitCheckpoint) -> PlannerCommitCheckpoint: ...

    def get_checkpoint(self, run_id: RunId | str) -> PlannerCommitCheckpoint: ...

    def find_checkpoint(self, run_id: RunId | str) -> PlannerCommitCheckpoint | None: ...


class FileExecutionPlanStore:
    """Publish canonical plans exclusively; exact replay returns the first record."""

    def __init__(self, root: str | Path) -> None:
        configured = Path(root).expanduser()
        if configured.is_symlink():
            raise ExecutionPlanPathError("ExecutionPlan store root cannot be a symlink")
        self._root = configured.resolve(strict=False)
        self._root.mkdir(parents=True, exist_ok=True)
        self._require_root()
        root_stat = self._root.lstat()
        self._root_identity = (root_stat.st_dev, root_stat.st_ino)

    def put_execution_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        _validate_plan(plan)
        target = self._path("execution-plans", plan.id)
        if target.exists() or target.is_symlink():
            return self._require_exact(target, plan)
        wire = plan.to_wire()
        envelope: dict[str, JsonValue] = {"record": wire, "sha256": _digest(wire)}
        if not _publish_exclusive(self._root, self._root_identity, target, envelope):
            return self._require_exact(target, plan)
        return self.get_execution_plan(plan.id)

    def get_execution_plan(self, plan_id: ExecutionPlanId | str) -> ExecutionPlan:
        try:
            identity = _PLAN_ID.validate_python(plan_id)
        except ValidationError as error:
            raise ExecutionPlanNotFound(f"invalid ExecutionPlan identity: {plan_id}") from error
        target = self._path("execution-plans", identity, create=False)
        if not target.exists():
            raise ExecutionPlanNotFound(f"ExecutionPlan not found: {identity}")
        if target.is_symlink() or not target.is_file():
            raise ExecutionPlanPathError(f"untrusted ExecutionPlan path: {target}")
        self._require_path(target)
        try:
            payload: object = json.loads(
                _read_trusted_text(self._root, self._root_identity, target),
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON value: {value}")
                ),
            )
            if not isinstance(payload, dict) or set(payload) != {"record", "sha256"}:
                raise ExecutionPlanCorruption("ExecutionPlan envelope is invalid")
            wire = payload["record"]
            digest = payload["sha256"]
            if not isinstance(wire, dict) or not isinstance(digest, str):
                raise ExecutionPlanCorruption("ExecutionPlan envelope is incomplete")
            if digest != _digest(wire):
                raise ExecutionPlanCorruption("ExecutionPlan envelope digest mismatch")
            plan = ExecutionPlan.model_validate(wire)
            _validate_plan(plan)
            if plan.id != identity:
                raise ExecutionPlanCorruption("ExecutionPlan filename identity mismatch")
            return plan
        except ExecutionPlanCorruption:
            raise
        except (OSError, UnicodeError, ValueError, ValidationError, StageContractError) as error:
            raise ExecutionPlanCorruption("cannot decode ExecutionPlan record") from error

    def find_for_request(self, request_id: str) -> ExecutionPlan | None:
        """Return the latest contiguous plan revision, or fail on ambiguous history."""
        directory = self._root / "execution-plans"
        if not directory.exists():
            return None
        if directory.is_symlink() or not directory.is_dir():
            raise ExecutionPlanPathError(f"untrusted ExecutionPlan directory: {directory}")
        self._require_path(directory)
        plans = tuple(
            plan
            for path in sorted(directory.glob("*.json"))
            for plan in (self.get_execution_plan(path.stem),)
            if plan.request_id == request_id
        )
        if not plans:
            return None
        versions = tuple(plan.version for plan in plans)
        if len(set(versions)) != len(versions):
            raise ExecutionPlanCorruption(
                f"ambiguous ExecutionPlan version history for request: {request_id}"
            )
        if set(versions) != set(range(1, max(versions) + 1)):
            raise ExecutionPlanCorruption(
                f"non-contiguous ExecutionPlan version history for request: {request_id}"
            )
        return max(plans, key=lambda plan: plan.version)

    def put_run(self, record: PlannerRunRecord) -> PlannerRunRecord:
        record.validate_integrity()
        return self._put_record("runs", record.run_id, record, PlannerRunRecord)

    def get_run(self, run_id: RunId | str) -> PlannerRunRecord:
        identity = _identity(_RUN_ID, run_id, "Planner run")
        record = self._get_record("runs", identity, PlannerRunRecord)
        if record.run_id != identity:
            raise ExecutionPlanCorruption("PlannerRunRecord filename identity mismatch")
        return record

    def find_run(self, run_id: RunId | str) -> PlannerRunRecord | None:
        try:
            return self.get_run(run_id)
        except ExecutionPlanNotFound:
            return None

    def put_checkpoint(self, checkpoint: PlannerCommitCheckpoint) -> PlannerCommitCheckpoint:
        checkpoint.validate_integrity()
        run = self.get_run(checkpoint.run_id)
        expected = PlannerCommitCheckpoint.create(run, committed_at=checkpoint.committed_at)
        if checkpoint != expected:
            raise ExecutionPlanCorruption(
                "PlannerCommitCheckpoint does not bind the exact durable PlannerRunRecord"
            )
        return self._put_record(
            "checkpoints",
            checkpoint.run_id,
            checkpoint,
            PlannerCommitCheckpoint,
        )

    def get_checkpoint(self, run_id: RunId | str) -> PlannerCommitCheckpoint:
        identity = _identity(_RUN_ID, run_id, "Planner run")
        record = self._get_record("checkpoints", identity, PlannerCommitCheckpoint)
        if record.run_id != identity:
            raise ExecutionPlanCorruption("PlannerCommitCheckpoint filename identity mismatch")
        try:
            run = self.get_run(identity)
        except ExecutionPlanNotFound as error:
            raise ExecutionPlanCorruption(
                "PlannerCommitCheckpoint has no durable PlannerRunRecord"
            ) from error
        expected = PlannerCommitCheckpoint.create(run, committed_at=record.committed_at)
        if record != expected:
            raise ExecutionPlanCorruption(
                "PlannerCommitCheckpoint does not bind the exact durable PlannerRunRecord"
            )
        return record

    def find_checkpoint(self, run_id: RunId | str) -> PlannerCommitCheckpoint | None:
        try:
            return self.get_checkpoint(run_id)
        except ExecutionPlanNotFound:
            return None

    def _require_exact(self, target: Path, plan: ExecutionPlan) -> ExecutionPlan:
        existing = self.get_execution_plan(plan.id)
        if existing.to_wire() != plan.to_wire():
            raise ExecutionPlanConflict(
                f"ExecutionPlan already exists with different content: {target.stem}"
            )
        return existing

    def _put_record(
        self,
        category: str,
        identity: str,
        record: _RecordT,
        model: type[_RecordT],
    ) -> _RecordT:
        target = self._path(category, identity)
        if target.exists() or target.is_symlink():
            existing = self._get_record(category, identity, model)
            if existing.to_wire() == record.to_wire():
                return existing
            raise ExecutionPlanConflict(f"Planner record conflict: {identity}")
        wire = record.to_wire()
        envelope: dict[str, JsonValue] = {"record": wire, "sha256": _digest(wire)}
        if not _publish_exclusive(self._root, self._root_identity, target, envelope):
            existing = self._get_record(category, identity, model)
            if existing.to_wire() == record.to_wire():
                return existing
            raise ExecutionPlanConflict(f"Planner record concurrently conflicted: {identity}")
        return self._get_record(category, identity, model)

    def _get_record(self, category: str, identity: str, model: type[_RecordT]) -> _RecordT:
        target = self._path(category, identity, create=False)
        try:
            payload: object = json.loads(
                _read_trusted_text(self._root, self._root_identity, target)
            )
            if not isinstance(payload, dict) or set(payload) != {"record", "sha256"}:
                raise ExecutionPlanCorruption("Planner record envelope is invalid")
            wire = payload["record"]
            digest = payload["sha256"]
            if not isinstance(wire, dict) or not isinstance(digest, str):
                raise ExecutionPlanCorruption("Planner record envelope is incomplete")
            if digest != _digest(wire):
                raise ExecutionPlanCorruption("Planner record envelope digest mismatch")
            record = model.model_validate(wire)
            validator = record.validate_integrity
            validator()
            return record
        except ExecutionPlanCorruption:
            raise
        except FileNotFoundError as error:
            raise ExecutionPlanNotFound(identity) from error
        except (OSError, UnicodeError, ValueError, ValidationError) as error:
            raise ExecutionPlanCorruption("cannot decode Planner record") from error

    def _path(self, category: str, identity: str, *, create: bool = True) -> Path:
        if category not in {"execution-plans", "runs", "checkpoints"}:
            raise ExecutionPlanPathError(f"unknown Planner record category: {category}")
        self._require_root()
        directory = self._root / category
        if create:
            directory.mkdir(exist_ok=True)
        if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
            raise ExecutionPlanPathError(f"untrusted ExecutionPlan directory: {directory}")
        self._require_path(directory)
        return directory / f"{identity}.json"

    def _require_root(self) -> None:
        if (
            self._root.is_symlink()
            or not self._root.is_dir()
            or self._root.resolve(strict=False) != self._root
        ):
            raise ExecutionPlanPathError("ExecutionPlan store root is no longer trusted")
        if hasattr(self, "_root_identity"):
            current = self._root.lstat()
            if (current.st_dev, current.st_ino) != self._root_identity:
                raise ExecutionPlanPathError("ExecutionPlan store root identity changed")

    def _require_path(self, path: Path) -> None:
        self._require_root()
        try:
            path.resolve(strict=False).relative_to(self._root)
        except ValueError as error:
            raise ExecutionPlanPathError("ExecutionPlan path escapes store root") from error


def _validate_plan(plan: ExecutionPlan) -> None:
    try:
        plan.validate_integrity()
    except (RuntimeError, ValueError) as error:
        raise ExecutionPlanCorruption("ExecutionPlan inner digest mismatch") from error


def _publish_exclusive(
    root: Path,
    root_identity: tuple[int, int],
    target: Path,
    payload: dict[str, JsonValue],
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
                    raise OSError("Planner record write made no progress")
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
            raise ExecutionPlanPathError("ExecutionPlan directory changed during publication")
        return True
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name, dir_fd=directory_fd)
        os.close(directory_fd)


def _identity[IdentityT](
    adapter: TypeAdapter[IdentityT], value: IdentityT | str, label: str
) -> IdentityT:
    try:
        return adapter.validate_python(value)
    except ValidationError as error:
        raise ExecutionPlanNotFound(f"invalid {label} identity: {value}") from error


def _relative_target(root: Path, target: Path) -> Path:
    try:
        return target.relative_to(root)
    except ValueError as error:
        raise ExecutionPlanPathError("Planner record path escapes store root") from error


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
            raise ExecutionPlanPathError("Planner store root identity changed")
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
            raise ExecutionPlanPathError("Planner record directory changed before read")
        record_fd = os.open(
            relative.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        before = os.fstat(record_fd)
        if not stat.S_ISREG(before.st_mode):
            raise ExecutionPlanPathError("Planner record is not a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(record_fd, 64 * 1024):
            chunks.append(chunk)
        after = os.fstat(record_fd)
        if not _same_file(before, after) or not _directory_fd_matches_path(
            directory_fd, target.parent
        ):
            raise ExecutionPlanPathError("Planner record changed during read")
        return b"".join(chunks).decode("utf-8")
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise ExecutionPlanPathError("Planner record path is untrusted") from error
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
    "ExecutionPlanConflict",
    "ExecutionPlanCorruption",
    "ExecutionPlanNotFound",
    "ExecutionPlanPathError",
    "ExecutionPlanStore",
    "ExecutionPlanStoreError",
    "FileExecutionPlanStore",
]
