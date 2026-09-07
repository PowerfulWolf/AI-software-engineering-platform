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

## Increment C2 result — 2026-09-07

Repository seed implemented with real isolated-index conflict preflight, fresh target identity and
both policies. Post-apply interruption preserves evidence. Original source files/index/refs remain
unchanged; attributes changes and custom merge behavior are rejected. No production entry added.

Full regression: 867 passed /198.85s. After final `.gitattributes` guard and public error export,
final seed suite: 18 passed /72.42s. Ruff/format (488 files), Mypy (270 files), offline lock/build and
diff-check pass. Source-only changes; no business DB writes, live model calls or original Coder edits.
Next: target preparation/carry-forward, authorized new execution and seed receipt/provider admission.

## Increment C3 result — 2026-09-07

Native source/current target gate and authorized in-memory Task draft implemented. Shared Host rule
builder avoids mismatched company context; original request/Task join already-verified source facts.
Draft keeps original stage digests, budgets and constraints, and cannot overwrite old request history.
No persisted recovery execution or actual model/Task run yet.

Full 870 passed /140.55s; Ruff/format493files/Mypy274files/offline lock/build/diff-check passed.
Actual original-base inspection passed with unchanged capture955b3247, BLOCKED/revision3 and 15 files.
No real Task draft or plan persisted, business writes, candidate, QA or Review. Zero real model calls.

## Increment D1 result — 2026-09-07

Sealed Task input model/schema, scoped store and current-fact sealing/admission service implemented.
Historical read is deliberately separate from current execution admission. New Task remains only a
sealed recovery input, not a MySQL Task or allocation/dispatch. No live business effects.

Recovery61 passed /46.65s; full879 passed /153.94s. First full collection caught missing Schema
registration identity; fixed `$id/$schema`, added focused checks and reran full regression.
Ruff/format497files, strict Mypy277files, offline lock/build and diff-check passed. Zero real models.
