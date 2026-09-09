# Candidate verification recovery

## Goal and scope

Complete the generic post-candidate recovery path: when Coder has already produced a durable commit
but the original delivery becomes terminal during QA, retain that Task/history and run only fresh,
independent QA and Reviewer against the same candidate.

## Delivered capability

- Top-level `verify-propose / verify-inspect / verify-approve / verify-run` commands.
- Exact native Task/event/dispatch/artifact and optional joint-parent provenance checks.
- Immutable plan, exact human authorization, pre-provider invocation receipts, and sealed completion.
- A distinct verification execution Task ID for QA/Reviewer Assignment, Lease and worktree identity;
  reports continue to bind the original Task and candidate.
- MySQL verification reservations participate in the ordinary global capacity fence and release only
  after trusted completion validation.
- QA FAIL stops before Reviewer; Review REJECT and uncertain invocation never rerun Coder or rewrite
  the original terminal Task.

## Verification evidence

- Full suite with dedicated MySQL database: `999 passed in 456.92s`.
- Final focused recovery/CLI/worktree suite: `43 passed`.
- Final real MySQL dispatch/native suite: `14 passed`.
- Ruff: all checks passed; format: 562 files; strict Mypy: 313 source files.
- Offline package build produced the v0.1 source distribution and wheel.
- Real non-model acceptance pinned candidate `dcc2ab1fd65fc12d18ea48ba7dcab869ea6fdeda`,
  produced a plan, and read it back with `approved=false`, no invocations and no completion.

## Preserved boundaries

The feature does not mark the failed Task or joint checkpoint DONE, fabricate a Coder result, run
joint integration automatically, merge, push or deploy a candidate. A completion is an auditable
association with the original demand; human/project delivery policy remains the final acceptance
boundary. Provider invocation was deliberately not performed during implementation verification.

## Post-release correction: terminal Task planning composition

The first live `verify-run` safely stopped before any provider invocation with
`approved planning lineage does not match the Task`. The stored request, Product/Design/Plan chain,
candidate and approval were all current. The composition layer had incorrectly instantiated the
normal `ExecutionPlanAgentAdapter`, whose valid contract requires a `NEW` Task, for the intentionally
terminal source Task used by candidate verification.

Candidate verification now composes `DispatchDeliveryAgentAdapter` with no planning adapter and
explicitly refuses Orchestrator/Coder requests. Normal delivery still requires a planning adapter;
constructor guards make the two modes mutually exclusive. A focused regression went red on the old
`NoneType.run` behavior and green after the change. The real stored FAILED Task plus active
verification reservation was then assembled read-only as `QA_REVIEWER_ONLY_READY`; no worktree or
provider was created.

## Commit

This archive is stored in the implementation commit; use that commit as the immutable baseline.

## Post-release correction: failed verifier successor plan

The first admitted QA call returned a durable `RATE_LIMITED` failure. Its run correctly became part
of native history, but the freshness gate incorrectly treated every post-proposal run addition as
external source drift. The gate now accepts only append-only runs backed by this plan's immutable
invocation receipts. Missing historical runs, foreign runs and all non-run changes still fail closed.

The same approved plan remains at-most-once and cannot call QA again. `verify-run` now reports the
consumed role/run before allocation or provider work and instructs the operator to run
`verify-propose` again for the same project/delivery. The successor plan receives a new digest,
approval, execution Task and verifier run IDs while retaining the same candidate; Coder never runs.

### Bug analysis

- **Root cause**: D (test coverage gap) plus E (implicit assumption). Offline admission tests proved
  duplicate prevention but never exercised native source inspection after the admitted QA run became
  visible in the route/artifact ledgers. The freshness check implicitly assumed source inputs stayed
  byte-identical throughout execution.
- **Why the earlier fix was insufficient**: separating terminal-Task planning composition allowed QA
  to start, but it did not trace the write-back path from provider route evidence into the next
  native freshness read.
- **Prevention**: the runtime now structurally authorizes only same-plan invocation additions; focused
  tests cover admitted, foreign, removed and non-run-changed facts; the executable recovery spec
  defines successor-plan handling and the at-most-once boundary.
- **Systematic expansion**: every workflow that revalidates an approved snapshot after performing its
  own append-only write must classify self-authored facts separately from external drift. Exact object
  equality is valid only for genuinely immutable projections.
