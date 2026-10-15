# Verification

Baseline deployed before this fix: `caa8227`.

Red/green public reproduction: `tests/manager/test_legacy_rescue_delivery.py -k False-False-True-False-True` against baseline source fails with the real production error `旧现场包含未纳入完整草稿的忽略文件`; the same test with maintenance source passes (41.53s). It retains the same Task/unknown execution, checks the prepared tree's ignored module, pauses, performs an approved source/rules rebind, resumes, and reaches native Coder/independent QA/Review on the exact candidate with the module present.

Commands below use original project `.venv/bin/python` and `PYTHONPATH=/tmp/ase-fix-legacy-ignored/src`:

- `pytest tests/manager/test_legacy_rescue_delivery.py tests/web_console/test_legacy_rescue_acceptance.py -q --tb=short`: 23 passed; 2 existing Starlette deprecation warnings.
- `pytest tests/git/test_mutation_capture.py tests/git/test_worktree.py -q --tb=short`: 67 passed (includes ignored-only cleanup preservation and explicit-cache cleanup).
- `pytest tests/manager/test_legacy_snapshot.py tests/manager/test_legacy_containment.py tests/git/test_mutation_capture.py -q --tb=short`: 91 passed before adding the two cleanup tests.
- `pytest tests/manager/test_execution_baseline.py tests/manager/test_paused_baseline_service.py tests/manager/test_baseline_wait_fact_collection.py tests/manager/test_wait_fact_collection.py tests/manager/test_rejected_coder_output.py tests/manager/test_stopped_budget_settlement.py -m 'not mysql' -q --tb=short`: 78 passed.
- Native/Responses/candidate/factory suite: 105 passed, with final constructor/type refinements retested in the 36-case focused subset.
- Native v1/v2/idle reconciliation suite: 82 passed, 4 expected v1 skips. Additional exact-base restoration/deletion matrix: 12 passed + 6 expected v1 skips; clean-base behavior: 2 passed + 1 expected skip. Final type-narrowed affected subset: 16 passed + 10 expected skips.
- Ruff check + format check and full mypy on all 20 changed Python source/test files: passed.
- `git diff --check`: passed.

Independent read-only reviewers identified and verified fixes for preview-tree omission, candidate omission, continuation omission, ignored-only cleanup loss and tracked-edit reversal. Final review reports no blocking findings. Reviewer separately exercised exact-base byte/mode/untracked/deny refusals.

No Schema or SQL migration; historical serialized record bytes/digests remain unchanged. Production existing-data recovery must use the public exact engineering plan/decision and preserve the old UNKNOWN start/outcome gap. Rollback: revert the maintenance commit, controlled pause/restart; do not rewrite published immutable recovery facts or delete retained source.
