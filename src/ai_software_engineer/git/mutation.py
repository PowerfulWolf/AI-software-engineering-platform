"""Bounded no-follow final-state inventory, including Git-ignored workspace files.

This is observation, not OS isolation or a history of transient filesystem writes.
The manager-owned Git administration directory is inspected separately by Git's
HEAD/index/worktree guards. Everything else is observed without ignore filtering.
"""

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ai_software_engineer.git.policy import is_protected_rule_path

MAX_INVENTORY_FILES = 20_000
MAX_INVENTORY_BYTES = 256_000_000
MAX_INVENTORY_FILE_BYTES = 16_000_000


class MutationInventoryRejected(RuntimeError):
    """A bounded, stable workspace observation could not be established."""


@dataclass(frozen=True, slots=True)
class MutationFile:
    path: str
    kind: Literal["file", "symlink", "git_directory"]
    sha256: str
    mode: int
    size: int


@dataclass(frozen=True, slots=True)
class WorkspaceMutationInventory:
    files: tuple[MutationFile, ...]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                [(f.path, f.kind, f.sha256, f.mode, f.size) for f in self.files],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


def capture_mutation_inventory(root: Path) -> WorkspaceMutationInventory:
    """Compare two complete observations; never follow workspace symlinks."""
    if root.is_symlink() or not root.is_dir():
        raise MutationInventoryRejected("mutation inventory requires a regular workspace root")
    try:
        first, second = _observe(root), _observe(root)
    except (OSError, UnicodeError, ValueError) as error:
        raise MutationInventoryRejected("workspace mutation inventory could not be read") from error
    if first != second:
        raise MutationInventoryRejected("workspace changed during mutation observation")
    return first


def changed_mutation_paths(
    before: WorkspaceMutationInventory, after: WorkspaceMutationInventory
) -> tuple[str, ...]:
    old, new = {f.path: f for f in before.files}, {f.path: f for f in after.files}
    return tuple(sorted(path for path in old.keys() | new.keys() if old.get(path) != new.get(path)))


def is_execution_cache_path(path: str) -> bool:
    """Only the explicit Python/static-check cache capability, never rules/VCS."""
    parts = path.split("/")
    if is_protected_rule_path(path) or any(part.casefold() == ".git" for part in parts):
        return False
    return (
        ("__pycache__" in parts and path.endswith(".pyc"))
        or ".pytest_cache" in parts
        or ".ruff_cache" in parts
    )


def _observe(root: Path) -> WorkspaceMutationInventory:
    pending = [""]
    files: list[MutationFile] = []
    total_bytes = 0
    while pending:
        prefix = pending.pop()
        # Directory descriptors prevent a rename/symlink substitution from
        # making an observation traverse out of the trusted workspace.
        fd = _directory_descriptor(root, prefix)
        try:
            with os.scandir(fd) as entries:
                for entry in entries:
                    name = entry.name
                    if any(ord(c) < 32 for c in name) or "\\" in name:
                        raise MutationInventoryRejected("workspace contains an unsafe path")
                    path = prefix + name
                    metadata = entry.stat(follow_symlinks=False)
                    mode = stat.S_IMODE(metadata.st_mode)
                    if stat.S_ISDIR(metadata.st_mode):
                        if not prefix and name.casefold() == ".git":
                            identity = f"{metadata.st_dev}:{metadata.st_ino}:{mode}".encode()
                            files.append(
                                MutationFile(
                                    path,
                                    "git_directory",
                                    hashlib.sha256(identity).hexdigest(),
                                    mode,
                                    0,
                                )
                            )
                        else:
                            pending.append(path + "/")
                        continue
                    if stat.S_ISLNK(metadata.st_mode):
                        target = os.readlink(name, dir_fd=fd).encode("utf-8")
                        fingerprint = MutationFile(
                            path, "symlink", hashlib.sha256(target).hexdigest(), mode, len(target)
                        )
                    elif stat.S_ISREG(metadata.st_mode):
                        if metadata.st_size > MAX_INVENTORY_FILE_BYTES:
                            raise MutationInventoryRejected(
                                "workspace file exceeds inventory limit"
                            )
                        file_fd = os.open(
                            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
                        )
                        try:
                            actual = os.fstat(file_fd)
                            if not stat.S_ISREG(actual.st_mode) or _identity(actual) != _identity(
                                metadata
                            ):
                                raise MutationInventoryRejected(
                                    "workspace file changed before observation"
                                )
                            digest = hashlib.sha256()
                            size = 0
                            while chunk := os.read(file_fd, 1_000_000):
                                size += len(chunk)
                                if size > MAX_INVENTORY_FILE_BYTES:
                                    raise MutationInventoryRejected(
                                        "workspace file exceeds inventory limit"
                                    )
                                digest.update(chunk)
                            if (
                                _identity(os.fstat(file_fd)) != _identity(actual)
                                or size != actual.st_size
                            ):
                                raise MutationInventoryRejected(
                                    "workspace file changed during observation"
                                )
                            fingerprint = MutationFile(path, "file", digest.hexdigest(), mode, size)
                        finally:
                            os.close(file_fd)
                    else:
                        raise MutationInventoryRejected(
                            "workspace contains an unsupported file type"
                        )
                    files.append(fingerprint)
                    total_bytes += fingerprint.size
                    if len(files) > MAX_INVENTORY_FILES or total_bytes > MAX_INVENTORY_BYTES:
                        raise MutationInventoryRejected("workspace exceeds inventory limits")
        finally:
            os.close(fd)
    return WorkspaceMutationInventory(tuple(sorted(files, key=lambda f: f.path)))


def _directory_descriptor(root: Path, prefix: str) -> int:
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in prefix.rstrip("/").split("/") if prefix else ():
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
