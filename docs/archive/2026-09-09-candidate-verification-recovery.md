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
