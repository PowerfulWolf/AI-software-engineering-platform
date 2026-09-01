# T025 Verification

- `PYTEST_ADDOPTS='-p no:cacheprovider' .venv/bin/pytest -q tests/e2e` — **4 passed** (the matrix
  always runs profile, sidecar, evidence setup, and serial delivery; runtime probes are conditional).
- `RUFF_CACHE_DIR=/private/tmp/ase-ruff-cache .venv/bin/ruff check tests/e2e` — passed.
- `MYPYPATH=src MYPY_CACHE_DIR=/private/tmp/ase-mypy-cache .venv/bin/mypy --explicit-package-bases tests/e2e/test_target_project_delivery.py` — passed.
- `git diff --check` — pending final integration commit.

Known limitation: Java, Go, and TypeScript source compilation is not forced when their local
toolchain is absent, and no package manager/network access is allowed by this fixture task.  The
typed delivery contract remains fully exercised offline.
