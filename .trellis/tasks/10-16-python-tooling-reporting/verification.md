# Verification

Run in `/tmp/ase-fix-legacy-ignored` with the registered maintenance interpreter:

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q tests/agents/test_native_python_tooling.py::test_coder_receives_registered_tools_and_current_source_only tests/agents/test_native_python_tooling.py::test_unsafe_registered_pytest_is_not_bound_or_installed
```

Result: **5 passed in 2.84s**. These existing tests exercise the safe registered tooling and current
worktree binding supplied to the runner, plus all four unsafe registered pytest cases. They check
that missing-tool guidance still includes `NOT_RUN`, preserves a legal progress path and does not
install a worktree environment. No model is called and no production state is accessed.

Static checks:

```sh
/Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m ruff check src/ai_software_engineer/agents/codex_cli.py
/Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m ruff format --check src/ai_software_engineer/agents/codex_cli.py
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m mypy src/ai_software_engineer/agents/codex_cli.py
git diff --check
```

Results: Ruff passed; one file already formatted; mypy found no issues in one source file; diff
check passed. The production code diff is restricted to `_coder_python_tooling_instruction()`.

These checks establish no tooling regression in the selected existing cases and consistent
wording. They do not prove deterministic model interpretation, resolve historical K1 failures,
or establish a candidate verdict. No launcher, bootstrap, permission, environment, schema or
recovery logic changed. Independent read-only review and a safe idle deployment boundary remain
required before release. No production API/SQL, Coder worktree, service restart or Git commit was
used during this implementation subtask.

Independent read-only review of the final narrow change found no blocking issue. The reviewer
confirmed that reporting conditions are explicit while tooling isolation, no dependency repair,
candidate acceptance and independent QA/Review boundaries remain unchanged. No tests were repeated
for that static review. The previous NOT_RUN/FAIL records are not rewritten or claimed resolved.
