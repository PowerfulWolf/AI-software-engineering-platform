"""Local Git CLI adapter for isolated role worktrees."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Final

from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.git.ports import WorktreeRef, WorktreeSnapshot, WorktreeSpec

_GIT_ENV: Final[dict[str, str]] = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": os.defpath,
}
_GIT_SAFETY_CONFIG: Final[tuple[str, ...]] = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
)


class GitWorkspaceError(RuntimeError):
    """Base class for stable Repository Plane failures."""


class InvalidRepository(GitWorkspaceError):
    """Raised when the configured repository is missing or not a Git root."""


class InvalidWorktreeRoot(GitWorkspaceError):
    """Raised when role worktrees would be created inside the main checkout."""


class UnsafeRepositoryConfiguration(GitWorkspaceError):
    """Raised when checkout could execute a repository-configured program."""


class RevisionNotFound(GitWorkspaceError):
    """Raised when a source ref cannot be resolved to a commit."""


class WorktreeAlreadyExists(GitWorkspaceError):
    """Raised when a target path or Coder branch is already present."""


class UnmanagedWorktree(GitWorkspaceError):
    """Raised when a reference does not identify a worktree owned by this manager."""


class DirtyWorktree(GitWorkspaceError):
    """Raised when cleanup would discard tracked or untracked evidence."""

    def __init__(self, changed_paths: tuple[str, ...]) -> None:
        super().__init__(f"worktree has unsaved changes: {', '.join(changed_paths)}")
        self.changed_paths = changed_paths


class GitCommandError(GitWorkspaceError):
    """Raised when an allowlisted Git command returns a non-zero status."""


class GitCommandTimeout(GitWorkspaceError):
    """Raised when an allowlisted Git command exceeds its fixed timeout."""


class GitWorktreeManager:
    """Create role worktrees without using the main checkout as an Agent workspace."""

    def __init__(
        self,
        repository: str | Path,
        worktree_root: str | Path,
        *,
        command_timeout_seconds: float = 30.0,
    ) -> None:
        self._repository = Path(repository).resolve()
        self._worktree_root = Path(worktree_root).resolve()
        self._command_timeout_seconds = command_timeout_seconds
        self._git = shutil.which("git", path=os.defpath)

    def create(self, spec: WorktreeSpec) -> WorktreeRef:
        """Create one new role worktree at a fully resolved commit."""
        self._validate_repository()
        self._validate_repository_filters()
        self._validate_worktree_root()
        source_revision = self._resolve_revision(spec.source_revision)
        target = self._target_path(spec)
        self._validate_target_containment(target)
        branch = self._branch_name(spec) if spec.role is AgentRole.CODER else None

        if target.exists() or (branch is not None and self._branch_exists(branch)):
            raise WorktreeAlreadyExists(str(target if target.exists() else branch))

        target.parent.mkdir(parents=True, exist_ok=True)
        arguments = ["worktree", "add"]
        if branch is None:
            arguments.append("--detach")
        else:
            arguments.extend(("-b", branch))
        arguments.extend((str(target), source_revision))
        self._run_git(tuple(arguments), cwd=self._repository)

        return WorktreeRef(
            task_id=spec.task_id,
            role=spec.role,
            attempt=spec.attempt,
            path=target,
            head_revision=source_revision,
            branch=branch,
            detached=branch is None,
        )

    def inspect(self, worktree: WorktreeRef) -> WorktreeSnapshot:
        """Return the exact HEAD and changed repository paths for a managed worktree."""
        path = self._validate_owned_worktree(worktree)
        head_revision = self._run_git(("rev-parse", "HEAD"), cwd=path)
        tracked = self._run_git_bytes(
            ("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", "HEAD", "--"),
            cwd=path,
        )
        untracked = self._run_git_bytes(
            ("ls-files", "--others", "--exclude-standard", "-z"), cwd=path
        )
        changed_paths = tuple(sorted(_decode_nul_paths(tracked + untracked)))
        return WorktreeSnapshot(head_revision=head_revision, changed_paths=changed_paths)

    def remove(self, worktree: WorktreeRef) -> None:
        """Remove one clean managed worktree while retaining its Git branch and commits."""
        snapshot = self.inspect(worktree)
        if snapshot.dirty:
            raise DirtyWorktree(snapshot.changed_paths)
        self._run_git(("worktree", "remove", str(worktree.path.resolve())), cwd=self._repository)

    def _validate_repository(self) -> None:
        if self._git is None or not self._repository.is_dir():
            raise InvalidRepository(str(self._repository))
        try:
            top_level = self._run_git(("rev-parse", "--show-toplevel"), cwd=self._repository)
        except GitWorkspaceError as error:
            raise InvalidRepository(str(self._repository)) from error
        if Path(top_level).resolve() != self._repository:
            raise InvalidRepository(f"repository must be a Git root: {self._repository}")

    def _resolve_revision(self, revision: str) -> str:
        try:
            return self._run_git(
                ("rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"),
                cwd=self._repository,
            )
        except GitWorkspaceError as error:
            raise RevisionNotFound(revision) from error

    def _validate_repository_filters(self) -> None:
        completed = self._invoke_git(
            (
                "config",
                "--local",
                "--name-only",
                "--get-regexp",
                r"^filter\..*\.(clean|smudge|process)$",
            ),
            cwd=self._repository,
        )
        if completed.returncode == 0:
            keys = ", ".join(completed.stdout.splitlines())
            raise UnsafeRepositoryConfiguration(
                f"external checkout filters require a stronger sandbox: {keys}"
            )
        if completed.returncode != 1:
            message = completed.stderr.strip() or "cannot inspect repository filter config"
            raise GitCommandError(message)

    def _validate_worktree_root(self) -> None:
        if (
            self._worktree_root == self._repository
            or self._repository in self._worktree_root.parents
        ):
            raise InvalidWorktreeRoot(
                f"worktree root must be outside main checkout: {self._worktree_root}"
            )

    def _validate_target_containment(self, target: Path) -> None:
        try:
            resolved_target = target.resolve(strict=False)
        except (OSError, RuntimeError) as error:
            raise InvalidWorktreeRoot(f"cannot resolve worktree target: {target}") from error
        if not resolved_target.is_relative_to(self._worktree_root):
            raise InvalidWorktreeRoot(f"worktree target escapes configured root: {target}")

    def _branch_exists(self, branch: str) -> bool:
        completed = self._invoke_git(
            ("show-ref", "--verify", "--quiet", f"refs/heads/{branch}"),
            cwd=self._repository,
        )
        return completed.returncode == 0

    def _target_path(self, spec: WorktreeSpec) -> Path:
        return self._worktree_root / spec.task_id / f"{spec.role.value}-attempt-{spec.attempt:02d}"

    @staticmethod
    def _branch_name(spec: WorktreeSpec) -> str:
        return f"ai/{spec.task_id}/attempt-{spec.attempt}"

    def _validate_owned_worktree(self, worktree: WorktreeRef) -> Path:
        expected = (
            self._worktree_root
            / worktree.task_id
            / f"{worktree.role.value}-attempt-{worktree.attempt:02d}"
        )
        if worktree.path.resolve() != expected.resolve() or not expected.is_dir():
            raise UnmanagedWorktree(str(worktree.path))
        try:
            common_directory = self._run_git(
                ("rev-parse", "--path-format=absolute", "--git-common-dir"), cwd=expected
            )
        except GitWorkspaceError as error:
            raise UnmanagedWorktree(str(worktree.path)) from error
        if Path(common_directory).resolve() != (self._repository / ".git").resolve():
            raise UnmanagedWorktree(str(worktree.path))
        return expected

    def _run_git(self, arguments: tuple[str, ...], *, cwd: Path) -> str:
        completed = self._invoke_git(arguments, cwd=cwd)
        if completed.returncode != 0:
            command = " ".join(("git", *arguments))
            message = completed.stderr.strip() or "Git command failed"
            raise GitCommandError(f"{command}: {message}")
        return completed.stdout.strip()

    def _run_git_bytes(self, arguments: tuple[str, ...], *, cwd: Path) -> bytes:
        if self._git is None:
            raise InvalidRepository("Git executable is unavailable")
        try:
            completed = subprocess.run(
                (self._git, *_GIT_SAFETY_CONFIG, *arguments),
                cwd=cwd,
                env=_GIT_ENV,
                check=False,
                capture_output=True,
                text=False,
                timeout=self._command_timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise GitCommandTimeout("Git command timed out") from error
        except OSError as error:
            raise GitCommandError("Git command could not start") from error
        if completed.returncode != 0:
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise GitCommandError(message or "Git command failed")
        return completed.stdout

    def _invoke_git(
        self, arguments: tuple[str, ...], *, cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        if self._git is None:
            raise InvalidRepository("Git executable is unavailable")
        try:
            return subprocess.run(
                (self._git, *_GIT_SAFETY_CONFIG, *arguments),
                cwd=cwd,
                env=_GIT_ENV,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._command_timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise GitCommandTimeout("Git command timed out") from error
        except OSError as error:
            raise GitCommandError("Git command could not start") from error


def _decode_nul_paths(payload: bytes) -> set[str]:
    try:
        return {raw_path.decode("utf-8") for raw_path in payload.split(b"\0") if raw_path}
    except UnicodeDecodeError as error:
        raise GitCommandError("Git returned a non-UTF-8 repository path") from error
