# 2026-09-08 — Production role timeout repair

## Trigger

Real recovery run `run_f76e3034c3ae49f1babd42ceb5f5b92a` reached the production Coder's
hard-coded 600-second limit after modifying all 15 authorized files. It was terminated before
tests, commit, or Artifact sealing, so the Task correctly became BLOCKED with no candidate.

## Delivered platform repair

- Preserved the failed Task, invocation facts, and dirty worktree without retrying or promoting it.
- Replaced the shared delivery timeout with bounded role budgets: Coder 1,800 seconds; QA and
  Reviewer 1,200 seconds; deterministic Orchestrator remains 60 seconds.
- Kept `max_retries=0`, timeout classification, no-Artifact behavior, and dirty-worktree retention.
- Applied the contract through the common production composition seam used by native and recovery
  delivery.
- Added pure contract coverage, production adapter assertions, and an offline recovery assertion at
  the Codex subprocess boundary.
- Captured the D/E root cause (test gap plus implicit duration assumption) in the production Host
  code-spec.

## Verification

- Focused timeout contract: 4 passed.
- Production and recovery real Git/MySQL integration: 8 passed in 215.61 seconds.
- Full suite with the dedicated MySQL test database: 896 passed in 382.04 seconds.
- Ruff check and format, strict mypy over 286 source files, `uv lock --check`, offline sdist/wheel
  build, and `git diff --check`: passed.
- Live model tests were not run; this repair consumed no model quota.

## Delivery boundary

This commit repairs the platform only. It does not import the interrupted Coder's dirty files,
resurrect either BLOCKED Task, produce a candidate revision, run QA/Reviewer on those files, merge,
push, or deploy. Real requirement delivery must start from a new approved recovery plan on this
verified base.
