# Candidate verification recovery design

## Decision

Keep original terminal Task and original artifacts. A separately authorized verification execution
references the exact candidate, plan and implementation. New verifier runs retain the original
task_id and direct parent lineage; they do not invent a new Coder run or a new successful Task.
Do not reset FAILED, clone implementation under another Task, or run Coder again.

## Internal execution contract

`CandidateVerificationRunner.verify_candidate(inputs)` accepts pinned Task revision/digest,
plan/implementation IDs and digests, and full candidate SHA. It requires a terminal transition
directly from QA following candidate_ready, exact base/criteria/parents and independent historical
Agent identities. It reads original artifacts from the trusted store. Only QA then Reviewer may
execute, with original immutable Task context and fresh run IDs. Before each role and before result
return, recheck original Task/events/artifacts. Return VERIFIED or REJECTED, never Task DONE.
All provider failures propagate without automatic retry or Coder routing.

The production entry validates the exact approved inputs before any model call and durably reserves
each fresh invocation. `verify-run` supplies current native facts, allocation, worktree isolation and
durable admission; the lower runner remains independently testable and has no ambient authority.

## Production integration

- Immutable proposal/approval/invocation/result schema and exclusive store publication are wired.
- Native/joint ownership, approved upstream stages, candidate availability and policy are revalidated.
- MySQL reserves fresh verifier Assignment/Lease identities under the shared capacity fence; QA and
  Reviewer use clean worktrees at the pinned candidate with an execution Task ID distinct from the
  original terminal Task.
- `verify-propose / verify-inspect / verify-approve / verify-run` are top-level CLI commands; only
  `verify-run` invokes models.
- Plan parent identity plus sealed completion associates verification with the original demand while
  preserving the failed checkpoint. Automatic rewrite of that checkpoint is intentionally excluded.

## Test matrix

Good: QA PASS + Review APPROVE, two calls, original SHA, original Task/events unchanged.
Base: QA FAIL or Review REJECT stops; invalid output propagates; no implicit Coder/retry.
Bad: missing approval, stale Task/artifact/event, no candidate checkpoint, wrong candidate/parents,
wrong criteria, reused run or self-review must reject. Replaying consumed admission must not call.
Rollback only platform changes; never delete old artifacts, records, branches or candidate commits.
