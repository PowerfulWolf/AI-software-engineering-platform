"""Repository Plane interfaces for role-isolated Git worktrees."""

from ai_software_engineer.git.policy import (
    CommandPolicyViolation,
    PathPolicyViolation,
    WorkspacePolicy,
    WorkspacePolicyError,
)
from ai_software_engineer.git.ports import (
    GitWorkspace,
    WorktreeRef,
    WorktreeSnapshot,
    WorktreeSpec,
)
from ai_software_engineer.git.worktree import (
    DirtyWorktree,
    GitCommandError,
    GitCommandTimeout,
    GitWorkspaceError,
    GitWorktreeManager,
    InvalidRepository,
    InvalidWorktreeRoot,
    RevisionNotFound,
    UnmanagedWorktree,
    UnsafeRepositoryConfiguration,
    WorktreeAlreadyExists,
)

__all__ = [
    "CommandPolicyViolation",
    "DirtyWorktree",
    "GitCommandError",
    "GitCommandTimeout",
    "GitWorkspace",
    "GitWorkspaceError",
    "GitWorktreeManager",
    "InvalidRepository",
    "InvalidWorktreeRoot",
    "PathPolicyViolation",
    "RevisionNotFound",
    "UnmanagedWorktree",
    "UnsafeRepositoryConfiguration",
    "WorkspacePolicy",
    "WorkspacePolicyError",
    "WorktreeAlreadyExists",
    "WorktreeRef",
    "WorktreeSnapshot",
    "WorktreeSpec",
]
