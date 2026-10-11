# Structured execution trustworthy observations

## Goal
Preserve trusted admission and actual native-process shutdown facts for structured
model calls before the subprocess bridge raises or the caller parses output.

## Scope
Only agents structured execution/observation, minimal structured client wiring,
dedicated tests, one additive Schema and one new core spec. No knowledge retry,
queue, orchestration, recovery, production maintenance or durable-state changes.

Allowed paths: `agents/structured_execution.py`, `agents/structured_observation.py`,
minimal `agents/structured.py` wiring, `tests/agents/test_structured_observation.py`,
existing structured execution tests if needed, the dedicated observation Schema,
this task directory and `.trellis/spec/core/structured-execution-observation.md`.
Independent review extends the allowlist to the minimal startup-failure type and
post-Popen cleanup placement in `agents/codex_cli.py`; runner permissions, command
environment, timeout and ownership checks remain authoritative.

## Acceptance
- Optional typed observer receives admission before each actual fallback route.
- Native receipts contain only the owned runner's validated NativeProcessStop.
- Timeout, nonzero exit and invalid JSON retain the actual stop receipt.
- HTTP round trips have their own typed receipt, never a native stop.
- Definitive pre-Popen startup failure has a distinct typed NOT_STARTED receipt;
  post-Popen registration failure stops the actual child and never claims that
  execution did not start or falls through as a provider transient failure.
- Unknown execution endings never produce a stop; failed receipt publication
  fails closed and cannot be masked by provider fallback.
- Context binding resets on all exits and isolates concurrent callers.
- Incremental real subprocess and Schema contract tests pass; no full suite.

## Rollback
Remove the optional observation wiring at an idle deployment boundary. No data
migration/backfill; existing unknown calls remain unknown. This layer alone does
not repair the current Requirement or authorize its continuation.
