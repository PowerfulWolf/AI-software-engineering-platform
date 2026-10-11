# Independent integration review

## Scope and decisions

Root reviewed the production journal, finite consumed-window chain, actual claim and
repository scope, native stop checks, frozen work budget, EngineeringAuthority,
read-side history and frontend gates. A separate reviewer reviewed the production
core and phase without modifying them. Root independently reviewed the Schema
worker's changes and the generator fix.

Two integration defects were identified and closed before publication:

1. Historical QA/Reviewer continuation knowledge could retain Task scope while
   delivery used a parent Requirement. Runtime, wait collection and history now
   share an exact legacy gap/snapshot check. The optional delivery_requirement_id
   records the verified parent without rewriting original knowledge ownership.
   Reader passes the parent separately; native preflight keeps its original scope.
2. Repair Schema regeneration dropped six existing legacy rescue allOf families.
   The generator now reuses canonical guards and has isolated red/green contract
   cases. Direct comparison against HEAD found zero lost cross-field guards.

Repository scopes are part of immutable claim identity. Provider successors retain
consumed windows within the same role/checkpoint/source slice. Current configuration
cannot reset expansion counts, and neither budget nor runtime upgrade approves a
candidate or replaces independent QA/Review.

## Root incremental verification

- Generator + knowledge retry Schema + existing resolution Schema + knowledge parity:
  71 passed in 1.80s.
- Seven related DOM suites (engineering wait, product execution, delivery status,
  operation progress, knowledge preparation timeout/gap, retry budget):
  192 passed, zero skipped or failed.
- Knowledge engineering history, including resealed wrong-request rejection,
  registered scope, parent/native separation and independent legacy gap/snapshot:
  9 passed, 27 deselected.
- Knowledge history plus the real three-projection reader wiring regression:
  10 passed, 37 deselected in 9.75s.
- Final complete engineering history regression: 36 passed in 27.53s.
- Scoped Ruff, strict mypy, format and diff checks passed. No full suite was run.

The implementation worker separately ran real isolated MySQL/native integration;
its exact commands and totals are in verification.md. The shared test database was
never used concurrently. Production SQL inspection used an explicit read-only
transaction, without constructing a mutation Host or changing records.

## Production read measurement and existing data

An isolated process ran the current ProductionTeamReader against the existing
project with a 45-second hard limit. It returned in 7.816s, read 2 Requirements and
25 Task projections, and peaked at 695,451,648 bytes RSS on macOS. The same K1
Requirement projected DELIVERING / ROLE_RUNNING and correctly identified its
current Coder main invocation. This is one full-read sample, not a long-running
memory-leak test or proof that the currently running service already has the fix.

At measurement time the original service and Operation were active. No service
restart, duplicate Continue, source rebase or new Requirement was performed. K1
retains its existing source/worktree, progress, failed attempts and approvals.
Deploy only after current work is safely idle; use the controlled service restart.
No database migration, historical receipt fabrication or manual attempt reset is
required. Missing legacy invocation facts remain missing and use the established
public recovery path rather than being invented by this patch.

Rollback must retain readers for already consumed knowledge resolution facts.
Do not delete events, reset work counters or deploy an old writer that cannot read
the new typed resolution.
