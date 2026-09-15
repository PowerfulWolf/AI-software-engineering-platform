# Requirement source baseline design

## Data flow

```text
Requirement intake
  -> capture Repository HEAD as DirectoryUnit.base_revision
  -> create/recover a detached read-only baseline worktree per Requirement + Repository
  -> seal preparation/profile/spec/context facts in the Requirement checkpoint

Product / Designer / Planner
  -> run against the retained baseline worktree(s)

Native child delivery
  -> replay the sealed preparation
  -> dispatch Task.base_ref = DirectoryUnit.base_revision
  -> Coder creates its own writable Task worktree from that commit

QA / Review / joint integration
  -> verify exact candidate commits
  -> return candidates for final human merge
```

## Baseline layout

The hardened `GitWorktreeManager` is reused to materialize an exact detached checkout:

```text
<platform_root>/worktrees/requirements/<delivery_id>/<unit_id>/
  <baseline_task_id>/reviewer-attempt-01
```

The Reviewer role is deliberately used because baseline inspection is read-only and detached.
The path is deterministic, and recovery verifies the registered Git worktree, detached identity,
HEAD and cleanliness. The Requirement worktree remains registered so Git retains the commit even
when the configured checkout advances.

## Runtime changes

- `JointBackend.client` receives the whole checkpoint so it can resolve the exact Requirement
  baseline paths rather than the mutable source roots.
- The configured structured-client factory accepts one primary root plus additional read-only roots;
  Codex CLI receives them through `--add-dir`.
- The derived native backend receives a frozen `PrepareProjectResult` and source revision. It
  replays those facts and uses the pinned commit for dispatch instead of reading the current checkout
  HEAD.
- Reconciliation validates retained baseline worktrees and sealed preparation facts. It no longer
  compares the configured checkout HEAD with the Requirement baseline.
- Initial preparation still fences a clean checkout at the captured commit before and after reading
  project facts, closing the intake race.

## Failure behavior

- Baseline commit unavailable: reject and ask the operator to restore the recorded commit/worktree.
- Baseline worktree HEAD/identity/cleanliness drift: reject and preserve it for inspection.
- Configured checkout advances after preparation: allowed; no journal change and no re-preparation.
- Knowledge/spec/profile changes after preparation: future Requirements see them; the current
  Requirement keeps its sealed facts.

## Rollback

Revert the implementation commit. Existing baseline worktrees are read-only and can remain as
recoverable evidence; no source branch or Requirement journal is rewritten by this change.
