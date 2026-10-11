# Incremental verification

## Red signal

Before bridge wiring, ran:

```sh
.venv/bin/python -m pytest tests/agents/test_structured_observation.py -q
```

Three real native subprocess cases (success / timeout / nonzero) failed in 1.25s:
the structured bridge returned/raised while both admission and stop observation
lists stayed empty. This exercised the actual lost-stop bridge.

## Green checks

```sh
.venv/bin/python -m pytest tests/agents/test_structured_execution.py tests/agents/test_structured_observation.py tests/agents/test_structured_models.py tests/agents/test_model_diagnostics.py -q
.venv/bin/ruff check src/ai_software_engineer/agents/structured_observation.py src/ai_software_engineer/agents/structured_execution.py src/ai_software_engineer/agents/structured.py tests/agents/test_structured_observation.py
MYPYPATH=src .venv/bin/mypy src/ai_software_engineer/agents/structured_observation.py src/ai_software_engineer/agents/structured_execution.py src/ai_software_engineer/agents/structured.py tests/agents/test_structured_observation.py
git diff --check
```

73 tests pass. Ruff and strict mypy pass for all four scoped files; formatting and
diff whitespace checks pass. No full test suite or production model call was run.
Tests cover real bridge/client success, native timeout, nonzero exit, invalid JSON,
unknown or missing stop callback, publication failures before native spawn/HTTP
post and after actual stop/roundtrip, fallback identity and no fallback on observer
failure, nested/thread context isolation, exact request digest, full Schema equality
and admission/native/HTTP fixtures, and receipt tampering.

## Existing data / limits / rollback

No production service action, SQL/store mutation, knowledge retry or recovery
execution occurred in this subtask. Existing unknown historical executions remain
unknown; no observations are backfilled. This is an optional trusted observation
foundation. Knowledge composition must still bind a real authorization/claim and
persist these exact typed facts; its recovery behavior is a separate work item.
Remove optional observer wiring at an idle boundary to roll back, while retaining
any future sealed records. HTTP roundtrip receipts never prove remote execution
stopped and cannot authorize a native-process recovery.

## Independent-review startup closure

Review found that an admission followed by a missing executable had no trustworthy
closure. A fenced observer rejected the backup route forever. Behavior-first
regressions produced 4 failures / 1 pass: missing executable, input preparation,
post-Popen ownership cleanup, and failed NOT_STARTED persistence. The generic
unclassified runner failure already correctly produced no invented NOT_STARTED.

Added a separate exact-admission NOT_STARTED receipt and a runner-only typed
startup failure. Post-Popen registration failures now enter owned cleanup, publish
the real stop if proven, reap the child and fail as execution uncertainty; they do
not become provider fallback. The fixture verifies no child remains running.

```sh
.venv/bin/python -m pytest tests/agents/test_structured_execution.py tests/agents/test_structured_observation.py tests/agents/test_structured_models.py tests/agents/test_model_diagnostics.py -q
.venv/bin/python -m pytest tests/agents/test_codex_cli.py -q -k runner
.venv/bin/ruff check src/ai_software_engineer/agents/codex_cli.py src/ai_software_engineer/agents/structured_execution.py src/ai_software_engineer/agents/structured_observation.py tests/agents/test_structured_observation.py
MYPYPATH=src .venv/bin/mypy src/ai_software_engineer/agents/codex_cli.py src/ai_software_engineer/agents/structured_execution.py src/ai_software_engineer/agents/structured_observation.py tests/agents/test_structured_observation.py
git diff --check
```

78 structured tests pass in 6.04s; 2 runner regressions pass in 1.08s (42 unrelated
tests deselected). Scoped Ruff, strict mypy and whitespace checks pass. Updated
standalone Schema equality, positive NOT_STARTED wire validation, digest tampering,
forbidden PID and transport-kind mismatch checks all pass in that incremental run.
No full suite, production model call or durable production mutation was performed.
No backfill: historical unknown admissions remain unknown.
