"""Bounded current-account surveys; these do not reconstruct historical process stops."""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, Protocol, Self, cast

from pydantic import AwareDatetime, model_validator

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.owned_processes import (
    OwnedProcessesUncertain,
    finish_owned_process,
    observe_owned_process,
)
from ai_software_engineer.recovery.models import digest

if TYPE_CHECKING:
    from ai_software_engineer.manager.legacy_containment import LocalBootObservation

type LegacyLocalExecutionBlocker = Literal[
    "CODEX_EXECUTION_ACTIVE",
    "CODEX_WRAPPER_ACTIVE",
    "WORKTREE_PROCESS_ACTIVE",
    "PROCESS_SCAN_INCOMPLETE",
    "PROCESS_STATE_UNKNOWN",
]

_SCANNER_VERSION = "local-execution-v1"
_MAX_PROCESSES = 4096
_MAX_FILES = 65_536
_PROC_ROOT = Path("/proc")
_DEADLINE: ContextVar[float | None] = ContextVar("legacy_local_survey_deadline", default=None)
_QUERY_PIDS: ContextVar[set[int] | None] = ContextVar("legacy_local_survey_queries", default=None)


class LegacyRescuePrerequisiteError(RuntimeError):
    """An actionable wait, not a decision about the original invocation outcome."""

    def __init__(self, *, code: str, safe_message: str, next_action: str) -> None:
        self.code = code
        self.safe_message = safe_message
        self.next_action = next_action
        super().__init__(safe_message)


class LegacyLocalExecutionSurvey(DomainModel):
    worktree_path: NonEmptyStr
    machine_sha256: Sha256
    boot_session_sha256: Sha256
    account_sha256: Sha256
    observed_at: AwareDatetime
    scanner_version: NonEmptyStr
    blockers: tuple[LegacyLocalExecutionBlocker, ...]
    survey_sha256: Sha256

    @model_validator(mode="after")
    def validate_boundary(self) -> Self:
        path = PurePosixPath(self.worktree_path)
        if not path.is_absolute() or ".." in path.parts or str(path) != self.worktree_path:
            raise ValueError("本机执行调查必须绑定精确的绝对工作区路径")
        if tuple(sorted(set(self.blockers))) != self.blockers:
            raise ValueError("本机执行调查的等待原因必须唯一且有序")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.survey_sha256 != digest(self.model_dump(mode="json", exclude={"survey_sha256"})):
            raise ValueError("本机执行调查记录完整性异常")

    def require_idle(self) -> None:
        self.validate_integrity()
        if not self.blockers:
            return
        incomplete = any(
            code in {"PROCESS_SCAN_INCOMPLETE", "PROCESS_STATE_UNKNOWN"} for code in self.blockers
        )
        raise LegacyRescuePrerequisiteError(
            code=(
                "LEGACY_LOCAL_SURVEY_INCOMPLETE" if incomplete else "LEGACY_LOCAL_EXECUTION_ACTIVE"
            ),
            safe_message=(
                "平台尚未完成本机执行核验, 不能据此准备旧执行恢复。"
                if incomplete
                else "本机仍有开发执行或进程正在访问保留的工作区, 暂不能准备恢复。"
            ),
            next_action=(
                "请让平台维护者检查当前账户的进程读取权限和本机调查能力; 补齐后重新检查, "
                "也可保存其他工作后采用整机重启恢复路径。"
                if incomplete
                else "请等待相关开发执行结束, 或由维护者通过原执行入口正常停止; "
                "关闭正在使用该工作区的终端或工具后重新检查。不要清空工作区。"
            ),
        )

    def same_boundary(
        self, other: LegacyLocalExecutionSurvey, *, allow_new_boot: bool = False
    ) -> bool:
        """Compare exact facts; later boot permission must come from a trusted OS check."""
        self.validate_integrity()
        other.validate_integrity()
        return (allow_new_boot or self.boot_session_sha256 == other.boot_session_sha256) and (
            self.worktree_path,
            self.machine_sha256,
            self.account_sha256,
            self.scanner_version,
        ) == (
            other.worktree_path,
            other.machine_sha256,
            other.account_sha256,
            other.scanner_version,
        )

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "survey_sha256": "0" * 64})
        return value.model_copy(
            update={
                "survey_sha256": digest(value.model_dump(mode="json", exclude={"survey_sha256"}))
            }
        )


