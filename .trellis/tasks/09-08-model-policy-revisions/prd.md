# Immutable production model-policy revisions

## Goal and evidence

Approved recovery533febc8 stops before seed/provider: production _workforce reuses policy ID/version
while changing its model. Existing immutable put_policy raises RuntimeWorkspaceConflict. A read-only
reproduction against the existing record confirms this. No requirement code is involved.

## Requirements and acceptance

- Keep AgentProfile identity and default policy ID stable.
- Publish new policy versions without overwriting the legacy record or old dispatch selections.
- Production version is deterministic from complete policy content, excluding version itself.
- Resolve ModelSelection by exact policy ID/version; no latest-version fallback.
- Both native and recovery dispatch use the same revision storage.
- Test two models in one organization, exact replay, conflicting same-version payload, legacy
  lookup, missing version and corrupted revision. Existing runtime allocation tests must pass.

## Decision / scope

Use the existing ModelPolicy.version and ModelSelection.policy_version contract. Add opt-in versioned
storage and exact-version reads; legacy writes/reads remain available. Unlike changing Agent IDs,
this preserves team identity; unlike replacing the fixed policy file, it preserves history.
No automatic model discovery/fallback, database migration, new state machine, or old Task resurrection.
Current user authorization covers fixing platform workflow bugs; model choice was already approved.
No unresolved product preference. Expand later to policy administration, not in this repair.

## Files / verification / rollback

runtime_workspace.py; production_backend.py; recovery/entry.py; focused tests and production spec.
Run focused runtime/workforce/production/recovery tests then full offline suite, lint/type/build.
Rollback code/config only; keep published immutable revisions and all historical records.
