# Authorized nested file writes for K1

## Goal

Let a Coder or QA create a planned file under a new repository directory through the existing typed `write_file` tool, without widening its path grant. Recover the original K1 Requirement after verifying its current terminal Task and preserved history.

## Scope and acceptance

- A write to an allowed nested file creates only its missing parent directories inside the role worktree and returns the normal typed write receipt.
- A denied path, forbidden role, symlinked parent, or non-directory component cannot create a file outside the worktree or cross a protected path.
- Existing regular-file writes retain their atomic replacement and mode behavior. No new Agent tool, shell permission, verdict, or approval is introduced.
- The failed K1 Run remains failed. A later execution requires an exact same-Requirement recovery decision and a fresh Run, followed by independent QA and Review.

## Allowed paths and validation

Platform change: `src/ai_software_engineer/tools/registry.py`, focused tests in `tests/tools/test_registry.py` and `tests/agents/test_responses_continuation.py`, this task record, `docs/architecture/prompt-protocol.md`, and `.trellis/spec/core/responses-wire.md`. Validate with focused pytest, Ruff, Mypy, and the applicable recovery fixture. Roll back code to platform `90c2aabb` only before any new Task consumes the improved tool behavior; immutable failed Run and recovery facts stay intact.
