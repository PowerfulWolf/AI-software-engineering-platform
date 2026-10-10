# Implementation

## Changes

- Current recovery/file-scope approval is an always-visible section. The existing exact title,
  facts, consequence and action are retained; optional engineering identities remain folded.
- Nonblocked `requestOperation` preserves the visible current decision instead of adding a closed
  engineering ancestor. `latestApproval` now recognizes consumed prerequisite-repair digests too.
- Added `submitRecoveryApprovalOperation` to freeze render-time input and reject a changed
  checkpoint/approval, consumed or closed history, Project/capability/readiness drift and active
  parallel operation before submission. Existing scope/repair/plan payload mapping is unchanged.
- Pause shows the validated saved `expected_source_revision` without requiring a proposal. Its
  `viewBlock` signature uses the complete baseline binding; no target SHA/main is guessed.
- Added compact current-version card styling using existing card colors and wrapping.
- Updated the older live-view contract that directed all technical approvals into folds, and
  added executable current-decision/pause contracts and the existing-data/rollback procedure.

## Red → Green evidence

Before production edits, the 3 new engineering-wait selectors failed for hidden native-details
approval, old callback posting after checkpoint change and missing saved-source node. The full
Requirement fixture selector independently failed its new native visibility assertion.
After the fix, those 4 selectors passed; the two affected Node test files pass together.
Independent review identified the nonblocked ancestor fold and missing repair-consumption digest;
two additional contract selectors went red before the correction and green afterward.

## Boundaries

No API/schema/backend/production operation or persistent data changes. No automatic baseline target
selection; the separate generic exact-SHA input remains. No browser visual acceptance claimed.
