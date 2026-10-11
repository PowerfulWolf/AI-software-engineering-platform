# Incremental verification

All commands below ran only in the isolated maintenance worktree. No full suite,
MySQL test (including fake MySQL-specific fixtures), model call, ASE operation,
production database/sidecar or production role workspace was used.

## Red-to-green evidence

Before implementation, the real native silent separate-PGID test failed because the
child remained alive after the runner reported a successful stop: **1 failed in
1.25 seconds**. The final dedicated group covers this case, TERM-resistant peers,
all current registered consumer categories, true known-birth setsid escape, stop-save
failure and before-capture leader reap.

Final protocol review also exposed repeated save confirmation and post-confirmation
execution: both real-command cases first failed because earlier observations were
removed. The invalid latch fixes both; the final 11 finalization cases all pass.

## Final dedicated group

```sh
uv run pytest -q \
  tests/execution/test_owned_session_stop.py \
  tests/execution/test_owned_session_inspection.py \
  tests/execution/test_owned_record_finalization.py \
  tests/contracts/test_owned_session_stop_schema.py
```

**46 passed in 11.49 seconds**: 22 stop/consumer regressions, 6 inspection cases,
11 actual durable finalization cases and 7 compatibility/schema cases. The schema
cases cover exact ten embeddings, repeated fresh repair generation, original absent/
null ordinary and wire dumps, nested digests and invalid proof fields.

The controlled-verification storage barrier uses a real fixture executor binary,
exact approved fixture capability/argv and actual FileRecoveryStore receipt put.
It does not execute Swift or MySQL. A real Darwin libproc saturated-buffer test
rejects enumeration; Linux parser/identity tests are unit-level, not real Linux runtime.

## Existing regressions

```sh
uv run pytest -q \
  tests/agents/test_codex_cli.py \
  tests/agents/test_native_output_bounds.py \
  tests/agents/test_structured_observation.py \
  tests/execution/test_executor.py \
  tests/execution/test_owned_processes.py \
  -k 'not mysql_proxy'
```

**120 passed, 1 deselected in 37.98 seconds**.

```sh
uv run pytest -q \
  tests/evidence/test_capture.py \
  tests/contracts/test_continuation_schema.py \
  tests/orchestration/test_native_continuation.py \
  tests/orchestration/test_native_continuation_v2.py
```

**81 passed in 210.73 seconds**. Real Git fixtures account for much of this scoped
regression time; no database or model was used.

```sh
uv run pytest -q \
  tests/recovery/test_native_ui.py \
  tests/recovery/test_verification_environment.py \
  -k 'not real_'
```

**38 passed, 6 deselected in 5.34 seconds**. An earlier run had 2 mock fixture failures:
the tests passed a Mock instead of a real Popen. Only those fixtures' ownership seam
was mocked; actual runtime Popen identity validation remains strict.

The prior schema compatibility/repair-generation focused group was **19 passed**;
the final dedicated group independently verifies the changed schema contract again.

## Static gates

Ruff formatting/check and strict mypy passed on all **17 changed/new Python files**:
10 production modules, the schema sync script, four new tests and two existing test
fixture modules. `git diff --check` passed. The exact reproducible changed-Python gate:

```sh
uv run python - <<'PY'
import subprocess

tracked = subprocess.check_output(["git", "diff", "--name-only"], text=True).splitlines()
new = subprocess.check_output(
    ["git", "ls-files", "--others", "--exclude-standard"], text=True
).splitlines()
paths = sorted({p for p in tracked + new if p.endswith(".py")})
assert len(paths) == 17
for argv in (
    ["uv", "run", "ruff", "format", "--check", *paths],
    ["uv", "run", "ruff", "check", *paths],
    ["uv", "run", "mypy", "--strict", *paths],
    ["git", "diff", "--check"],
):
    subprocess.run(argv, check=True)
PY
```

No new dependency or schema permission is introduced. No template tree exists at
`src/templates/markdown/spec`; the executable spec is canonical in `.trellis/spec`.

## Remaining independent checks

Root must review the complete tracked and **untracked** file inventory before
commit/integration. Real Linux runtime and MySQL verification remain outside the
executed validation. Current production run/service readiness is not inferred from
this worktree's tests; deployment requires its separate idle controlled boundary.
