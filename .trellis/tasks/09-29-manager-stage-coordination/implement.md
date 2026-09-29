# Implementation and delivery record

## Milestones

1. Define typed time/retry and Manager run/claim/advice contracts, canonical Schema and compatibility
   tests. Finalize lease persistence without weakening the existing delivery-only WorkQueue validator.
2. Integrate durable Manager execution accounting into existing verification coordination; preserve
   exact-input cache, capability checks, source provenance and independent QA/Review.
3. Add cross-stage evidence readers and policy-bound coordinator at application composition, shared by
   Console/CLI/resume; separate advice from execution, stop recursive or budget-evading loops.
4. Wire configuration/Settings/UI projections and actionable original-stage + Manager status.
5. Check incremental tests, schema/spec parity, permission/refusal cases, restart and rollback.
   Commit only this task's changes, not other work already dirty at entry.

## Incremental validation targets

- Config/policy: `tests/config/test_execution_retry_policy.py`, new time/Manager policy contract tests.
- Existing path: `tests/manager/test_verification_coordination.py`, `tests/recovery/test_manager_coordination.py`.
- Upstream: `tests/manager/test_stage_retry_budget.py`, `tests/manager/test_design_retry_budget.py`.
- Cross-stage: new fake-client/store/coordinator tests for Product/Design/Plan/Coder/QA/Review,
  stale-source/action refusal, evidence tampering, cache/restart, interrupted reservation, exhausted limits.
- Claim/fence: isolated fixture tests for duplicate claims, lease expiry and write-before/after fencing;
  actual MySQL only with the repository's explicit test DSN safety guard, never production credentials.
- Wire: selected new/affected cases in `tests/contracts/test_json_schema_contracts.py`.
- UI: affected tests under `tests/team_view/` and `tests/web_console/`; only targeted browser tests if
  dependencies are installed, no full browser or Python suite.
- Ruff, format, strict mypy on affected modules; `git diff --check`.

## Completed implementation

- Task documents created manually because `.trellis/scripts/get_context.py` and `task.py` are absent.
- All five milestones implemented in the current checkout, single agent. Baseline implementation
  commit `349f971` already includes the separate context-budget work; it was not overwritten.
- Manager retries/time growth use durable SQL receipts, fresh real owner claims, exact input reuse,
  separate correction contexts, before/after transaction fences and CLI process-group cancellation.
- Cross-stage advice applies only advertised actions after source-fact recheck. Local timeout retry
  preserves Product approval; context failures/terminal delivery never gain automatic retry rights.
- Settings adds separate Manager and role time controls; contract version 2 blocks old-server saves.
  Read projections retain the actual stage and preserve exact approvals.

## Incremental verification

No full suite, production model, production database mutation, service restart or real requirement run.

```sh
.venv/bin/pytest -q --tb=short \
  tests/config/test_execution_retry_policy.py tests/config/test_execution_time_policy.py \
  tests/agents/test_structured_models.py tests/manager/test_manager_model_execution.py \
  tests/manager/test_stage_coordination.py tests/manager/test_verification_coordination.py \
  tests/manager/test_stage_retry_budget.py tests/manager/test_design_retry_budget.py \
  tests/recovery/test_manager_coordination.py tests/contracts/test_manager_coordination_schema.py \
  tests/team_view/test_design_budget.py tests/web_console/test_manager.py \
  tests/web_console/test_transport.py
# 172 passed; two existing Starlette/httpx deprecation warnings.

.venv/bin/pytest -q --tb=short tests/manager/test_manager_claim_mysql.py
# 1 passed, isolated test DSN only; pre/post fence loss rolls back.

node --test tests/team_view/ui.test.cjs tests/team_view/readiness.test.cjs
# 37 passed.

NODE_PATH=/Users/zhangjunshuai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
  node --test tests/team_view/browser/settings-layout.test.cjs tests/team_view/browser/design-budget.test.cjs
# Isolated browser fixture; settings alignment and submitted Manager/time policy verified.
```

Additional affected-file gates: `tests/agents/test_structured_execution.py`,
`tests/work_queue/test_owned_execution.py`, selected production-config/retry schema contracts;
Ruff check/format and strict `MYPYPATH=src .venv/bin/mypy` on changed Python files;
schema generator followed by `git diff --check`. Exact final results are recorded below before commit.

## 存量数据处置 / operator handoff

- No production facts were rewritten. Old checkpoint bytes/hashes and consumed approvals remain.
- Deployment requires Host restart and browser refresh; defaults apply to old config. First real
  Manager use creates an additive audit table, never edits existing Task/approval records.
- Only after separate user authorization: inspect the selected paused requirement and use its normal
  Continue/Recovery entry. Preserve any required new exact approval; no direct SQL resets.
- Rollback before publishing new facts: revert this code change. After publication: stop executions,
  retain audit history and prefer a forward-compatible correction; an old strict reader may require
  a verified consistent pre-rollout backup. Never delete receipts or strip fields to bypass hashes.
- Scope/limitations and precise APIs are in `.trellis/spec/core/manager-coordination.md`.
- User requested commit + push, then explicit authorization before resuming production work.

## Final verification results

- Final main incremental selection: **172 passed**; selected structured/owned-execution/schema
  checks: **58 passed, 55 deselected**; final isolated MySQL test: **1 passed**.
- Lightweight JS: **37 passed**. Real browser: both affected files **11 passed**, followed by the
  final budget file **6 passed** after adding original-stage/exact-approval coverage (12 unique cases).
- Ruff check/format: **29 Python files passed**. Strict mypy: **28 source/test files passed**.
- Schema regeneration and `git diff --check` passed. No new dependencies or service/model calls.
- Read-only `JointJournal(read_only=True).current(...)` validated the existing K1 requirement's full
  journal: ID `delivery_multi_33d30fe0776a232e31617caa9e702b915dcb4c65`, title
  `K1 自动知识采集首个闭环`, stage `BLOCKED`, sequence 16. No resume, approval or repair was submitted.
- No production smoke run by design: rollout/restart/resume await explicit user authorization.
