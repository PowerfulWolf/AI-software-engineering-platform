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
    RecoverableGitWorkspace,
    RevisionNotFound,
    UnmanagedWorktree,
    UnsafeRepositoryConfiguration,
    WorktreeAlreadyExists,
    WorktreeIdentityDrift,
    WorktreeNotFound,
    WorktreeRevisionDrift,
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
    "RecoverableGitWorkspace",
    "RevisionNotFound",
    "UnmanagedWorktree",
    "UnsafeRepositoryConfiguration",
    "WorkspacePolicy",
    "WorkspacePolicyError",
    "WorktreeAlreadyExists",
    "WorktreeIdentityDrift",
    "WorktreeNotFound",
    "WorktreeRef",
    "WorktreeRevisionDrift",
    "WorktreeSnapshot",
    "WorktreeSpec",
]
