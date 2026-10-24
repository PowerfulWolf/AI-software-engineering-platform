# Native execution observations survive bounded interruption

## Goal
Preserve bounded, body-free original pipe/event observations for future Coder native
runs, so a real local timeout can be investigated without reading raw provider logs.
K1's historical fourth run remains unknown beyond its real 1800-second owned stop.

## Scope
Only this isolated 67daf0e source mirror. Existing runner/drain/parser, a private typed
observation, exact capture-linked immutable store, deletion closure, tests and specs.
No provider calls, production API/DB edits, source baseline change, schema inventory
regeneration, restart, budget change, retrospective backfill or role verdict change.

## Acceptance
- Actual raw byte counts, first/last relative byte times, real EOF flags and fixed
  root JSONL event counts survive an actual owned timeout and sidecar reopen.
- Counts/timing are diagnostic only. No event body, tool args, path, URL, credential,
  prompt or arbitrary event type survives serialization or repr.
- Poisoned/partial/oversized/duplicate-key/invalid UTF8 JSONL never claims complete
  trusted counts. Counters saturate; memory and watchdog fairness stay bounded.
- New record binds original capture start/stop, Task/Run/claim/source/Context/scope.
  Existing stop/receipt bytes and all state/authority/budget semantics stay unchanged.
- Missing/failed telemetry reads as explicit UNAVAILABLE with no zero substitute;
  a telemetry write failure cannot erase or replace the actual stop/outcome.
- Requirement physical deletion includes only exact validated new records and
  continues rejecting unknown, foreign, altered or late-added files.

## Verification
Focused pure parser/drain tests first, then no-provider real subprocess and real
Git/SQLite continuation/store tests. Root runs OS-denied cases outside sandbox.
Ruff/format/strict Mypy on changed Python files. No MySQL reset or production model.

## Rollback
No SQL migration or historical rewrite. Before new records exist revert code;
after publication keep private reader/deletion compatibility. Do not delete facts.
