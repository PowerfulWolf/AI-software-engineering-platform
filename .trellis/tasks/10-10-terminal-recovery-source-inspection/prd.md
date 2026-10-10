# Terminal recovery synchronous inspection cost

## Goal

Reduce repeated complete-source detection inside one recovery preparation or exact approval.
The public preparation observed by the root task succeeded after 434.864 seconds; its trusted
source, patch, inventory, stop and approval checks must remain intact.

## Scope and ownership

Allowed production files: `recovery/entry.py`, `recovery/current.py`,
`recovery/workspace_snapshot.py`, using the existing `redaction.source_inspection_scope` only.
Add `tests/recovery/test_terminal_source_inspection_scope.py`, this task's records, and an
executable contract in `.trellis/spec/core/read-memory-lifecycle.md`.

No production operation, restart, approval, execution, database migration, full tests or commit
is owned by this subtask. No scope may surround `execute`/`resume_execution`, Host lifetime or
model execution. Other agents own concurrent Console and deployment work.

## Acceptance

- `NativeRecoveryEntry.propose`, `propose_delivery`, `approve`,
  `NativeRecoveryFactsVerifier.inspect` and `read_terminal_workspace_snapshot` each enter a
  bounded synchronous scope; nested calls share only exact pure detection tuples.
- Identical complete source/path is parsed once per outer call. A changed body/path still scans;
  every SQL, file, Git, capture, inventory, stop, claim, digest and authority check still runs.
- Double observations reject changed safe text and changed non-text facts.
- The existing 512-entry/16 MiB bounds remain unchanged; oversized entries scan without caching.
- Cache is absent after success/error and before returning to caller/model execution.
- Independent proposal and approval replay scan afresh; existing immutable receipt bytes agree.
- Targeted tests, Ruff and strict Mypy pass; independent review checks the envelopes.

## Rollback and existing data

Remove only the five decorators and their imports to restore prior inspection cost.
No Schema, Task, Operation, approval, candidate, plan, hash, workspace or database data changes
are required. Existing plans remain usable under their original exact approval and current-facts
gates. The root task owns an idle code restart and new public-path timing observation.
