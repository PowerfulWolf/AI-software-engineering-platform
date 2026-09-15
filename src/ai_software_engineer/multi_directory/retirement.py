"""Digest-bound current visibility for immutable Requirement journals."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId, Sha256
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.multi_directory.store import JointJournal

RetirementReason = Literal["deleted", "replaced"]
_MAX_RETIREMENT_BYTES = 256_000


class RequirementRetirementError(RuntimeError):
    """Raised when the current Requirement visibility record is unsafe."""


class RequirementRetirementEntry(DomainModel):
    delivery_id: DeliveryId
    checkpoint_sha256: Sha256
    reason: RetirementReason
    replacement_delivery_id: DeliveryId | None = None
    retired_at: AwareDatetime

    @model_validator(mode="after")
    def validate_replacement(self) -> Self:
        if (self.reason == "replaced") != (self.replacement_delivery_id is not None):
            raise ValueError("Requirement replacement identity does not match retirement reason")
        if self.replacement_delivery_id == self.delivery_id:
            raise ValueError("Requirement cannot replace itself")
        return self


class RequirementRetirement(DomainModel):
    """Project-owned exclusions without erasing immutable Requirement history."""

    schema_version: Literal["v0.1"] = "v0.1"
    team_id: TeamId
    team_manifest_sha256: Sha256
    project_id: ProjectId
    project_manifest_sha256: Sha256
    entries: Annotated[tuple[RequirementRetirementEntry, ...], Field(max_length=1_024)] = ()
    retirement_sha256: Sha256

    @model_validator(mode="after")
    def validate_entries(self) -> Self:
        identities = tuple(entry.delivery_id for entry in self.entries)
        if identities != tuple(sorted(identities)) or len(set(identities)) != len(identities):
            raise ValueError("retired Requirement IDs must be unique and sorted")
        return self

    @classmethod
    def seal(cls, **values: object) -> RequirementRetirement:
        provisional = cls.model_validate({**values, "retirement_sha256": "0" * 64})
        return provisional.model_copy(update={"retirement_sha256": provisional.recompute_digest()})

    def recompute_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"retirement_sha256"})
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate_integrity(self) -> None:
        if self.retirement_sha256 != self.recompute_digest():
            raise RequirementRetirementError("Requirement retirement digest mismatch")


class RequirementRetirementStore:
    """Atomically maintain the current set of retired Requirement journals."""

    def __init__(
        self,
        root: Path,
        *,
        team_id: str,
        team_manifest_sha256: str,
        project_id: str,
        project_manifest_sha256: str,
        read_only: bool = False,
    ) -> None:
        self.root = root.absolute()
        self.team_id = team_id
        self.team_manifest_sha256 = team_manifest_sha256
        self.project_id = project_id
        self.project_manifest_sha256 = project_manifest_sha256
        self._read_only = read_only
        _no_symlinks(self.root)
        if read_only:
            if not self.root.is_dir():
                raise RequirementRetirementError("Requirement workspace is missing")
        else:
            self.root.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self.root / "retirement.json"

    def retirement(self) -> RequirementRetirement:
        record = self._read()
        record.validate_integrity()
        if (
            record.team_id != self.team_id
            or record.team_manifest_sha256 != self.team_manifest_sha256
            or record.project_id != self.project_id
            or record.project_manifest_sha256 != self.project_manifest_sha256
        ):
            raise RequirementRetirementError("Requirement retirement owner mismatch")
        return record

    def retired_delivery_ids(self, journal: JointJournal) -> frozenset[str]:
        record = self.retirement()
        for entry in record.entries:
            checkpoint = journal.current(entry.delivery_id)
            if checkpoint is None or checkpoint.checkpoint_sha256 != entry.checkpoint_sha256:
                raise RequirementRetirementError(
                    "Requirement retirement does not match immutable journal"
                )
            if (
                checkpoint.team_id != self.team_id
                or checkpoint.team_manifest_sha256 != self.team_manifest_sha256
                or checkpoint.project_id != self.project_id
                or checkpoint.project_manifest_sha256 != self.project_manifest_sha256
            ):
                raise RequirementRetirementError("retired Requirement owner mismatch")
            if entry.replacement_delivery_id is not None:
                replacement = journal.current(entry.replacement_delivery_id)
                if replacement is None:
                    raise RequirementRetirementError("Requirement replacement journal is missing")
                try:
                    self._validate_checkpoint_owner(replacement)
                except RequirementRetirementError as error:
                    raise RequirementRetirementError(
                        "Requirement replacement owner mismatch"
                    ) from error
        return frozenset(entry.delivery_id for entry in record.entries)

    def entry(self, delivery_id: str) -> RequirementRetirementEntry | None:
        return next(
            (item for item in self.retirement().entries if item.delivery_id == delivery_id),
            None,
        )

    def retire(
        self,
        checkpoint: JointCheckpoint,
        *,
        reason: RetirementReason,
        retired_at: AwareDatetime,
        replacement_delivery_id: str | None = None,
    ) -> RequirementRetirement:
        if self._read_only:
            raise RequirementRetirementError("Requirement retirement store is read-only")
        self._validate_checkpoint_owner(checkpoint)
        candidate = RequirementRetirementEntry(
            delivery_id=checkpoint.delivery_id,
            checkpoint_sha256=checkpoint.checkpoint_sha256,
            reason=reason,
            replacement_delivery_id=replacement_delivery_id,
            retired_at=retired_at,
        )
        with self._lock():
            current = self.retirement()
            existing = next(
                (item for item in current.entries if item.delivery_id == checkpoint.delivery_id),
                None,
            )
            if existing is not None:
                if (
                    existing.checkpoint_sha256 == candidate.checkpoint_sha256
                    and existing.reason == candidate.reason
                    and existing.replacement_delivery_id == candidate.replacement_delivery_id
                ):
                    return current
                raise RequirementRetirementError("Requirement was already retired differently")
            return self._write((*current.entries, candidate))

    def restore(self, delivery_id: str) -> RequirementRetirement:
        if self._read_only:
            raise RequirementRetirementError("Requirement retirement store is read-only")
        with self._lock():
            current = self.retirement()
            if all(item.delivery_id != delivery_id for item in current.entries):
                return current
            return self._write(
                tuple(item for item in current.entries if item.delivery_id != delivery_id)
            )

    def _validate_checkpoint_owner(self, checkpoint: JointCheckpoint) -> None:
        if (
            checkpoint.team_id != self.team_id
            or checkpoint.team_manifest_sha256 != self.team_manifest_sha256
            or checkpoint.project_id != self.project_id
            or checkpoint.project_manifest_sha256 != self.project_manifest_sha256
        ):
            raise RequirementRetirementError("Requirement belongs to another Team or Project")

    def _new(self, entries: tuple[RequirementRetirementEntry, ...]) -> RequirementRetirement:
        return RequirementRetirement.seal(
            team_id=self.team_id,
            team_manifest_sha256=self.team_manifest_sha256,
            project_id=self.project_id,
            project_manifest_sha256=self.project_manifest_sha256,
            entries=tuple(sorted(entries, key=lambda item: item.delivery_id)),
        )

    def _read(self) -> RequirementRetirement:
        if not self.path.exists():
            return self._new(())
        _no_symlinks(self.path)
        try:
            data = self.path.read_bytes()
            if len(data) > _MAX_RETIREMENT_BYTES:
                raise RequirementRetirementError("Requirement retirement record is too large")
            return RequirementRetirement.model_validate_json(data)
        except (OSError, ValueError) as error:
            raise RequirementRetirementError("Requirement retirement record is invalid") from error

    def _write(self, entries: tuple[RequirementRetirementEntry, ...]) -> RequirementRetirement:
        record = self._new(entries)
        fd, temporary = tempfile.mkstemp(prefix=".retirement-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(record.model_dump_json(indent=2).encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return self.retirement()

    @contextmanager
    def _lock(self) -> Iterator[None]:
        lock_path = self.root / ".retirement.lock"
        _no_symlinks(lock_path)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)


def _no_symlinks(path: Path) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise RequirementRetirementError("Requirement retirement cannot traverse symlinks")


__all__ = [
    "RequirementRetirement",
    "RequirementRetirementEntry",
    "RequirementRetirementError",
    "RequirementRetirementStore",
]
