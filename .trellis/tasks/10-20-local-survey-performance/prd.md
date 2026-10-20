# Repair bounded current-process surveys under Host CPU contention

## Goal and observed problem

Restore complete current local surveys within the existing five-second acceptance budget.
A real contention profile remained in `_mac_paths → Path.resolve` while the Host performed
other Python work. This is a platform performance defect in a recovery prerequisite; it does
not prove any original execution stopped or authorize bypassing an active-process blocker.

## Scope and acceptance

- Move only complete captured macOS lsof path parsing into a fixed owned interpreter with its
  own GIL. Preserve every alias resolution and existing classification/coverage boundary.
- Keep five-second absolute survey and 1.5-second OS query limits, scanner version, durable
  wire/digests and all current recovery/authority gates unchanged.
- Use strict bounded request/result protocols bound by the SHA of every request input.
  Fixed isolated launch must not process `.pth`/`sitecustomize` or inherit secrets/import paths.
- Reject all incomplete, malformed, overdue or unconfirmed-child observations. Finalize the
  captured owned process on every path; do not signal discovered processes or add PID exemptions.
- Fail immediately on the first non-idle knowledge-isolation survey; retain all four
  repository/repository/worktree/worktree observations on success.
- Demonstrate real contention performance and isolated contract/security regressions without
  representing maintenance results as K1 QA/Review.

## Allowed paths and verification

Implementation: `src/ai_software_engineer/manager/{local_path_observation.py,local_path_worker.py,
legacy_local_execution.py,knowledge_isolation.py}`; tests:
`tests/manager/{test_local_path_observation.py,test_legacy_local_execution.py,test_knowledge_isolation.py}`.
Knowledge: `.trellis/spec/core/local-path-survey-worker.md`, its core index link and this task directory.
Run these three focused test files, changed-file Ruff/format/strict Mypy and independent static review.
Preserve only aggregate performance evidence; no raw process or secret data enters the task directory.

## Existing data and rollback

Keep the original K1 Task, frozen source, waiting WorkItem, artifacts and complete dirty progress.
Any later recovery uses its original public exact-plan PAUSE and independent RESUME. No direct SQL,
historical stop/outcome repair or manual worktree edits are in scope. Roll back at an official
controlled stop/proven-exit boundary, restore code and restart, retaining all historical facts.
