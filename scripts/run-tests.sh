#!/usr/bin/env bash
# Full test suite (see README "开发与验证"):
#   1. Python tests in parallel (pytest-xdist), excluding `serial` tests;
#   2. `serial` tests (signals, service supervisors, wall-clock windows) one at a time;
#   3. Node unit tests for the Web Console;
#   4. Browser layout tests, when Playwright is available on NODE_PATH.
# Each xdist worker gets its own MySQL test database (test_ase_<base>_<worker>).
set -euo pipefail
cd "$(dirname "$0")/.."
python=${PYTHON:-.venv/bin/python}
"$python" -m pytest -q -n auto --timeout 600 -m "not serial" "$@"
"$python" -m pytest -q --timeout 600 -m serial "$@"
node --test tests/team_view/*.test.cjs
if node -e 'require("playwright")' 2>/dev/null; then
  ASE_UI_BROWSER_CHANNEL=${ASE_UI_BROWSER_CHANNEL:-chromium} \
    node --test --test-timeout=120000 tests/team_view/browser/*.test.cjs
else
  echo "skip browser tests: Playwright is not on NODE_PATH (see README)" >&2
fi
