# Incremental verification

Baseline: `48a08fd9962cc84de52118ee8aeabc077a1a1ec4`.

Focused Python suites for config, workforce, delivery composition, structured diagnostics,
fallback ledgers, role/worker binding, recovery, runtime allocation, Settings status and JSON
Schema contracts passed: **347 passed, 3 MySQL cases deselected** in the final combined
`pytest -m 'not mysql'` command. The browser-independent Team View DOM/readiness suites passed
25 cases with `node --test tests/team_view/ui.test.cjs tests/team_view/readiness.test.cjs`.
The focused Playwright Settings page passed both cases with bundled `NODE_PATH` and Chrome outside
the restricted sandbox, including legacy direct-route preservation and explicit CLIProxyAPI
selection. Changed Python paths passed `ruff format --check`, `ruff check` and `mypy`; `node --check`
and `git diff --check` passed. No full suite or real provider call ran.

Final Python command (repository root, `.venv`):

```sh
.venv/bin/python -m pytest -q \
  tests/config/test_production.py tests/manager/test_production_delivery.py \
  tests/manager/test_production_backend.py tests/agents/test_structured_models.py \
  tests/agents/test_model_diagnostics.py tests/agents/test_fallback.py \
  tests/work_queue/test_route_binding.py tests/web_console/test_administration.py \
  tests/team_view/test_live.py::test_wire_schema_and_extra_fields \
  tests/workforce/test_contracts.py tests/runtime_workspace/test_allocation.py \
  tests/manager/test_dispatch.py tests/recovery/test_verification_routing.py \
  tests/contracts/test_json_schema_contracts.py tests/manager/test_t031_schemas.py \
  tests/recovery/test_candidate_verification.py tests/recovery/test_verification_snapshot.py \
  tests/runtime_workspace/test_binding.py tests/runtime_workspace/test_binding_versions.py \
  tests/role_workspace/test_role_workspace.py tests/planning/test_preview.py \
  -m 'not mysql'
```

The restricted execution environment denied the configured local MySQL socket. Three
MySQL-marked production-backend cases and 13 MySQL-marked Team View cases failed during fixture
setup before assertions; later focused runs excluded them with `-m 'not mysql'`. This is an
environment limit, not a passing integration verdict. When MySQL is available, rerun only the
affected `tests/manager/test_production_backend.py` and `tests/team_view/test_live.py` marked
cases before production rollout.

## Existing data disposition

No database migration or automatic fact rewrite is required. Legacy config without a route mode
continues using the proxy when its saved global URL exists, otherwise direct CLI. Existing
immutable Task, Operation, approval, policy and call records retain their bytes and digest;
historic calls lacking mode are displayed as “连接方式未记录”. To continue an existing Requirement,
restart the Team Host after saving, inspect the frozen route/policy and current checkpoint, then
use the normal UI continuation. If adding a same-model second connection makes an old frozen
reference ambiguous, keep only its original matching route available until that Run completes,
or use the existing human-approved recovery flow; do not guess a transport or edit MySQL facts.

Known risk: live MySQL and real Codex/CLIProxyAPI integration were not exercised. Rollback is to
revert this commit and restart the Team Host. Existing route/call facts need no rollback rewrite.
