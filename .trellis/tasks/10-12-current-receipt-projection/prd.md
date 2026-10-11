# Current execution receipt projection

Goal: current Task/Requirement execution facts must never inherit a historical Coder
interruption receipt merely because it is the newest saved receipt.

Scope and allowed paths: `src/ai_software_engineer/team_view/reader.py`, focused
`tests/team_view/` regressions, `.trellis/spec/core/live-team-view.md`, this task directory.
No production SQL, service operation, Task transition, approval, Coder workspace change,
schema change or write-side recovery behavior.

Acceptance:

- Preserve every validated interruption and policy admission in complete history.
- A current receipt requires the unique open Coder work item in IMPLEMENTING, a verified
  immutable invocation start for that exact work item, and exact receipt work/request/lease
  equality. Never infer a Run from the greatest attempt or receipt timestamp.
- A later interrupted Coder without its own receipt, a formal admitted successor without
  its own receipt, a paused baseline, QA, Review and terminal work expose no historical
  receipt as current. A newly saved exact current receipt becomes visible on refresh.
- Repeated Task/Requirement projection does not restore stale policy or receipt references.
- Missing optional stores create no directories. History integrity/scope/policy checks stay
  fail closed and reading does not mutate files.

Validation: focused non-MySQL pytest for continuation history, baseline snapshots, Task
read snapshots and product execution; Ruff and scoped strict mypy. No full suite.

Rollback point: worktree base `53c71c1`; revert the isolated commit while idle and refresh.
No facts are migrated or deleted; a code rollback restores the misleading presentation only.
