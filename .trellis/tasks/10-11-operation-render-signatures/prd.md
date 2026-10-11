# Bounded operation rendering signatures

## Goal
Keep complete verifiable operation history and exact approval facts while avoiding
repeatedly stringifying megabytes of immutable baseline captures for DOM invalidation.

## Measured problem
The current production response contains 309 complete operations and 9,339,214 bytes.
Four historical baseline proposals account for about 8.66 MB. A local Chrome fixture
using that preserved response serialized 26.63 million characters in an unchanged
poll and 69.74 million after a Requirement text update. This is frontend allocation
and CPU overhead, not evidence that it causes the independent Team-read admission wait.

## Scope and acceptance
- Use backend-validated operation identity/digest only as read-side render sources.
- Preserve full API responses, visible history, immutable results and approval inputs.
- Fall back to complete facts for missing or invalid operation identity/digest.
- A changed digest refreshes the row and current controls; an unchanged digest does
  not repeatedly serialize its heavy immutable result.
- Scope/readiness/checkpoint changes still invalidate old approval callbacks.
- Run focused DOM/browser regressions and repeat the measured Chrome fixture.
- No production mutation, full suite, cross-snapshot fact cache or new API contract.

## Existing data and rollback
No database/history changes. Existing valid operation hashes already cover their
complete canonical facts. Missing historical digests retain the previous comparison
behavior. Deploy after the active Operation safely ends; refresh the same Requirement.
Revert the presentation commit to restore full serialization, retaining all evidence.
