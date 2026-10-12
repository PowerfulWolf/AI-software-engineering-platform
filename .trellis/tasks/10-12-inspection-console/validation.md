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
