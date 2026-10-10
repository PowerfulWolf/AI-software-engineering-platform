# Design

## Boundaries

Only the existing Console read-side UI changes. No schema/API, database, Task, role authority,
plan digest, native-rule approval, model or production operation changes.

## Current exact decision

`requestBlockerSection` retains `latestApproval(request.id, request.checkpoint_sha256)` as its
current approval source. `recoveryApprovalBox` uses an always-visible section; plan title,
facts, consequence and the precise action are outside any closed native `details`. Optional
metadata elsewhere remains folded. Current business/engineering duties remain explicit. Both
blocked placement and nonblocked `requestOperation` must avoid introducing closed ancestor folds.
Consumption recognizes scope, plan and prerequisite-repair digests per issuance.

The action freezes its exact input and visible approval signature at render. Before POST it
checks current Project/Requirement/checkpoint, current unconsumed approval, service capability,
control readiness and absence of an active operation. A stale detached callback cannot approve
new facts or revive history. Displaying, polling or expanding details issues no command.

## Paused current version

`engineeringBaselinePauseFacts` remains the only validated source. After binding passes,
`engineeringBaselinePauseBox` displays its `expected_source_revision` as the saved code version
that continuation will actually use, independent of any proposal/history. The current-version
block signature includes the complete source/baseline binding. Unrelated polling retains it;
a source change replaces it. Do not initialize target input with a guessed SHA or main/HEAD.

## Contract tests

1. Native disclosure-aware traversal proves current recovery/scope approval facts and actions
   are visible, not merely present in DOM; full Requirement and nonblocked action placement are
   both exercised. Every approval kind is consumed by its corresponding digest.
2. Saved callbacks fail closed after checkpoint, digest/facts, consumed approval, current
   Project/readiness/capability/active-operation changes; fresh exact input remains unchanged.
3. Pause without a proposal shows its saved source, retains its block on unrelated heartbeat,
   replaces it on bound source changes, and submits only the new exact continuation.

## Verification and rollback

Incremental `node --test` for the two owned UI files, `node --check app.js` and `git diff --check`.
No full suite. Browser authentication is unavailable, so real-browser layout/visual acceptance
is explicitly outstanding. No existing-data migration: refresh repaired assets on the same
Requirement. Revert these frontend changes and refresh to roll back; audit history stays intact.
