# Increment B implementation / validation plan

1. Define strict capture/source/plan/command/decision/receipt models and JSON Schema.
2. Contract tests for round-trip, tamper, cross-identity and no execution authority.
3. Scoped append-only store: read-only open, explicit initialize, concurrent first-winner, corruption,
   symlink/root replacement, short writes and no target-project mutations.
4. Authorization service with explicit ports: fresh facts before/after human verification, replay
   without callbacks, reject stale facts at execution gate, rejected decision, no runtime calls.
5. Full offline-model regression including dedicated MySQL test DB; Ruff/format/Mypy/lock/build;
   update executable spec, archive and external observation log; commit locally, no push.

Rollback: isolated commit revert; no old record migration and no target worktree/Task state changes.

## Result — 2026-09-07

Steps 1–5 implemented and verified: 42 new recovery tests, full regression 842 passed /81.74s,
Ruff/format, Mypy (267 files), offline lock/build and diff-check passed. Durable scope is revalidated on
reopen/read; original decision replay does not bypass fresh execution admission. Schema and executable
spec have been synchronized. Production execution integration remains outside this increment.

## Increment C1 result — 2026-09-07

Added native original-source reader and explicit read-only upstream stores. Source inspection verifies
Task/dispatch/event snapshot, authoritative READY/approval/design/planner chain, preparation,
Coder context/route and joint delegation. No target preparation or execution capability is added.
Native stores retain their formats; reader reuses their validation rather than duplicating decoders.

135 targeted tests; final full suite 850 passed /84.30s. Ruff/format485files/Mypy269files/offline
lock/build/diff-check passed. Actual round3 read-only inspection succeeded with the unchanged known
source/parent digests. Old checkpoint timestamps are initiating-command times, not a causal ordering
fence for model completion; identity/state chains remain authoritative. No paid model calls.
