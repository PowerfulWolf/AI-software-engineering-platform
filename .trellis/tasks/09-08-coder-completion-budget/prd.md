# Deadline-aware Coder finalization

## Evidence

Real run `run_9554f0ce2c224ca3997818c2497db0d8` used the repaired 1,800-second Coder
limit, modified every authorized implementation/test/spec area, ran a broad offline pytest command,
and still reached the hard timeout before commit or Artifact output. The compiled role prompt says
what must eventually happen but does not expose the external deadline or reserve finalization time.

## Acceptance

- Compile the exact `AgentRequest.timeout_seconds` into every Codex role prompt.
- Allocate a deterministic bounded completion reserve; for a 1,800-second Coder request it is 300
  seconds.
- Tell Coder to prioritize focused required tests, stop scope expansion before the reserve, and make
  the clean candidate commit plus JSON Artifact higher priority than broader optional validation.
- Keep the existing hard timeout, sandbox, permissions, Git guard, retry policy, schemas, and
  independent QA/Reviewer gates unchanged.
- Add a fast prompt-boundary regression test; use a subsequent real recovery run as the only proof
  of remote-model compliance.

## Non-goals

Do not adopt the dirty timeout worktree, auto-commit model edits, stream hidden reasoning, remove the
hard limit, weaken tests, merge/push/deploy, or claim a deterministic unit test proves model timing.
