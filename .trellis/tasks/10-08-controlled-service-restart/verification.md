# Verification

Only incremental tests were run. No production service restart, model invocation, K1 operation,
database mutation or credential inspection was performed.

## Final touched Console / lifecycle regression

```bash
.venv/bin/python -m pytest \
  tests/web_console/test_core.py tests/web_console/test_shutdown.py \
  tests/web_console/test_service_lifecycle.py tests/web_console/test_controlled_host.py \
  tests/web_console/test_controlled_restart_schema.py \
  tests/knowledge/test_index_worker_shutdown.py tests/web_console/test_transport.py \
  tests/web_console/test_lifecycle.py tests/web_console/test_directories.py -q
```

**107 passed in 6.60s.** Two upstream Starlette/httpx deprecation warnings; no failures.

## Owned runner / integration regression

The combined changed-area command below completed **228 passed / 3 skipped in 23.93s** before the final
startup/state-only fixes, which were subsequently covered by the 107-test Console regression above:

```bash
.venv/bin/python -m pytest \
  tests/web_console/test_core.py tests/web_console/test_shutdown.py \
  tests/web_console/test_service_lifecycle.py tests/web_console/test_controlled_host.py \
  tests/web_console/test_controlled_restart_schema.py \
  tests/knowledge/test_index_worker_shutdown.py tests/web_console/test_transport.py \
  tests/web_console/test_lifecycle.py tests/web_console/test_directories.py \
  tests/execution/test_owned_processes.py tests/execution/test_executor.py \
  tests/agents/test_codex_cli.py tests/agents/test_structured_models.py \
  tests/agents/test_candidate_source_binding.py tests/recovery/test_native_ui.py -q
```

The three skips require explicit real macOS GUI enablement. Native/structured/tools/proxy/chooser real
owned-process fixtures and policy regressions ran; no real provider calls were made.

## Service-script regression

```bash
.venv/bin/python -m pytest tests/test_console_service_script.py -q
```

30 script cases were covered. Final full-file run passed 28; 2 asynchronous apply assertions exceeded
old 4/6-second test polling windows after adding the typed handshake and fresh startup proof.
The test deadline was changed to 15 seconds without changing production shutdown policy. The affected
removed-runtime-value and malformed/symlink-runtime cases were rerun together: **3 passed in 27.58s**.
All 30 cases therefore have passing verification on the final script. Earlier focused rerun also
passed 7 cases for startup, invalid apply and checkout handoff in 58.89s.

Assertions cover exact nonce/state/timestamps, real exit, timeout/refusal/resume, preserved supervisor,
missing/dead/foreign PID, no old handshake, actual replacement lock ownership, configuration apply
idempotence and no retained removed secret. Fixture environment explicitly excludes host secrets.

## Quality / build

- Changed Python files: Ruff check and format check **35 passed**, strict mypy **35 passed**.
- `sh -n scripts/ase-console-service.sh`: passed.
- `git diff --check`: passed.
- `uv build --offline`: source distribution and wheel built successfully.
- Three static service lifecycle schemas regenerated; parity tests passed, including STARTING.
- A shared verification test fixture received its missing capability annotation so changed-file strict
  type checking includes its actual imported dependency without suppressing a type error.

## Independent review and production boundary

Core/Host/owned runner workers reviewed files they did not implement; root reviewed core and integration.
Concrete findings and completed repairs are in `implement.md` and `analysis.md`. No remaining mandatory
finding was reported after the final targeted regression. This is proof of the changed restart path,
not a claim that the entire ASE platform has no defects.

Original K1 Task `task_dc5cf0aee44e5ffe0cb600557204e0d0` and unknown Run
`run_9b76fb2865144f2abb6407923320ec4e` remain untouched and paused. Old in-memory services cannot load this
protocol via disk changes alone; one-time verified maintenance rollout is documented separately.
