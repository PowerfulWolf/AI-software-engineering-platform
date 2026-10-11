# Verification and handoff

Base: `53c71c1` in isolated checkout `ase-current-receipt-projection`.
Production and main checkout were not modified. No ASE operation, SQL access, service
restart, K1 workspace change, model call or full test suite was performed.

## Root cause and behavior

`_continuation_history` returned `receipts[-1]` regardless of the current work. The
native Task reader attached its URI/policy to the current execution, and repeated
Task/Requirement projection retained those old fields. A later run without a receipt
therefore appeared to have a previous run's stopping/capture facts.

History remains complete. Current references require the unique open Coder work in
IMPLEMENTING and a real immutable start with matching work/Task/role/attempt; the
receipt's complete request and claimed lease must equal that start, and the stop
must follow the start. Missing current receipt/start is neutral. A mismatched start
fails closed. A formal admission is retained history, not a substitute for the new
call's own stopping/capture facts. QA, Review, terminal work and a baseline successor
without its own receipt have no current Coder receipt reference.

The verified current receipt entry carries two read-projection details. Repeated
projection uses those exact current work/attempt markers and never copies a previous
execution reference. No wire model, Schema, authorization or state transition changed.

## Incremental checks

Use the existing main virtualenv, `PYTHONPATH=src` and isolated checkout cwd.

1. Red: initial focused continuation-history test run reproduced the unconditional
   historical selection and missing new binding path (9 failed, 1 passed). The old
   QA fixture also lacked ROLE_EXECUTION while asserting actual execution; it now
   explicitly provides that phase rather than weakening state accuracy.
2. `python -m pytest -q tests/team_view/test_continuation_history.py
   tests/team_view/test_baseline_snapshot.py tests/team_view/test_task_read_snapshot.py
   tests/team_view/test_product_execution.py -m 'not mysql' --tb=short`
   — 52 passed in 90.78 s before adding the final v2 arrival case.
3. Final `python -m pytest -q tests/team_view/test_continuation_history.py --tb=short`
   — 17 passed in 0.63 s. Includes v1/v2 receipt selection, later work, actual start,
   source/run/context/lease/digest rejection, formal admission, pause, QA/Review/DONE,
   repeated Task/Requirement projection, no new directory and unchanged file bytes.
4. `python -m pytest -q
   tests/team_view/test_baseline_snapshot.py::test_task_read_snapshot_wires_all_three_real_projections
   tests/team_view/test_execution_history.py tests/team_view/test_joint_history_snapshot.py
   -m 'not mysql' --tb=short` — 11 passed in 9.85 s. Real reader composition retains
   all history and does not attach a historical receipt to a different queue work.
5. Ruff format/check and strict mypy for `reader.py`, `test_continuation_history.py`
   and `test_baseline_snapshot.py` passed. `git diff --check` passed.

No MySQL fixtures or production database were accessed. No browser was operated:
this change corrects the existing nullable API projection without changing UI code.

## Independent review

`/root/owned_scan_review` performed read-only static review of the production diff,
all binding negative tests, v2 append/refresh and real-reader snapshot assertions.
No blocking findings remain. Reviewer ran no tests or production operations.
Its semantic finding was adopted: a formal admission must not make an old receipt
appear to be the new call's own stop/capture record.

## 存量数据处置

No database migration or sealed file rewrite is needed. Existing run 6/run 8 receipts
remain valid historical facts. Once Root reaches a safe idle boundary, integrate the
commit and load the repaired service; refreshing the original K1 Requirement will
remove historical current references from a successor with no own receipt. The
current work's typed blocker and authorized public recovery flow remain unchanged.
Do not update the actively executing service or Coder baseline for this read-side fix.

## Risk and rollback

Legacy current receipts with no matching durable invocation start remain visible in
history only; absence is not newly interpreted as a lost draft or failed stop. This
is deliberately conservative. Reverting the isolated commit while idle and refreshing
rolls back presentation without deleting audit history, progress, approval or verdict.
The original misleading historical-current reference would return on that rollback.
