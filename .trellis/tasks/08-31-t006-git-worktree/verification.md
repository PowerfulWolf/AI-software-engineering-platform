# T006 Verification

## Standards Check

- `GitWorkspace` is a typed Protocol with one local `GitWorktreeManager` adapter. `WorktreeSpec`, `WorktreeRef`, and `WorktreeSnapshot` are typed values; domain enums remain imported from the canonical domain module.
- Coder worktrees use `ai/<task-id>/attempt-<n>` branches. QA and Reviewer receive distinct detached worktrees at the exact candidate SHA. Main checkout is never selected as an Agent workspace, and configured roots or pre-existing task symlinks cannot escape containment.
- `WorkspacePolicy` is bound to the role worktree root. Read/write paths are separate, deny globs win, `.git` and symlink escapes are rejected, and command allowlists match token prefixes rather than substrings.
- Git calls use argv, explicit cwd, bounded timeout, minimal environment, `shell=False`, hooks/fsmonitor disabled, and external diff/textconv disabled. Repository-local external checkout filters fail closed because v0.1 does not yet provide a process sandbox.

## Cross-Layer Check

- Flow verified: `AgentPermissions` + Task deny paths → root-bound `WorkspacePolicy` → normalized path/argv decision; `WorktreeSpec` → revision resolution → role-specific worktree layout → `WorktreeRef` → `inspect`/cleanup evidence.
- Existing Task, Agent, Artifact, StateEvent, SQLite, and JSON Schema contracts were not duplicated or weakened. Git worktree data is runtime metadata and does not cross the existing artifact wire schemas yet.
- Errors stay at the Repository Plane seam: invalid repository/root/revision/configuration, collision, unmanaged reference, dirty cleanup, Git failure/timeout, path policy, and command policy each have stable typed outcomes.

## Unit and Fixture Coverage

- 10 real-Git worktree tests cover Coder isolation, detached QA/Reviewer candidate SHA, staged/unstaged/untracked inspection, dirty preservation, clean removal with branch retention, invalid role/repository/root/revision, symlink escape, collision, forged reference, hook suppression, and external filter rejection.
- 15 pure policy tests cover read/write separation, deny precedence, canonical/traversal/`.git` checks, symlink containment, empty write allowlist, token-prefix authorization, command collisions, shell-like argv, and unsafe allowlist entries.
- Tests use temporary fixture repositories and public seams; internal subprocess calls are not mocked.

## Validation Evidence

```text
ruff format --check .                   PASS (85 files)
ruff check .                            PASS
mypy src tests                          PASS (40 source files)
pytest                                  PASS (137 tests)
uv lock --check                         PASS (41 packages resolved)
git diff --check                        PASS
uv build                                PASS (sdist + wheel)
```

No major or blocking finding remains. T006 completes the M2 Git/workspace isolation slice without adding a queue, vector store, remote service, automatic merge, or process sandbox. The latter remains an explicit follow-up requirement before enabling arbitrary repository filters or broader command execution.
