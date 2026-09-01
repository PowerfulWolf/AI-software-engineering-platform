"""Policy-bound tool registry used by Coder, QA, and Reviewer runs."""

import hashlib
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol

from ai_software_engineer.domain import AgentDefinition
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.execution import (
    CommandExecutionError,
    CommandExecutor,
    CommandResult,
    CommandTimedOut,
    SubprocessCommandExecutor,
)
from ai_software_engineer.git import PathPolicyViolation, WorkspacePolicy, WorkspacePolicyError

from .models import (
    ReadFileRequest,
    ReadFileResult,
    RunCommandRequest,
    RunCommandResult,
    ToolRejectedResult,
    ToolRequest,
    ToolResult,
    WriteFileRequest,
    WriteFileResult,
)

_SHELL_EXECUTABLES = frozenset(
    {"sh", "bash", "dash", "zsh", "fish", "ksh", "csh", "tcsh", "cmd", "powershell", "pwsh"}
)


class ToolProtocolError(RuntimeError):
    """Base class for tool protocol configuration and validation errors."""


class ToolRequestIdentityMismatch(ToolProtocolError):
    """Raised when a request attempts to use another role/run's tool registry."""


class ToolBackend(Protocol):
    """Minimal command port required by :class:`PolicyBoundToolRegistry`."""

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult: ...


