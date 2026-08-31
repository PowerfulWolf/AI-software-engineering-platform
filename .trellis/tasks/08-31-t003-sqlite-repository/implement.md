# T003 Implementation Plan

1. Add the StateEvent schema and typed model contract tests.
2. Confirm the new repository tests fail before any SQLite implementation exists.
3. Add the `TaskRepository` Protocol, typed repository errors, and idempotent SQLite implementation.
4. Use JSON snapshots plus explicit `BEGIN IMMEDIATE` transactions; never mutate a Task without an event.
5. Run focused repository/schema tests, then formatting, lint, strict mypy, full pytest, lock, and build checks.
6. Update core specs and task verification with the exact persistence contract and failure matrix.

## Validation Commands

```text
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv build
```

## Rollback Point

Before merging the T003 branch. Revert the single implementation commit; any local SQLite fixture files are created under pytest temporary directories.
