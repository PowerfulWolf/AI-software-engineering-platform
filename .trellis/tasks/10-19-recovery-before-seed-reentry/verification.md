# Verification

Implementation is test-only at baseline `0901d25`. Production source, Schemas,
production database/Host and real K1 workspaces were not modified by this task.

## Completed static and nearby checks

- Ruff check and format check: passed for `tests/recovery/test_preseed_reentry.py`.
- Strict Mypy with `MYPYPATH=src`: no issues in the changed source file.
- Collection: three parameterized cases (`unchanged`, `dirty_target`, `target_drift`).
- Necessary non-MySQL neighbors: `test_execution_records.py` and
  `test_preparation_inspection_scope.py`: **16 passed in 6.50s**.

The interpreter is the existing main checkout `.venv/bin/python`; all commands run
with the maintenance checkout as cwd. Runtime tests set `PYTHONPATH=src`; Mypy uses
`MYPYPATH=src` so it analyzes the checkout rather than the installed editable package.
No dependency or environment credentials were written or displayed.

Reproduction uses cwd `/tmp/ase-fix-legacy-ignored` and inherits the existing
`ASE_TEST_MYSQL_DSN` from the trusted test environment. Never derive it from a
production DSN or put its value into a command/report. MySQL runs were explicitly
authorized outside the sandbox so the isolated local database and owned temporary
subprocess could be reached.

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -x -q -s --tb=short tests/recovery/test_preseed_reentry.py --basetemp /tmp/ase-preseed-reentry-final-20261019
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q tests/recovery/test_execution_records.py tests/recovery/test_preparation_inspection_scope.py --basetemp /tmp/ase-preseed-reentry-neighbors-20261019
/Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m ruff check tests/recovery/test_preseed_reentry.py
/Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m ruff format --check tests/recovery/test_preseed_reentry.py
MYPYPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m mypy --strict --cache-dir /tmp/ase-preseed-reentry-mypy tests/recovery/test_preseed_reentry.py
```

## Initial test-helper failures

The first three-case batch returned **3 failed in 277.87s**. All failures were in
the new `_require_unstarted` helper: after correctly confirming that the successor
Task was absent, it called `MySqlTaskRepository.list_events`, whose existing contract
requires an existing Task and correctly raises `TaskNotFound`. The helper now checks
the absence of events with read-only SQL counts alongside queue items/claims.
This was not a production-source RED case. Each fixture confirmed owned offline
processes stopped and all 13 mutable fact tables empty on cleanup.

The next `-x` batch returned **1 failed in 170.16s**, after the unchanged public
Continue had produced seed/invocation and all three role invocation results. The
test tried to inspect the Coder worktree after normal delivery cleanup had removed
it. Identity checks now run after real seed verification and before the provider,
while negative-case scene checks remain after refusal. The fixture again confirmed
owned processes stopped and all 13 tables empty. No production source was changed.
Independent read-only review accepted the corrected lifecycle assertions before
the final three-case batch was started.

## Final native batch

The corrected three cases completed serially with exit code 0:
**3 passed in 405.60s (0:06:45)**. Test data is retained under
`/tmp/ase-preseed-reentry-final-20261019`; no test process remains running.

| Case | Verified result | Final cleanup observation |
| --- | --- | --- |
| `unchanged` | Same approval, sealed Task, dispatch, assignments/leases and managed worktree identity; one seed, one first invocation, complete old patch Context; Coder/QA/Reviewer DONE; repeated public Continue makes no extra role call | owned processes zero; all 13 tables empty at 161.741s |
| `dirty_target` | Existing approval/allocation retained; unseeded dirty target refuses with WAITING_HUMAN; no new Task/seed/invocation; both scenes preserved | owned processes zero; all 13 tables empty at 147.011s |
| `target_drift` | Old Plan freshly rejected; public Continue requires a different exact Plan approval; no new Task/seed/invocation; old records and both workspaces preserved | owned processes zero; all 13 tables empty at 96.201s |

The times in the final column are fixture elapsed observations, not portable latency
thresholds. The OS and MySQL locks were released after the last cleanup. The worker
has finished database testing and informed root and the independent reviewer that
the isolated database is available for the separately authorized unchanged-case
verification. That independent execution and integration are recorded by their
owners; they are not implied by the worker's results here.

The shared fixture's existing safety gate accepts only the exact
`ai_software_engineer_test` database, holds its private nonblocking OS lock and MySQL
advisory lock, checks the connected identity/no other sessions/all 13 tables empty,
and owns every reset after that admission. The local empty autouse override prevents
the repository-wide reset from running before the gate. Tests use actual stores,
Git and owned offline provider inputs; no live provider is contacted.

## Independent acceptance

A different read-only reviewer reran only the unchanged positive against the same final
test bytes: **1 passed in 162.85s**, exit0. Test SHA-256 before and after was
`e0917d12efceebf5bd0b5a94fa1cf83646c7caad634d610a3e10d682289693c4`. Actual fixture
observations confirmed owned processes zero at162.258s and all13 tables empty at162.278s;
the isolated locks were released. This positive overlaps the author's three cases and
does not make four unique cases. The reviewer also accepted all eight test/spec/task
files with no blocking standards or contract findings, without querying production.

Independent report `/private/tmp/ase-preseed-reentry-independent-review-20261019.json`,
SHA-256 `5b68f5998ee05d18b6b0950b5523694366abb1e0d88441d28db2cdd8c733f8ce`, contains
the exact credential-free command, log digest and reviewed file digests. The test-only
rollback and absence of production migration remain as described below.

## Existing data and rollback

存量数据处置：this task requires no data migration and performs no production SQL,
approval, Task, Operation, queue or execution repair. The tests preserve their real
original failed Task/events/worktree and demonstrate the existing public recovery
contract. Isolated test rows are cleared only by the helper under exclusive ownership.
Fixture acceptance does not establish real K1 QA/Review acceptance or delivery completion.

Rollback removes the new test and task documentation; no runtime or Schema rollback
and no production restart are required. Independent review and root integration remain
separate from this worker's test results. No commit was made by the worker.
