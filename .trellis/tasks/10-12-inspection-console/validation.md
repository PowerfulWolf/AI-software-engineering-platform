# Validation

- RED: focused test collection failed because InspectionConsole did not exist before implementation.
- Focused pytest (PYTHONPATH=src:. using existing Python 3.12 virtualenv):
  - tests/web_console/test_transport.py, test_inspection_console.py, test_shutdown.py: 65 passed.
  - test_team_summary_detail.py, test_model_calls.py, test_operation_budget.py: 28 passed.
  - Earlier core/operation-summary/preparation broad incremental selection: 98 passed, 3 failed.
    All three failures independently reproduced unchanged from the main checkout at fde7930:
    test_preparation_progress seed and after_seed fixtures lack the artifact root;
    test_operation_summaries real_update Node fixture fails saved-UPDATE navigation assertion.
    These are recorded pre-existing issues, not claimed PASS or changed in this task.
- Chrome fixture suites inspection-console, operation-capabilities, recovery-read-contention: 4 passed.
  Expanded inspection test re-run passed: admin maintenance 503 does not turn global connection red,
  retained demand remains readable, and no mutation request is sent.
- Ruff all touched Python and tests: passed. Mypy 4 changed source modules: passed.
- Independently reviewed by maintenance_successor_boundary: no blocking implementation finding.
- Temporary peer fault_retirement.py and owned_sessions.py copies enabled normal-host integration
  tests and typecheck. They are excluded from this commit and belong to the maintenance worker.
  Final real marker->production positive/negative integrated tests are owned by root after both merges.
- No production access, requirement action, model invocation, database migration or record rewrite.
- Full test suite intentionally not run, per user instruction.

Existing data treatment: all Operation versions, RUNNING state, model calls and files remained
byte-identical across inspection startup, read APIs, mutation rejections and shutdown in fixtures.
Missing Operation/preparation directories remained missing. No migration or repair of historical
execution proof is performed. Rollback requires controlled service stop and preserves the marker.

## Actual retirement marker integration

`tests/web_console/test_inspection_fault_boundary.py`: 4 passed (2026-10-12).
The test uses real isolated subprocess `_host`, `prepare_fault_retirement`, and the actual
`execute_fault_retirement` to produce sealed plans, receipts, archived log and inspection marker.
It does not mock `inspection_required` or synthesize the marker. Configuration and Team/Operation
fixtures are prepared before the exact maintenance plan is captured.

- Valid real marker + explicit normal mode -> production inspection composition.
- Writer constructors/index/start are assertion traps; none is reached.
- Existing RUNNING Operation remains RUNNING; operation summary/detail/model-call/preparation GETs
  succeed; HTTP POST is rejected before parsing; platform and old lifecycle bytes remain identical
  through the new read-only lifespan and shutdown.
- Corrupt marker, archived log or archived lifecycle -> FaultRetirementError before any writer,
  while platform bytes stay unchanged.

The first integrated run exposed lsof's macOS return code 1 with a real positive sentinel and empty
stderr; peer maintenance worker repaired its strict survey handling and its own suite passed before
these 4 integration cases were repeated successfully. No survey gate was mocked or bypassed here.
This closes the fixture integration gap above; live replacement acceptance remains a root task.
Peer module/test copies are temporary dependencies only and excluded from this test commit.
