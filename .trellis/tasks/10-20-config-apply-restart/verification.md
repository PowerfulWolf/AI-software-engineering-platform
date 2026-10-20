# Configuration apply restart verification (2026-10-20)

## Reproduction and root cause

The real Console writer saves fixed Chinese PENDING summaries with JSON Unicode escapes.
The shell supervisor compared serialized JSON against literal Chinese/English strings, leaving
an accepted request PENDING indefinitely. The browser's existing 30-second timeout then showed
the reported failure. The startup orphan reconciliation had the same parsing defect.

Before this fix, the actual writer/supervisor and duplicate-key regression command returned
5 failed / 1 passed in 43.95 seconds. The only passing case was the legacy English orphan.

## Fix and checks

Both shell read sites now call the fixed typed `apply-state [expected_request_id]` helper.
It validates the complete lifecycle state, exact request identity and fixed status/summary.
Escaped Chinese, literal UTF-8, legacy English and valid JSON formatting are supported.
Duplicate keys, extra fields, unknown summary, trailing garbage, wrong ID and symlinks fail closed.
Replacement lock, controlled READY handshake, actual predecessor exit and fresh instance checks remain.

Commands run from the isolated maintenance checkout using the repository Python 3.12 venv:

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q tests/test_console_service_script.py tests/web_console/test_lifecycle.py
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m mypy --cache-dir /tmp/ase-config-apply-mypy-20261020 --follow-imports=silent scripts/ase-console-lifecycle.py src/ai_software_engineer/web_console/lifecycle.py tests/test_console_service_script.py tests/web_console/test_lifecycle.py
```

Full focused regression: **55 passed in 417.09s**, before the final defensive nested-JSON increment.
Changed-file Ruff check/format, strict Mypy (4 files), `/bin/sh -n` and diff whitespace checks passed.
Independent read-only review of the five files found **0 findings**. The root reviewer then requested
an additional deeply nested JSON rejection check for the new stdlib decoder. Its two cases first
failed in 1.33s, exposing `RecursionError` and helper traceback. The decoder now maps that exception
to the same fixed safe error; both cases plus the real writer/supervisor happy path passed
(**3 passed in 18.78s**). Final Ruff/format, Mypy, shell syntax and diff checks passed again.
Tests use isolated service directories and fake service instances, without production SQL or K1 writes.

## Existing-data treatment

Before deployment, the public API still reports:

- request `configuration_apply_e16ed760d58d42fcf035db5a1e687385`, PENDING, target port 8765;
- saved settings `restart_required=true`;
- service PID18502, instance `console_instance_4707506cbe26f16151d828e840e7a16c`, RUNNING.

Original state-file SHA-256:
`be83a5b88bd162ee4ce72043c7bab4b5b6f2e1156ae4eb48806b825aff972ae7`.
Original marker SHA-256:
`3c20416f438befd703aac4bda8c829e2dc11d5116269fd7bc620851677e5d082`.

Keep these files and the request ID intact until the fixed official supervisor consumes them.
Deploy only through the official controlled stop/verified exit/start path. Do not fabricate success,
edit SQL, reset Task attempts or rewrite any old approval, execution outcome or K1 dirty draft.
Real deployment and public verification results will be appended after completion.

## Risks and rollback

A running old supervisor retains the faulty shell function and requires a controlled reload.
Malformed lifecycle records still refuse replacement. Service-start acknowledgement requires a fresh
instance; script success alone is not an independent QA verdict or proof of K1 completion.
Rollback requires a controlled idle stop first, then reverting this maintenance commit and restarting.
Preserve lifecycle and requirement history; do not erase an unproven stop to allow replacement.
