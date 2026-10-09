"""Read-only regular-text mutation snapshots, distinct from legacy recovery captures."""

import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ai_software_engineer.git.capture import MAX_CAPTURE_BYTES
from ai_software_engineer.git.ports import WorktreeRef
from ai_software_engineer.redaction import source_secret_occurrences

RegularMode = Literal[0o644, 0o755]
MAX_MUTATION_BODY_BYTES = 2 * MAX_CAPTURE_BYTES


@dataclass(frozen=True, slots=True)
class MutationTextBody:
    text: str
    mode: RegularMode
    source_path: str | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        payload = self.text.encode("utf-8")
        if (
            self.mode not in (0o644, 0o755)
            or len(payload) > MAX_CAPTURE_BYTES
            or b"\0" in payload
            or source_secret_occurrences(self.text, source_path=self.source_path)
        ):
            raise ValueError("mutation body must be bounded nonsensitive regular UTF-8 text")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def size(self) -> int:
        return len(self.text.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class FileMutationCapture:
    path: str
    before: MutationTextBody | None
    after: MutationTextBody | None

    def __post_init__(self) -> None:
        if (self.before is None and self.after is None) or self.before == self.after:
            raise ValueError("mutation must bind distinct before/after file facts")


@dataclass(frozen=True, slots=True)
class WorktreeMutationCapture:
    worktree: WorktreeRef
    patch: bytes
    index_diff_sha256: str
    mutations: tuple[FileMutationCapture, ...]
    base_revision: str | None = None

    @property
    def effective_base_revision(self) -> str:
        return self.base_revision or self.worktree.head_revision

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.mutations)

    @property
    def capture_sha256(self) -> str:
        def body(value: MutationTextBody | None) -> object:
            return None if value is None else (value.sha256, value.size, value.mode)

        payload = {
            "kind": "worktree_mutation_capture",
            "version": 2,
            "task_id": self.worktree.task_id,
            "role": self.worktree.role.value,
            "attempt": self.worktree.attempt,
            "path": str(self.worktree.path),
            "head_revision": self.worktree.head_revision,
            "branch": self.worktree.branch,
            "detached": self.worktree.detached,
            "base_revision": self.base_revision,
            "patch_sha256": hashlib.sha256(self.patch).hexdigest(),
            "index_diff_sha256": self.index_diff_sha256,
            "mutations": [
                (item.path, body(item.before), body(item.after)) for item in self.mutations
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()


def read_mutation_body(root: Path, relative_path: str) -> MutationTextBody:
    """No-follow bounded read with exact named-file identity and mode checks."""
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = relative_path.split("/")
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        try:
            metadata = os.fstat(descriptor)
            mode = stat.S_IMODE(metadata.st_mode)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or mode not in (0o644, 0o755)
                or metadata.st_size > MAX_CAPTURE_BYTES
            ):
                raise ValueError("mutation requires a bounded regular 0644/0755 file")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                payload = stream.read(MAX_CAPTURE_BYTES + 1)
            after = os.fstat(descriptor)
            named = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)

            def identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
                return (
                    value.st_dev,
                    value.st_ino,
                    value.st_mode,
                    value.st_size,
                    value.st_mtime_ns,
                    value.st_ctime_ns,
                )

            if (
                identity(metadata) != identity(after)
                or identity(metadata) != identity(named)
                or len(payload) != metadata.st_size
                or len(payload) > MAX_CAPTURE_BYTES
            ):
                raise ValueError("mutation file changed during read")
            return MutationTextBody(
                payload.decode("utf-8"),
                0o755 if mode == 0o755 else 0o644,
                source_path=relative_path,
            )
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)
