# Reclaimed, uninvoked Coder claim in a legacy rescue

## Goal

Keep the original K1 Requirement deliverable after a Coder WorkItem was claimed,
expired before its first main invocation, and then claimed again for a real
start-only invocation whose outcome and native stop were not sealed.

## Scope

- Baseline collection may classify the earlier claim only from its original
  CLAIMED record, exact EXPIRED/LEASE_EXPIRED facts, complete negative main-run
  observation, and a later distinct claim with an exact invocation start.
- The current start-only invocation retains `UNKNOWN`. Existing local survey,
  human cessation declaration, complete draft capture, Task/queue fences, and
  independent QA/Review remain mandatory.
- No production MySQL edits, original record rewrite, fabricated preflight or
  stop fact, source rebind, budget refund, or changed role permissions.

## Acceptance

- A two-claim fixture with no first invocation/preflight and a second start-only
  invocation can prepare a bound legacy rescue proof.
- A first-claim start, route, capture, artifact, incomplete knowledge execution,
  missing/changed expiry, wrong generation, or changed later claim rejects.
- Recollection before queue consumption sees the same exact proof or refuses.
- Schema regeneration preserves all changed proof contracts; targeted tests,
  lint, type checking and isolated public API fixture pass.

## Allowed paths

`src/ai_software_engineer/{manager,work_queue}/`, focused tests in
`tests/{manager,work_queue,contracts}/`, exact affected `schemas/` and generator,
this task directory, and `.trellis/spec/core/legacy-execution-rescue.md`.

## Rollback

Revert the platform commit before a new rescue is consumed. Keep any immutable
plans, operations and UNKNOWN execution history already created; do not rewrite
them. A previously approved plan must fail current-fact validation on an older
binary rather than silently continuing.
