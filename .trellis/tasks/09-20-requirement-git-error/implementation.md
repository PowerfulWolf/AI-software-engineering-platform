# Git baseline error correction

Task: `09-20-requirement-git-error`  
Source revision: `0c5d0bb9cf42ae75ce5d43acbfa11379a58db124`  
Coder worktree: `/private/tmp/ase-requirement-git-error-20260920`  
Contract: `docs/requirement-git-baseline.md`  
Contract SHA-256: `ca3775ba3b378aae5f188e4d14f1d66d855e2596b567b4d0275940294b103ef9`

## Root cause and implementation

The real production-preparation/Console test reproduced the exact original message for both
non-Git directories and repositories without commits. The underlying error is a 510-character
Pydantic ValidationError: checkpoint serialization omitted the required nullable base_revision
before the old Git guard could run. Console correctly bounded the diagnostic but lost the
actionable cause.

The fix checks the discovered scope before intake persistence. Historical PREPARING status
returns verified missing-baseline facts without reconcile; advance validates before
reconcile/prepare. A typed exception maps to
GIT_BASELINE_REQUIRED and a bounded Chinese explanation identifying the directory. Other
errors retain their safe fallback. No Schema, permissions, model or state-machine changes.

## Regression evidence

Before the fix:

`PYTHONPATH=src <main>/.venv/bin/python -m pytest -q tests/web_console/test_git_baseline.py`

Both baseline cases failed with `COMMAND_REJECTED` and the exact reported generic message.
After the fix the expanded suite has 9 passing cases. Independent QA identified the extra
`status()` call before resume; a failing sentinel regression was added and then fixed, ensuring
neither reconcile nor prepare precedes the historical baseline check.

The final combined Console/contracts/Requirement/preparation/workspace run passed 204 tests
(two existing dependency deprecation warnings). It preserves the existing ability to inspect
PREPARING history when source is missing. Changed source/tests passed Ruff, Ruff formatting,
strict Mypy and diff whitespace checks. Independent QA/Review
results belong to their respective agents; this document is implementation evidence only.

## Existing data (read-only verification)

- Project: `project_codex_ea3536b4974b`.
- Failed Operation: `operation_3e0a1c1bf6e3d489f3e8baa049d66f9e`.
- Requirement: `delivery_multi_fc67f5be15a3e75d2f99f04c2945044d4351c1f7`.
- Stage/sequence: PREPARING/1; preparations and attempts are empty; base_revision is null.
- Checkpoint digest: `0ea0ba291b36c0de4e87437d8b4d85fe5a05e5cf592a8df322420011f08347dc`.
- Original file SHA-256: `2776c11c6939cad8296d80afec7578cddb26e24b43befbd57aff21b36b4ed6c0`.
- The selected source `/Users/zhangjunshuai/workspace/codex/codex-quota-monitor` now has a clean
  Git checkout at `9eed71416cd55c0712f9b80ee477299adea80c4e` (Initial commit).

Using the patched validation against the integrity-checked historical checkpoint returns
the specific instruction to recreate the Requirement. Read-only rediscovery of the current
source passes the baseline prerequisite. Nothing was changed in production Operations,
requirements, MySQL, or source repositories, and no live Agent was invoked.

No database migration is required. Recreate the original named Requirement against the current
committed source; its new baseline gives it a new identity. Retain the old failure for audit.
The code has not been merged into main or loaded by the running Console. Follow the repository's
human merge/restart process to activate it. Rollback consists only of reverting this code patch.
