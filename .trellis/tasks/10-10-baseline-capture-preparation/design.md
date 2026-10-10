# Design

The source proposal's production fact collector already holds the real Task process lock
and SQL idle fence. Bind the explicit `BaselineProposeCommand` to that collector before
`ExecutionBaselineService.propose`; validate expected intent/revision/work-item/source
inside the same scope before publishing any missing invocation outcome or capture receipt.

For SOURCE_REBIND and unresolved EXECUTION_UNCERTAIN/PLATFORM_BUG waits, reuse
`DeliveryWaitFactCollector.collect` with exact native ContinuationScope and the existing
guard. Do not call HANDLE and do not acquire a second SQL idle scope. The collector appends
only real original facts; the existing baseline proof, budget accounting, mutation preview,
human native-rule approval and PAUSE/RESUME contracts remain authoritative.

Public delivery_multi addressing is resolved through Host's exact Requirement/Task mapping
before binding. Only the internal typed command copy is normalized to the native child ID;
the receipt ContinuationScope never uses the parent ID. Foreign parents fail before any
receipt publication. The original public command still verifies the resulting plan facts.

Execute/continue recollection does not bind a new proposal and therefore cannot reconcile
new facts implicitly. Paused and ordinary preflight items skip reconciliation. Success
outcomes remain success and cannot be overwritten by baseline retry. Stale commands,
missing or live stop, changed claim/scope/source, actual credentials and output-present
stops fail closed, keeping Task, queue, budgets and workspace unchanged.

Validation: focused real-Git tests plus one public Host missing-receipt→proposal→PAUSE→
explicit RESUME→independent QA/Review variant; only incremental tests, Ruff and strict Mypy.
Rollback changes code only; immutable new receipts remain readable and no production data
is changed by this task.
