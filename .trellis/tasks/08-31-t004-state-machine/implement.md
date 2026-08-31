# T004 Implementation Plan

1. Add contract tests for the full transition graph, terminal/self/skip rejection, event construction, and immutable reduction.
2. Implement the canonical transition map and typed guard errors in `orchestration/state_machine.py`.
3. Export the state-machine API from the orchestration package without adding I/O.
4. Synchronize `docs/state-machine.md` and `.trellis/spec/core/architecture.md` with the exact signatures and error behavior.
5. Run focused tests, then format, lint, strict mypy, full pytest, lock, build, and diff checks.

## Validation Commands

```text
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv build
git diff --check
```

