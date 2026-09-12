# QA environment-aware verification recovery design

## Decision

QA receives `workspace-write` only inside its manager-owned detached worktree. The adapter still
compares the final HEAD with the pinned candidate and requires `git status --porcelain` to be empty.
This permits ignored tool caches/build output without allowing candidate mutation. Reviewer stays
read-only and consumes QA evidence.

Classify a failed QA report as `INCONCLUSIVE` only when it contains no `QaCriterionStatus.FAIL` and
no `QaTestStatus.FAIL`, while at least one criterion is `NOT_TESTED` or one test is `ERROR`. Under the
QA contract, candidate-caused failures must be represented as FAIL; ERROR means the verifier could
not establish a verdict. An inconclusive completion creates a successor verification plan against
the same candidate and therefore requires exact human approval.

For an already-created remediation continuation that failed without a candidate, resolve the
current `ContinuationDispatchRecord`, its sealed source verification completion, and the historic
source checkpoint. Only if that completion is inconclusive may the reader use the retained source
candidate. Every project/delivery/task/dispatch/candidate digest must match; genuine failed
remediation remains a Coder recovery/human gate.

## Error matrix

| Fact | Route |
|---|---|
| QA has criterion/test FAIL | Coder remediation |
| Review REJECT | Coder remediation |
| QA has only NOT_TESTED/ERROR, no FAIL | Fresh QA verification plan |
| QA workspace has Git-visible changes | POLICY_VIOLATION |
| Continuation/source/completion lineage differs | Fail closed |
| Fresh plan is not approved | VERIFICATION_APPROVAL_REQUIRED, zero model calls |

## Rollback

Revert code and spec changes. Existing immutable delivery, verification, dispatch and Artifact
records are not rewritten or deleted.

## Bug analysis

### Root cause category

- **B — Cross-layer contract:** QA's process sandbox was treated as equivalent to its repository
  mutation permission, so legitimate pytest/Ruff scratch writes were blocked.
- **E — Implicit assumption:** the resume controller treated every unverified top-level QA `FAIL`
  as proof of a candidate defect, even when the detailed evidence was only `NOT_TESTED/ERROR`.
- **C/D — Propagation and coverage:** Candidate V1 remained valid in immutable history after the
  wrongly created continuation failed, but source resolution only understood the latest Task. Unit
  tests covered direct candidates, not this complete legacy sequence.
- **B/D/E — Recursive lineage gap:** continuation ancestry treated every historic Delivery
  `candidate_revision` projection as candidate authority. Real multi-generation history contained a
  valid terminal source cursor with `candidate_revision=null`; the candidate was present only in the
  Task event/artifact chain. Fixtures incorrectly stored the SHA directly in that cursor, so the
  recursive production path was never exercised.

### Why earlier fixes did not close the loop

Improving structured-output diagnostics exposed `GIT_CONTRACT` but did not answer why Coder had no
changes. Retained-candidate support covered a failed Coder after a genuine finding, but did not bind
fallback to the source verification disposition. Both were surface/incomplete-scope fixes.

### Prevention mechanisms

| Priority | Mechanism | Action | Status |
|---|---|---|---|
| P0 | Architecture | Typed completion disposition separates verifier uncertainty from code failure | DONE |
| P0 | Runtime guard | QA may write scratch, while HEAD and Git-visible inventory remain immutable | DONE |
| P0 | Provenance | Legacy fallback verifies exact continuation → plan → completion → invocation lineage | DONE |
| P0 | Integration test | Real Git/MySQL recreates the complete failed-continuation sequence | DONE |
| P0 | Shared runtime predicate | Planner ancestry and retained-candidate lookup share the same strict nullable terminal source-cursor rule | DONE |
| P0 | Regression test | Nullable terminal ancestry is accepted; nullable non-terminal ancestry is rejected | DONE |
| P1 | Documentation | Recovery and worktree specs contain signatures, matrices and wrong/correct cases | DONE |

The project has no separate `.trellis/spec/guides/` or generated spec-template tree; knowledge is
therefore captured in the authoritative core code-spec and operator documents instead.