class PolicyBoundToolRegistry:
    """Expose only typed, policy-authorized operations for one Agent run.

    The registry intentionally has no ``shell``/``exec(text)`` method and no
    verdict or artifact mutation operation.  A reviewer can inspect files and run
    allowlisted commands, but cannot write anything; QA writes only under
    ``tests/``; Coder writes only paths granted by its role policy.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        agent: AgentDefinition,
        *,
        run_id: str | None = None,
        denied_paths: tuple[str, ...] = (),
        command_executor: CommandExecutor | None = None,
        max_read_bytes: int = 1_000_000,
    ) -> None:
        if max_read_bytes < 1 or max_read_bytes > 10_000_000:
            raise ValueError("max_read_bytes must be between 1 and 10000000")
        self._workspace_root = Path(workspace_root).resolve()
        self._agent = agent
        self._run_id = run_id
        self._policy = WorkspacePolicy(
            self._workspace_root,
            agent.permissions,
            denied_paths=denied_paths,
        )
        self._executor = command_executor or SubprocessCommandExecutor(
            self._workspace_root,
            agent.permissions,
            denied_paths=denied_paths,
        )
        self._max_read_bytes = max_read_bytes

    @property
    def role(self) -> AgentRole:
        return self._agent.role

    def execute(self, request: ToolRequest) -> ToolResult:
        """Execute one validated request, returning a typed success or refusal."""
        if request.role is not self._agent.role:
            raise ToolRequestIdentityMismatch(
                f"request role {request.role.value} does not match bound role "
                f"{self._agent.role.value}"
            )
        if self._run_id is not None and request.run_id != self._run_id:
            raise ToolRequestIdentityMismatch("request run_id does not match bound run")
        if isinstance(request, ReadFileRequest):
            return self._read_file(request)
        if isinstance(request, WriteFileRequest):
            return self._write_file(request)
        if isinstance(request, RunCommandRequest):
            return self._run_command(request)
        # TypeAdapter guarantees this branch is unreachable for external input.
        raise ToolProtocolError(f"unsupported tool request: {type(request).__name__}")

    def _read_file(self, request: ReadFileRequest) -> ToolResult:
        try:
            path = self._policy.authorize_read(request.path)
            absolute = self._absolute(path)
            with absolute.open("rb") as stream:
                payload = stream.read(min(request.max_bytes, self._max_read_bytes) + 1)
        except WorkspacePolicyError as error:
            return self._rejected(request, "PATH_DENIED", str(error))
        except FileNotFoundError:
            return self._rejected(request, "FILE_NOT_FOUND", "requested file does not exist")
        except IsADirectoryError:
            return self._rejected(request, "NOT_A_FILE", "requested path is a directory")
        except OSError:
            return self._rejected(request, "FILE_READ_FAILED", "requested file could not be read")
        truncated = len(payload) > min(request.max_bytes, self._max_read_bytes)
        if truncated:
            payload = payload[: min(request.max_bytes, self._max_read_bytes)]
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError:
            return self._rejected(request, "NON_UTF8_FILE", "tool protocol only returns UTF-8 text")
        return ReadFileResult(
            run_id=request.run_id,
            role=request.role,
            operation_id=request.operation_id,
            path=path.as_posix(),
            content=content,
            content_sha256=hashlib.sha256(payload).hexdigest(),
            bytes_read=len(payload),
            truncated=truncated,
        )

    def _write_file(self, request: WriteFileRequest) -> ToolResult:
        try:
            path = self._policy.authorize_write(request.path)
            self._authorize_role_write(path)
            absolute = self._absolute(path)
            parent = absolute.parent
            if not parent.is_dir():
                return self._rejected(
                    request,
                    "PARENT_NOT_FOUND",
                    "parent directory does not exist",
                )
            payload = request.content.encode("utf-8")
            # A same-directory temporary + replace prevents readers from seeing a
            # partially written report and does not follow an existing target link.
            fd, temporary_name = tempfile.mkstemp(prefix=".ase-tool-", dir=parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, absolute)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
        except WorkspacePolicyError as error:
            return self._rejected(request, "PATH_DENIED", str(error))
        except PermissionError:
            return self._rejected(request, "WRITE_DENIED", "file cannot be written")
        except OSError:
            return self._rejected(request, "FILE_WRITE_FAILED", "file could not be written")
        return WriteFileResult(
            run_id=request.run_id,
            role=request.role,
            operation_id=request.operation_id,
            path=path.as_posix(),
            content_sha256=hashlib.sha256(payload).hexdigest(),
            bytes_written=len(payload),
        )

    def _run_command(self, request: RunCommandRequest) -> ToolResult:
        if Path(request.argv[0]).name.lower() in _SHELL_EXECUTABLES:
            return self._rejected(
                request,
                "COMMAND_DENIED",
                "shell interpreters are not exposed through the tool protocol",
            )
        try:
            result = self._executor.run(
                request.argv,
                timeout_seconds=request.timeout_seconds,
            )
        except WorkspacePolicyError as error:
            return self._rejected(request, "COMMAND_DENIED", str(error))
        except CommandTimedOut as error:
            return self._rejected(request, "COMMAND_TIMED_OUT", str(error))
        except CommandExecutionError as error:
            return self._rejected(request, "COMMAND_FAILED_TO_START", str(error))
        return RunCommandResult(
            run_id=request.run_id,
            role=request.role,
            operation_id=request.operation_id,
            command=result,
        )

    def _authorize_role_write(self, path: PurePosixPath) -> None:
        if self._agent.role is AgentRole.REVIEWER:
            raise PathPolicyViolation("reviewer has no repository write capability")
        if self._agent.role is AgentRole.QA and (not path.parts or path.parts[0] != "tests"):
            raise PathPolicyViolation("qa may write only under tests/")
        if any(
            part == ".trellis"
            or part in {"artifacts", "state", "verdict"}
            or "report" in part.lower()
            for part in path.parts
        ):
            raise PathPolicyViolation("role tools cannot modify policy, artifact, or verdict files")

    def _absolute(self, path: PurePosixPath) -> Path:
        return self._workspace_root.joinpath(*path.parts)

    def _rejected(self, request: ToolRequest, code: str, message: str) -> ToolRejectedResult:
        return ToolRejectedResult(
            run_id=request.run_id,
            role=request.role,
            operation_id=request.operation_id,
            tool=request.tool,
            error_code=code,
            error_message=message or "tool request rejected",
        )


__all__ = [
    "PolicyBoundToolRegistry",
    "ToolBackend",
    "ToolProtocolError",
    "ToolRequestIdentityMismatch",
]
