# Incremental verification

Baseline: `14cd8c0e69879731bd56f71264a6c2383da3300e`.

Red feedback loop before the fix:

- `UV_CACHE_DIR=/private/tmp/ase-uv-cache uv run --offline pytest -q tests/config/test_production.py -k 'same_model_reasoning_can_use_distinct_route_types or agent_reference_requires_type_when_same_model_has_two_types'` — 2 failed on three-field catalog uniqueness.
- `node --test tests/team_view/ui.test.cjs` — failed because explicit Codex CLI `image_input=false` still displayed “图像输入”.

Green incremental checks after the fix:

- Focused config/roster/queue/fallback/structured/dispatch/runtime/recovery/workforce/Settings Python suite — 193 passed.
- Focused planning-preview/model-routing/dispatch contracts — 39 passed (overlaps the previous suite).
- `node --test tests/team_view/ui.test.cjs tests/team_view/readiness.test.cjs` — 25 passed.
- Focused `tests/team_view/browser/settings-layout.test.cjs` with bundled `NODE_PATH` and a Chrome-capable execution context — 2 passed.
- `ruff format --check` and `ruff check` on changed Python paths — passed.
- `mypy src/ai_software_engineer` — passed; `git diff --check` — passed.
- Typed production config and ModelPolicy payloads also pass their static JSON Schema validators in the focused tests.

MySQL-backed `test_mysql_dispatch_authority.py`, selected `test_production_backend.py` and
`test_live.py` cases could not run because the configured local test MySQL endpoint is unavailable.
These are environment errors before the assertions, not test verdicts. No full suite was run, per
the user's constraint. No live provider call was made.

## Existing data disposition

No database migration or Task/Operation/approval rewrite is needed. Existing config/policy and
frozen Task facts without `route_kind` remain valid when their declared fields resolve to exactly
one route; optional fields are omitted from their canonical wire/hash. To continue a previously
frozen Run after adding a same-model/same-effort second type: inspect its frozen route facts
read-only, keep only its original matching route enabled for that Run, save and restart the Host,
then resume through the normal UI/CLI. After that Run finishes, restore the desired typed catalog
and restart. If the original transport cannot be established uniquely, stop and use the existing
human-approved recovery flow; do not edit MySQL facts or assign a type by guess.

Known risk: live MySQL/real-provider integration was not verified on this machine. Rollback is a
revert of this commit and restart of the Host; no secret file or database state was changed here.
