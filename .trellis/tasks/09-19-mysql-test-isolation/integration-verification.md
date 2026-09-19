# Integration verification after updating main

- `task_id`: `mysql-test-isolation-20260919`
- `source_revision`: `8a7f761` (latest fetched `origin/main`)
- `context_manifest_id`: `203d24b402317266969d133db8ce81b2b38e3131beea34b6c4140c7cabd7e6e9`

The local branch fast-forwarded from `de4edcc` to `8a7f761`; the existing patch reapplied without
conflicts. The unrelated Settings UI patch retained the same stable patch ID and is excluded from
this commit. Historical QA manifests remain bound to their original baseline.

## Latest-main validation

With `ASE_TEST_MYSQL_DSN` pointing to an exclusive disposable database:

```sh
pytest -q tests/test_mysql_test_isolation.py tests/test_mysql_test_safety.py \
  tests/e2e/test_joint_delivery.py tests/e2e/test_project_revision_preparation.py \
  tests/manager/test_mysql_dispatch_authority.py tests/work_queue/test_mysql_queue.py \
  tests/knowledge/test_queue_mysql.py tests/store/test_mysql_repository.py --tb=short
```

Result: **50 passed in 83.24s**, including the original serial capacity regression, failed-fixture
cleanup and the new knowledge queue bridge. No concurrent test process shared this database.

- `ruff check .`: passed.
- `ruff format --check .`: 753 files formatted.
- `MYPYPATH=src mypy src tests`: passed, 411 source files. The old baseline's 17 errors are absent
  after incorporating the upstream commits.
- `node --test tests/team_view/ui.test.cjs`: 6 passed; includes the preserved local UI patch.
- `git diff --check`: passed.

The earlier **1340 passed, 2 warnings in 1436.74s** full run is evidence for `de4edcc` plus this
fix, not a claim that the expanded latest-main suite was fully rerun. The latest-main validation
above targets every changed test-infrastructure seam and the added MySQL knowledge bridge.

## Existing data and rollback

No production facts, approvals or schemas were changed. The next MySQL-marked test clears old
facts only in its guarded disposable schema. Revert this commit to undo the test harness and
its documentation; retain upstream commits and unrelated UI work.

## Evidence hashes

```text
dfd5fb71e550988b915361d64fb3e80d96d801d168d9c969a328b4a4a6859403  integration-mysql.log
804973b23cbfa298f6099888e8b79a12ca0c003f704e5d3e2a57b667295f0bfe  integration-mypy.log
```
