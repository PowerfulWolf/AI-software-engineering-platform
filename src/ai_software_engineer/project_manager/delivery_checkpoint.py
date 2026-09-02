"""Append-only checkpoints for the unified project-delivery entry point.

The journal stores references to authoritative Product, Design, Planning, Dispatch,
and Task records.  It deliberately does not duplicate those native records.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import (
    AwareDatetime,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from ai_software_engineer.domain.enums import TaskStatus
from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, WirePayload

DeliveryId = Annotated[str, StringConstraints(pattern=r"^delivery_[a-z0-9][a-z0-9_-]{2,95}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
CommitSha = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40,64}$")]
_DELIVERY_ID: Final[TypeAdapter[DeliveryId]] = TypeAdapter(DeliveryId)
_ENVELOPE_KEYS: Final = frozenset(("record", "sha256"))
_INTAKE_DIRECTORY: Final = "intakes"


class ProjectDeliveryIntake(DomainModel):
    """Immutable business input required to resume before Product has a native fact."""

    kind: Literal["project_delivery_intake"] = "project_delivery_intake"
    schema_version: Literal["v0.1"] = "v0.1"
    delivery_id: DeliveryId
    project_id: ProjectId
    project_root: NonEmptyStr
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    requirement: NonEmptyStr
    submitted_at: AwareDatetime
    intake_sha256: Sha256

    @field_validator("project_root")
    @classmethod
    def require_absolute_project_root(cls, value: str) -> str:
        if not Path(value).is_absolute() or any(ord(character) < 32 for character in value):
            raise ValueError("project_root must be absolute and contain no controls")
        return value

    @classmethod
    def create(cls, **values: object) -> ProjectDeliveryIntake:
        provisional = cls.model_validate({**values, "intake_sha256": "0" * 64})
        return provisional.model_copy(update={"intake_sha256": provisional.recompute_sha256()})

    def recompute_sha256(self) -> Sha256:
        payload = self.to_wire()
        payload.pop("intake_sha256", None)
        return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()

    def validate_integrity(self) -> None:
        if self.intake_sha256 != self.recompute_sha256():
            raise ProjectDeliveryCheckpointCorruption("intake digest does not match content")


class DeliveryStage(StrEnum):
    PREPARING = "PREPARING"
    PRODUCT_DISCOVERY = "PRODUCT_DISCOVERY"
    WAITING_PRODUCT_REPLY = "WAITING_PRODUCT_REPLY"
    WAITING_PRODUCT_APPROVAL = "WAITING_PRODUCT_APPROVAL"
    DESIGNING = "DESIGNING"
    PLANNING = "PLANNING"
    DISPATCHING = "DISPATCHING"
    DELIVERING = "DELIVERING"
    DONE = "DONE"
    WAITING_HUMAN = "WAITING_HUMAN"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class DeliveryNextAction(StrEnum):
    PREPARE_PROJECT = "PREPARE_PROJECT"
    CONTINUE_PRODUCT_DISCOVERY = "CONTINUE_PRODUCT_DISCOVERY"
    RECORD_PRODUCT_REPLY = "RECORD_PRODUCT_REPLY"
    APPROVE_PRODUCT_SPEC = "APPROVE_PRODUCT_SPEC"
    RUN_DESIGNER = "RUN_DESIGNER"
    RUN_PLANNER = "RUN_PLANNER"
    COMMIT_DISPATCH = "COMMIT_DISPATCH"
    RUN_DELIVERY = "RUN_DELIVERY"
    REQUEST_HUMAN = "REQUEST_HUMAN"
    RETRY_STAGE = "RETRY_STAGE"
    NONE = "NONE"


class DeliveryFailureCode(StrEnum):
    PROJECT_SPEC_CONFLICT = "PROJECT_SPEC_CONFLICT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"
    TRANSIENT_PROVIDER_FAILURE = "TRANSIENT_PROVIDER_FAILURE"
    INVALID_AGENT_OUTPUT = "INVALID_AGENT_OUTPUT"
    RETRY_BUDGET_EXHAUSTED = "RETRY_BUDGET_EXHAUSTED"
    CHECKPOINT_DRIFT = "CHECKPOINT_DRIFT"
    TASK_COLLISION = "TASK_COLLISION"
    WORKTREE_DRIFT = "WORKTREE_DRIFT"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"


class DeliveryStageAttempts(DomainModel):
    """Bounded attempt counters kept independently for every resumable stage."""

    preparing: int = Field(default=0, ge=0, le=100)
    product_discovery: int = Field(default=0, ge=0, le=100)
    designing: int = Field(default=0, ge=0, le=100)
    planning: int = Field(default=0, ge=0, le=100)
    dispatching: int = Field(default=0, ge=0, le=100)
    delivering: int = Field(default=0, ge=0, le=100)

    def increment(self, stage: DeliveryStage) -> DeliveryStageAttempts:
        field = {
            DeliveryStage.PREPARING: "preparing",
            DeliveryStage.PRODUCT_DISCOVERY: "product_discovery",
            DeliveryStage.DESIGNING: "designing",
            DeliveryStage.PLANNING: "planning",
            DeliveryStage.DISPATCHING: "dispatching",
            DeliveryStage.DELIVERING: "delivering",
        }.get(stage)
        if field is None:
            raise ValueError(f"stage does not have an attempt budget: {stage.value}")
        return self.model_copy(update={field: getattr(self, field) + 1})

    def for_stage(self, stage: DeliveryStage) -> int:
        field = {
            DeliveryStage.PREPARING: "preparing",
            DeliveryStage.PRODUCT_DISCOVERY: "product_discovery",
            DeliveryStage.DESIGNING: "designing",
            DeliveryStage.PLANNING: "planning",
            DeliveryStage.DISPATCHING: "dispatching",
            DeliveryStage.DELIVERING: "delivering",
        }.get(stage)
        return 0 if field is None else int(getattr(self, field))


class ProjectDeliveryCheckpoint(DomainModel):
    """One immutable delivery cursor containing only verified native fact references."""

    kind: str = "project_delivery_checkpoint"
    schema_version: str = "v0.1"
    delivery_id: DeliveryId
    sequence: int = Field(ge=1)
    previous_checkpoint_sha256: Sha256 | None = None
    project_id: ProjectId
    project_root: NonEmptyStr
    preparation_sha256: Sha256 | None = None
    request_id: str | None = None
    request_revision: int | None = Field(default=None, ge=1)
    product_checkpoint_sha256: Sha256 | None = None
    product_spec_id: str | None = None
    product_spec_sha256: Sha256 | None = None
    approval_id: str | None = None
    approval_sha256: Sha256 | None = None
    technical_design_id: str | None = None
    technical_design_sha256: Sha256 | None = None
    execution_plan_id: str | None = None
    execution_plan_sha256: Sha256 | None = None
    planning_preview_id: str | None = None
    planning_preview_sha256: Sha256 | None = None
    dispatch_commit_id: str | None = None
    dispatch_commit_sha256: Sha256 | None = None
    task_id: str | None = None
    task_revision: int | None = Field(default=None, ge=0)
    task_status: TaskStatus | None = None
    candidate_revision: CommitSha | None = None
    stage: DeliveryStage
    stage_attempts: DeliveryStageAttempts
    next_action: DeliveryNextAction
    failure_code: DeliveryFailureCode | None = None
    failure_summary: str | None = Field(default=None, max_length=500)
    checkpointed_at: AwareDatetime
    checkpoint_sha256: Sha256

    @field_validator("project_root")
    @classmethod
    def require_absolute_project_root(cls, value: str) -> str:
        if not Path(value).is_absolute() or any(ord(character) < 32 for character in value):
            raise ValueError("project_root must be absolute and contain no controls")
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.sequence == 1 and self.previous_checkpoint_sha256 is not None:
            raise ValueError("first checkpoint cannot have a predecessor")
        if self.sequence > 1 and self.previous_checkpoint_sha256 is None:
            raise ValueError("later checkpoint requires a predecessor")
        self._require_group(
            "Product discovery reference",
            self.request_id,
            self.request_revision,
            self.product_checkpoint_sha256,
        )
        if self.request_id is not None and self.preparation_sha256 is None:
            raise ValueError("Product discovery requires a preparation reference")
        self._require_pair(
            "product specification reference",
            self.product_spec_id,
            self.product_spec_sha256,
        )
        self._require_pair("approval reference", self.approval_id, self.approval_sha256)
        self._require_pair(
            "technical design reference",
            self.technical_design_id,
            self.technical_design_sha256,
        )
        self._require_pair(
            "execution plan reference",
            self.execution_plan_id,
            self.execution_plan_sha256,
        )
        self._require_pair(
            "planning preview reference",
            self.planning_preview_id,
            self.planning_preview_sha256,
        )
        self._require_pair(
            "dispatch commit reference",
            self.dispatch_commit_id,
            self.dispatch_commit_sha256,
        )
        self._require_group("Task reference", self.task_id, self.task_revision, self.task_status)
        if self.approval_id is not None and self.product_spec_id is None:
            raise ValueError("approval requires a product specification reference")
        if self.technical_design_id is not None and self.approval_id is None:
            raise ValueError("technical design requires approval")
        if self.execution_plan_id is not None and self.technical_design_id is None:
            raise ValueError("execution plan requires technical design")
        if self.planning_preview_id is not None and self.execution_plan_id is None:
            raise ValueError("planning preview requires execution plan")
        if self.dispatch_commit_id is not None and self.planning_preview_id is None:
            raise ValueError("dispatch commit requires planning preview")
        if self.task_id is not None and self.dispatch_commit_id is None:
            raise ValueError("Task reference requires dispatch commit")
        if self.candidate_revision is not None and self.task_id is None:
            raise ValueError("candidate revision requires Task reference")
        if self.stage is DeliveryStage.DELIVERING and self.dispatch_commit_id is None:
            raise ValueError("DELIVERING requires a dispatch commit")
        if self.stage is DeliveryStage.DONE and (
            self.task_status is not TaskStatus.DONE or self.candidate_revision is None
        ):
            raise ValueError("DONE requires a DONE Task and candidate revision")
        terminal_failure = self.stage in {
            DeliveryStage.WAITING_HUMAN,
            DeliveryStage.BLOCKED,
            DeliveryStage.FAILED,
        }
        if terminal_failure != (self.failure_code is not None and self.failure_summary is not None):
            raise ValueError("failure details are required only for failure/wait stages")
        if self.stage is DeliveryStage.DONE and self.next_action is not DeliveryNextAction.NONE:
            raise ValueError("DONE has no next action")
        return self

    @staticmethod
    def _require_pair(label: str, left: object, right: object) -> None:
        if (left is None) != (right is None):
            raise ValueError(f"{label} must be complete")

    @staticmethod
    def _require_group(label: str, *values: object) -> None:
        present = tuple(value is not None for value in values)
        if any(present) and not all(present):
            raise ValueError(f"{label} must be complete")

    @classmethod
    def create(cls, **values: object) -> ProjectDeliveryCheckpoint:
        provisional = cls.model_validate({**values, "checkpoint_sha256": "0" * 64})
        return provisional.model_copy(update={"checkpoint_sha256": provisional.recompute_sha256()})

    def recompute_sha256(self) -> Sha256:
        payload = self.to_wire()
        payload.pop("checkpoint_sha256", None)
        return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()

    def validate_integrity(self) -> None:
        if self.checkpoint_sha256 != self.recompute_sha256():
            raise ProjectDeliveryCheckpointCorruption("checkpoint digest does not match content")


class ProjectDeliveryCheckpointError(RuntimeError):
    """Base error for the unified-delivery journal."""


class ProjectDeliveryCheckpointNotFound(ProjectDeliveryCheckpointError):
    pass


class ProjectDeliveryCheckpointConflict(ProjectDeliveryCheckpointError):
    pass


class ProjectDeliveryCheckpointCorruption(ProjectDeliveryCheckpointError):
    pass


class ProjectDeliveryCheckpointPathError(ProjectDeliveryCheckpointError):
    pass


class FileProjectDeliveryCheckpointStore:
    """Filesystem append-only journal with contiguous hash-chain verification."""

    def __init__(self, root: str | Path) -> None:
        configured = Path(root).expanduser()
        if configured.is_symlink():
            raise ProjectDeliveryCheckpointPathError("checkpoint root cannot be a symlink")
        self._root = configured.resolve(strict=False)
        self._root.mkdir(parents=True, exist_ok=True)
        self._require_root()
        root_stat = self._root.lstat()
        self._root_identity = (root_stat.st_dev, root_stat.st_ino)
        self._intake_root = self._root / _INTAKE_DIRECTORY
        self._intake_root.mkdir(exist_ok=True)
        self._require_intake_root()
        intake_stat = self._intake_root.lstat()
        self._intake_root_identity = (intake_stat.st_dev, intake_stat.st_ino)

    def put_intake(self, intake: ProjectDeliveryIntake) -> ProjectDeliveryIntake:
        """Exact-create one durable start command without changing checkpoint ordering."""
        intake.validate_integrity()
        self._require_intake_root()
        target = self._intake_root / f"{intake.delivery_id}.json"
        if target.exists() or target.is_symlink():
            existing = self.get_intake(intake.delivery_id)
            if existing != intake:
                raise ProjectDeliveryCheckpointConflict("delivery intake has different content")
            return existing
        envelope: WirePayload = {"record": intake.to_wire(), "sha256": _digest(intake.to_wire())}
        if not _publish_exclusive(
            self._intake_root,
            self._intake_root_identity,
            target,
            envelope,
        ):
            existing = self.get_intake(intake.delivery_id)
            if existing != intake:
                raise ProjectDeliveryCheckpointConflict("delivery intake has different content")
            return existing
        return self.get_intake(intake.delivery_id)

    def get_intake(self, delivery_id: DeliveryId | str) -> ProjectDeliveryIntake:
        self._require_intake_root()
        try:
            identity = _DELIVERY_ID.validate_python(delivery_id)
        except ValidationError as error:
            raise ProjectDeliveryCheckpointNotFound(str(delivery_id)) from error
        target = self._intake_root / f"{identity}.json"
        if target.is_symlink() or not target.is_file():
            raise ProjectDeliveryCheckpointNotFound(f"delivery intake: {identity}")
        self._require_root()
        _require_regular_below(self._intake_root, target)
        try:
            payload: object = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != _ENVELOPE_KEYS:
                raise ProjectDeliveryCheckpointCorruption("intake envelope is invalid")
            wire = payload.get("record")
            digest = payload.get("sha256")
            if not isinstance(wire, dict) or not isinstance(digest, str) or digest != _digest(wire):
                raise ProjectDeliveryCheckpointCorruption("intake envelope digest mismatch")
            intake = ProjectDeliveryIntake.model_validate(wire)
            intake.validate_integrity()
        except ProjectDeliveryCheckpointCorruption:
            raise
        except (OSError, UnicodeError, ValueError, ValidationError) as error:
            raise ProjectDeliveryCheckpointCorruption("cannot decode delivery intake") from error
        if intake.delivery_id != identity:
            raise ProjectDeliveryCheckpointCorruption("intake filename identity mismatch")
        return intake

    def put(self, checkpoint: ProjectDeliveryCheckpoint) -> ProjectDeliveryCheckpoint:
        checkpoint.validate_integrity()
        directory = self._delivery_directory(checkpoint.delivery_id, create=True)
        assert directory is not None
        target = directory / f"{checkpoint.sequence:010d}.json"
        if target.exists() or target.is_symlink():
            existing = self.get(checkpoint.delivery_id, checkpoint.sequence)
            if existing != checkpoint:
                raise ProjectDeliveryCheckpointConflict("checkpoint identity has different content")
            return existing
        history = self.list(checkpoint.delivery_id)
        if checkpoint.sequence != len(history) + 1:
            raise ProjectDeliveryCheckpointConflict("checkpoint is not the next sequence")
        expected_previous = history[-1].checkpoint_sha256 if history else None
        if checkpoint.previous_checkpoint_sha256 != expected_previous:
            raise ProjectDeliveryCheckpointConflict("checkpoint predecessor does not match")
        envelope: WirePayload = {
            "record": checkpoint.to_wire(),
            "sha256": _digest(checkpoint.to_wire()),
        }
        if not _publish_exclusive(self._root, self._root_identity, target, envelope):
            existing = self.get(checkpoint.delivery_id, checkpoint.sequence)
            if existing != checkpoint:
                raise ProjectDeliveryCheckpointConflict("checkpoint identity has different content")
            return existing
        return self.get(checkpoint.delivery_id, checkpoint.sequence)

    def get(self, delivery_id: DeliveryId | str, sequence: int) -> ProjectDeliveryCheckpoint:
        if type(sequence) is not int or sequence < 1:
            raise ProjectDeliveryCheckpointNotFound(str(delivery_id))
        directory = self._delivery_directory(delivery_id, create=False)
        assert directory is not None
        target = directory / f"{sequence:010d}.json"
        if target.is_symlink() or not target.is_file():
            raise ProjectDeliveryCheckpointNotFound(f"{delivery_id}:{sequence}")
        return self._read(target, delivery_id, sequence)

    def current(self, delivery_id: DeliveryId | str) -> ProjectDeliveryCheckpoint:
        records = self.list(delivery_id)
        if not records:
            raise ProjectDeliveryCheckpointNotFound(str(delivery_id))
        return records[-1]

    def list(self, delivery_id: DeliveryId | str) -> tuple[ProjectDeliveryCheckpoint, ...]:
        directory = self._delivery_directory(delivery_id, create=False, missing_ok=True)
        if directory is None:
            return ()
        try:
            paths = sorted(directory.iterdir())
        except OSError as error:
            raise ProjectDeliveryCheckpointPathError("cannot list delivery checkpoints") from error
        expected_names = [f"{index:010d}.json" for index in range(1, len(paths) + 1)]
        if [path.name for path in paths] != expected_names:
            raise ProjectDeliveryCheckpointCorruption("checkpoint sequence is not contiguous")
        records = tuple(
            self._read(path, delivery_id, index) for index, path in enumerate(paths, start=1)
        )
        previous: str | None = None
        for record in records:
            if record.previous_checkpoint_sha256 != previous:
                raise ProjectDeliveryCheckpointCorruption("checkpoint hash chain is broken")
            previous = record.checkpoint_sha256
        return records

    def _read(
        self, target: Path, delivery_id: DeliveryId | str, sequence: int
    ) -> ProjectDeliveryCheckpoint:
        self._require_root()
        _require_regular_below(self._root, target)
        try:
            payload: object = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != _ENVELOPE_KEYS:
                raise ProjectDeliveryCheckpointCorruption("checkpoint envelope is invalid")
            wire = payload.get("record")
            digest = payload.get("sha256")
            if not isinstance(wire, dict) or not isinstance(digest, str) or digest != _digest(wire):
                raise ProjectDeliveryCheckpointCorruption("checkpoint envelope digest mismatch")
            record = ProjectDeliveryCheckpoint.model_validate(wire)
            record.validate_integrity()
        except ProjectDeliveryCheckpointCorruption:
            raise
        except (OSError, UnicodeError, ValueError, ValidationError) as error:
            raise ProjectDeliveryCheckpointCorruption("cannot decode checkpoint") from error
        if record.delivery_id != delivery_id or record.sequence != sequence:
            raise ProjectDeliveryCheckpointCorruption("checkpoint filename identity mismatch")
        return record

    def _delivery_directory(
        self,
        delivery_id: DeliveryId | str,
        *,
        create: bool,
        missing_ok: bool = False,
    ) -> Path | None:
        self._require_root()
        try:
            identity = _DELIVERY_ID.validate_python(delivery_id)
        except ValidationError as error:
            raise ProjectDeliveryCheckpointNotFound(str(delivery_id)) from error
        directory = self._root / identity
        if create:
            directory.mkdir(exist_ok=True)
        if not directory.exists():
            if missing_ok:
                return None
            raise ProjectDeliveryCheckpointNotFound(identity)
        if directory.is_symlink() or not directory.is_dir():
            raise ProjectDeliveryCheckpointPathError("delivery checkpoint directory is unsafe")
        _require_below(self._root, directory)
        return directory

    def _require_root(self) -> None:
        if self._root.is_symlink() or not self._root.is_dir() or self._root.resolve() != self._root:
            raise ProjectDeliveryCheckpointPathError("checkpoint root is no longer trusted")
        if hasattr(self, "_root_identity"):
            current = self._root.lstat()
            if (current.st_dev, current.st_ino) != self._root_identity:
                raise ProjectDeliveryCheckpointPathError("checkpoint root identity changed")

    def _require_intake_root(self) -> None:
        if (
            self._intake_root.is_symlink()
            or not self._intake_root.is_dir()
            or self._intake_root.resolve() != self._intake_root
        ):
            raise ProjectDeliveryCheckpointPathError("delivery intake root is unsafe")
        _require_below(self._root, self._intake_root)
        if hasattr(self, "_intake_root_identity"):
            current = self._intake_root.lstat()
            if (current.st_dev, current.st_ino) != self._intake_root_identity:
                raise ProjectDeliveryCheckpointPathError("delivery intake root identity changed")


def _digest(payload: WirePayload) -> str:
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _canonical_json(payload: WirePayload) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _require_below(root: Path, path: Path) -> None:
    try:
        path.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as error:
        raise ProjectDeliveryCheckpointPathError("checkpoint path escapes its root") from error


def _require_regular_below(root: Path, path: Path) -> None:
    _require_below(root, path)
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode):
        raise ProjectDeliveryCheckpointPathError("checkpoint path is not a regular file")


def _publish_exclusive(
    root: Path,
    root_identity: tuple[int, int],
    target: Path,
    payload: WirePayload,
) -> bool:
    temporary = root / f".checkpoint-{secrets.token_hex(12)}.tmp"
    try:
        current = root.lstat()
        if (current.st_dev, current.st_ino) != root_identity:
            raise ProjectDeliveryCheckpointPathError("checkpoint root identity changed")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(temporary, flags, 0o600)
        try:
            data = _canonical_json(payload).encode()
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short write while publishing checkpoint")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError:
            return False
        directory_descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        return True
    except ProjectDeliveryCheckpointPathError:
        raise
    except OSError as error:
        raise ProjectDeliveryCheckpointError("cannot publish checkpoint") from error
    finally:
        with suppress(OSError):
            temporary.unlink()


__all__ = [
    "DeliveryFailureCode",
    "DeliveryId",
    "DeliveryNextAction",
    "DeliveryStage",
    "DeliveryStageAttempts",
    "FileProjectDeliveryCheckpointStore",
    "ProjectDeliveryCheckpoint",
    "ProjectDeliveryCheckpointConflict",
    "ProjectDeliveryCheckpointCorruption",
    "ProjectDeliveryCheckpointError",
    "ProjectDeliveryCheckpointNotFound",
    "ProjectDeliveryCheckpointPathError",
    "ProjectDeliveryIntake",
]
