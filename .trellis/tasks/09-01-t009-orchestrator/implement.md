# T009 Implementation Plan

1. Add a red Agent contract test proving Coder input base revision may produce a new candidate while
   `commit_sha == Artifact.source_revision` remains mandatory.
2. Add one public-seam fixture e2e test for `SerialOrchestrator.run_task` using real SQLite and
   filesystem stores, deterministic identities/time, Context Builder and FakeAgentAdapter.
3. Implement the smallest typed Context composition and serial runner needed to pass the happy path.
4. Add vertical negative slices for non-NEW Tasks, Agent failure, verdict/revision/criteria/lineage and
   duplicate run identity guards without implementing retries.
5. Synchronize docs, milestone paths and `.trellis/spec/core/` with exact signatures and validation.
6. Run focused tests, then format, lint, strict mypy, full pytest, lock, build and diff checks.

## Validation commands

```text
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv build
git diff --check
```
