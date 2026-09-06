"""Read-only, untrusted Coder change captures; never an execution authorization."""

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from ai_software_engineer.git.ports import WorktreeRef

MAX_CAPTURE_BYTES = 1_000_000
MAX_CAPTURE_FILES = 256


def without_hunk_labels(patch: bytes) -> bytes:
    """Drop Git's optional unchanged source labels, retaining hunk ranges and edits."""
    return re.sub(rb"(?m)^(@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@)[^\n]*", rb"\1", patch)


@dataclass(frozen=True, slots=True)
class WorktreeChangeCapture:
    """In-process repository fact, not a persisted Artifact, approval or candidate.

    The patch represents HEAD-to-working-tree content, including staged edits. The
    index digest also binds staging state, even when a staged change was undone in
    the working file. Application code must persist/authorize this fact separately
    before implementing recovery; possession of this object grants no write rights.
    """

    worktree: WorktreeRef
    patch: bytes
    index_diff_sha256: str
    file_sha256s: tuple[tuple[str, str], ...]

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return tuple(path for path, _ in self.file_sha256s)

    @property
    def capture_sha256(self) -> str:
        """Bind exact source identity, content and staging without mutable refs."""
        payload = {
            "kind": "worktree_change_capture",
            "version": 1,
            "task_id": self.worktree.task_id,
            "role": self.worktree.role.value,
            "attempt": self.worktree.attempt,
            "path": str(self.worktree.path),
            "head_revision": self.worktree.head_revision,
            "branch": self.worktree.branch,
            "detached": self.worktree.detached,
            "patch_sha256": hashlib.sha256(self.patch).hexdigest(),
            "index_diff_sha256": self.index_diff_sha256,
            "file_sha256s": self.file_sha256s,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        ).hexdigest()


def read_capture_file(root: Path, relative_path: str, *, executable: bool) -> bytes:
    """Bounded regular-file read with no-follow descriptors for every component.

    The caller must first authorize the canonical relative path with WorkspacePolicy.
    No-follow protects reads from symlink swaps; it does not lock out a concurrent
    authorized writer. The manager compares complete observations before returning.
    """
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = relative_path.split("/")
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
        )
        try:
            metadata = os.fstat(file_descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_CAPTURE_BYTES:
                raise ValueError("capture requires bounded regular files")
            if bool(metadata.st_mode & stat.S_IXUSR) != executable:
                raise ValueError("capture does not support mode changes")
            with os.fdopen(file_descriptor, "rb", closefd=False) as stream:
                content = stream.read(MAX_CAPTURE_BYTES + 1)
            if len(content) > MAX_CAPTURE_BYTES or b"\0" in content:
                raise ValueError("capture requires bounded text files")
            content.decode("utf-8")
            return content
        finally:
            os.close(file_descriptor)
    finally:
        os.close(descriptor)
