"""Reentrant, scope-local serialization for knowledge selection and retirement."""

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import local


class _HeldScopes(local):
    def __init__(self) -> None:
        self.paths: set[Path] = set()


_held_scopes = _HeldScopes()


@contextmanager
def knowledge_mutation_lock(knowledge_root: Path) -> Iterator[None]:
    """Serialize scope RMW operations across threads/processes; nested stores reuse the lock."""
    if any(path.is_symlink() for path in (knowledge_root, *knowledge_root.parents)):
        raise OSError("knowledge mutation lock cannot traverse a symlink")
    root = knowledge_root.resolve()
    if root in _held_scopes.paths:
        yield
        return
    root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(root / "mutation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("knowledge mutation lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _held_scopes.paths.add(root)
        try:
            yield
        finally:
            _held_scopes.paths.remove(root)
    finally:
        os.close(descriptor)
