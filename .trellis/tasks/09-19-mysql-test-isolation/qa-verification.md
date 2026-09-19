# Independent QA verification — MySQL test isolation

- `task_id`: `mysql-test-isolation-20260919`
- `source_revision`: `de4edcce73d7c2f57fe2213cf772b7d9dda45e2f`
- `context_manifest_id`: `6a1e3e2c702df9398df7ecb4cdc423831b657e307f382ca1975425761bdc60de`
- QA workspace: `/private/tmp/ase-mysql-isolation-20260919`
- Database: `ase_isolation_qa_final_20260919_test` (disposable, dedicated, no production DSN)

## Evidence

| Check | Command/result |
|---|---|
| Lifecycle and safety | `ASE_ISOLATION_DATABASE=ase_isolation_qa_final_20260919_test python3 /private/tmp/ase-isolation-run.py -q tests/test_mysql_test_isolation.py tests/test_mysql_test_safety.py --tb=short` → **15 passed in 14.74s** |
| Independent probes | `ASE_TEST_MYSQL_DSN=<redacted dedicated DSN> .../.venv/bin/python -m pytest -q /private/tmp/ase-isolation-qa-probes.py -m 'not mysql' --tb=short` → **4 passed in 0.90s** |
| Ruff | `ruff check` on six changed test files → **All checks passed**; `ruff format --check` → **6 files already formatted** |
| Targeted mypy | `MYPYPATH=src mypy --follow-imports=silent` on six changed test files → **Success: no issues found** |
| Diff hygiene | `git diff --check` → **passed** |

The lifecycle producer-only tests cover pass, test-body failure, dependent-fixture setup failure, and direct post-process inspection of all eight mutable fact tables. Startup cleanup covers facts left by an interrupted process. The guard test verifies rejection before a dependent fixture runs and credential redaction. Independent probes verify empty/partial schema behavior, rollback and propagation on deletion failure, retention of unknown tables and both authority-lock rows, and teardown using the originally captured DSN after the test mutates the environment.

## Findings

No QA findings. The reported capacity failure is reproducible as cross-process database pollution when two pytest processes share one test schema; with the dedicated schema and serialized focused run, the isolation regression and safety suite pass. The earlier concurrent run was stopped and excluded from evidence.

Evidence hashes:

```text
60ed940cb4132e1b9cf6c7d7569a4483b51459f158f3acd2c71d2b8a658249a2  qa-mysql.log
ca3bc939e5ab70b14ab977548ae0e0576560d31e07665eb0d6c9ac2c7ee2a172  qa-probes.log
ab35ee42183d4d6d3ba483825ab037d18a5a15622d03be01d82220b1564851ff  qa-mypy.log
```
