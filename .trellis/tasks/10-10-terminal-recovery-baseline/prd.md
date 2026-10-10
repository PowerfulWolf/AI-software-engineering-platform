# Terminal recovery after a verified source update

## Goal

Allow the original, terminal K1 delivery source to be inspected after a legitimate same-Task
execution baseline update. Preserve the frozen Task/approval/dispatch and every historical event.
Do not include platform fixes from before the effective execution base in the requirement patch.

## Scope

- Validate pre-candidate StateEvent source epochs against the complete, store-verified baseline
  binding chain, including exact event revision, attempt and completion-time boundaries.
- Bind terminal recovery to the current execution baseline through the original immutable
  invocation request and required Context, with paired optional wire references.
- Keep original approved `base_revision` distinct from the effective recovery capture base.
- Synchronize recovery consumers, schemas and incremental contracts.
- No production writes, recovery approval/execution, service restart, reset, cleanup or commit.
- Existing terminal workspace containment/stop/inventory prerequisites remain separate gates.

## Acceptance

- Historical records without a baseline keep identical wire content and SHA-256.
- The 17 old-base events followed by the legitimate attempt-8 terminal event pass source epoch
  validation when all four verified bindings match; unknown/early/stale epochs reject.
- Wrong task, scope, predecessor, revision, attempt, digest or required Context reject.
- Current recovery capture uses the approved execution base rather than frozen Task base.
- Source-reader inspection remains read-only; old Task and events are unchanged.
- Only incremental tests, Ruff and strict type checks run.

## Production observation

The formal `NativeRecoverySourceReader.inspect` and its read-only SQL gate rejected the existing
native delivery on 2026-10-10 with `pre-candidate event source revision mismatch`.
The frozen base is `0a562f4f64ea5bbc63c371513bb623b1fe5b2101`; event revision 18 and the latest
verified execution baseline use `4bf596d5ed487b96c1fbfbee892bdfba58457e1d`.

## Rollback

Revert only this task's source/schema/test/spec changes. Optional references are omitted from
historical records; do not rewrite persisted Task/event/plan bytes or discard the retained worktree.
