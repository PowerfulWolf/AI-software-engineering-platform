# Verification — Project Switching

Release follow-up: user subsequently authorized commit/tag. The fix is now committed/pushed as
`4d1e799ed48abf0b3a8c053b71772c8567da45d2`, annotated `v0.1.2`; 61 Node cases reran successfully.
The original verification-phase notes below retain their historical uncommitted state.

Date: 2026-09-28. Baseline: `321f15e`, pushed to `origin/main` before task creation.
That baseline contains the prior 174-file change set; the navigation fix is separate, uncommitted
work. Final `HEAD...origin/main` is `0 0`.

## Regression evidence

- Before repair, a real ai-project→codex click while Refresh was disabled remained on ai-project
  across later polls. The requested codex API returned the correct identity in 7.4–8.0 seconds.
- Held-poll regression failed first: expected `project_other`, actual `project_fixture`. The repair
  retains the click and drains it without another click/tick.
- Review found a second async boundary: a Knowledge snapshot could become B internally while its
  selector still displayed A. The added regression failed first (expected `Project B`, actual
  `Fixture project`), then passed after publishing B together with a Knowledge loading view. It also
  proves later C failure leaves coherent B scope/assets rather than a stale A view or stuck loading.

## Automated checks

| Command | Result |
|---|---|
| `node --test tests/team_view/*.test.cjs` | 61 passed; 12 new navigation/boundary regressions |
| `.venv/bin/pytest -q -m 'not mysql'` | 1971 passed, 10 opt-in skipped, 101 MySQL deselected; 205.75s |
| `.venv/bin/pytest -q tests/team_view tests/web_console -m 'not mysql'` | Final Knowledge-boundary change: 151 passed, 6 deselected; 17.10s |
| `.venv/bin/ruff check .` | Passed |
| `.venv/bin/ruff format --check src tests` | 480 files already formatted |
| `.venv/bin/mypy src tests` | Passed, 485 source files |
| `node --check src/ai_software_engineer/team_view/app.js` | Passed |
| `uv build --offline` | sdist and wheel built successfully after final code change |
| `git diff --check` | Passed |

The full Python run preceded the small final Knowledge rendering change; all Node regressions and
the focused Python Team/Console suite were rerun afterward. Two existing Starlette/httpx/AnyIO
deprecation warnings remain. No MySQL integration, live model, native GUI or sandbox opt-in suite is
claimed by this task. The browser checks below are separate from those opt-in Python tests.

## Actual localhost browser

Read-only checks against the running `http://127.0.0.1:8765/` service:

1. While Refresh was disabled, click codex once. Immediately observed:
   `正在切换到「codex」…当前仍显示「ai-project」的数据。`
2. No second click: Project picker became codex. Project Knowledge selected codex and displayed
   `codex · Project 知识`.
3. Switch Knowledge to app-cloud and ai-project: selector/context/content followed the new Project.
4. Reload the final JS version, open Project Knowledge while refreshing, then click codex followed
   by app-cloud in the same verification call. Final selected tab, Project scope and asset heading
   all displayed app-cloud. No browser warnings/errors captured.

Existing inventories were empty; this live check proves Project identity and empty-state scope,
not imported document contents. Deterministic tests cover held reads, failure/timeout, late body,
latest selection, cancellation, command gates and Knowledge loading. No approval, Continue,
upload, selection write or business operation was submitted.

## Bug Analysis

### 1. Root Cause Category

- E — implicit assumption: the shared refresh would be idle when a person selected a Project.
- D — test gap: selector rendering existed, but no held-poll + actual picker-click test.
- A — missing spec: polling coalescing and explicit navigation had no distinct contracts.

### 2. Why Fixes Failed

No earlier navigation repair is claimed. Code review of this repair exposed an additional
Knowledge publication window: checking staleness after an await is insufficient if identity has
already changed without rendering. A failing test was added before correcting that window.

### 3. Prevention Mechanisms

- DONE: latest-intent single-flight coordinator; periodic ticks cannot overwrite the target.
- DONE: exact target validation, body-await stale guard and retained failure retry target.
- DONE: identity/loading-view publication before Knowledge awaits; late navigation feedback retained.
- DONE: deterministic UI regressions and a seven-section executable navigation spec.

### 4. Systematic Expansion

Both the Team/Requirement picker and Knowledge tabs share the coordinator. Manual runtime-status
refresh and composer protections are explicitly covered. Shared Console/Operations reads remain
serial because naive cancellation would alter global readiness. API read latency remains a separate
performance concern; this fix does not claim faster backend projection.

### 5. Knowledge Capture

- `.trellis/spec/core/project-navigation.md`: contracts, error matrix, cases and assertions.
- Core index and Web Console user-visible flow link to that contract.
- No repository template mirror or Trellis scripts exist; task files follow `tasks/FORMAT.md`.

## 存量数据处置 / rollout / rollback

- No database, Requirement/Task/Operation, approval, candidate or verification record changes are
  needed. This is lost browser intent, not corrupted durable state; no delivery resume is required.
- The running service reads the updated static asset. Refresh an existing browser page to load it;
  no service restart, Xcode action or environment permission change is necessary.
- Slow reads can still delay completion, now with explicit destination feedback and retained intent.
- Rollback, if requested: restore only this task's UI/test/spec/task changes to the `321f15e`
  baseline and reload the browser. Do not reset unrelated work or rewrite business history.
- Status remains `in_progress / verified_pending_commit`. Trellis finish/archive is not run with
  this task's code still uncommitted; no independent QA/Reviewer verdict is fabricated.
