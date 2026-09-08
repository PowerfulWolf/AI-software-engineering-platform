# Implementation progress

- Read-only existing-store reproduction: RuntimeWorkspaceConflict at fixed policy ID.
- Red test: new version write rejected by old API. Implemented opt-in versioned immutable store,
  deterministic production policy version, exact resolver reads, both dispatch call sites.
- Initial new test fixture used invalid routes; corrected fixture to preserve eligible tiers and
  unique provider/model pairs. These were fixture errors, not a relaxation of domain validation.
- Runtime/workforce/scheduler tests passed; Ruff and strict mypy passed. Real Git/MySQL offline
  native and recovery regression passed: 74 tests / 287.58s. Full suite: 892 passed / 383.64s.
  Ruff check/format, strict mypy (286 files), offline lock/build and diff-check passed.
  No real demand model invocation after preflight failure.

## Bug analysis

1. Root cause B/D/E: configurable model content was coupled to an immutable fixed identity;
   fresh-workspace tests assumed configuration never changed.
2. Merely replacing the CLI model fixed access but exposed this independent persistence failure.
3. Prevention: immutable content revisions, exact selection-version reads, existing-org regression.
4. Expansion checked: native dispatch, recovery dispatch and low-level RuntimeWorkforceResolver;
   AgentProfile remains stable. General policy management/version promotion remains out of scope.
5. Knowledge captured in production-team-host and python-runtime specs. No spec template tree exists.
