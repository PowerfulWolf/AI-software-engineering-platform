# Verification

- Exact source recovery parent scope helper: 18 targeted tests PASS / 1.91 s:
  `uv run pytest tests/manager/test_baseline_recovery_knowledge_scope.py -q --tb=short`.
- Ruff/format and strict mypy over the four production modules plus the two tests PASS.
- Public joint native delivery regression: 1 PASS / 54.40 s:
  `uv run pytest tests/manager/test_baseline_knowledge_parent_scope.py -q --tb=short`.
- Independent production typed read of exact frozen parent ancestor and actual native chain PASS:
  parent journal 74, native journal 22; interrupted/old child sequence 20, current child/native 22.
  No Host/provider/store write or SQL initialization.
- Independent complete knowledge reader replay of production original attempt 1 PASS:
  1/1 original claims covered, 2 intents, 2 outcomes, 8 structured observations; proof digest
  `4ba569231a9ec3a5d42464ecbf4466ac2087c3e0bf788cdce2788160b941c92e`.
  Exact original READY request preparation and successor target preparation are associated
  through the real immutable source dispatch and existing allocation conversion.
  SQL reads use a consistent READ ONLY transaction and typed decode; no SQL schema initialization,
  Host construction, provider calls or store writes. Latest trusted wrapper and reader checked together.

Existing data: no changes to Task/events/queue/knowledge/approval/Operation or preserved Git state.
This fix locates the actual approved parent knowledge lane while the proposal/continuation keep
the native child scope. Independent final reviewer release PASS: final production wrapper including
workspace/team-root guards, sealed original allocation, 18 unit tests / 2.24 s, six-file Ruff/format/
strict mypy and diff checks. No full suite was run.
