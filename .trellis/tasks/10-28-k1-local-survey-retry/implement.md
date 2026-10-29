# Implementation and verification

The deterministic facade regression first failed on the original one-attempt behavior:
four expected retry paths failed, while the protocol-failure refusal passed. The facade now
retries only a validated typed child result with the sole `PROCESS_SCAN_INCOMPLETE`
blocker. A parent/protocol/cleanup failure creates a synthetic incomplete survey and
stops immediately. Each retry performs a complete new survey with a fresh request,
deadline and owned worker; earlier partial observations never contribute to the result.

## Validation

- Focused red test before implementation: `4 failed, 1 passed`.
- Focused green test after final boundary cases: `7 passed`.
- `PYTHONPATH=src .../.venv/bin/pytest -q -p no:cacheprovider tests/manager/test_local_survey_observation.py tests/manager/test_contained_unknown_budget.py`: `117 passed`.
- `PYTHONPATH=src .../.venv/bin/pytest -q -p no:cacheprovider tests/manager/test_legacy_local_execution.py tests/manager/test_knowledge_isolation.py`: `219 passed`.
- Ruff check, Ruff format check, Mypy for the changed production module, and
  `git diff --check` passed.

The real local-process tests require normal process visibility. An initial sandbox run
failed three existing real-process cases because the sandbox could not observe or start
the owned worker; the same suite passed with the approved isolated-test execution
permission. No production Requirement, Task, Operation, source checkout, approval or
database was modified by this worktree.

## Existing K1 and rollback

The original K1 keeps its approved Plan, old UNKNOWN history and current capacity wait.
After a controlled platform release, use a **new** public Continue Operation key against
the current parent checkpoint. A successful survey permits only the existing exact
source/target/dispatch/seed checks; it does not solve the separate 256k Context capacity
block or skip Coder, QA and Reviewer. If all three current surveys remain incomplete,
preserve the wait and investigate the host. Before any new recovery fact is consumed,
the code can be rolled back at an idle service boundary; this change adds no persisted
field or Schema.
