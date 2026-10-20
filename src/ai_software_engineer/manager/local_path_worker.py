"""Fixed private stdin/stdout worker; never inspect processes or launch commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import BinaryIO

# -I -S starts with only the standard library: never process sitecustomize or
# .pth code. sys.executable retains the selected venv path even when -S makes
# sys.prefix refer to the base installation. Add only its direct dependencies
# and this script's fixed checkout; neither location comes from survey input.
_installation = Path(sys.executable).parent.parent
_dependencies = (
    _installation
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
sys.path[:] = [str(Path(__file__).parents[2]), *sys.path, str(_dependencies)]

from ai_software_engineer.manager.local_path_observation import (  # noqa: E402
    _MAX_REQUEST_BYTES,
    MacPathObservationRequest,
    MacPathObservationResult,
    inspect_mac_paths,
)


def _execute(source: BinaryIO, output: BinaryIO) -> int:
    try:
        raw = source.read(_MAX_REQUEST_BYTES + 1)
        request = MacPathObservationRequest.decode(raw)
        covered, blockers = inspect_mac_paths(
            request.body.encode("utf-8", errors="strict"),
            Path(request.root),
            frozenset(request.ignored_pids),
            frozenset(request.cwd_blocker_pids),
            request.deadline,
        )
        result = MacPathObservationResult(
            request_sha256=request.request_sha256,
            covered_pids=tuple(sorted(covered)),
            blockers=tuple(sorted(blockers)),
        )
        output.write(result.encode())
        output.flush()
        return 0
    except Exception:
        # The parent accepts only a complete typed result and zero stderr.
        # Never print raw lsof, paths, PIDs or exception/validation input.
        return 1


if __name__ == "__main__":
    raise SystemExit(_execute(sys.stdin.buffer, sys.stdout.buffer))
