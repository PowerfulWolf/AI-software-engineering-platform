# 2026-09-08 — Deadline-aware Coder finalization

## Trigger

Real recovery run `run_9554f0ce2c224ca3997818c2497db0d8` used the repaired 1,800-second
Coder limit and progressed through all authorized implementation, test, documentation, and spec
areas. It ran a broad offline pytest command but reached the hard deadline dirty, before candidate
commit or implementation-report. The Task correctly became BLOCKED; QA and Reviewer did not start.

## Root cause

Categories B/D/E: the subprocess knew the hard deadline but the Agent-visible prompt did not. Fake
runners committed immediately, so existing tests proved Git/Artifact postconditions without proving
the real Agent was told how to budget finalization. Raising 600 to 1,800 seconds removed the first
surface constraint but left this cross-layer contract gap.

## Platform repair

- `_compile_prompt` now exposes the exact `AgentRequest.timeout_seconds` to every Codex role.
- `_completion_reserve_seconds` deterministically reserves 20%, capped at 300 seconds and always
  below the total timeout.
- Coder is instructed to prioritize focused required tests, stop scope expansion before the reserve,
  and prioritize a clean candidate commit plus JSON Artifact over broader optional validation.
- Existing hard timeout, sandbox, permissions, Git policy, retries, schemas, and independent
  QA/Reviewer gates are unchanged.
- The two failed Tasks and dirty worktrees remain preserved and are not adopted as candidates.

## Verification

- Codex CLI unit tests: 17 passed.
- Codex CLI plus real Git/MySQL recovery: 20 passed in 213.56 seconds.
- Full suite with dedicated MySQL test database: 902 passed in 373.68 seconds.
- Ruff check/format over 519 files, strict mypy over 286 source files, `uv lock --check`, offline
  sdist/wheel build, and `git diff --check`: passed.
- No live model was used for repair verification. Remote-model compliance requires a fresh explicitly
  approved recovery run.

## Next boundary

If a fresh live run still cannot finalize, do not make the timeout unbounded and do not auto-commit
dirty work. The next architectural increment should introduce staged/checkpointed Coder execution or
a separately authorized finalization phase with durable intermediate evidence.
