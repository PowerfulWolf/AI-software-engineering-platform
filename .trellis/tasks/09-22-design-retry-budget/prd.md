# Configurable Design retry budgets

## Goal

Allow operators to continue Design after temporary model failures without spending the design
correction allowance, and expose the correct recovery action when a budget is exhausted.

## Requirements

- Work in the current checkout, without subagents; commit the verified change as requested.
- Preserve serial stages, exact ProductSpec approval, journal hashes and historical failures.
- Split Design artifact attempts from typed transient infrastructure failures (including knowledge
  consultation before generation); unknown/non-transient exceptions remain conservative.
- Configure both finite limits through ProductionConfig and the existing Settings UI.
- Persist counts across restarts; raising a limit permits another attempt without editing history.
- Recovery must take precedence over ordinary retry. Exhausted budgets without an eligible recovery
  explain how to change settings instead of offering a guaranteed-to-fail continuation.
- Existing knowledge-approved Design recovery remains available for the reported codex Requirement.

## Acceptance

- [x] Typed retryable provider 504/timeouts/429 quota or rate failures do not spend Design attempts.
- [x] Rejected/invalid designs consume Design attempts; unknown failures cannot obtain free retries.
- [x] Exhausted transient or Design budget prevents another model call, including after restart.
- [x] Old config/journals remain readable and do not need migration or a MySQL write.
- [x] Config validation, service, projection, settings round-trip and actual UI action tests pass.
- [x] Trellis specs, generated schemas, operator recovery/rollback instructions agree with the code.

Validation evidence and untested production boundaries are recorded in [verification.md](verification.md).

## Scope and validation

Allowed paths: src/ai_software_engineer/{agents,config,multi_directory,manager,team_view}, tests/,
schemas/, config/production.example.json, docs/, .trellis/spec/, this task directory, AGENTS.md.
Run Ruff, mypy and only incremental pytest/Node checks for the changed contracts, service, settings
and UI (without live model access or production DB). The user explicitly ruled out full test runs.
No deployment, production mutation or real model retry is required for this code task.

## Decisions

Use existing append-only checkpoint attempts with a separate `design_transient` count. Refund the
reserved Design attempt only for a typed retryable provider failure or the existing knowledge wait.
Keep the reservation for unknown interruption/crash safety. No new automatic provider retry loop:
existing fallback stays bounded; another user continuation spends the separate durable allowance.
Default limits: 3 Design attempts and 5 transient failures, each configurable from 1 to 100.

Alternatives rejected: removing all limits permits endless provider traffic; increasing the old
shared limit continues to conflate invalid designs and infrastructure availability.
