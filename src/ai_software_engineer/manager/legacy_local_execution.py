"""Bounded current-account surveys; these do not reconstruct historical process stops."""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import shlex
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
_DESKTOP_CONTROL_BUNDLE = Path("/Applications/ChatGPT.app")
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
                "停止仍在读写保留工作区的工具后重新检查。普通空闲终端无需关闭, 不要清空工作区。"
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
    ppid: int
    state: str
    birth: str
    command: str
    executable_name: str


@dataclass(frozen=True, slots=True)
class _DesktopProcessIdentity:
    pid: int
    ppid: int
    birth: str
    command: str
    executable_name: str
    executable_path: str


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
            (
                "/bin/ps",
                "-ww",
                "-U",
                str(uid),
                "-o",
                "pid=,ppid=,uid=,stat=,lstart=,command=",
            )
        )
        if len(body) > self.MAX_QUERY_BYTES:
            raise _IncompleteSurvey
        result: dict[int, _Process] = {}
        for line in body.decode("utf-8", errors="strict").splitlines():
            fields = line.split(maxsplit=9)
            if (
                len(fields) != 10
                or not all(field.isdigit() for field in fields[:3])
                or not fields[3]
            ):
                raise _IncompleteSurvey
            if int(fields[2]) != uid:
                continue  # effective UID, consistent with lsof and the trusted runner
            pid = int(fields[0])
            if pid < 1 or pid in result or len(result) >= _MAX_PROCESSES:
                raise _IncompleteSurvey
            fixed_query = f"/bin/ps -ww -U {uid} -o pid=,ppid=,uid=,stat=,lstart=,command="
            if pid in (_QUERY_PIDS.get() or ()) and fields[9] == fixed_query:
                continue
            try:
                birth = self._birth(pid)
                executable_name = "" if fields[3][0] == "Z" else self._executable_name(pid)
            except ProcessLookupError:
                # Preserve the observed command for classification. Only its
                # absence from the final inventory permits missing birth facts.
                birth = "unobserved"
                executable_name = ""
            result[pid] = _Process(
                pid,
                int(fields[1]),
                fields[3][0],
                birth,
                fields[9],
                executable_name,
            )
        if not result:
            raise _IncompleteSurvey
        return result

    def _executable_name(self, pid: int) -> str:
        """Read the OS executable identity, not a name appearing in argv data."""
        self._remaining()
        platform = sys.platform
        if platform == "darwin":
            info = self._darwin_info(pid)
            # The kernel basename remains readable for a running executable
            # whose old on-disk app version was removed by an update. PIDPATH
            # can return ENOENT for that live process; argv is not a substitute.
            name = (info[64:96].split(b"\0", 1)[0] or info[48:64].split(b"\0", 1)[0]).decode(
                "utf-8", errors="strict"
            )
            if not name or "/" in name:
                raise _IncompleteSurvey
            return name
        try:
            executable = os.readlink(_PROC_ROOT / str(pid) / "exe")
        except FileNotFoundError as error:
            raise ProcessLookupError from error
        if not executable.startswith("/"):
            raise _IncompleteSurvey
        return Path(executable.removesuffix(" (deleted)")).name

    def _executable_path(self, pid: int) -> str | None:
        """Optional positive attribution, never an absence or historical stop proof."""
        self._remaining()
        try:
            if sys.platform == "darwin":
                library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
                query = library.proc_pidpath
                query.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
                query.restype = ctypes.c_int
                buffer = ctypes.create_string_buffer(4096)
                size = cast(int, query(pid, ctypes.byref(buffer), len(buffer)))
                if size <= 0 or size >= len(buffer):
                    return None
                executable = buffer.raw[:size].removesuffix(b"\0").decode("utf-8", errors="strict")
            elif sys.platform.startswith("linux"):
                executable = os.readlink(_PROC_ROOT / str(pid) / "exe")
            else:
                return None
        except (OSError, UnicodeError):
            # A live old app binary can have no PIDPATH after an update. Keep
            # its ordinary classification rather than treating it as stopped.
            return None
        path = PurePosixPath(executable)
        if (
            not path.is_absolute()
            or ".." in path.parts
            or str(path) != executable
            or "\0" in executable
        ):
            return None
        return executable

    def _darwin_info(self, pid: int) -> bytes:
        self._remaining()
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
        # Fixed 136-byte proc_bsdinfo ABI: effective UID, kernel executable
        # name and high-resolution start time; no environment or prompt data.
        buffer = ctypes.create_string_buffer(136)
        size = cast(int, query(pid, 3, 0, ctypes.byref(buffer), len(buffer)))
        if size == 0 and ctypes.get_errno() == 3:
            raise ProcessLookupError
        if size != len(buffer) or struct.unpack_from("=I", buffer.raw, 20)[0] != os.getuid():
            raise _IncompleteSurvey
        return buffer.raw

    def _birth(self, pid: int) -> str:
        """Native high-resolution identity; ps lstart's seconds are insufficient."""
        self._remaining()
        platform = sys.platform
        if platform == "darwin":
            sec, usec = struct.unpack_from("=QQ", self._darwin_info(pid), 120)
            if not sec or usec >= 1_000_000:
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
    def _codex_action(arguments: tuple[str, ...]) -> str | None:
        """Find the subcommand position; option values and prompts are data."""
        valued = {
            "-c",
            "--config",
            "-m",
            "--model",
            "-p",
            "--profile",
            "-C",
            "--cd",
            "--add-dir",
            "--enable",
            "--disable",
            "-s",
            "--sandbox",
            "-a",
            "--ask-for-approval",
            "-i",
            "--image",
        }
        flags = {
            "--search",
            "--oss",
            "--full-auto",
            "--no-alt-screen",
            "--dangerously-bypass-approvals-and-sandbox",
            "--analytics-default-enabled",
        }
        index = 0
        while index < len(arguments):
            token = arguments[index]
            if token in valued:
                if index + 1 >= len(arguments):
                    return None
                index += 2
            elif token in flags or (token.split("=", 1)[0] in valued and "=" in token):
                index += 1
            elif token.startswith("-"):
                return None
            else:
                return token
        return None

    @staticmethod
    def _native_cli_name(name: str) -> bool:
        return bool(
            re.fullmatch(
                r"codex(?:\.(?:m?js|sh)|-(?:aarch64|x86_64|arm64)[a-z0-9_-]*)?", name.lower()
            )
        )

    @classmethod
    def _argv_blocker(
        cls, arguments: tuple[str, ...], *, executable_name: str | None = None, depth: int = 0
    ) -> LegacyLocalExecutionBlocker | None:
        if not arguments:
            return None
        if depth > 3:
            return "CODEX_WRAPPER_ACTIVE"
        executable = (executable_name or Path(arguments[0]).name).lower()
        if cls._native_cli_name(executable):
            action = cls._codex_action(arguments[1:])
            if action in {"app-server", "mcp-server"}:
                return None
            return "CODEX_EXECUTION_ACTIVE" if action in {"exec", "e"} else "CODEX_WRAPPER_ACTIVE"
        if executable == "ase" and arguments[1:3] == ("task", "run"):
            return "CODEX_WRAPPER_ACTIVE"
        if executable in {"sh", "bash", "zsh", "fish", "csh", "tcsh", "ksh"}:
            for index, token in enumerate(arguments[1:], start=1):
                if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", token):
                    tail = arguments[index + 1 :]
                    if not tail:
                        return None
                    command = tail[0] if len(tail) == 1 else " ".join(tail)
                    try:
                        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
                        lexer.whitespace_split = True
                        tokens = tuple(lexer)
                    except ValueError:
                        return "CODEX_WRAPPER_ACTIVE"  # an opaque active shell is not a stop fact
                    blockers: list[LegacyLocalExecutionBlocker] = []
                    segment: list[str] = []
                    for part in (*tokens, ";"):
                        if part in {";", "&&", "||", "|", "&"}:
                            route = tuple(segment[1:] if segment[:1] == ["exec"] else segment)
                            blocker = cls._argv_blocker(route, depth=depth + 1)
                            if blocker is not None:
                                blockers.append(blocker)
                            segment = []
                        else:
                            segment.append(part)
                    if "CODEX_EXECUTION_ACTIVE" in blockers:
                        return "CODEX_EXECUTION_ACTIVE"
                    return blockers[0] if blockers else None
            # A script wrapper is identified by its script position, not its
            # ordinary arguments naming a Codex directory.
            tail = tuple(token for token in arguments[1:] if not token.startswith("-"))
            return cls._argv_blocker(tail, depth=depth + 1)
        if re.fullmatch(r"(?:node(?:js)?|python(?:\d+(?:\.\d+)?)?)", executable):
            tail = arguments[1:]
            while tail and tail[0] in {"-u", "-B", "-E", "-s", "-S"}:
                tail = tail[1:]
            if tail[:2] == ("-m", "ai_software_engineer.cli"):
                return "CODEX_WRAPPER_ACTIVE" if tail[2:4] == ("task", "run") else None
            if tail and not tail[0].startswith("-"):
                return cls._argv_blocker(tail, depth=depth + 1)
        if executable == "env":
            tail = arguments[1:]
            while tail and "=" in tail[0] and not tail[0].startswith("-"):
                tail = tail[1:]
            return cls._argv_blocker(tail, depth=depth + 1)
        return None

    @classmethod
    def _execution_blocker(
        cls, command: str, executable_name: str | None = None
    ) -> LegacyLocalExecutionBlocker | None:
        if (
            executable_name is not None
            and not cls._native_cli_name(executable_name)
            and not re.fullmatch(
                r"(?:node(?:js)?|python(?:\d+(?:\.\d+)?)?|sh|bash|zsh|fish|csh|tcsh|ksh|env|ase)",
                executable_name.lower(),
            )
        ):
            return None
        try:
            arguments = tuple(shlex.split(command))
        except ValueError:
            return "CODEX_WRAPPER_ACTIVE"
        return cls._argv_blocker(arguments, executable_name=executable_name)

    @classmethod
    def _operator_control_process(cls, command: str, executable_name: str | None = None) -> bool:
        """Exclude direct control routes, never their open files or descendants."""
        try:
            arguments = tuple(shlex.split(command))
        except ValueError:
            return False
        if not arguments:
            return False
        executable = (executable_name or Path(arguments[0]).name).lower()
        if executable == "codex-code-mode-host":
            return True
        if not cls._native_cli_name(executable):
            return False
        if ".app/contents/resources/" in command.lower():
            return False
        action = cls._codex_action(arguments[1:])
        return action == "resume" or arguments[1:4] == ("app-server", "daemon", "pid-update-loop")

    def _operator_control_pids(self, processes: dict[int, _Process]) -> frozenset[int]:
        return frozenset(
            pid
            for pid, process in processes.items()
            if self._operator_control_process(process.command, process.executable_name)
        )

    def _arguments_reference_worktree(self, arguments: tuple[str, ...], root: Path) -> bool:
        """Do not exempt a control tool explicitly targeted at the retained checkout."""
        directory_options = {"--working-dir", "-C", "--cd"}
        for index, argument in enumerate(arguments):
            self._remaining()
            option, separator, value = argument.partition("=")
            if option in directory_options:
                if not separator:
                    if index + 1 == len(arguments):
                        return True
                    value = arguments[index + 1]
                if not value.startswith("/") or self._covers(value, root):
                    return True  # relative/unknown targets do not grant attribution
            elif argument.startswith("-C") and len(argument) > 2:
                value = argument[2:]
                if not value.startswith("/") or self._covers(value, root):
                    return True
            candidate = value if separator else argument
            if candidate.startswith("/") and self._covers(candidate, root):
                return True
        return False

    def _desktop_sandbox_chains(
        self, processes: dict[int, _Process], root: Path
    ) -> dict[int, tuple[_DesktopProcessIdentity, ...]]:
        """Attribute only the native sandbox of the fixed macOS desktop CUA route.

        Process ancestry alone is insufficient. These identities do not remove
        any process or descendant from cwd/open-file checks.
        """
        if sys.platform != "darwin":
            return {}
        chains: dict[int, tuple[_DesktopProcessIdentity, ...]] = {}
        paths: dict[int, str | None] = {}
        names = ("codex", "node_repl", "node", "codex", "ChatGPT")
        for sandbox in processes.values():
            self._remaining()
            if sandbox.executable_name != "codex":
                continue
            try:
                sandbox_arguments = tuple(shlex.split(sandbox.command))
            except ValueError:
                continue
            if not sandbox_arguments or self._codex_action(sandbox_arguments[1:]) != "sandbox":
                continue
            chain: list[_Process] = []
            process: _Process | None = sandbox
            for name in names:
                if (
                    process is None
                    or process.state not in {"R", "S", "I"}
                    or process.birth == "unobserved"
                    or process.executable_name != name
                    or process.pid in {parent.pid for parent in chain}
                ):
                    break
                chain.append(process)
                process = processes.get(process.ppid)
            if len(chain) != len(names):
                continue
            identity: list[_DesktopProcessIdentity] = []
            for process in chain:
                if process.pid not in paths:
                    paths[process.pid] = self._executable_path(process.pid)
                executable_path = paths[process.pid]
                if executable_path is None:
                    break
                identity.append(
                    _DesktopProcessIdentity(
                        process.pid,
                        process.ppid,
                        process.birth,
                        process.command,
                        process.executable_name,
                        executable_path,
                    )
                )
            if len(identity) != len(names):
                continue
            # The installed trust root is fixed by this adapter, never selected
            # from an inventory's self-consistent app title or caller input.
            bundle = _DESKTOP_CONTROL_BUNDLE
            codex = str(bundle / "Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex")
            node = str(bundle / "Contents/Resources/cua_node/bin/node")
            node_repl = str(bundle / "Contents/Resources/cua_node/bin/node_repl")
            app = str(bundle / "Contents/MacOS/ChatGPT")
            script = str(
                bundle
                / "Contents/Resources/cua_node/lib/node_modules/@oai/cua-repl/bin/cua-repl.mjs"
            )
            if tuple(item.executable_path for item in identity) != (
                codex,
                node_repl,
                node,
                codex,
                app,
            ):
                continue
            try:
                arguments = tuple(tuple(shlex.split(item.command)) for item in identity)
                payload_index = sandbox_arguments.index("--") + 1
            except ValueError:
                continue
            if (
                sandbox_arguments[0] != codex
                or sandbox_arguments[payload_index : payload_index + 1] != (node,)
                or arguments[1] not in {("node_repl",), (node_repl,)}
                or arguments[2] != (node, script)
                or not arguments[3]
                or arguments[3][0] != codex
                or self._codex_action(arguments[3][1:]) != "app-server"
                or arguments[4] != (app,)
                or self._arguments_reference_worktree(sandbox_arguments, root)
            ):
                continue
            chains[sandbox.pid] = tuple(identity)
        return chains

    @staticmethod
    def _verified_desktop_sandbox_pids(
        before_chains: dict[int, tuple[_DesktopProcessIdentity, ...]],
        after_chains: dict[int, tuple[_DesktopProcessIdentity, ...]],
        before_covered: frozenset[int],
        covered: set[int],
    ) -> frozenset[int]:
        return frozenset(
            pid
            for pid, chain in before_chains.items()
            if after_chains.get(pid) == chain
            and all(item.pid in before_covered and item.pid in covered for item in chain)
        )

    def _execution_related_pids(
        self, processes: dict[int, _Process], roots: frozenset[int]
    ) -> frozenset[int]:
        """Keep live native execution descendants in the workspace check.

        Control ancestry is never permission to ignore an arbitrary child
        process or its open source files.
        """
        related = set(roots)
        changed = True
        while changed:
            self._remaining()
            changed = False
            for pid, process in processes.items():
                if pid in related or process.ppid not in related:
                    continue
                if process.state != "Z":
                    related.add(pid)
                    changed = True
        return frozenset(related)

    def _execution_pids(
        self, processes: dict[int, _Process], control_pids: frozenset[int]
    ) -> frozenset[int]:
        return frozenset(
            pid
            for pid, process in processes.items()
            if pid not in control_pids
            and process.state != "Z"
            and self._execution_blocker(process.command, process.executable_name) is not None
        )

    @staticmethod
    def _idle_terminal(process: _Process) -> bool:
        if process.state not in {"S", "I"} or process.executable_name not in {
            "sh",
            "bash",
            "zsh",
            "fish",
            "csh",
            "tcsh",
            "ksh",
        }:
            return False
        try:
            arguments = shlex.split(process.command)
        except ValueError:
            return False
        return all(
            argument in {"-l", "-i", "-il", "-li", "--login", "--interactive"}
            for argument in arguments[1:]
        )

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
        self,
        uid: int,
        root: Path,
        *,
        pids: tuple[int, ...] = (),
        ignored_pids: frozenset[int] = frozenset(),
        cwd_blocker_pids: frozenset[int] = frozenset(),
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
                if (
                    pid not in ignored_pids
                    and self._covers(value, root)
                    and (descriptor != "cwd" or pid in cwd_blocker_pids)
                ):
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
        self,
        before: dict[int, _Process],
        root: Path,
        *,
        ignored_pids: frozenset[int] = frozenset(),
        cwd_blocker_pids: frozenset[int] = frozenset(),
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
                if pid not in ignored_pids and pid in cwd_blocker_pids and self._covers(cwd, root):
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
                    if pid not in ignored_pids and self._covers(opened, root):
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
            before_desktop_chains = self._desktop_sandbox_chains(before, root)
            control_pids = self._operator_control_pids(before)
            execution_pids = self._execution_related_pids(
                before, self._execution_pids(before, control_pids)
            )
            cwd_blocker_pids = execution_pids | frozenset(
                pid for pid, process in before.items() if not self._idle_terminal(process)
            )
            # Only the observer itself is excluded from open-file checks.
            # A control session's real source descriptors still block rescue.
            observer_pids = frozenset({os.getpid()})
            covered, path_blockers = (
                self._mac_paths(
                    uid,
                    root,
                    ignored_pids=observer_pids,
                    cwd_blocker_pids=cwd_blocker_pids,
                )
                if sys.platform == "darwin"
                else self._linux_paths(
                    before,
                    root,
                    ignored_pids=observer_pids,
                    cwd_blocker_pids=cwd_blocker_pids,
                )
            )
            blockers.update(path_blockers)
            before_covered = frozenset(covered)
            after = self._processes(uid)
            after_desktop_chains = self._desktop_sandbox_chains(after, root)
            after_control_pids = self._operator_control_pids(after)
            execution_pids = execution_pids | self._execution_related_pids(
                after, self._execution_pids(after, after_control_pids)
            )
            previous_cwd_blocker_pids = cwd_blocker_pids
            cwd_blocker_pids = (
                cwd_blocker_pids
                | execution_pids
                | frozenset(
                    pid for pid, process in after.items() if not self._idle_terminal(process)
                )
            )
            missing = {
                pid: process
                for pid, process in after.items()
                if process.state != "Z"
                and (
                    pid not in covered
                    or before.get(pid) != process
                    or (pid in cwd_blocker_pids and pid not in previous_cwd_blocker_pids)
                )
            }
            if missing:
                extra_covered, extra_blockers = (
                    self._mac_paths(
                        uid,
                        root,
                        pids=tuple(sorted(missing)),
                        ignored_pids=observer_pids,
                        cwd_blocker_pids=cwd_blocker_pids,
                    )
                    if sys.platform == "darwin"
                    else self._linux_paths(
                        missing,
                        root,
                        ignored_pids=observer_pids,
                        cwd_blocker_pids=cwd_blocker_pids,
                    )
                )
                covered.difference_update(missing)
                covered.update(extra_covered)
                blockers.update(extra_blockers)
            desktop_sandbox_pids = self._verified_desktop_sandbox_pids(
                before_desktop_chains, after_desktop_chains, before_covered, covered
            )
            for process in (*before.values(), *after.values()):
                if process.state not in {"R", "S", "I", "T", "U", "D", "W", "Z"}:
                    blockers.add("PROCESS_STATE_UNKNOWN")
                if (
                    not self._operator_control_process(process.command, process.executable_name)
                    and process.state != "Z"
                    and (
                        blocker := self._execution_blocker(process.command, process.executable_name)
                    )
                    and (
                        blocker != "CODEX_WRAPPER_ACTIVE" or process.pid not in desktop_sandbox_pids
                    )
                ):
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
