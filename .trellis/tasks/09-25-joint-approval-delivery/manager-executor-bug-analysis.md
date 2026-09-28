# Bug Analysis: unconnected Manager recovery and unproven execution boundaries

## 1. Root Cause Category

B (cross-layer contract), D (coverage gap), E (implicit assumption): a tested recovery class was
mistaken for a wired production path; normal subprocess success was mistaken for CLI OS-sandbox
success. Human approval of a plan did not make missing execution capability exist.

## 2. Why Fixes Failed

Installing Xcode supplied XCTest but not platform authority. Relocating caches fixed one denial,
then exposed nested SwiftPM sandbox denial. A retained readonly outer sandbox still exposed Xcode
27's default swiftbuild linking failure; the explicitly selected native backend passed. None of
these observations establishes UI acceptance, so a further blind approval loop is not a solution.

## 3. Prevention Mechanisms

| Priority | Mechanism | Action | Status |
|---|---|---|---|
| P0 | Production wiring | Manager incident persisted from sealed inconclusive QA | Implemented/tested/live proposal |
| P0 | Authority separation | Capability belongs to exact-plan executor, not model allowlist | Implemented/tested |
| P0 | Actual isolation | Both role fixtures test XCTest plus denied source writes/network | Passed |
| P0 | Recovery evidence | STARTED/final receipts, timeout blocked, uncertain start no replay | Implemented/tested |
| P1 | Wire/history | Optional fields omitted from legacy plans, explicit schema generator | Tested |
| P1 | Honest UI | Display incident, restricted capability and outstanding UI conditions | Tested/live API |

## 4. Systematic Expansion

Other languages need their own bounded executors and environment facts, not Swift conditions in
universal project knowledge. No generic installer or self-promoting Skill was added. UI automation
and isolated data remain distinct capabilities requiring real verification. Regular delivery and
upstream phases still need a later comprehensive prerequisite integration; do not claim this slice
fixed every lifecycle stage. Model gateway failures also remain independent of the Swift toolchain.

## 5. Knowledge Capture

Updated `verification-environment.md`, core index, Swift spec, public contracts and AGENTS.
No `src/templates/markdown/spec/` tree exists here, so no template counterpart is applicable.
No commit/archive: this is an unfinished live delivery in a pre-existing dirty user worktree.
Formal command receipt proves the approved candidate's 20 tests pass under the new executor;
only sealed independent QA/Reviewer and full acceptance can establish delivery completion.
