# QA environment-aware verification recovery

## Goal

Keep candidate verification serial and immutable while allowing QA tools to create disposable
cache/build output, and resume an inconclusive verification without incorrectly assigning Coder.

## Requirements

- Run QA in its isolated disposable worktree with workspace write capability while retaining the
  post-run invariant that HEAD and every Git-visible path are unchanged.
- Treat a QA report with no criterion/test failure but with `NOT_TESTED`/`ERROR` evidence as an
  inconclusive verifier execution, not a code defect.
- Require a fresh approved verification plan for an inconclusive result; do not reuse an admitted
  Agent Run and do not start Coder.
- Recover an existing failed remediation continuation by following its immutable dispatch back to
  the retained candidate when the sealed source QA result was inconclusive.
- Keep genuine QA failures and Reviewer rejections routed to Coder remediation.

## Acceptance Criteria

- [x] Codex CLI QA uses `workspace-write`; Reviewer remains `read-only`.
- [x] Any QA Git-visible change or HEAD change still returns `POLICY_VIOLATION`.
- [x] Inconclusive QA produces `VERIFICATION_APPROVAL_REQUIRED` for a new plan and zero Coder calls.
- [x] A terminal failed continuation can safely resolve and reverify its retained source candidate.
- [x] QA criterion/test FAIL and Review REJECT still create remediation.
- [x] Targeted tests, Ruff, strict Mypy and `git diff --check` pass.

## Out of Scope

- Containers, distributed execution, automatic merge/push/deploy, or relaxing repository path
  policy.
- Reusing a consumed provider invocation or silently approving a new verification plan.
