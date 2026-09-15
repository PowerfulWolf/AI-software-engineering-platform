# Verification

## Focused evidence

- `tests/manager/test_requirement_retirement.py`: replacement, logical deletion, immutable history,
  stale/stage/unchanged guards, tamper detection, idempotent retry and replacement existence.
- `tests/web_console/test_manager.py`: typed UPDATE/DELETE delegation with exact checkpoint.
- `tests/contracts/test_json_schema_contracts.py` and `tests/manager/test_joint_contracts.py`: public
  Console operation and retirement schema parity.
- `tests/team_view/test_live.py`: retired Requirement hidden from list and Project count.
- `tests/team_view/ui.test.cjs`: edit/delete controls and payloads, replacement selection, deletion,
  and dismissible failed Operation notification.

Incremental Ruff, formatter, strict Mypy, JavaScript syntax, schema and focused tests must pass before
handoff. Full regression remains the human gate before commit/push.

## Result

- Focused Python suites: `88 passed`.
- Retired Requirement read projection: `1 passed`.
- Browser DOM harness: `4 passed`.
- Targeted Ruff check and format check: passed.
- Strict Mypy for six affected source modules: passed.
- JavaScript syntax and `git diff --check`: passed.
- Full regression: passed by the human on 2026-09-15; commit/push authorized.
