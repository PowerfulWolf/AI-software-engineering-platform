# T007 Implementation Plan

1. Add a context wire schema and the first deterministic router/builder contract test through the public seam.
2. Implement typed context values, role routing, root-bound file loading, canonical hashing, and stable token estimation in vertical slices.
3. Add secret redaction and policy/injection boundary tests, then deterministic optional truncation and required overflow errors.
4. Export the context package without changing Task, Agent, Artifact, StateEvent, or Git wire contracts.
5. Synchronize `docs/context-routing.md`, `docs/contracts.md`, `docs/architecture.md`, README, and `.trellis/spec/core/` with exact signatures, fields, errors, cases, and test points.
6. Run focused tests, then format, lint, strict mypy, full pytest, lock, build, and diff checks.

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
