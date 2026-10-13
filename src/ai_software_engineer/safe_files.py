"""Dependency-free bounded regular-file and symlink checks for sidecar adapters."""

import os
import stat
from pathlib import Path


def _reject_symlinks(path: Path) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("team workspace cannot traverse a symlink")


def _read_regular(path: Path, limit: int) -> bytes:
    _reject_symlinks(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("team record must be a regular file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("team document exceeds byte budget")
    return data
