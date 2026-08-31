# T005 Implementation Plan

1. Add public-seam tests for digest sealing, round-trip, duplicate immutability, lineage, corruption, and atomic temp-file cleanup.
2. Implement `ArtifactRef`, `ArtifactStore`, typed errors, canonical digesting, and atomic JSON storage under `src/ai_software_engineer/artifacts/`.
3. Export the artifact store API without changing the existing domain schemas.
4. Synchronize `docs/contracts.md`, `docs/architecture.md`, and `.trellis/spec/core/` with exact signatures, digest rules, and error matrix.
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

