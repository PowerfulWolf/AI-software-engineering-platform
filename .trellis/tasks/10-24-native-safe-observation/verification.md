# Verification record

Base: `67daf0ecc8341e5c81b54b4d14187d86090ead4a`.
Code location: `/private/tmp/ase-native-safe-observation-20261024`.
All tests use the existing repository `.venv` interpreter with `PYTHONPATH=src` and
`PYTHONDONTWRITEBYTECODE=1`, without provider calls, MySQL or production operations.

## Red / green evidence

- The initial baseline pure-observation loop (`test_native_output_observation.py`)
  ran before implementation: **8 failed**, all missing observation APIs.
- After parser/drain implementation plus original JSON observer regressions:
  **67 passed in 0.18s**.
- New exact private-store test collection initially failed because the separate
  `orchestration.native_observation` module did not exist. After model/store addition,
  **20 passed** across the new store and initial pure-observation tests.
- New optional-write fault-injection tests: **3 passed**. They assert mandatory stop
  is saved before optional telemetry, optional exception text cannot survive,
  WORK_INTERRUPTED remains unchanged, and mandatory stop errors are not swallowed.
- Latest pure observation + adapter fault-injection command below: **23 passed,
  2 deselected in 3.79s**; the deselected cases require real OS ownership inspection.

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python \
  -m pytest -q tests/agents/test_native_output_observation.py \
  tests/agents/test_native_observation_runner.py \
  -k 'not real_timeout and not unselected' --tb=short
```

Shared-epoch assertion freezes monotonic=100 with original runner epoch=90; both
pipes' first/last times and enclosing elapsed must all equal 10. Invalid time tests
reject zero-byte/timing mismatch, one absent timestamp, reversed times, last>elapsed,
NaN and raw count overflow. Saturation tests seed the real stream/parser at their
unsigned63 bounds and require capped counts plus overflow flags. Store tests rehash
impossible elapsed or foreign Task/Run/work/lease/source/Context/request/start/stop
bindings and still require rejection.

## Independent authorized OS verification

The sandbox attempted the two new real-runner cases and both were refused by the
existing Darwin ownership survey (`spawn ownership capture failed`), before statistics
assertions. These were reported as failures, not passes. Parent `/root` then ran
`test_native_observation_runner.py`, `test_native_observation_store.py` and
`test_native_observation_deletion.py` in the authorized real OS environment and reported
**27 passed in 7.60s**, with import path verified to this isolated mirror. This covers
the real no-provider timeout and explicit protocol runner cases, strict store and
deletion tests. Parent owns any additional OS cleanup/flooding regressions and integration.

The deletion worker separately ran **15 passed** across the 10 new cases and five
existing continuation/baseline namespace closure regressions. An exploratory larger
purge suite returned 30 passed / 8 failed; all eight stopped at pre-existing OS
fixtures because the sandbox denied `kern.bootsessionuuid`, before deletion assertions.
No MySQL test was added or executed.

## Quality checks

- Ruff check on all 13 changed/new Python files: **passed**.
- Ruff format check: **13 files already formatted**.
- Strict mypy on all 13 changed/new Python files: **passed**.
- `git diff --check`: **passed**.
- Final test-only correction: the first freeze/"mypy passed" status preceded the
  final shared-epoch test's static check. That check found its reference to the
  non-exported `_native_output.time`. The test now imports `time` directly, and an
  unused local import was removed after Ruff identified it. The epoch assertion
  passed again. No production code changed in this correction. Final Ruff, format
  and strict mypy checks cover this corrected test; the original report was premature.
- Wider existing parser/store/continuation/reconciliation regressions: **216 passed,
  11 skipped, 2 deselected in 196.78s**. The 11 skips are existing v1 fixtures where
  ignored retained-source/multi-round restoration applies only to v2; two deselections
  are the real OS cases independently passed by root. This run collected before the
  final deterministic shared-epoch case was added; that case passed in the later
  23-test focused check above.

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python \
  -m pytest -q tests/agents/test_native_output_observation.py \
  tests/agents/test_codex_json_observer.py tests/agents/test_native_observation_runner.py \
  tests/orchestration/test_native_observation_store.py \
  tests/orchestration/test_continuation_store.py \
  tests/orchestration/test_capture_reconciliation.py \
  tests/orchestration/test_native_continuation.py \
  tests/orchestration/test_native_continuation_v2.py \
  tests/manager/test_native_observation_deletion.py \
  -k 'not real_timeout and not unselected' --tb=short
```

## Stock data and rollback

No database or production sidecar was changed. Existing stop/receipt classes and
their wire/hash definitions were left unchanged. The store replay test proves old
capture-start/stop bytes remain exact after adding/reopening the independent file;
diagnostics neither create receipts nor admissions. Historical runs remain explicit
UNAVAILABLE; they are not backfilled. Existing K1 continuation remains governed by
its approved recovery and budget facts, independent of these statistics.

No SQL migration is needed. Revert code before new records are published; after any
publication retain strict read/deletion compatibility and immutable history even if
future writes are disabled. No merge, push, restart or deployment was performed by
this worker. Parent must independently review and integrate the frozen patch.


## Root integration and independent review

Root verified the base67daf0e and all20 before/after file hashes before applying
the worker patch and the v2 test-import/documentation increment into the attached
`codex/verification-feasibility-gate` worktree. Main remained untouched while the
original K1 role was executing. Root independently ran Ruff check/format and strict
Mypy on all13 changed Python files: all passed. Diff whitespace checks passed.

Independent `/root/native_observation_design_check` reviewed the complete production
patch and reported no P1/P2 blockers. It rechecked the corrected timing contract,
mandatory/optional error ordering, exact capture bindings, corruption-vs-absence and
resource deletion closure. Its low-priority missing real-purge test was then addressed
by a separate test-only worker; root reviewed and ran that new file.

Additional root actual-OS regression command (isolated mirror, no provider):

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python \
  -m pytest -q tests/agents/test_native_output_observation.py \
  tests/agents/test_native_output_bounds.py tests/agents/test_native_json_events.py \
  tests/agents/test_codex_cli.py tests/agents/test_cli_unknown_failure.py \
  tests/orchestration/test_native_continuation.py \
  tests/manager/test_purge_record_closure.py -m 'not mysql'
```

Result: **185 passed,1 deselected in99.00s**. The deselected case requires MySQL.

The complete `prepare→execute` purge test needs SQL facts; a selector mock or edited
plan would not test the actual contract. User authorization for isolated tests was
already present. Before connecting, root applied the repository test-DSN guard,
required loopback host, and read-only verified actual DATABASE() matched the exact
`ai_software_engineer_test` database. The first read-only identity probe assumed a
tuple cursor and failed with KeyError before any writes; the corrected alias/dict
read verified identity. No production config, DSN or database was used or printed.

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python \
  -m pytest -q tests/manager/test_native_observation_purge_execution.py --tb=short
```

Result: **3 passed in2.11s**, using existing guarded serial SQL fixtures. Actual
physical deletion removes the new record and owned Task directory/journal while
retaining foreign Task bytes. Post-plan addition and same-size mutation both reject
execution, preserve original SQL/Task/files/pending plan and write no completion.
No production sidecar/SQL or K1 draft was modified. These are platform regressions,
not K1 QA/Review verdicts. Suites overlap and must not be summed as unique coverage.
