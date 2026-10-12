"""Reuse a proven inherited service lock, or acquire it for direct Host startup."""

import fcntl
import os
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from .fault_retirement import replacement_lock
from .service_lifecycle import ServiceLifecycleError


@contextmanager
def maintenance_start_lock(root: Path, environment: Mapping[str, str]) -> Iterator[None]:
    inherited = environment.get("ASE_REPLACEMENT_LOCK_FD")
    if inherited is None:
        with replacement_lock(root):
            yield
        return
    try:
        descriptor = int(inherited)
        actual = os.fstat(descriptor)
        expected = (root / "console-service-replacement.lock").lstat()
        if (
            not stat.S_ISREG(expected.st_mode)
            or (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino)
            or actual.st_uid != os.getuid()
            or actual.st_nlink != 1
            or stat.S_IMODE(actual.st_mode) != 0o600
        ):
            raise ValueError("invalid inherited lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ValueError) as error:
        raise ServiceLifecycleError("服务启动缺少可验证的维护控制锁; 未恢复普通模式。") from error
    yield
