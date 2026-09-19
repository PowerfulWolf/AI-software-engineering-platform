# Independent review — MySQL test isolation

- `task_id`: `mysql-test-isolation-20260919`
- `source_revision`: `8a7f7618971a9715dcf3c6bb487095561c036f19`
- `context_manifest_id`: `203d24b402317266969d133db8ce81b2b38e3131beea34b6c4140c7cabd7e6e9`
- Reviewer: `review_mysql_commit` (separate from implementation and QA agents)
- Inputs: `integration-context-manifest.json`; all eight listed SHA-256 values were independently recomputed and matched before this report was written.
- Scope: the manifest's six test files, README and production-team-host spec, plus this task's PRD, design, historical context and QA evidence. Existing Web Console UI edits are excluded.

## Findings

No issues found in the reviewed changes.

## Behavior and safety review

The reset validates the database name before opening its connection. Table discovery is restricted to the selected database, and SQL identifiers come exclusively from the fixed source-code allowlist. The reset uses the existing connection factory's `autocommit=False` transaction, commits only after all deletes succeed, and rolls back and propagates failures. The deletion order agrees with the actual Task and WorkQueue foreign keys. Authority lock tables, legacy archive tables and unrelated tables are excluded; absent tables are skipped without schema initialization.

The function-scoped autouse fixture resets before the existing function-scoped MySQL fixtures and holds the original DSN through teardown. Its `finally` runs after dependent fixtures, including when their setup or test bodies fail. Unmarked tests do not reset. The repository-wide setup hook preserves the earlier rejection before fixture construction. The new subprocess tests exercise the real pytest setup/call/teardown sequence, inspect the database immediately after subprocess exit, and independently exercise startup cleanup and unsafe-DSN rejection.

The newer MySQL coverage on this main revision remains compatible: `tests/knowledge/test_queue_mysql.py` imports the queue fixture but retains the `mysql` module marker, so the shared reset applies; `tests/e2e/test_project_revision_preparation.py` also carries the marker. Inspection of the current production schemas found no additional mutable MySQL table requiring reset. No existing module/session-scoped MySQL fixture is invalidated by the function-scoped cleanup.

## Spec and evidence review

The PRD's test-isolation scope is respected. The fix does not change production capacity, approval, dispatch, verdict or schema behavior. README and the spec document the disposable-database fence, serial-process assumption, pre/post cleanup, retained tables, failure behavior and production-data handling. The design explicitly preserves the uncertainty about the exact row behind the historical full-suite failure while recording the separate reproducible reservation-contamination mechanism.

Historical QA is bound to `de4edcce73d7c2f57fe2213cf772b7d9dda45e2f`; it is not presented here as a fresh run on the integrated main revision. Its six test-file input hashes still match the integrated inputs. The following evidence hashes were independently verified against the retained files:

| Evidence | SHA-256 | Recorded result |
|---|---|---|
| `qa-mysql.log` | `60ed940cb4132e1b9cf6c7d7569a4483b51459f158f3acd2c71d2b8a658249a2` | 15 passed |
| `qa-probes.log` | `ca3bc939e5ab70b14ab977548ae0e0576560d31e07665eb0d6c9ac2c7ee2a172` | 4 passed |
| `qa-mypy.log` | `ab35ee42183d4d6d3ba483825ab037d18a5a15622d03be01d82220b1564851ff` | Targeted mypy success |

This review did not connect to MySQL or rerun integration tests. Fresh post-update verification is owned and recorded separately by the integrating agent. The reviewer changed only this review artifact and did not commit, merge, modify implementation, or alter QA evidence.
