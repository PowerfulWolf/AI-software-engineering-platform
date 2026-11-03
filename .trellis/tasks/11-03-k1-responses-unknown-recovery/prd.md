# Responses start-only Coder recovery

## Goal

Restore the original K1 Task after a synchronous Responses Coder Run left a real invocation start and local capture start, but no final outcome or stop. Keep the old Run UNKNOWN and preserve every worktree byte.

## Scope and allowed paths

- `src/ai_software_engineer/manager/{legacy_containment,baseline_production}.py`
- `tests/manager/{test_legacy_containment,test_legacy_rescue_delivery}.py`
- `scripts/sync-legacy-rescue-schemas.py`, its seven embedded `schemas/*.json` outputs, and `tests/contracts/{test_local_legacy_rescue_schema,test_repair_schema_generation}.py`
- `src/ai_software_engineer/manager/legacy_local_execution.py` for route-neutral survey guidance
- `.trellis/spec/core/legacy-execution-rescue.md`, `docs/architecture/contracts.md`, and this task record

No ProductSpec, Design, Plan, candidate, historical invocation, production database row or original Coder worktree may be changed by this platform patch.

## Acceptance

- Exact frozen Responses claim and start-only invocation may prepare a same-Task preserved-draft plan only after a complete current local survey.
- Responses cannot use a reboot-only approval. The independent engineering confirmation must bind the exact Run and all derived tools.
- Old outcome, stop, route final, receipt and accepted artifact remain absent; one ordinary work allowance is consumed only by the separately approved public execution.
- Native CLI recovery, missing route, sealed final, active process, drifted inventory and changed claim keep their prior fail-closed behavior.
- Subsequent Coder, QA and Reviewer remain separate claims with normal candidate checks.

## Validation and rollback

Run focused red/green tests, recovery regression, schema parity, Ruff, Mypy, and isolated MySQL public recovery. Before release, verify K1's current Task, claim, source, inventory, no late original output and service drain. Rollback to platform `e7b5e6663c77f0e56f947477099c0fe8abeaca5a` before any new Responses legacy binding is consumed; after consumption retain the new typed facts and use forward repair only.
