# Result and recovery

Implemented in the current checkout without delegation. No live model call, production
restart, human answer/approval, or production Requirement mutation was performed.

## Behavior

- WAITING_HUMAN keeps the durable Design/Planning flow origin. Unknown origin does not
  highlight Product. Explicit recheck has a separate pending/Continue state after reload.
- Production joint knowledge calls receive typed per-unit read roots and Git revisions,
  including reviewed candidates for integration re-planning. Aggregate knowledge identity
  remains unchanged; new consultation run identity is versioned.
- Approved upstream resolutions cross Product/Designer/Planner boundaries under matching
  frozen scope/source. Prompts assign technical decisions to Designer and executable
  decomposition/feasibility to Planner. Repository conflicts are not silently deferred.
- New design calls require an explicit empty blocking_issues declaration to proceed.
  Rejected designs are feedback, consume the existing bounded work budget, and never dispatch.
- RECHECK_DESIGN appends a scoped investigation handoff; exact approval, budgets and history
  remain unchanged. It makes no model call. New real human gaps still stop the workflow.
- Preserved and completed the preceding CLI diagnostics presentation fix: CLI success no
  longer shows HTTP-only placeholders; Responses diagnostics retain HTTP status/request IDs.

## Incremental verification

163 Python tests passed, 26 Node tests passed. No full suite was run.

```sh
.venv/bin/pytest -q tests/knowledge/test_joint_recheck.py tests/knowledge/test_consultation.py tests/knowledge/test_stages.py tests/knowledge/test_schema_parity.py tests/manager/test_joint_designer_feedback.py tests/manager/test_joint_contracts.py tests/manager/test_joint_planner_feedback.py tests/web_console/test_manager.py tests/web_console/test_knowledge_resolution.py --tb=short
# 130 passed
.venv/bin/pytest -q -m 'not mysql' tests/team_view/test_live.py --tb=short
# 21 passed, 6 deselected
.venv/bin/pytest -q -m mysql tests/team_view/test_live.py tests/e2e/test_joint_delivery.py --tb=short
# 10 passed, 21 deselected; isolated test DB, scripted model clients
.venv/bin/pytest -q tests/contracts/test_json_schema_contracts.py -k console_operation --tb=short
# 2 passed, 100 deselected
node --test tests/team_view/knowledge-gap.test.cjs tests/team_view/ui.test.cjs
# 26 passed
```

Targeted strict Mypy passed for 18 touched source/test files; touched Python Ruff checks,
Node syntax, schema parity and `git diff --check` passed. `uv lock --check --offline` passed
using a writable temporary cache. Initial sandbox network/socket errors were rerun with
permission against loopback test infrastructure; no functional failure remains. Two
existing Starlette/httpx/anyio deprecation warnings remain. DOM tests cover flow, confirm,
loading and reload; the running production UI was not restarted for a visual smoke test.

## 存量数据处置

Affected Project: `project_codex_ea3536b4974b`.
Requirement: `delivery_multi_bd73c5ce9fa226eaa8e427b5c7c1dd96dce1e006`.

Read-only checks validated all 39 journal checkpoints, 8 historic stage proofs and 10
consultation digests. Latest stage is WAITING_HUMAN with origin PLANNING. Existing Product
approval is intact. No SQL migration or journal rewrite is needed.

Loaded local config `self-iteration-ai.json` has Designer work limit 5 and transient limit 5.
The requirement has used work 4 / transient 2; recheck eligibility is true under that policy.

1. Restart the Console/service with the updated code and its existing configuration.
2. Refresh this Requirement. Its flow should remain at Planning while waiting.
3. Click “重新核对设计” and confirm the investigation handoff (NOT the icon suggestion).
4. Click “继续交付” to invoke Designer with original Product approval, previous answers,
   original question and correct repository facts. Only 1 Designer work attempt remains.
5. If needed, raise Designer work budget in Settings, save and restart before retrying.
   Do not delete gaps, reset attempts or approve an unwanted behavior change to unblock it.

Rollback: before step 3, revert the code/schema commit. After step 3, retain compatible readers
or roll forward; keep the new journal fields and full history. Model behavior is not proven by
scripted tests, so the real rerun remains a user-controlled verification step.
