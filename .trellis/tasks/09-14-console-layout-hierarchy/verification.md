# Verification

- `node --check src/ai_software_engineer/team_view/app.js` — passed.
- `node --test tests/team_view/ui.test.cjs` — 1 passed.
- `.venv/bin/pytest -q tests/web_console/test_transport.py` — 6 passed, 2 dependency deprecation warnings.
- `.venv/bin/ruff check src tests` — passed.
- `.venv/bin/ruff format --check src tests` — 347 files formatted.
- `.venv/bin/mypy src` — passed for 176 source files.
- `git diff --check` — passed.
- Manual local-browser inspection — Team, Requirements, Knowledge, Settings and Status rendered
  without browser errors; Agent queue board and responsive master/detail structure were visible.
- Human-operated full regression — passed on 2026-09-14.

The human-operated full regression merge gate is satisfied.
