# Close explicitly abandoned engineering waits

Goal: let an exact user CLOSE_REQUIREMENT withdraw a stopped DELIVERING Requirement whose
complete historical Task/queue scope consists of terminal work and verified engineering waits.
Then the current CLOSED checkpoint can be deleted through the ordinary product tombstone operation.

Allowed paths: multi_directory/service.py, deletion.py, cancellation.py; cancellation schema;
manager lifecycle tests; team_view/app.js and focused UI tests; requirement-deletion/web-console
specs and team-console user instructions. No production SQL, verdict, Task state-machine, source
cleanup, candidate or merge changes.

Acceptance: full historical worker locks, no valid leases, complete typed owner/inventory checks,
current engineering waiting facts, exact checkpoint and close action; durable cancellation receipt
before Task/queue mutation; partial replay without duplicated events; CLOSED published last.
BLOCKED close behavior remains unchanged. Delete after close preserves the original close receipt.
Nonwaiting/live/missing-guard/drift facts fail closed.

Validation: focused manager lifecycle and MySQL queue cancellation tests, Node UI contract,
Ruff and strict mypy for changed Python files. Independent review is required before deployment.

Existing data: no direct DB patch. Stop admitted work through normal lifecycle, load the fix at an
idle controlled restart, submit CLOSE with the exact current digest, reread CLOSED, then submit
DELETE with its new digest. All audit history and dirty worktree bytes remain retained.

Rollback: revert this change while idle, retain published cancellation/tombstone records; do not
reopen cancelled engineering Tasks or rewrite old receipts.
