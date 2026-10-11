# Incremental verification and stock handling

Contract-first test reproduced the default 16MB rejection for a real 16,000,001-byte file.
The original API could not admit an exact observation capability. After implementation:

- `uv run pytest -q tests/git/test_exact_oversized_inventory.py
  tests/git/test_mutation_inventory.py tests/git/test_mutation_capture.py`: 54 passed (48.13s).
- Two additional total/count boundary cases: complete exact inventory module, 13 passed.
- `uv run pytest -q tests/git/test_cache_quarantine_maintenance.py --tb=short`: 2 passed
  (4.11s), actual rename/hash plus completion fault/resume/replay and authority/hash drift.
- Ruff check/format and strict mypy over inventory, both test modules and maintenance script:
  pass. `git diff --check`: pass. No full test suite.

Prepare ran twice under exact Task/queue locks and real stop validation, yielding the same plan
`119ac8bf3826cedcb389f70a050261e5a15ff56174edb6902b5e221633f43e0c`. No production mutation.
The private 0600 review plan is excluded from Git and will be preserved in the sidecar audit.

存量数据处置：only the exact four original cache files will be preserved outside the worktree.
No database/state/outcome/verdict or old stop fact is edited. The original report remains UNKNOWN.
Apply and independent after/replay verification are pending; public baseline recovery is separate.
Rollback preserves the archive and requires a separately verified idle rename, not deletion.
