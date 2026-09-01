# T008 Implementation Plan

1. Add typed agent execution models and protocol without changing existing domain wire schemas.
2. Add FakeAgentAdapter scenario scripting, artifact alignment checks, typed failures, and run idempotency.
3. Add public-seam tests for success, QA FAIL, Review REJECT, timeout, invalid/provider failures, mismatch and replay.
4. Synchronize docs, README, and `.trellis/spec/core/` with exact signatures, errors, and test points.
5. Run focused tests, then format, lint, strict mypy, full pytest, lock, build, and diff checks.

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
