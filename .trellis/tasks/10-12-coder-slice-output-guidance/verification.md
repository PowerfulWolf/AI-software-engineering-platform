# Verification

Isolation: task/coder-slice-output-guidance based on 770c02e in
/Users/zhangjunshuai/workspace/code/ase-coder-slice-output-guidance. No production API,
MySQL, models, service restart, registered source checkout or original Coder worktree
was touched. Tests use only fake process ports and temporary real Git repositories.

## Red signals

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest tests/agents/test_coder_slice_output_guidance.py -q -m 'not mysql'
```

Before implementation: **10 failed, 9 passed in 2.62s**. Six Request/Context/native
partial/final cases lacked the machine guidance. Four actual native/Git slice failures
were labeled GIT_CONTRACT. Legacy/no-slice and real final candidate controls passed.

Follow-up Chinese diagnostic requirement, before its implementation:
`-k actual_native_slice_rejection --tb=short`: **4 failed, 16 deselected in 1.99s**.
Each fixed WORK_SLICE code was present but its safe Chinese explanation was missing.

## Green incremental verification

- New agent guidance/gate tests + planning work-slice tests + negative-credential guidance:
  **49 passed in 2.77s**.
- Existing native/OpenAI adapter files: **77 passed in 13.27s**.
- After native Chinese diagnostic change: new agent tests + existing Codex adapter:
  **72 passed in 17.17s**. This reruns 20 new + 52 existing cases and is not added to the
  first two batches. The union is **126 relevant passing cases**, not a full suite.
- After final punctuation-only normalization, focused new-file rerun:
  **20 passed in 3.46s**; these 20 are already counted in the union above.
- Scoped Ruff check and format check: clean for five touched Python files.
- Scoped strict Mypy: **Success: no issues found in 5 source files**.
- git diff --check: clean.

The relevant commands use the explicit test files:

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest tests/agents/test_coder_slice_output_guidance.py tests/planning/test_execution_window.py tests/agents/test_negative_credential_prompt_guidance.py -q -m 'not mysql'
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest tests/agents/test_codex_cli.py tests/agents/test_openai_compatible.py -q -m 'not mysql'
```

## Limits and review

This verifies the real adapter boundaries and deterministic gate, not actual model
compliance or delivery completion. Existing production K1 GIT_CONTRACT subcause remains
unknown. DEFERRED_STEPS is retained at the original final gate position; earlier exact
partition/unselected-completion checks normally reject that shape first. No acceptance
gate was relaxed or reordered. Independent review is delegated by root after implementation.

## 存量数据处置

No migration or historical update is required. New future invocations receive the new
guidance and fixed diagnostic. Existing Task/Operation/outcome/failure/approval/source/
attempt/lease and all drafts remain unchanged. The original Requirement must continue
through the existing exact public engineering investigation/approved recovery path;
this isolated task neither resolves nor guesses that old failure and grants no retry.

## Rollback

Revert this dedicated commit and reconstruct the Host only after real role execution
is idle. Retain all immutable historical records and worktrees. Root separately owns
read-side translation and integration/deployment; this branch does not push main.
