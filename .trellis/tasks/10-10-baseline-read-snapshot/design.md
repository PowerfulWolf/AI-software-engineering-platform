# Read-only baseline binding snapshot

`_TaskReadSnapshot` owns one `BaselineBindingSnapshot` for its finite HTTP projection.
The small interface accepts an already constructed read-only `FileExecutionBaselineStore`
and exact Task ID; `(store.root.absolute(), task_id)` identifies its complete verified
binding prefix. A successful original `bindings_for_task` result, including an empty
tuple, is reused only in that object. A raised validation error registers nothing.

The helper does not open stores, resolve symlinks, observe SQL, decide authorization,
or enter execution services. Each caller still constructs its read-only store and
performs its existing Task/scope/receipt/current-queue checks. Optional explicit helper
arguments preserve the original full-read behavior for standalone callers.

Allowed callers are engineering history, pending baseline continuation and interruption
history. No module/global/reader-instance/ContextVar cache, production writer change,
schema change or persisted-data migration is allowed. Each subsequent snapshot verifies
all bytes again and detects historical corruption or path changes.

Good: three projections consume the same fully validated immutable binding tuple.
Base: an empty prefix is reused during this snapshot, then a new snapshot observes append.
Bad: cache the latest engineering approval, skip caller scope checks, or reuse between HTTP reads.

Validation: real Git plan/decision/binding and interruption receipt exercise all three
callers; expect full binding validation 3 -> 1 with equal projections. Verify actual
`_TaskReadSnapshot` wiring, fresh append/tamper/symlink, distinct root/task, no writer use,
failure-before-registration and success/failure lifetime release. Only targeted tests,
Ruff, strict Mypy and short-deadline read-only performance measurements are in scope.
