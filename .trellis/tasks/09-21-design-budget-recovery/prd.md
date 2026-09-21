# Restore design after knowledge-only budget exhaustion

## Goal
Preserve approved Requirement history while allowing a Design checkpoint whose attempts were consumed by knowledge gates to resume safely.

## Requirements
- Knowledge gap handling must not consume the Design artifact attempt budget when no TechnicalDesign was requested.
- Existing DESIGNING checkpoints with exhausted budget and approved historical knowledge resolutions must expose an explicit, auditable design recovery action.
- Recovery must be bound to the exact checkpoint and approved resolution, append a new hash-chain checkpoint, reset only the Design budget, and continue through the normal Designer validation path.
- Active delivery stages must not expose generic continuation.

## Acceptance Criteria
- [ ] Knowledge-only Design waits preserve the unused Design budget.
- [ ] Three real invalid Design artifacts still exhaust the budget and cannot be silently retried.
- [ ] A current DESIGNING checkpoint with no design/plan and a matching approved knowledge resolution offers RECOVER_DESIGN; stale or unapproved recovery is rejected.
- [ ] Recovery preserves all prior journal records and approval/product facts and records operator/rationale/reference in the recovery operation/checkpoint action.
- [ ] Regression tests cover the current persisted shape and console intent path.

## Validation
- pytest targeted manager, team_view and web_console tests
- ruff check, mypy, JS syntax
