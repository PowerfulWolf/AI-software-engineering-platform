"""Sealed Operation cleanup; partial histories are never parsed on restart."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.multi_directory.purge import PurgeFile
from ai_software_engineer.safe_files import _read_regular, _reject_symlinks

from .models import ConsoleOperation, ConsoleOperationStatus
from .summary_models import OperationSummary

MAX_CLEANUP_BYTES = 32 * 1024 * 1024


class ConsoleDeletionCleanup(DomainModel):
    kind: Literal["console_deletion_cleanup"] = "console_deletion_cleanup"
    team_id: str
    operations: tuple[ConsoleOperation, ...] = Field(min_length=1, max_length=2048)
    files: tuple[PurgeFile, ...] = Field(max_length=100_000)
    directories: tuple[tuple[Literal["operations", "preparations"], str], ...]
    cleanup_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def exact_identity(self) -> Self:
        owner = OperationSummary.from_operation(self.operations[0])
        ids = {item.operation_id for item in self.operations}
        if len(ids) != len(self.operations) or owner.delivery_id is None:
            raise ValueError("cleanup requires unique Requirement Operations")
        for item in self.operations:
            item.validate_integrity()
            summary = OperationSummary.from_operation(item)
            if item.team_id != self.team_id or (summary.project_id, summary.delivery_id) != (
                owner.project_id,
                owner.delivery_id,
            ):
                raise ValueError("cleanup Operation scope differs")
            if not item.terminal and not (
                item.intent.action == "DELETE_REQUIREMENT"
                and item.status is ConsoleOperationStatus.RUNNING
            ):
                raise ValueError("cleanup Operation is still active")
        for scope, relative in (
            *self.directories,
            *((item.scope, item.path) for item in self.files),
        ):
            path = Path(relative)
            if (
                scope not in {"operations", "preparations"}
                or path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] not in ids
            ):
                raise ValueError("cleanup path scope differs")
        return self

    def recompute_sha256(self) -> str:
        return digest(self.model_dump(mode="json", exclude={"cleanup_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.cleanup_sha256 != self.recompute_sha256():
            raise ValueError("cleanup digest differs")


def pending_cleanups(root: Path, team_id: str) -> tuple[ConsoleDeletionCleanup, ...]:
    directory = root.parent / "console-deletion-pending"
    _reject_symlinks(directory)
    records = []
    paths = sorted(directory.glob("*.json"))
    if len(paths) > 64:
        raise ValueError("cleanup pending limit exceeded")
    seen: set[str] = set()
    for path in paths:
        record = ConsoleDeletionCleanup.model_validate_json(_read_regular(path, MAX_CLEANUP_BYTES))
        record.validate_integrity()
        ids = {item.operation_id for item in record.operations}
        if record.team_id != team_id or path.stem != record.cleanup_sha256 or ids & seen:
            raise ValueError("cleanup pending identity differs")
        seen.update(ids)
        records.append(record)
    return tuple(records)


def execute_cleanup(root: Path, record: ConsoleDeletionCleanup) -> None:
    from ai_software_engineer.multi_directory.purge import (
        _file_sha,
        _regular_files,
        _rmdir_sealed,
        _unlink_sealed,
    )

    record.validate_integrity()
    bases: dict[Literal["operations", "preparations"], Path] = {
        "operations": root,
        "preparations": root.parent / "console-preparation-progress",
    }
    expected = {(item.scope, item.path): item for item in record.files}
    # Validate all surviving bytes and reject additions before any mutation.
    for operation in record.operations:
        for scope, base in bases.items():
            directory = base / operation.operation_id
            _reject_symlinks(directory)
            if not directory.exists():
                continue
            for path in _regular_files(directory):
                item = expected.get((scope, path.relative_to(base).as_posix()))
                if item is None or _file_sha(path) != (item.size, item.sha256):
                    raise ValueError("cleanup Operation bytes changed")
    for item in record.files:
        if item.scope == "operations":
            base = bases["operations"]
        elif item.scope == "preparations":
            base = bases["preparations"]
        else:
            raise ValueError("cleanup scope differs")
        _unlink_sealed(base, item)
    for scope, relative in sorted(
        record.directories, key=lambda item: len(Path(item[1]).parts), reverse=True
    ):
        _rmdir_sealed(bases[scope], relative)
    pending = root.parent / "console-deletion-pending" / (record.cleanup_sha256 + ".json")
    pending.unlink()
