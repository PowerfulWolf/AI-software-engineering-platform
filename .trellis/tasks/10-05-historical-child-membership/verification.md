# Incremental verification

- Before implementation, four new historical membership tests failed against the old reader:
  DESIGNING/PLANNING cleared children, later child and independent same-title native. They each
  showed the old child incorrectly becoming another Requirement.
- After the reader repair, the same four tests passed.
- Historical/current, retirement, member-history and retained-reference tests: 15 passed.
- Historical candidate-verification/remediation descendant isolation: 2 passed.
- Ruff check and format check passed for `reader.py` and `test_live.py`.
- Strict mypy passed for both owning Python files.
- Related existing joint/current-role/in-flight incremental selection initially produced 23 passes
  and one `test_real_inflight_joint_and_terminal_reads` failure in the execution backend:
  MySQL TaskNotFound during Reviewer `before_run`, not a reader assertion. The isolated serial
  single-test rerun passed in 43.06 seconds with coordinated serial MySQL execution.
  Independent checker later clarified its earlier selection had also included MySQL fixtures before
  serial coordination; shared test database resets may have interfered. The initial failure did not
  reproduce, and its exact cause is not established. All 26 selected distinct Python cases passed, including the two
  separately selected descendant cases. No full suite has been run.

Commands:

```sh
.venv/bin/pytest -q tests/team_view/test_live.py -k 'historical_child or historical_membership or historical_member_work or retired_requirement'
.venv/bin/pytest -q tests/team_view/test_live.py -k 'historical_native_descendant'
.venv/bin/pytest -q tests/team_view/test_live.py -k 'joint_reader or real_inflight_joint or current_role_lease or active_child_task or historical_child or historical_membership or historical_member_work or retired_requirement'
.venv/bin/pytest -q tests/team_view/test_live.py::test_real_inflight_joint_and_terminal_reads
.venv/bin/ruff check src/ai_software_engineer/team_view/reader.py tests/team_view/test_live.py
.venv/bin/ruff format --check src/ai_software_engineer/team_view/reader.py tests/team_view/test_live.py
.venv/bin/mypy src/ai_software_engineer/team_view/reader.py tests/team_view/test_live.py
```

Frontend Node/Chrome and production GET verification are performed and recorded by root. The
reader regressions assert unchanged file inventories on successful and rejected reads.

## Frontend incremental checks

- Two new DOM contracts initially failed on the former current-work selection, then passed.
- Eight related DOM contract files passed: 129 tests. Existing fixtures were completed with their
  current scope IDs; the superseded QA regression still excludes the failure from current blocker
  presentation and additionally verifies its accessible history reason.
- Four related Chrome suites passed across 17 distinct tests (16 together, the repaired new history
  navigation test as a focused final rerun). The new test preserves original Task facts while
  verifying list/flow/member queue/count and historical detail links. Its initial test failures
  were an incorrect request CSS selector and the intentionally collapsed engineering disclosure.
  Neither required loosening the current/history contract.
- JavaScript syntax and diff whitespace checks passed. No full suite was run.
- Independent review found the new history region needed the full owned Task inventory in the
  detail polling signature. The signature now uses `requestTasks`, while business projection still
  uses `currentRequestTasks`. The Chrome regression mutates only an old reason/time, verifies it
  refreshes without changing current flow or collapsing history, and navigates to the exact old ID.
- Independent implementation review found no remaining issue after the signature correction.
  Its unrelated static snapshot Schema drift finding is handled in a separate Trellis task.

```sh
node --test tests/team_view/historical-child.test.cjs tests/team_view/delivery-status.test.cjs tests/team_view/ui.test.cjs tests/team_view/knowledge-gap.test.cjs tests/team_view/engineering-wait.test.cjs tests/team_view/product-execution.test.cjs tests/team_view/operation-progress.test.cjs tests/team_view/readiness.test.cjs
NODE_PATH=/Users/zhangjunshuai/Library/Caches/ase-validation/node/node_modules node --test tests/team_view/browser/historical-child.test.cjs tests/team_view/browser/product-execution.test.cjs tests/team_view/browser/execution-history.test.cjs tests/team_view/browser/polling-state.test.cjs
node --check src/ai_software_engineer/team_view/app.js
git diff --check
```