class LegacyLocalExecutionObserver(Protocol):
    def observe(
        self, *, worktree_root: Path, boot: LocalBootObservation
    ) -> LegacyLocalExecutionSurvey: ...


@dataclass(frozen=True, slots=True)
class _Process:
    pid: int
    state: str
    birth: str
    command: str


class _IncompleteSurvey(RuntimeError):
    pass


class TrustedLegacyLocalExecutionObserver:
    """Fixed OS reads only. No discovered PID, argv or environment is persisted or signaled."""

    MAX_QUERY_BYTES = 8 * 1024 * 1024
    MAX_SCAN_SECONDS = 5.0

    @staticmethod
    def _remaining() -> float:
        deadline = _DEADLINE.get()
        if deadline is None:
            raise _IncompleteSurvey
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _IncompleteSurvey
        return remaining

    def _query(self, argv: tuple[str, ...]) -> bytes:
        # Query bytes are bounded and short lived. Neither output nor native
        # error text is attached to a persisted record or public exception.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=errors,
                cwd="/",
                env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C"},
                shell=False,
                start_new_session=True,
            )
            owned = observe_owned_process(process, kind="tool")
            query_pids = _QUERY_PIDS.get()
            if query_pids is not None:
                query_pids.add(process.pid)
            try:
                process.wait(timeout=min(1.5, self._remaining()))
                partial_targeted_lsof = (
                    argv[0] == "/usr/sbin/lsof" and "-p" in argv and process.returncode == 1
                )
                if (
                    (process.returncode and not partial_targeted_lsof)
                    or errors.tell()
                    or output.tell() > self.MAX_QUERY_BYTES
                ):
                    raise _IncompleteSurvey
                output.seek(0)
                return output.read(self.MAX_QUERY_BYTES + 1)
            finally:
                # This can stop only our fixed OS query process group, never a
                # PID found in the survey. File outputs have no escaped pipes.
                finish_owned_process(process, owned, output_drained=True)

    def _processes(self, uid: int) -> dict[int, _Process]:
        body = self._query(
            ("/bin/ps", "-ww", "-U", str(uid), "-o", "pid=,uid=,stat=,lstart=,command=")
        )
        if len(body) > self.MAX_QUERY_BYTES:
            raise _IncompleteSurvey
        result: dict[int, _Process] = {}
        for line in body.decode("utf-8", errors="strict").splitlines():
            fields = line.split(maxsplit=8)
            if (
                len(fields) != 9
                or not fields[0].isdigit()
                or not fields[1].isdigit()
                or not fields[2]
            ):
                raise _IncompleteSurvey
            if int(fields[1]) != uid:
                continue  # effective UID, consistent with lsof and the trusted runner
            pid = int(fields[0])
            if pid < 1 or pid in result or len(result) >= _MAX_PROCESSES:
                raise _IncompleteSurvey
            fixed_query = f"/bin/ps -ww -U {uid} -o pid=,uid=,stat=,lstart=,command="
            if pid in (_QUERY_PIDS.get() or ()) and fields[8] == fixed_query:
                continue
            try:
                birth = self._birth(pid)
            except ProcessLookupError:
                # Preserve the observed command for classification. Only its
                # absence from the final inventory permits missing birth facts.
                birth = "unobserved"
            result[pid] = _Process(pid, fields[2][0], birth, fields[8])
        if not result:
            raise _IncompleteSurvey
        return result

    def _birth(self, pid: int) -> str:
        """Native high-resolution identity; ps lstart's seconds are insufficient."""
        self._remaining()
        platform = sys.platform
        if platform == "darwin":
            library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            query = library.proc_pidinfo
            query.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint64,
                ctypes.c_void_p,
                ctypes.c_int,
            ]
            query.restype = ctypes.c_int
            # Darwin proc_bsdinfo is a stable 136-byte OS ABI. Only the final
            # uint64 start sec/usec and effective UID are read, never argv/env.
            buffer = ctypes.create_string_buffer(136)
            size = cast(int, query(pid, 3, 0, ctypes.byref(buffer), len(buffer)))
            if size == 0 and ctypes.get_errno() == 3:
                raise ProcessLookupError
            if size != len(buffer):
                raise _IncompleteSurvey
            effective_uid = struct.unpack_from("=I", buffer.raw, 20)[0]
            sec, usec = struct.unpack_from("=QQ", buffer.raw, 120)
            if effective_uid != os.getuid() or not sec or usec >= 1_000_000:
                raise _IncompleteSurvey
            return f"{sec}:{usec}"
        try:
            stat = self._read_proc(_PROC_ROOT / str(pid) / "stat").decode("utf-8", errors="strict")
        except FileNotFoundError as error:
            raise ProcessLookupError from error
        close = stat.rfind(") ")
        fields = stat[close + 2 :].split() if close >= 0 else []
        if len(fields) < 20 or not fields[19].isdigit():
            raise _IncompleteSurvey
        return fields[19]  # kernel starttime ticks, within this survey's exact boot

    @staticmethod
    def _execution_blocker(command: str) -> LegacyLocalExecutionBlocker | None:
        lowered = command.lower()
        # Desktop app, language server and unrelated browser processes are not
        # native exec. An actual CLI or wrapper must name its executable/action.
        if re.match(
            r"^.*?\.app/Contents/(?:Frameworks/.+?\.app/Contents/)?MacOS/"
            r"Codex(?: Helper(?: \([A-Za-z ]+\))?)?(?:\s|$)",
            command,
        ):
            return None
        cli = re.search(
            r"(?:^|[/\s])codex(?:\.(?:m?js|sh)|-(?:aarch64|x86_64|arm64)[a-z0-9_-]*)?"
            r"(?=[\s]|$)",
            lowered,
        )
        if cli:
            # The desktop app's protocol server is not a Codex exec. Its real
            # cwd/open files still undergo the same complete worktree check.
            if not re.search(r"\bexec\b", lowered) and re.search(
                r"\s(?:app-server|mcp-server)(?:\s|$)", lowered[cli.end() :]
            ):
                return None
            return (
                "CODEX_EXECUTION_ACTIVE"
                if re.search(r"\bexec\b", lowered)
                else "CODEX_WRAPPER_ACTIVE"
            )
        if re.search(r"\b(?:ase|ai_software_engineer(?:\.cli)?)\b", lowered) and re.search(
            r"\btask\s+run\b", lowered
        ):
            return "CODEX_WRAPPER_ACTIVE"
        return None

    @staticmethod
    def _covers(path: str, root: Path) -> bool:
        if not path.startswith("/"):
            return False
        if path.endswith(" (deleted)"):
            path = path.removesuffix(" (deleted)")
        # Resolve existing parent aliases (notably /var versus /private/var).
        resolved = Path(path).resolve(strict=False)
        return resolved == root or root in resolved.parents

    def _mac_paths(
        self, uid: int, root: Path, *, pids: tuple[int, ...] = ()
    ) -> tuple[set[int], set[LegacyLocalExecutionBlocker]]:
        arguments = ("-p", ",".join(str(pid) for pid in pids)) if pids else ()
        body = self._query(
            ("/usr/sbin/lsof", "-n", "-P", "-a", "-u", str(uid), *arguments, "-F0pftn")
        )
        if pids and not body:
            return set(), set()
        if len(body) > self.MAX_QUERY_BYTES or not body.endswith((b"\0", b"\0\n")):
            raise _IncompleteSurvey
        covered: set[int] = set()
        blockers: set[LegacyLocalExecutionBlocker] = set()
        pid: int | None = None
        descriptor: str | None = None
        file_type: str | None = None
        count = 0
        for raw in body.split(b"\0"):
            field = raw.removeprefix(b"\n")
            if not field:
                continue
            tag, value = chr(field[0]), field[1:].decode("utf-8", errors="strict")
            if tag == "p":
                if not value.isdigit():
                    raise _IncompleteSurvey
                pid, descriptor, file_type = int(value), None, None
            elif tag == "f":
                if pid is None or count >= _MAX_FILES:
                    raise _IncompleteSurvey
                count += 1
                descriptor, file_type = value, None
            elif tag == "t":
                file_type = value
            elif tag == "n":
                if pid is None or descriptor is None:
                    raise _IncompleteSurvey
                if "(stat:" in value or "(readlink:" in value:
                    raise _IncompleteSurvey
                if descriptor == "cwd":
                    if not value.startswith("/") or file_type != "DIR":
                        raise _IncompleteSurvey
                    covered.add(pid)
                if self._covers(value, root):
                    blockers.add("WORKTREE_PROCESS_ACTIVE")
            else:
                raise _IncompleteSurvey
        return covered, blockers

    @staticmethod
    def _read_proc(path: Path) -> bytes:
        with path.open("rb") as source:
            body = source.read(65_537)
        if len(body) > 65_536:
            raise _IncompleteSurvey
        return body

    def _linux_paths(
        self, before: dict[int, _Process], root: Path
    ) -> tuple[set[int], set[LegacyLocalExecutionBlocker]]:
        covered: set[int] = set()
        blockers: set[LegacyLocalExecutionBlocker] = set()
        count = 0
        for pid, process in before.items():
            self._remaining()
            if process.state == "Z":
                covered.add(pid)
                continue
            proc = _PROC_ROOT / str(pid)
            try:
                cwd = os.readlink(proc / "cwd")
                if not cwd.startswith("/"):
                    raise _IncompleteSurvey
                if self._covers(cwd, root):
                    blockers.add("WORKTREE_PROCESS_ACTIVE")
                for entry in (proc / "fd").iterdir():
                    self._remaining()
                    count += 1
                    if count > _MAX_FILES or not entry.name.isdigit():
                        raise _IncompleteSurvey
                    try:
                        opened = os.readlink(entry)
                    except FileNotFoundError:
                        continue  # a closed descriptor cannot still access the worktree
                    if self._covers(opened, root):
                        blockers.add("WORKTREE_PROCESS_ACTIVE")
                covered.add(pid)
            except FileNotFoundError:
                # Only a second real inventory may establish this process exited.
                continue
        return covered, blockers

    def observe(
        self, *, worktree_root: Path, boot: LocalBootObservation
    ) -> LegacyLocalExecutionSurvey:
        root = worktree_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("本机执行调查的工作区不存在")
        uid = os.getuid()
        blockers: set[LegacyLocalExecutionBlocker] = set()
        token = _DEADLINE.set(time.monotonic() + self.MAX_SCAN_SECONDS)
        query_pids: set[int] = set()
        query_token = _QUERY_PIDS.set(query_pids)
        try:
            if uid != os.geteuid():
                raise _IncompleteSurvey
            if sys.platform != "darwin" and not sys.platform.startswith("linux"):
                raise _IncompleteSurvey
            before = self._processes(uid)
            covered, path_blockers = (
                self._mac_paths(uid, root)
                if sys.platform == "darwin"
                else self._linux_paths(before, root)
            )
            blockers.update(path_blockers)
            after = self._processes(uid)
            missing = {
                pid: process
                for pid, process in after.items()
                if process.state != "Z" and pid not in covered
            }
            if missing:
                extra_covered, extra_blockers = (
                    self._mac_paths(uid, root, pids=tuple(sorted(missing)))
                    if sys.platform == "darwin"
                    else self._linux_paths(missing, root)
                )
                covered.update(extra_covered)
                blockers.update(extra_blockers)
            for process in (*before.values(), *after.values()):
                if process.state not in {"R", "S", "I", "T", "U", "D", "W", "Z"}:
                    blockers.add("PROCESS_STATE_UNKNOWN")
                if process.state != "Z" and (blocker := self._execution_blocker(process.command)):
                    blockers.add(blocker)
            for pid in before.keys() & after.keys():
                if after[pid].state != "Z" and (
                    before[pid].birth == "unobserved" or before[pid].birth != after[pid].birth
                ):
                    raise _IncompleteSurvey
            for pid, process in after.items():
                if process.state != "Z":
                    try:
                        birth = self._birth(pid)
                    except ProcessLookupError:
                        continue  # no currently live process with this observed PID
                    if pid not in covered or birth != process.birth:
                        raise _IncompleteSurvey
            self._remaining()
        except (
            OSError,
            UnicodeError,
            subprocess.SubprocessError,
            _IncompleteSurvey,
            OwnedProcessesUncertain,
        ):
            blockers.add("PROCESS_SCAN_INCOMPLETE")
        finally:
            _DEADLINE.reset(token)
            _QUERY_PIDS.reset(query_token)
        return LegacyLocalExecutionSurvey.create(
            worktree_path=str(root),
            machine_sha256=boot.machine_sha256,
            boot_session_sha256=boot.boot_session_sha256,
            account_sha256=hashlib.sha256(f"{boot.machine_sha256}:uid:{uid}".encode()).hexdigest(),
            observed_at=datetime.now(UTC),
            scanner_version=_SCANNER_VERSION,
            blockers=tuple(sorted(blockers)),
        )
