# Verification

## Root cause and independent review
The documented sequence invariant was absent from dynamically generated provider
schemas and output bindings. A model could use queue checkpoint+1 rather than the
run attempt. SUCCEEDED invocation and ArtifactStore publication preceded the later
orchestrator check. This fix adds request-bound generation and explicit live validation,
without strengthening historical Pydantic decoding or rewriting any result.

Root reviewed the shared fresh-schema helper, Codex/Responses actual request call
sites, chat/shared prompt bindings, typed INVALID_OUTPUT projection, invocation
publication/replay and runner order. Current progress4 at attempt4 is valid despite
queuecheckpoint8; progress8/9 cannot be published or used. Existing orchestrator gate
remains. Existing invocation/preflight adapters have no replay completion side effect;
a replay does not need to write its immutable outcome again.

## Incremental checks
Worker ran 147 focused tests from the fake/Codex/Responses/chat adapters, invocation
journal, progress output contract and runner; then 64 retry/native/Responses continuation
and JSON Schema cases. One added positive journal regression also passed (journal
file 11 passed). The worker reports 212 different focused cases passed; no full suite.
Ruff check/format and strict mypy on the 7 source + 6 test files passed.

Root independently ran:

```sh
uv run pytest -q tests/orchestration/test_progress_output_contract.py \
 tests/work_queue/test_invocation_journal.py tests/agents/test_fake.py \
 -k 'progress or historical or replay' --tb=short
```

**19 passed, 28 deselected**, 0.92 seconds. This includes real immutable-store
roundtrips, live fake adapter publication, old result replay without adapter/completion,
valid exact-attempt output and nontransient wrong-sequence rejection.

## Existing data / rollback
No SQL or static wire migration, no original bytes/digest changed. The historical
attempt4 wrong-sequence outcome remains readable and is rejected at live replay.
It is deliberately not auto-corrected. The original K1's complete stopped workspace,
precise rejected artifact and same-Task continuation are handled by the separate
`10-11-rejected-coder-output` task; public recovery adoption is covered by
`10-11-recovery-pending-outcome`. These sibling tasks must complete before deploying
and continuing the actual requirement. Rolling back this forward admission change
cannot make the old result valid or authorize its replay.
