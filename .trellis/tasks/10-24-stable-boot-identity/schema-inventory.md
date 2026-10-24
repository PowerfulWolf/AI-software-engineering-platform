# Exact owned-session Schema embedding inventory maintenance — 2026-10-24

This is a pre-existing generator inventory omission at main
`1ec4edd6f08bb09e8709f2c3e7519d734ee98f46`, separate from the stable boot identity fix.
The new `rejected-knowledge-current-draft.schema.json` already embeds the canonical
NativeProcessStop graph, but both the synchronizer's explicit inventory and its independent
golden test omitted its filename. No domain, wire model or published Schema change is needed.

Only the synchronizer exact set and independent golden exact set gain that one filename.
All existing equality, missing, extra and same-count replacement guards remain unchanged.
The complete scan found177 Schema files and exactly19 stop embeddings:

- `schemas/completed-coder-output-unavailable.schema.json`
- `schemas/console-deletion-cleanup.schema.json`
- `schemas/console-operation.schema.json`
- `schemas/engineering-wait-resolution.schema.json`
- `schemas/execution-baseline-plan.schema.json`
- `schemas/execution-baseline-queue-consumption.schema.json`
- `schemas/execution-capture.schema.json`
- `schemas/execution-continuation.schema.json`
- `schemas/knowledge-execution-record.schema.json`
- `schemas/knowledge-invocation-outcome.schema.json`
- `schemas/knowledge-preparation-isolation.schema.json`
- `schemas/rejected-coder-output-checkpoint.schema.json`
- `schemas/rejected-knowledge-current-draft.schema.json`
- `schemas/service-pause-stop.schema.json`
- `schemas/stopped-coder-execution.schema.json`
- `schemas/stopped-failure-budget-settlement.schema.json`
- `schemas/stopped-failure.schema.json`
- `schemas/stopped-provider-failure.schema.json`
- `schemas/structured-execution-observation.schema.json`

Before changes, the complete contract file actually returned **2 failed,9 passed in1.35s**:
`test_all_known_embeddings_and_fresh_repair_regeneration_keep_exact_stop_graph` rejected
that extra embedding, and the known-inventory synchronizer fixture refused it. This is
an exact reproducible inventory defect, not a boot identity or schema payload mismatch.

After adding the filename to both independently explicit sets, the full contract file
actually passed **11 tests in3.60s**. The missing/additional/replacement negative cases
still reject before writing any fixture bytes. Fresh repair generation still executes twice.

```text
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python \
  -m pytest -q tests/contracts/test_owned_session_stop_schema.py --tb=short
```

A dry-run compared exact proposed JSON bytes before running the synchronizer: zero changes.
Then the real synchronization script executed twice in this isolated owned /tmp mirror.
All177 Schema file SHA values matched before/after each run, including the previously omitted
embedding. The complete filename→SHA map has canonical digest
`5dcaeeda50d181c52cb7a5cdf18b4bb648b12412436ca9cbd34915b7571c506b`.

Evidence files:
- `/tmp/ase-owned-session-schema-inventory-before-20261024.json`
- `/tmp/ase-owned-session-schema-sync-idempotence-20261024.json`

Ruff check and format check passed on the exact two Python paths. Strict Mypy must use
`MYPYPATH=src` in an extracted mirror; without it, its first attempt resolved the installed
untyped package and reported5 import/subclass errors. No type-ignore or assertion was added.
Final source-resolved strict Mypy: **Success, no issues in2 source files**.

## 存量数据处置 and rollback

No Schema bytes, database, historical receipt/proof, Task, approval, budget or K1 source was
changed. No production recovery or model invocation is part of this repair. No migration or
backfill is needed. Rollback of these two inventory additions restores the reproduced generator
failure; retain the canonical published Schema graph. Parent owns independent review/integration.
The core owned-session-stop spec's older eleven-file count is stale; parent owns that document
alongside its boot/bridge changes, so this worker did not overwrite it.
