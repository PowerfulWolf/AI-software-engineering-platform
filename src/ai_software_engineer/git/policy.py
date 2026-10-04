"""Fail-closed path and command policy for role worktrees."""

import re
import shlex
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Final

from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.swift_verification import is_restricted_swift_command


class WorkspacePolicyError(RuntimeError):
    """Base class for stable workspace authorization failures."""


class PathPolicyViolation(WorkspacePolicyError):
    """Raised when a repository path is invalid, denied, or not allowed."""


class CommandPolicyViolation(WorkspacePolicyError):
    """Raised when argv is unsafe or does not match an allowed token prefix."""


_SHELL_CONTROL_TOKENS: Final = frozenset({";", "&&", "||", "|", ">", ">>", "<", "<<"})
_PYTEST_SELECTOR = re.compile(
    r"^tests/(?:[A-Za-z0-9_][A-Za-z0-9_.-]*/)*test_[A-Za-z0-9_.-]+\.py"
    r"(?:::[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)?)?"
    r"(?:\[[A-Za-z0-9_.-]+\])?$"
)
_PYTEST_EXECUTABLES: Final = frozenset({"pytest", "py.test", "pytest-3"})


def is_protected_rule_path(path: str | PurePosixPath) -> bool:
    """Trellis belongs to the organization; no role grant makes it writable."""
    return any(part.casefold() == ".trellis" for part in PurePosixPath(path).parts)


def delivery_write_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    """Remove explicit native-rule paths; broad globs still face the runtime gate."""
    return tuple(path for path in paths if not is_protected_rule_path(path))


class WorkspacePolicy:
    """Authorize normalized repository operations against effective Agent permissions."""

    def __init__(
        self,
        workspace_root: str | Path,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
        require_focused_tests: bool = False,
    ) -> None:
        self._workspace_root = Path(workspace_root).resolve()
        if not self._workspace_root.is_dir():
            raise PathPolicyViolation(f"workspace root is not a directory: {self._workspace_root}")
        self._read_paths = _validated_patterns(permissions.read_paths)
        self._write_paths = _validated_patterns(permissions.write_paths)
        self._denied_paths = _validated_patterns(denied_paths)
        self._commands = _validated_commands(permissions.commands)
        self._require_focused_tests = require_focused_tests

    def authorize_read(self, path: str | PurePosixPath) -> PurePosixPath:
        """Return a normalized readable path or fail closed."""
        return self._authorize_path(path, self._read_paths, operation="read")

    def authorize_write(self, path: str | PurePosixPath) -> PurePosixPath:
        """Return a normalized writable path or fail closed."""
        return self._authorize_path(path, self._write_paths, operation="write")

    def authorize_historical_capture(self, path: str | PurePosixPath) -> PurePosixPath:
        """Read-only audit of old grants, never permission to write or seed them.

        Original read/write allowlists and explicit denies still apply. Only the
        dedicated legacy-capture service uses this check to preserve old mistakes.
        """
        self.authorize_read(path)
        return self._authorize_path(path, self._write_paths, operation="historical capture")

    def authorize_command(self, arguments: tuple[str, ...]) -> tuple[str, ...]:
        """Return safe argv when it starts with one complete allowed token prefix."""
        if not arguments or any(_is_shell_like(token) for token in arguments):
            raise CommandPolicyViolation("command argv is empty or contains shell syntax")
        if not any(
            len(arguments) >= len(prefix) and arguments[: len(prefix)] == prefix
            for prefix in self._commands
        ):
            raise CommandPolicyViolation(f"command is not allowed: {arguments[0]}")
        if arguments[0] == "swift" and not is_restricted_swift_command(arguments):
            raise CommandPolicyViolation(
                "Swift verification arguments exceed the restricted policy"
            )
        if self._require_focused_tests:
            _authorize_focused_pytest(arguments)
        return arguments

    def _authorize_path(
        self,
        path: str | PurePosixPath,
        allowed_patterns: tuple[str, ...],
        *,
        operation: str,
    ) -> PurePosixPath:
        normalized = _normalize_runtime_path(path)
        rendered = normalized.as_posix()
        self._validate_containment(normalized, operation=operation)
        if operation == "write" and (
            is_protected_rule_path(normalized)
            or is_protected_rule_path(
                (self._workspace_root / normalized)
                .resolve()
                .relative_to(self._workspace_root)
                .as_posix()
            )
        ):
            raise PathPolicyViolation(f"Trellis 规范为只读, 禁止 Agent 写入: {rendered}")
        if any(fnmatchcase(rendered, pattern) for pattern in self._denied_paths):
            raise PathPolicyViolation(f"{operation} path is explicitly denied: {rendered}")
        if not any(fnmatchcase(rendered, pattern) for pattern in allowed_patterns):
            raise PathPolicyViolation(f"{operation} path is not allowed: {rendered}")
        return normalized

    def _validate_containment(self, path: PurePosixPath, *, operation: str) -> None:
        try:
            candidate = (self._workspace_root / path).resolve(strict=False)
            git_control_path = (self._workspace_root / ".git").resolve(strict=False)
        except (OSError, RuntimeError) as error:
            raise PathPolicyViolation(f"cannot resolve {operation} path: {path}") from error
        if not candidate.is_relative_to(self._workspace_root):
            raise PathPolicyViolation(f"{operation} path escapes workspace: {path}")
        if candidate == git_control_path or git_control_path in candidate.parents:
            raise PathPolicyViolation(f"{operation} path resolves into .git: {path}")


