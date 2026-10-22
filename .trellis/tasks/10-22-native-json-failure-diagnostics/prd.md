# Native JSON failure diagnostics

## Goal and scope
Preserve complete trusted native main errors for future Codex Delivery and structured invocations when bounded output discards the middle. Reuse output-last-message, owned runner, stop proofs and all policy/artifact/retry gates.

Allowed: agents/codex_cli.py, agents/_native_output.py, new private agents/_codex_events.py, shared structured.py/structured_execution.py, corresponding tests/agents, core/native-cli-unknown-failure.md and this task. Parent task files and all K1/production facts are excluded. No commit, merge, deploy or restart.

## Acceptance
- Delivery requests --json; trusted composition explicitly enables the protocol, default off.
- Observe original stdout bytes before head/tail retention. Bound each line to 65536 bytes; reject invalid UTF-8/JSON, duplicate keys, nonfinite constants and partial final lines. Never reconstruct retained text.
- Only root error.message and turn.failed.error.message supply a candidate. New thread/turn and turn.completed clear earlier candidates. Nested tool/MCP/items carry no authority.
- One private typed observation binds event type, ordinal, complete-event SHA, completeness and cleaned bounded message to the same invocation after EOF and owned-session stop, before stop observer.
- rc0, signal, timeout, guard and pause retain priority. Missing trustworthy final event keeps stderr fallback/unknown nontransient behavior. All existing candidate/role/retry/recovery gates remain.
- Fully clean exact proxy key, private key, URL, credentials and controls before bounds. Structured path shares observer without post-hoc stdout classification.
- Real offline runner/adapter regressions, negatives, Ruff and strict Mypy pass.

## Stock data / rollback
No migration/backfill, refund or history rewrite. Existing failures, counters, outcomes and approvals retain their original bytes/meaning. Parent continues K1 through existing exact public recovery. Roll back these scoped source changes at idle release boundary while preserving published facts.
