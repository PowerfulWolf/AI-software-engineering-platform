# Verification — 2026-09-22

## Scope and result

Implemented in the current `main` checkout, from baseline
`faffb49fe26561a34e40db374cd905876387a96a`. No subagents, new worktree, production mutation,
deployment or real model call. These are single-agent engineering checks, not independent QA/Review
verdicts. Per the user's explicit instruction, only incremental tests were run.

Config → Host/service → immutable checkpoint → read projection → Settings/Requirement UI use one
typed retry policy. Existing recovery still requires the exact checkpoint and historical approved
knowledge; it cannot reset transient failures. No DB or immutable checkpoint schema migration.

## Incremental Python tests

```sh
.venv/bin/python -m pytest -q \
  tests/manager/test_design_retry_budget.py \
  tests/manager/test_joint_designer_feedback.py \
  tests/team_view/test_design_budget.py \
  tests/config/test_production.py \
  tests/contracts/test_json_schema_contracts.py::test_design_retry_budget_schema_rejects_invalid_limits \
  tests/contracts/test_json_schema_contracts.py::test_design_retry_budget_schema_allows_legacy_and_custom_policies \
  tests/web_console/test_administration.py::test_design_retry_settings_roundtrip_requires_restart \
  tests/manager/test_team_host.py::test_team_host_scopes_product_catalog_and_context \
  tests/team_view/test_live.py::test_wire_schema_and_extra_fields \
  tests/web_console/test_manager.py::test_recover_design_intent_binds_exact_checkpoint_and_audit_reference \
  tests/agents/test_structured_models.py
```

Result: **102 passed**. Covers typed/nonretryable errors, knowledge assessment, mixed rejections and
transients, crash-safe reservation, restart, raising/lowering limits, preserved historical hashes,
Host configuration propagation, Settings restart, read-only projection, schema and exact intent.

Seven HTTP fixture tests initially could not bind a local port in the sandbox. The same targeted
selection was rerun with approved local execution; no product test failure remained:

```sh
env -u ASE_TEST_MYSQL_DSN -u ASE_RUN_LIVE_TESTS .venv/bin/python -m pytest -q \
  tests/team_view/test_live.py -k 'write_methods_rejected or http_refresh_and_security'
```

Result: **7 passed, 20 deselected**. Local fixture only; no production DB.

## Incremental UI tests

```sh
node --test tests/team_view/knowledge-gap.test.cjs tests/team_view/ui.test.cjs
```

Result: **22 passed**.

```sh
NODE_PATH=/Users/zhangjunshuai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
  node --test tests/team_view/browser/design-budget.test.cjs
```

Result: **2 passed**, real Chrome with fixture routes and approved local browser execution. Verified
the exact RECOVER_DESIGN submission, failed-retry precedence, suppression during an active operation,
separate counters, absent impossible Continue action, settings values and browser range validation.

## Static checks

- `.venv/bin/ruff check src tests`: passed.
- `.venv/bin/mypy src tests`: passed, 434 source files.
- `.venv/bin/ruff format --check` on the 13 changed Python files: passed.
- `git diff --check`: passed.
- Full tests, live-provider validation and post-deployment human testing: deliberately not run.

## Existing data disposition

Read-only `ProductionTeamReader` and `JointJournal` verification of
`project_codex_ea3536b4974b` / `delivery_multi_bd73c5ce9fa226eaa8e427b5c7c1dd96dce1e006`
(“设置保存交互优化”) verified all **30 checkpoints**. Latest digest:
`8a5dce489acaa44f9d72c3e6548b16af3f17e6efd00781bbb75297a58f91fdce`.

The new projection reports DESIGNING, `design_recovery_available=true`, Design **3/3**, transient
**0/5**, exhausted `design`. Journal history before and after inspection is identical. Production
MySQL, Operation history, configuration and service process were not changed. Legacy 504 failures
were not silently reclassified or removed.

No data repair is necessary. After deploying/restarting this code and refreshing the Console,
the user can open the existing Requirement and click **恢复设计** once. This appends an audited
recovery and reuses the ProductSpec approval. Alternatively, increase the Design limit in Settings,
save/apply/restart, then retry; future typed transient failures have their own allowance.

## Risks and rollback

- Unknown process crashes conservatively spend Design reservations; no automatic infinite retry.
- Settings take effect after Host/Reader restart, and spent counts persist. No claim is made that
  the external provider is currently healthy or that the real Requirement has completed.
- Revert this code commit to roll back. If new Settings were saved, stop the service and remove
  `design_retry_policy` before starting the old strict config parser. Preserve all journals and
  pause Design continuation while rolled back; old code has the old shared-budget behavior.
- Detailed operator steps: `docs/operator-feedback-loop.md`, “Design 预算耗尽与存量需求处置”.