def _normalize_runtime_path(path: str | PurePosixPath) -> PurePosixPath:
    if isinstance(path, PurePosixPath):
        raw_path = path.as_posix()
    elif isinstance(path, str):
        raw_path = path
    else:
        raise PathPolicyViolation("repository path must be text")
    _validate_path_text(raw_path, label="repository path")
    return PurePosixPath(raw_path)


def _validated_patterns(patterns: tuple[str, ...]) -> tuple[str, ...]:
    for pattern in patterns:
        _validate_path_text(pattern, label="path pattern", allow_glob=True)
    return patterns


def _validated_commands(commands: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    validated: list[tuple[str, ...]] = []
    for command in commands:
        try:
            tokens = tuple(shlex.split(command, posix=True))
        except ValueError as error:
            raise CommandPolicyViolation(f"invalid command allowlist entry: {command!r}") from error
        if not tokens or any(_is_shell_like(token) for token in tokens):
            raise CommandPolicyViolation(f"invalid command allowlist entry: {command!r}")
        validated.append(tokens)
    return tuple(validated)


def _is_shell_like(token: str) -> bool:
    return (
        not token
        or token in _SHELL_CONTROL_TOKENS
        or any(ord(character) < 32 for character in token)
        or "$(" in token
        or "`" in token
    )


def _authorize_focused_pytest(arguments: tuple[str, ...]) -> None:
    """Reject verifier commands that can silently collect the whole test suite.

    QA and Reviewer prompts are advisory. This check is the executable boundary for
    Responses tool calls, including common wrapper forms such as ``uv run`` and
    ``python -m pytest``. ``pytest.main`` is intentionally rejected because the
    command policy cannot prove which selectors that Python string will collect.
    """
    lowered = tuple(token.lower() for token in arguments)
    if any("pytest.main" in token for token in lowered):
        raise CommandPolicyViolation(
            "pytest 执行被拒绝: QA/Review 必须使用 tests/ 下明确的测试文件或节点选择器,"
            "不得通过 pytest.main 运行未验证的测试范围"
        )
    pytest_index = next(
        (
            index
            for index, token in enumerate(arguments)
            if Path(token).name.lower() in _PYTEST_EXECUTABLES
            or (token.lower() == "pytest" and index > 0)
        ),
        None,
    )
    if pytest_index is None:
        if "-m" in lowered:
            marker_index = lowered.index("-m")
            if marker_index + 1 < len(lowered) and lowered[marker_index + 1] == "pytest":
                raise CommandPolicyViolation(
                    "pytest 执行被拒绝: QA/Review 必须提供 tests/ 下明确的测试文件或节点选择器"
                )
        if "-c" in lowered and any("pytest" in token for token in lowered):
            raise CommandPolicyViolation(
                "pytest 执行被拒绝: QA/Review 不得通过 Python 字符串动态收集全量测试"
            )
        return
    selectors = arguments[pytest_index + 1 :]
    if not any(_PYTEST_SELECTOR.fullmatch(token) for token in selectors):
        raise CommandPolicyViolation(
            "pytest 执行被拒绝: QA/Review 必须提供 tests/ 下明确的测试文件或节点选择器"
        )


def _validate_path_text(value: str, *, label: str, allow_glob: bool = False) -> None:
    if not value or "\\" in value or any(ord(character) < 32 for character in value):
        raise PathPolicyViolation(f"invalid {label}: {value!r}")
    candidate = PurePosixPath(value)
    parts = value.split("/")
    if candidate.is_absolute() or any(part in {"", ".", "..", ".git"} for part in parts):
        raise PathPolicyViolation(f"invalid {label}: {value!r}")
    if not allow_glob and any(character in value for character in "*?["):
        raise PathPolicyViolation(f"runtime {label} cannot contain glob syntax: {value!r}")
