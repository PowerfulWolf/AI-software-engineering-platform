# Verification

## Red evidence

`uv run pytest -q tests/manager/test_production_execution_baseline.py -k pause_missing_receipt --tb=short`
failed on the old composition: a stale proposal hit `原调用结果或真实停机事实不完整` before
checking its expected revision, and the valid stopped source had no baseline-compatible receipt.

`uv run pytest -q tests/manager/test_baseline_wait_fact_collection.py --tb=short`
gave 11 failing contract cases before the new proposal-only seam existed.

## Green evidence

- Focused preparation boundaries: 17 passed in 7.35s; independent reviewer also ran 17 passed.
- Public missing-receipt parent Requirement flow: 1 passed, 8 deselected in 46.54s. Includes
  foreign public parent/stale revision refusal before receipt writes, exact native child scope,
  PAUSE with no model calls and explicit RESUME through independent final same-SHA QA/Review.
- Changed-file Ruff: passed.
- Strict Mypy on baseline_production.py and production_host.py: passed (2 source files).

- Affected baseline/wait regressions:
  `uv run pytest -q tests/manager/test_baseline_wait_fact_collection.py tests/manager/test_execution_baseline.py tests/manager/test_execution_baseline_invocations.py tests/manager/test_execution_baseline_reservation.py tests/manager/test_wait_fact_collection.py --tb=short`
  → 64 passed in 71.58s.
- Existing public native PAUSE and repeated preflight:
  `uv run pytest -q tests/manager/test_production_execution_baseline.py -k 'pause_native_epoch or repeated_preflight' --tb=short`
  → 5 passed, 4 deselected in 63.94s.
- `git diff --check`: passed.
- Independent reviewer confirmed the public-parent/native-child correction and reported no
  remaining task2 blockers after reviewing the exact parent test assertions.

No full-suite test or production operation was run. Testing stopped after these affected
incremental suites passed.

## Existing data and rollback

No historical SQL/audit repair is necessary or performed. Original start/stop/failure records
remain immutable; one legal missing receipt is appended when explicit proposal preparation
validates them. User source approval and explicit continuation remain required. Roll back code
only while idle and retain readers of already sealed receipts and PAUSE/binding/continuation
records; do not delete records, reset the Task or recreate the Requirement.
