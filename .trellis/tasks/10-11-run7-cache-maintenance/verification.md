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
`119ac8bf3826cedcb389f70a050261e5a15ff56174edb6902b5e221633f43e0c`.
After independent review, the authorized apply completed at 2026-10-11T12:12:25Z, followed by
successful exact completion replay. The private 0600 plan, authorization, completion and all
four original cache files are retained in the sidecar's `state/external-maintenance/<plan-sha>/`.
The task-local review plan is excluded from Git.

存量数据处置：moved only the four exact root `.mypy_cache` files to the private audit archive.
The ordinary bounded after-inventory is
`dd809c4c11212185057e09488050966153aa49b6c819917772643f46ed9b2e71`;
the complete source capture stayed
`f8ce0c082b9089b7afa9ddcd82a4deb4024052db8041382bee7a325d0f9a68bc`.
HEAD/index, Task/work/claim and original invocation start/stop/outcome were checked unchanged.
No database/state/verdict or old stop fact was edited, and no budget was refunded. The original
report remains UNKNOWN. HumanActionEvent
`evalevt_external_cache_119ac8bf3826cedcb389f70a050261e5a1` records the supplied maintenance evidence.
Public baseline proposal/approval/continuation remains a separate, explicit operation.
Rollback preserves the archive and requires a separately verified idle rename, not deletion.
