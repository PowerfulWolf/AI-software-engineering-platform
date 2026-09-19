# MySQL pytest isolation design

## Evidence and hypotheses
The original ten-Task capacity test passed in a fresh disposable schema (39.48s). A genuine persistent-state producer was found in `test_active_candidate_verification_is_visible_as_qa_work`: it directly inserts a valid unfinished verification reservation and never completes/abandons it. `tmp_path` changes repository paths but every TeamHost still shares the SQL authority and Agent IDs.

Diagnostic alternatives were cross-test active reservations, leaked Python monkeypatch/global state, and broken terminal-Task lease release. Repeating the producer persisted eight reservations and made the original serial test BLOCKED before dispatch (`PlanningPreviewRejected`). A two-item subprocess regression showed the producer pass followed by a clean-database assertion failing with exactly one remaining reservation. Those results isolate the SQL lifecycle defect; no production capacity changes are justified. The original historical failure's exact native checkpoint was no longer available, so do not claim its precise row was identified.

## Contract
A function-scoped autouse fixture covers every mysql marker, independently of imported module-local fixtures. It validates and resets before dependent fixtures, captures the DSN, and resets in finally after them. Only the eight known mutable fact tables are deleted, in FK-safe order and one transaction. Missing tables are allowed. Authority locks, schema, archives and unrelated tables survive. Missing DSN skips; unsafe DSN aborts before SQL; failed cleanup propagates.

## Alternatives
- Fixing one producer with a local delete would leave recovery, dispatch, queue and future tests order-dependent.
- Creating one database per item would require broader database privileges and many schema initializations. The existing dedicated database plus per-item fact cleanup is the smaller change.
- Resetting only at session start would not isolate tests within the same session; only teardown would miss crash residue.
- Cross-worker locking is out of scope. Each concurrent process/worker must have its own disposable DSN, including independent QA.

## Regression coverage
The committed pytester tests use the actual production-host reader-test producer, real Git, MySQL dispatch/verification facts and a claimed WorkQueue item. They query SQL immediately after the subprocess exits to verify teardown on success, call failure and fixture failure. A separate test seeds old facts outside the child process to verify startup reset. A non-MySQL test proves unsafe DSN exit occurs before a dependent fixture marker file can be created and never prints the password.

## Existing data and rollback
No production data is read for repair or mutated. Old disposable test facts are intentionally reset by the next MySQL-marked test. Preserve needed failure evidence before rerunning; rerun the original node or complete suite with a dedicated DSN. Revert this task's tests and documentation patch to roll back. Production code and JSON Schema remain unchanged.
