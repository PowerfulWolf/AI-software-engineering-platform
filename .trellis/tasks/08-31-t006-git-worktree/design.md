# T006 Technical Design

## Confirmed Public Seams

The project bootstrap contract already names `GitWorkspace.create/inspect`, and the accepted T006 scope requires machine path/command policy. Tests therefore target only these two public seams:

| Module interface | Input | Output | Failure behavior |
|---|---|---|---|
| `GitWorkspace.create` | validated `WorktreeSpec` | immutable `WorktreeRef` | stable repository, revision, collision, or command error; no target reuse |
| `GitWorkspace.inspect` | manager-issued `WorktreeRef` | immutable `WorktreeSnapshot` | reject unmanaged/missing/mismatched worktree |
| `GitWorkspace.remove` | manager-issued `WorktreeRef` | `None` | reject unmanaged or dirty worktree; never force-delete |
| `WorkspacePolicy.authorize_read` | bound worktree root + repository-relative path | normalized POSIX path | `PathPolicyViolation` on invalid, escaping, or unauthorized path |
| `WorkspacePolicy.authorize_write` | bound worktree root + repository-relative path | normalized POSIX path | deny overrides allow; empty write allowlist fails closed |
| `WorkspacePolicy.authorize_command` | already-tokenized argv | immutable argv tuple | `CommandPolicyViolation` on empty, shell-like, or unmatched command |

`GitWorkspace` is retained as a Protocol because it is a project-level port explicitly required by the Python runtime contract; `GitWorktreeManager` is the v0.1 local Git CLI adapter.

## Layout and Revision Rules

```text
<worktree-root>/<task-id>/
├── coder-attempt-01/       # branch ai/<task-id>/attempt-1
├── qa-attempt-01/          # detached candidate SHA
└── reviewer-attempt-01/    # detached candidate SHA
```

Every source ref is resolved to a full commit SHA before `git worktree add`. Coder alone receives a branch; QA and Reviewer are detached. A retry uses a new attempt number, directory, and Coder branch. The main checkout is never selected as an Agent working directory, and a pre-existing symlink under the configured root cannot redirect a Task target outside that root.

## Policy Matching

- `WorkspacePolicy` binds the concrete role worktree root. Runtime paths are repository-relative POSIX paths; empty, absolute, backslash-containing, NUL-containing, `.`/`..`, and any `.git` segment are invalid.
- Existing symlink parents are resolved before authorization; the result must remain below the bound root and outside its `.git` control path.
- Explicit deny globs take precedence over read/write allow globs.
- Write authorization uses only `permissions.write_paths`; read authorization uses only `permissions.read_paths`.
- Command allowlist entries are parsed once as token prefixes (`"git diff"` means argv beginning with `("git", "diff")`, not `git push`). Runtime commands must already be argv tokens; shell control tokens and line breaks are rejected even though the adapter never enables a shell.
- This policy is an application guard, not an OS/container sandbox. A later command executor must also apply cwd/env/network/resource constraints and record rejection evidence.

## Git Subprocess Contract

The adapter invokes Git with `shell=False`, an argv sequence, a fixed timeout, an explicit cwd, and a minimal environment containing only deterministic locale, system `PATH`, `GIT_CONFIG_NOSYSTEM=1`, and `GIT_TERMINAL_PROMPT=0`. Every invocation overrides `core.hooksPath=/dev/null` and `core.fsmonitor=false`; inspection disables external diff/textconv. Repository-local checkout filters are rejected before `worktree add` because v0.1 has no process sandbox. Non-zero exit and timeout map to stable typed errors with sanitized command evidence.

## Validation and Error Matrix

| Input or state | Detection point | Result |
|---|---|---|
| repository missing/not Git | manager initialization/first operation | `InvalidRepository` |
| worktree root inside main checkout or target symlink escapes root | create guard | `InvalidWorktreeRoot` |
| orchestrator or unknown role | `WorktreeSpec` validation | Pydantic `ValidationError` |
| source ref missing/not commit | revision resolution | `RevisionNotFound` |
| repository-local external checkout filter | pre-create config inspection | `UnsafeRepositoryConfiguration` |
| target path or Coder branch exists | pre-create guard | `WorktreeAlreadyExists` |
| returned ref path escapes root or metadata mismatches layout | inspect/remove ownership guard | `UnmanagedWorktree` |
| worktree has tracked/untracked changes | remove precondition | `DirtyWorktree` and preserve directory |
| absolute/traversal/`.git`/denied path | policy normalization/match | `PathPolicyViolation` |
| argv empty, shell-like, or no exact allowed prefix | policy match | `CommandPolicyViolation` |
| Git timeout/non-zero exit | subprocess adapter | `GitCommandTimeout` / `GitCommandError` |

## Good / Base / Bad

- **Good**: Coder commits a candidate; QA and Reviewer are created detached at that exact SHA; their worktrees are independently inspectable and removable only when clean.
- **Base**: a clean fixture repository creates and removes one role worktree offline using the system Git executable.
- **Bad**: concatenate an Agent-provided shell string, create a role worktree inside the main checkout, accept `../secrets` or a symlink escape, execute repository hook/filter, match `git push` because `git` appears in an allowlist, or force-remove a dirty worktree.

## Test Seams

1. `GitWorktreeManager` against real temporary Git repositories: create, isolate, inspect, collision/error, dirty cleanup, clean cleanup.
2. `WorkspacePolicy` bound to a temporary worktree root: Good/Base/Bad lexical path, symlink containment, and argv cases.

Tests do not mock internal Git calls or assert subprocess call counts/order.
