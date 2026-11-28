#!/usr/bin/env bash
# Full test suite: parallel first, then the serial-only tests (see tests/conftest.py).
# Each pytest-xdist worker gets its own MySQL test database (test_ase_<base>_<worker>).
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pytest -q -n auto --timeout 600 -m "not serial" "$@"
python -m pytest -q --timeout 600 -m serial "$@"
