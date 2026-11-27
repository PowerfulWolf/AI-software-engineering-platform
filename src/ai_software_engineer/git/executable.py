"""Locate the trusted git binary without consulting the caller's PATH."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

_XCRUN_SHIM = Path("/usr/bin/git")


@lru_cache(maxsize=1)
def trusted_git_executable() -> str | None:
    """``git`` from the fixed default path, resolved past the macOS xcrun shim.

    ``/usr/bin/git`` on macOS only re-locates the developer tool on every call.
    Where xcrun cannot write its lookup cache (for example inside the isolated
    verification sandbox) each call re-runs ``xcodebuild`` and costs seconds, so a
    test that calls git a few hundred times exceeds its command window. The real
    binary is the one the shim would run: resolved once, with a fixed environment
    (no inherited PATH or DEVELOPER_DIR), and only accepted when it is a regular
    file named git outside ``/usr/bin``. Anything else keeps the default-path git.
    """
    default = shutil.which("git", path=os.defpath)
    if sys.platform != "darwin" or default is None or Path(default) != _XCRUN_SHIM:
        return default
    try:
        found = subprocess.run(
            ("/usr/bin/xcrun", "--find", "git"),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return default
    real = Path(found.stdout.strip())
    if (
        found.returncode != 0
        or not real.is_absolute()
        or real.name != "git"
        or real.parent == _XCRUN_SHIM.parent
        or not real.is_file()
        or not os.access(real, os.X_OK)
    ):
        return default
    return str(real)
