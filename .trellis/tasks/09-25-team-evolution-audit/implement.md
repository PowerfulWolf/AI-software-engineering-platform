# Execution and verification

1. Preserve pre-existing dirty fixes; record lifecycle facts and unresolved seams in audit.md.
2. Add red regression coverage for learning Schema/UI drift and evidenced project observations.
3. Extend report/schema contracts with hash-compatible absent defaults, role prompt guidance, and
   deterministic learning collection. No generic model-generated rule extraction.
4. Repair provenance rendering and knowledge-selection publication locking; verify future-context
   reuse and frozen-context isolation, including human approval and all delivery roles.
5. Run affected Python tests, frontend tests, Ruff, strict mypy and diff checks. Record actual results.
6. Continue Manager prerequisite incident integration and automatic/upstream capture in separately
   verified milestones. Keep overall task in_progress while these acceptance criteria remain open.

Allowed paths: domain/artifact.py; agents/openai_compatible.py; learning.py; schemas/*report*.json;
schemas/learning-proposal.schema.json; team_view/app.js; focused tests; CONTEXT.md; docs/contracts.md;
.trellis/spec/core and this task. Public HTTP round-trip regression lives in
tests/web_console/test_learning_observations.py. Manager integration requires its corresponding spec/tests first.

Validation: `.venv/bin/pytest tests/specs/test_learning.py tests/domain tests/artifacts tests/knowledge
tests/agents/test_openai_compatible.py`; `node --test tests/team_view/*.test.cjs`;
`.venv/bin/ruff check/format --check <changed paths>`; `.venv/bin/mypy <changed Python paths>`.
MySQL tests require only isolated ASE_TEST_MYSQL_DSN and run one process at a time.

Rollback: restore only this task's patch relative to 892f87e, preserving prior dirty work and all
external immutable records. No commit/merge, direct DB repair or service restart without review.
