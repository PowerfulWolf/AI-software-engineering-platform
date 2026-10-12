# Native rule review read isolation

## Goal and cause

The async native-rule review GET calls the synchronous Operation store directly before
its existing threaded complete-rule inspection. A FileConsoleOperationStore read can wait
on a file lock and block the ASGI event loop, including unrelated Console capability reads.
This is an independently reproduced defect, not an established cause of the user screenshot.

## Scope and allowed paths

- `src/ai_software_engineer/web_console/transport.py`: move the existing exact Operation
  lookup into the existing worker helper; retain validation and fixed failure envelope.
- `tests/web_console/test_native_rule_read_isolation.py`: Event-held fixture-only lookup,
  concurrent Console GET, read failures, invalid identity, unavailable administration.
- `.trellis/spec/core/web-console.md`: record the read isolation contract.
- This task directory.

## Acceptance

- While lookup is held, `/api/v1/console` completes before the test explicitly releases it.
- Rule reads and invalid/missing/corrupt inputs retain existing exact validation and HTTP errors.
- No Host construction, background execution, production SQL, K1 action, persisted facts,
  authorization or schema change. Existing records need no migration.

## Verification and rollback

Run the focused read-isolation and native-rule-review pytest files plus touched-file Ruff
and strict mypy. Run only incremental tests. Roll back this narrow code change; no durable
state needs restoring. Deploy only within the separately authorized service maintenance.
