"""Compose manager-owned role worktrees with the policy-bound command executor."""

from collections.abc import Mapping
from dataclasses import dataclass

from ai_software_engineer.domain import AgentDefinition
from ai_software_engineer.execution import (
    CommandExecutor,
    CommandExecutorSettings,
    SubprocessCommandExecutor,
)
from ai_software_engineer.git import (
    GitWorkspace,
    WorktreeRef,
    WorktreeSnapshot,
    WorktreeSpec,
)


class RoleWorktreeError(RuntimeError):
    """Base class for role worktree composition failures."""


class RoleWorktreeAgentMismatch(RoleWorktreeError):
    """Raised when a worktree spec and AgentDefinition belong to different roles."""


@dataclass(frozen=True, slots=True)
class RoleWorktreeBinding:
    """Immutable manager-issued worktree and its role-bound command port."""

    worktree: WorktreeRef
    executor: CommandExecutor


class RoleWorktreeSession:
    """Open and close one role worktree while preserving Git and executor guards."""

    def __init__(
        self,
        git_workspace: GitWorkspace,
        *,
        environment: Mapping[str, str] | None = None,
        environment_allowlist: tuple[str, ...] = ("PATH", "LANG", "LC_ALL"),
        default_timeout_seconds: float = 600.0,
        max_output_bytes: int = 1_000_000,
    ) -> None:
        self._git_workspace = git_workspace
        self._environment = environment
        self._settings = CommandExecutorSettings(
            environment_allowlist=environment_allowlist,
            default_timeout_seconds=default_timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    def open(
        self,
        spec: WorktreeSpec,
        agent: AgentDefinition,
        *,
        denied_paths: tuple[str, ...] = (),
    ) -> RoleWorktreeBinding:
        """Create a role worktree and bind its Agent permissions to the command executor."""
        if spec.role is not agent.role:
            raise RoleWorktreeAgentMismatch(
                f"worktree role {spec.role.value} does not match agent role {agent.role.value}"
            )
        worktree = self._git_workspace.create(spec)
        try:
            executor = SubprocessCommandExecutor(
                worktree.path,
                agent.permissions,
                denied_paths=denied_paths,
                environment=self._environment,
                environment_allowlist=self._settings.environment_allowlist,
                default_timeout_seconds=self._settings.default_timeout_seconds,
                max_output_bytes=self._settings.max_output_bytes,
            )
        except Exception as error:
            try:
                self._git_workspace.remove(worktree)
            except Exception as cleanup_error:
                error.add_note(f"role worktree cleanup failed: {cleanup_error}")
            raise
        return RoleWorktreeBinding(worktree=worktree, executor=executor)

    def inspect(self, binding: RoleWorktreeBinding) -> WorktreeSnapshot:
        """Return current Git evidence for a manager-issued binding."""
        return self._git_workspace.inspect(binding.worktree)

    def close(self, binding: RoleWorktreeBinding) -> None:
        """Remove only a clean manager-owned worktree; dirty evidence is preserved."""
        self._git_workspace.remove(binding.worktree)


__all__ = [
    "RoleWorktreeAgentMismatch",
    "RoleWorktreeBinding",
    "RoleWorktreeError",
    "RoleWorktreeSession",
]
