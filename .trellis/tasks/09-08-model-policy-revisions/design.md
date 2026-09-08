# Model policy revision contract

Follow production-team-host.md / Immutable policy revisions. Existing version fields carry identity;
no new wire/SQL schema. Production _workforce hashes full canonical policy excluding version. Agent
default policy family ID is unchanged. put_policy(versioned=True) stores a version-keyed immutable
envelope; exact-version get falls back to legacy only when legacy version matches. Resolver passes
selected version. Native and recovery producers both publish revisioned policy.

Tests must exercise legacy policy plus changed configuration in one existing organization, not just
two fresh organizations. Missing/corrupt/conflicting versions fail closed. No authentic provider call
is needed for regression; real Git/MySQL with scripted providers exercises dispatch and delivery.

No product requirement edits, schema relaxation, old-state reset, or automatic provider fallback.
