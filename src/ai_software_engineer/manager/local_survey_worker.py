"""Fixed whole-survey worker; only exact fixed ps/lsof peers inherit its SID."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO

_installation = Path(sys.executable).parent.parent
_dependencies = (
    _installation
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
sys.path[:] = [str(Path(__file__).parents[2]), *sys.path, str(_dependencies)]
import logging  # noqa: E402
from typing import cast  # noqa: E402

from ai_software_engineer.manager.legacy_local_execution import (  # noqa: E402
    _DEADLINE,
    _QUERY_PIDS,
    LegacyLocalExecutionBlocker,
    TrustedLegacyLocalExecutionObserver,
    _IncompleteSurvey,
)
from ai_software_engineer.manager.local_path_observation import inspect_mac_paths  # noqa: E402
from ai_software_engineer.manager.local_survey_observation import (  # noqa: E402
    _ENVIRONMENT,
    _MAX_REQUEST_BYTES,
    LocalSurveyPhase,
    LocalSurveyRequest,
    LocalSurveyResult,
)
from ai_software_engineer.owned_sessions import observe_current_process  # noqa: E402


class _SafePhaseHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.phase: LocalSurveyPhase | None = None

    def emit(self, record: logging.LogRecord) -> None:
        phase = record.__dict__.get("phase")
        if phase not in {
            "platform_boundary",
            "process_inventory_before",
            "desktop_attribution_before",
            "paths_before",
            "process_inventory_after",
            "desktop_attribution_after",
            "paths_after",
            "process_identity_final",
        }:
            raise _IncompleteSurvey
        self.phase = cast(LocalSurveyPhase, phase)


def _require_worker_parent(request: LocalSurveyRequest) -> None:
    if (
        os.getpid() != os.getsid(0)
        or os.getpid() != os.getpgrp()
        or os.getppid() != request.parent_identity.process_id
        or os.getuid() != request.uid
        or os.geteuid() != request.uid
    ):
        raise _IncompleteSurvey
    native_boot, identity = observe_current_process(os.getppid())
    if native_boot != request.parent_boot_identity or identity != request.parent_identity:
        raise _IncompleteSurvey
    if sys.platform == "darwin":
        birth = _parent_birth(os.getppid(), request.deadline)
        if identity.birth_identity != f"darwin-time:{birth}":
            raise _IncompleteSurvey
    elif sys.platform.startswith("linux"):
        if Path(f"/proc/{os.getppid()}").stat().st_uid != request.uid:
            raise _IncompleteSurvey
    else:
        raise _IncompleteSurvey


def _parent_birth(pid: int, deadline: float) -> str:
    token = _DEADLINE.set(deadline)
    try:
        return TrustedLegacyLocalExecutionObserver()._birth(pid)
    finally:
        _DEADLINE.reset(token)


class _WorkerSurveyEngine(TrustedLegacyLocalExecutionObserver):
    def __init__(self, request: LocalSurveyRequest) -> None:
        self.request = request

    def _confirm_observer_identity(self) -> None:
        self._remaining()
        _require_worker_parent(self.request)
        self._remaining()

    def _inspect_mac_paths(
        self,
        body: bytes,
        root: Path,
        *,
        ignored_pids: frozenset[int],
        cwd_blocker_pids: frozenset[int],
    ) -> tuple[set[int], set[LegacyLocalExecutionBlocker]]:
        self._remaining()
        covered, blockers = inspect_mac_paths(
            body, root, ignored_pids, cwd_blocker_pids, self.request.deadline
        )
        return covered, set(blockers)

    def _query(self, argv: tuple[str, ...]) -> bytes:
        self._remaining()
        _require_fixed_query(argv, self.request.uid)
        if os.getpid() != os.getsid(0) or os.getpid() != os.getpgrp():
            raise _IncompleteSurvey
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=errors,
                cwd=Path("/"),
                env=_ENVIRONMENT,
                shell=False,
                start_new_session=False,
                close_fds=True,
            )
            query_pids = _QUERY_PIDS.get()
            if query_pids is not None:
                query_pids.add(process.pid)
            try:
                process.wait(timeout=min(1.5, self._remaining()))
                partial = argv[0] == "/usr/sbin/lsof" and "-p" in argv and process.returncode == 1
                if (
                    (process.returncode and not partial)
                    or errors.tell()
                    or output.tell() > self.MAX_QUERY_BYTES
                ):
                    raise _IncompleteSurvey
                output.seek(0)
                return output.read(self.MAX_QUERY_BYTES + 1)
            finally:
                # Only this actual Popen is signaled; outer owner proves its full SID empty.
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=1.0)


def _require_fixed_query(argv: tuple[str, ...], uid: int) -> None:
    if argv == ("/bin/ps", "-ww", "-U", str(uid), "-o", "pid=,ppid=,uid=,stat=,lstart=,command="):
        return
    prefix = ("/usr/sbin/lsof", "-n", "-P", "-a", "-u", str(uid))
    if argv == (*prefix, "-F0pftn"):
        return
    if len(argv) == 9 and argv[:6] == prefix and argv[6] == "-p" and argv[8] == "-F0pftn":
        tokens = argv[7].split(",")
        if len(tokens) <= 4096 and all(token.isascii() and token.isdigit() for token in tokens):
            pids = tuple(int(token) for token in tokens)
            if (
                pids == tuple(sorted(set(pids)))
                and all(0 < pid <= 2147483647 for pid in pids)
                and all(str(pid) == token for pid, token in zip(pids, tokens, strict=True))
            ):
                return
    raise _IncompleteSurvey


def _execute(source: BinaryIO, output: BinaryIO) -> int:
    handler = _SafePhaseHandler()
    logger = logging.getLogger("ai_software_engineer.manager.legacy_local_execution")
    previous_propagate = logger.propagate
    logger.addHandler(handler)
    logger.propagate = False
    try:
        request = LocalSurveyRequest.decode(source.read(_MAX_REQUEST_BYTES + 1))
        _require_worker_parent(request)
        engine = _WorkerSurveyEngine(request)
        survey = engine._observe_with_deadline(
            worktree_root=Path(request.root),
            boot=request.boot,
            started=request.started,
            deadline=request.deadline,
            observer_pid=request.parent_identity.process_id,
        )
        _require_worker_parent(request)
        result = LocalSurveyResult(
            request_sha256=request.request_sha256,
            worker_pid=os.getpid(),
            survey=survey,
            incomplete_phase=handler.phase,
        )
        output.write(result.encode())
        output.flush()
        return 0
    except Exception:
        return 1
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous_propagate


if __name__ == "__main__":
    raise SystemExit(_execute(sys.stdin.buffer, sys.stdout.buffer))
