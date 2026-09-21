# Model-call diagnostics and knowledge clarification UI

## Goal and scope

Record each configured structured primary/fallback model attempt (success or failure),
including role/phase, duration, HTTP status and safe gateway request identifiers. Show
the records from the Console without rerunning models. Fix the knowledge gap section's
typography/spacing and repeated-click duplication while retaining answer drafts.

## Contracts

- Add a typed, bounded diagnostic observer scoped to one Console operation. Capture
  completed calls immediately in a separate append-only, content-addressed sidecar;
  do not change historical Operation hashes, delivery checkpoints or retry policies.
- HTTP response metadata contains only allowlisted request/correlation identifiers;
  never persist credentials, arbitrary headers, prompt, raw response body or URLs.
- GET /api/v1/operations/{operation_id}/model-calls is read-only. Old operations have
  no records; do not synthesize past failures. Diagnostics do not authorize replay.
- Knowledge gaps use one lazy expandable region per requirement/checkpoint, one
  in-flight load, bounded cards with ordinary body text, explicit field labels and
  one error region. Reopening and polling retain drafts. Resolution keeps the existing
  exact gap approval API; no automatic approval or continuation.

## Acceptance / incremental verification

- Offline primary 504 -> fallback success/failure records both calls, exact order,
  duration, status and request IDs. Timeout remains distinct from HTTP failure.
- Stored calls survive restart/interruption; unknown operations, tampering and
  symlinks fail closed. No changes to original operation history or production data.
- Concurrent observer scopes do not mix operations; exception paths reset context.
- Repeated/in-flight knowledge clicks show one form per gap. Retry does not append
  errors; collapsing/reopening and rerender preserve drafts. HTML stays text-only.
- Focused pytest, Node DOM contracts, Ruff, strict Mypy, diff check, offline visual QA.
  No live model requests, service restart, full regression, commit or push.

## Existing data and rollback

Existing requirements, approvals and operations require no repair/migration. Restart
Console to load the backend and refresh the browser; only subsequent calls acquire
diagnostics. Existing pending knowledge gaps use the updated UI without resubmission.
Rollback the changed source/assets; preserve diagnostic sidecars and historical data.

## Allowed implementation paths

`src/ai_software_engineer/agents/`, `knowledge/agents.py`, `manager/production_backend.py`,
`web_console/`, `team_view/app.js`, `team_view/style.css`, their focused tests,
`schemas/model-call-diagnostic.schema.json`, `docs/contracts.md`, and this task/spec documentation.
Keep pre-existing Product failure diagnostics edits intact. No production configuration, database,
requirement journal or model-route changes.

## Verification result — 2026-09-21

- 88 focused Python tests passed; two existing dependency deprecation warnings.
- 30 frontend Node tests passed, including repeated clicks, pending requests, approval retry,
  draft/checkpoint isolation and model diagnostic display.
- Ruff check/format, strict Mypy on 10 affected source files and `git diff --check` passed.
- Offline browser visual inspection used the actual app assets with fixture data at 900px and
  390px widths. Long text wraps, cards do not overflow and draft text survives reopening.
  The temporary preview server was stopped; no production service was restarted.
- New boundary tests first reproduced image-filtered backup being mislabeled as primary and
  a non-directory diagnostic path being silently treated as empty; both now pass.
- No real model calls, full regression, database edits, commit or push were performed.

Focused test commands (from repository root):

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/agents/test_model_diagnostics.py tests/agents/test_structured_models.py \
  tests/agents/test_openai_compatible.py tests/web_console/test_model_calls.py \
  tests/web_console/test_core.py tests/web_console/test_transport.py \
  tests/web_console/test_product_failure.py tests/knowledge/test_consultation.py \
  tests/manager/test_production_agents.py \
  tests/contracts/test_json_schema_contracts.py::test_all_committed_schemas_are_valid_draft_2020_12_documents \
  -p no:cacheprovider
node --test tests/team_view/*.test.cjs
```

Remaining operational action: the user restarts Console with the established environment when
idle and refreshes the page. Resume the original requirement only through the platform. This
adds evidence for any future 504; it does not establish or fix the historical gateway root cause.
