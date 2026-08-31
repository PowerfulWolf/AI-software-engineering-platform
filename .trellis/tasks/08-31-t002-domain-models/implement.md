# T002 Implementation Plan

1. Add Pydantic and JSON Schema dependencies and refresh the uv lock.
2. Write contract tests against only the public domain model surface and canonical schemas.
3. Confirm the tests fail because T002 models do not exist.
4. Implement canonical enums, the strict model base, Task, Agent Definition, and typed Artifacts.
5. Add only documented same-object validators; leave cross-aggregate policy for later tasks.
6. Run focused tests, then format, lint, strict mypy, the full test suite, and lock validation.
7. Sync executable domain invariants into `.trellis/spec/core/` and record verification evidence.

## Validation Commands

```text
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

## Rollback Point

Before merging the T002 branch. Revert the single T002 implementation commit if a contract or compatibility issue is found.
