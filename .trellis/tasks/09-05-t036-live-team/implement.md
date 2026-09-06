# T036 Implementation record

## Delivered scope

- Local `ase team serve --port 8765` with packaged HTML/CSS/JavaScript and typed TeamSnapshot API.
- Company-scoped live aggregation of organization members, multi-request assignments, exact directory
  scope, native Task stages, joint delivery status, blockers, candidate revisions and verified reports.
- Completed model route history distinguishes planned assignments from actual provider fallback.
- Read-only store opens and MySQL snapshot transactions; no Host construction, schema initialization,
  provider call, state mutation, arbitrary file route or remote hosting.
- Five-second polling preserves expanded reports and marks retained data stale after failures.

## Bug Analysis: model history was empty despite completed delivery

### 1. Root Cause Category

- **B / D — Cross-Layer Contract / Test Coverage Gap**: reader copied an outdated documented path
  (`evidence/model-route-attempts`) while production writes to `runs/model-routes`.

### 2. Why Fixes Failed

No repeated speculative fixes. Initial tests verified delivery stages and reports but did not require
non-empty run history. A stronger full-flow assertion exposed the incorrect path.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
|---|---|---|---|
| P0 | Shared contract | Writer and reader use `agents.fallback.model_route_root` | DONE |
| P0 | Integration assertion | Each successful scripted delivery exposes three gpt-5.5 role calls | DONE |
| P1 | UI regression | Show failed primary route and successful fallback with duration separately | DONE |
| P1 | Knowledge | Correct production-team-host path and add live-team-view read/write rule | DONE |

### 4. Systematic Expansion

Read-side review also covers checkpoint roots, event-linked artifacts, evaluation events, dispatch
identity and company boundaries through actual producer/consumer integration. Future read models
must assert expected facts, not merely accept an empty collection as a valid response.

### 5. Knowledge Capture

- [x] Updated `.trellis/spec/core/production-team-host.md` and `live-team-view.md`.
- No template tree exists in this repository; no synthetic template directory added.
- Changes remain uncommitted alongside existing T035 work; no automatic merge or push.

## Verification

Targeted team-view suite: 15 passed, using local MySQL and Git fixtures with scripted providers.
Node DOM harness: passed, including model fallback rendering and stale/refresh behavior.
Ruff check / format, strict Mypy, offline build, lock consistency and whitespace checks passed.
Built wheel includes all three browser assets. Full regression: **713 passed in 102.22 seconds**
(2026-09-06), with no skipped tests.

```bash
ASE_TEST_MYSQL_DSN='<local test DSN>' UV_CACHE_DIR=/tmp/ase-uv-cache uv run --offline pytest -q
UV_CACHE_DIR=/tmp/ase-uv-cache uv run --offline ruff check .
UV_CACHE_DIR=/tmp/ase-uv-cache uv run --offline ruff format --check .
UV_CACHE_DIR=/tmp/ase-uv-cache uv run --offline mypy src tests
UV_CACHE_DIR=/tmp/ase-uv-cache uv build --offline
UV_CACHE_DIR=/tmp/ase-uv-cache uv lock --check --offline
node --test tests/team_view/ui.test.cjs
git diff --check
```

## Limits / rollback

No browser automation or manual visual acceptance was performed. No real model usage or production
service launch. The default production config is not present locally; use configured ASE_CONFIG and
MySQL as documented in README before launching. No heartbeat exists: execution_liveness is UNKNOWN.
This is a loopback-only read view, not a remotely exposed authenticated service.

Rollback: stop `ase team serve`; revert only T036 modules, CLI wiring and opt-in read-only extensions.
No database migration or rewrite of existing company/project records is required.
