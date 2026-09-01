# T006 Implementation Plan

1. Add one real-repository public-seam test for an isolated Coder worktree, then implement the minimal typed Git port and local adapter.
2. Add QA/Reviewer detached-candidate behavior, inspection, collision/error mapping, and safe dirty/clean removal in vertical TDD slices.
3. Add worktree-root-bound `WorkspacePolicy` slices for normalized path allow/deny behavior, symlink containment, and tokenized command-prefix authorization.
4. Export the public Git package without changing Task, Agent, or JSON Schema wire contracts.
5. Synchronize `docs/git-worktree.md`, `docs/contracts.md`, README, and `.trellis/spec/core/` with exact interfaces, errors, cases, and validation points.
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
