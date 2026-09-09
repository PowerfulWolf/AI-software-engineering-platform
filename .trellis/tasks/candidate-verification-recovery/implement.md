# Progress

- [x] Record scope and choose provenance-preserving verification execution.
- [x] Offline verification execution and negative tests.
- [x] Durable approved plan and per-role invocation admission.
- [x] Immutable completion bound to approved artifacts and admitted verifier runs; exact replay.
- [x] Read-only candidate SQL snapshot validator and legacy stale-projection regression tests.
- [x] Shared native approval-chain reader and candidate source reader; validated against original requirement read-only.
- [x] Native source/current policy/allocation/worktree integration.
- [x] CLI and original joint demand result association without rewriting old checkpoints.
- [x] Annotated commands and targeted/real-MySQL quality gates.

No live model invocation is part of this development task. A real `verify-propose` and
`verify-inspect` were run against the preserved candidate; they created only an immutable sidecar
plan and confirmed approval/result are absent.

Latest targeted verification: 91 recovery tests passed, 7 MySQL-dependent tests skipped;
Ruff/format/Mypy (310 files) and diff-check passed. Full suite must be rerun after integration.

Final integration verification supersedes that intermediate snapshot: 999 full-suite tests passed
with the dedicated MySQL database; final focused recovery/CLI/worktree tests passed 43/43 and final
real-MySQL dispatch/native tests passed 14/14. Ruff/format covered 562 files, strict Mypy covered 313
source files, offline sdist/wheel build passed, and real non-model propose/inspect acceptance passed.

Integration constraint discovered: MySqlDispatchAuthority._current_snapshot filters every lease
whose Task is terminal. A new verification allocation cannot simply reuse the failed Task's old
dispatch, or be inserted as ordinary recovery dispatch: it would not count against capacity.
Verification needs separately tracked execution liveness in the shared reservation authority,
without resetting the original Task or manufacturing a new Coder Task. The reservation contract,
worktree consumer and native approved-stage resolver are now wired before exposing the CLI.

Reservation integration now has 6 passing real MySQL tests in the dedicated test database,
including concurrent exact replay and release. Shared approval-chain refactoring passes 8 native
recovery tests against that test database. Candidate snapshot/admission focused suite: 14 passing.
Original requirement read-only inspection now resolves candidate dcc2ab1fd65fc12d18ea48ba7dcab869ea6fdeda
and its joint parent. Legacy QA failure events carry base SHA; candidate_ready and implementation
jointly establish candidate identity. Arbitrary foreign failure-event revisions are still rejected.
No live QA/Reviewer call, production record update, branch edit or candidate reset has occurred.

Final command surface: `verify-propose` pins candidate/current allocation, `verify-inspect` reads,
`verify-approve` seals exact human consent, and `verify-run` invokes only QA then Reviewer. The
original Task ID remains in reports while a separate execution Task ID scopes Assignment, Lease and
worktree names so terminal-task capacity filtering cannot release live verifier work.

Post-live retry correction: a first QA provider call ended with a durable `RATE_LIMITED` route attempt
and no report. The source reader then included that run in its append-only history, while current-fact
validation compared the entire input object exactly and mislabeled the platform's own admitted run as
source drift. Validation now permits only run additions sealed by this exact plan, while retaining
exact checks for every other fact and rejecting foreign additions/removals. A consumed plan stops
before provider reuse and directs the operator to propose and approve a new plan for the same
candidate; Coder is not rerun.
