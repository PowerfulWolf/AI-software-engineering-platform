# Isolate default Coder pytest cache

Goal: registered Python Coder validation must not create a default pytest cache in the source workspace.

Observed K1 run_c9014385fa3c4dc6b0a7e4872876ad9e ended rc1 without output. The intact final POLICY_VIOLATION remains history. A later read found exactly four new .pytest_cache files and zero noncache mutations relative to capture-start. The private failed-invocation index snapshot was not persisted, so this does not retrospectively prove every comparison component or the original provider cause.

Scope / ownership: src/ai_software_engineer/agents/codex_cli.py; tests/agents/test_coder_cache_isolation.py; .trellis/spec/core/coder-cache-isolation.md; this task directory. No Schema, DB, final classifier, workspace inventory or recovery authority changes.

Acceptance:
- Both default ASE_PROJECT_PYTEST and ASE_PROJECT_PYTHON -m pytest use a mode0700, per-invocation private pytest-cache under the existing writable run root, even with reduced/hostile environment.
- Real pytest executes tests and writes cache outside the source inventory; current-source, isolated interpreter, read-only dependencies, network and role boundaries remain.
- Fresh runs have distinct cache paths and clean them on success/failure. No tooling / QA / Reviewer receives the capability.
- Explicit workspace redirection is not authorized and strict failed-invocation mutation negatives still reject it.
- Keep K1 outcomes, drafts, claims and original approvals. Recover via public terminal plan only after current complete scene checks; do not rewrite POLICY or refund budget.

Validation: focused pytest tests/agents/test_coder_cache_isolation.py tests/agents/test_native_python_tooling.py tests/agents/test_codex_failed_continuation.py; scoped Ruff, strict Mypy, git diff --check. Add a real default-pytest regression that fails before production changes.

Rollback: revert this maintenance commit only at a verified idle service boundary. Preserve newly published recovery/artifact records and compatible readers; never reset the old Task or delete retained caches/drafts.
