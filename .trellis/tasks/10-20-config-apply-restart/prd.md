# Repair configuration application after a saved Console setting

## Goal and observed failure

The real lifecycle writer persists fixed Chinese summaries as escaped JSON. The service
supervisor compares literal serialized strings and therefore never consumes the valid
PENDING request. The browser eventually reports a connection timeout although the original
service remains running. The orphan-PENDING startup reconciliation uses the same faulty
literal matching. Fix the shared read boundary, not the browser wait duration.

## Scope and acceptance

- Read configuration-apply state through the typed lifecycle model and exact request identity.
- Accept existing escaped Chinese, literal Chinese and legacy English, independent of JSON
  field ordering/whitespace; reject duplicate/extra keys, unknown summary, wrong identity,
  trailing garbage and symlinks before any child replacement.
- Preserve controlled READY/actual exit/new instance, replacement locking and secret handling.
- Verify the real FileConfigurationLifecycle writer with the isolated service supervisor,
  including exact-once restart and orphan PENDING settlement. No production SQL or K1 edits.
- Deploy through official controlled stop/start, consume the existing pending request and
  verify public settings no longer require restart. Do not print configuration secrets.

## Allowed paths and validation

scripts/ase-console-service.sh; scripts/ase-console-lifecycle.py;
src/ai_software_engineer/web_console/lifecycle.py;
tests/test_console_service_script.py; tests/web_console/test_lifecycle.py;
.trellis/spec/core/web-console.md; this task directory.

Run focused writer/supervisor red-green tests, existing lifecycle/service-script regressions,
changed-file Ruff/format/strict Mypy, shell syntax, diff checks and independent review.

## Existing state and rollback

Current pending ID: configuration_apply_e16ed760d58d42fcf035db5a1e687385.
Preserve its bytes/identity and request marker until the fixed official supervisor consumes
or explicitly settles it. Restarting loads the saved config and fresh Host. Retain original
K1 IMPLEMENTING / revision11 / SERVICE_PAUSED checkpoint and all artifacts/drafts.
Rollback only at the controlled idle/exit boundary; do not reset requirement or execution
history, forge a successful apply, edit production SQL or rewrite the saved credentials.
