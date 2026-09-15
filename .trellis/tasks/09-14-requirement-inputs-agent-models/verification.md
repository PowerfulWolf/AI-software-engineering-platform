# Verification update: explicit Agent fallbacks

## Focused checks

- `node --check src/ai_software_engineer/team_view/app.js` — passed.
- `node --test tests/team_view/ui.test.cjs` — 3 passed.
- `uv run pytest -q tests/config/test_production.py` — 27 passed.
- `uv run pytest -q tests/web_console/test_administration.py -k 'runtime_values_are_write_only_and_feed_status or status_reports_each_agent_exact_model_route_and_readiness'` — 2 passed.
- `uv run pytest -q tests/manager/test_team_roster.py` — 4 passed.
- `uv run pytest -q tests/web_console/test_transport.py -k administration_endpoints_create_project_import_document_and_save_settings` — 1 passed.
- `uv run ruff check tests/config/test_production.py` — passed.
- `uv run ruff format --check tests/config/test_production.py` — passed.
- `MYPYPATH=src uv run mypy tests/config/test_production.py` — passed.
- `git diff --check` — passed.

## Covered behavior

- Enabling or adding a catalog route does not add it to any Agent fallback list.
- A legacy empty policy becomes seven primary-only policies in Settings.
- Fallbacks are selected from enabled catalog routes and can be added, removed and reordered.
- Saved route order is preserved by Python configuration and runtime status projection.

## Human regression

Full repository regression passed on 2026-09-15 and authorized commit/push.
