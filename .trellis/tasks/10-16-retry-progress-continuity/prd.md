# Preserve accepted progress across exact same-base stopped-failure retries

## Goal

An exact stopped_failure_retry preserves the complete legal draft on the same source.
It must also preserve the applicable already accepted coder-progress when selecting the
next serial work slice. Failure recovery must not silently repeat completed work merely
because the generic source-rebind path retires its progress artifact.

## Scope and boundaries

Use the maintenance worktree; never write the running K1 Coder checkout. Change only the
execution-baseline service's retirement decision and focused baseline/runtime regressions,
plus .trellis/spec/core/stopped-failure-retry.md and this task's documents. Final exact
source/test paths are recorded in design.md before implementation.

Keep all historical binding, authority, progress, failure and evaluation bytes immutable.
Do not remove existing superseded IDs, revive retired artifacts in a read-side resolver,
reset Task state or directly write production SQL. Source-changing/reapply recovery and
other recovery families retain their existing retirement behavior.

## Acceptance

- A newly approved same-source stopped_failure_retry with an existing accepted progress
  must preserve that progress through the real binding/resolver/runner work-slice path.
- Completed step01 remains completed; the next slice selects the next unfinished step,
  with unchanged full workspace validation, source, claim, budget and candidate gates.
- Exact replay and repeated retries do not retire accepted progress, consume extra budget
  or rewrite old accepted/failed records.
- A source-changing or coder_reapply baseline still retires incompatible old progress.
- Invalid, unaccepted, corrupt or source-incompatible progress cannot gain acceptance.
- Existing K1 bindings keep their historical retirement declarations. The active native
  Coder is allowed to produce a new independently validated progress artifact in its
  current explicitly selected step01/02 slice; this is the preferred existing-data repair.

## Verification and rollback

Establish RED at the actual recovery-to-slice seam before changing code; GREEN targeted
unit/contract/runtime tests, lint/format/typecheck and independent read-only review.
Use the isolated test MySQL only if the public integration regression requires it, never
production fixtures. Deploy at an observed idle boundary with controlled restart.
Before publishing new bindings, revert code if needed; after publication keep additive
compatible readers and use a forward fix. Never delete historical records or drafts.
