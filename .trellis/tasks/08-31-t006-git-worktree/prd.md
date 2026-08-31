# T006 — Isolated Git Worktrees and Workspace Policy

## Goal

Provide the Repository Plane seam that creates isolated Coder, QA, and Reviewer Git worktrees and rejects path or command operations outside the effective machine policy.

## Requirements

- Define typed `GitWorkspace`, `WorktreeSpec`, `WorktreeRef`, and `WorktreeSnapshot` contracts.
- Create Coder worktrees on `ai/<task-id>/attempt-<n>` from an explicitly resolved source revision.
- Create QA and Reviewer worktrees detached at the same immutable candidate revision.
- Keep all role worktrees under the configured `worktrees/<task-id>/` root and reject collisions, path escapes, invalid roles, and unknown revisions.
- Inspect a role worktree through Git and return its exact HEAD plus sorted changed paths.
- Remove only a clean, manager-owned worktree; preserve dirty worktrees for evidence and recovery.
- Enforce read/write glob allowlists, explicit deny globs, `.git` protection, relative-path normalization, symlink containment under a bound worktree root, and command token-prefix allowlists before execution.
- Invoke Git with argument arrays, bounded timeout, explicit working directory, a minimal environment, and no shell; disable repository hooks/fsmonitor/external diff and reject external checkout filters before they can run.

## Acceptance Criteria

- [x] A real fixture repository can create an isolated Coder worktree without changing the main checkout.
- [x] QA and Reviewer worktrees are detached at the same candidate commit and use distinct directories.
- [x] Existing target/branch collisions, invalid roles, and unknown revisions produce stable typed errors.
- [x] Inspection reports exact HEAD and staged, unstaged, and untracked changed paths.
- [x] Clean manager-owned worktrees can be removed; dirty worktrees are never removed silently.
- [x] Allowed paths/commands pass, while traversal, symlink escape, absolute paths, `.git`, denied paths, unauthorized writes, command prefix collisions, and shell-control tokens fail closed.
- [x] Repository `post-checkout` hooks cannot execute; repository-local external checkout filters are rejected before worktree creation.
- [x] Tests use real temporary Git repositories and exercise only the public seams, without mocking internal subprocess calls.
- [x] Ruff, strict mypy, pytest, lock, build, and diff checks pass.

## Out of Scope

- Executing arbitrary Agent commands, process/container sandboxing, network isolation, secret redaction, or resource limits beyond Git command timeout.
- Automatically committing Agent changes, merging candidate branches, pushing refs, or deleting branches.
- Parallel Agents, worktree pooling, remote repositories, distributed locks, or multi-repository Tasks.

## Rollback

Revert the single T006 commit. The implementation never auto-removes the caller's main checkout or candidate branches; runtime worktree directories remain recoverable until explicitly cleaned through the manager.
