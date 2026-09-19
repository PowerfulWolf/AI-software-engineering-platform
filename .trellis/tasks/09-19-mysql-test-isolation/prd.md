# MySQL regression-test isolation

## Goal and scope
Reproduce and remove cross-test MySQL state pollution behind the serial joint-delivery capacity failure. Keep production capacity, state, approval and verdict contracts unchanged. Preserve unrelated UI edits.

## Acceptance criteria
- Identify a concrete persistent-state producer and a red reproduction of the reported BLOCKED symptom.
- Every MySQL-marked test begins with independent mutable facts and cleans up even after failure.
- Reject non-test DSNs before SQL; tolerate absent DSN and fresh schemas; do not delete unrelated tables.
- Existing serial joint deliveries and MySQL dispatch, queue, recovery and reader tests pass together.
- Record evidence, limitations and existing-data handling without editing production records.

## Allowed paths
`tests/conftest.py`, `tests/mysql_safety.py`, `tests/test_mysql_test*.py`, `tests/manager/test_mysql_dispatch_authority.py`, `tests/work_queue/test_mysql_queue.py`, `README.md`, `.trellis/spec/core/production-team-host.md`, this task directory.

## Verification
Use scripted Agents and a dedicated test-named MySQL schema. Run a producer/consumer reproduction, pytest lifecycle regression, affected MySQL suites, non-MySQL safety cases, Ruff, strict mypy and diff checks. Independent QA and read-only review are required by AGENTS.md.

## Rollback
Revert only this task's test harness/documentation patch. No production migration or data repair. Disposable test data may be reset only behind the existing database-name guard; preserve production audit history.
