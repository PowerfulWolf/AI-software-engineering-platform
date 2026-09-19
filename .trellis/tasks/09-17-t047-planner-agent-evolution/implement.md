# T047 continuation — implementation notes

Resumed the existing `/private/tmp/ase-t047-t049-20260918` worktree; retained its earlier gate,
complex graph, schema and journal work. No production data, role verdict or Git merge was changed.

Independent review follow-ups addressed:

- Trusted joint projections reach native planning unchanged; only the dedicated Host factory
  disables the native fast-plan generator.
- New plan revisions require exact latest predecessor and contiguous version plus feedback.
  Validation precedes successful run receipt/READY; failures retain typed INVALID_OUTPUT runs.
  Historical plans lacking the new extension still read and replay unchanged.
- Shared test-matrix validation preserves each acceptance criterion's required Design levels
  in both native and joint plans. Positive fixtures now provide the required tests explicitly.
- All semantic joint plan ValueErrors retain the typed rejected plan and feedback in the journal;
  resumed planning binds the previous digest and retains the original approval.

Tests cover native routing, exact trusted projection, lineage failure/no READY, legacy v2 reads,
test-level weakening, joint graph rejection/restart/revision and materialized delivery evidence.
Continuation checks: `PYTHONPATH=src <main-repo>/.venv/bin/python -m pytest -q tests/planning
tests/manager/test_joint_planner_feedback.py tests/e2e/test_planned_delivery.py` passed 70 tests;
targeted Ruff lint/format passed for 26 files, Mypy passed for 20 planning/test source files,
and `git diff --check` passed. The main checkout virtualenv was used without rebuilding work.
Final independent QA/review, global schema parity and full checks are owned by the coordinating
session; this note is implementation evidence, not a QA or Reviewer verdict.

Existing data: no migration needed. Reopen and resume PLANNING Requirement checkpoints using
existing Manager operations to feed retained feedback into the next attempt. Exhausted budgets
and terminal Tasks keep their current human recovery requirements. Rollback reverts code and
schemas together while retaining immutable sidecar history and user approvals.
