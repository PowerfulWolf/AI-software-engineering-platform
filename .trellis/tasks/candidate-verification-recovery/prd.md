# Candidate verification recovery

## Goal

Recover a stopped post-candidate delivery by verifying the original candidate with independent
QA and Reviewer, without rerunning Coder, rewriting source artifacts or resetting terminal Tasks.
User approved implementation on 2026-09-09; real model execution is not authorized by this task.

## Requirements

- Bind exact original Task, candidate, plan, implementation report and native/joint ownership.
- Separate proposal, exact human approval, execution and read-only inspection.
- Preserve terminal history; record recovery facts separately and associate them with the demand.
- Reuse policy-bound context, worktree, artifact and evaluation boundaries.
- QA FAIL, Review REJECT, invalid output and uncertain invocation stop; no implicit Coder run.
- Refuse stale facts, changed candidate/policy, duplicate execution and missing approval.

## Acceptance

- [x] Offline success calls only QA then Reviewer on the original candidate.
- [x] Invalid/missing approval and tampered/stale input cause zero model calls.
- [x] Failure/rejection never invokes Coder or declares the original Task DONE.
- [x] Restart/replay preserves facts and prevents duplicate provider invocation.
- [x] Production CLI binds native/joint ownership and records result association.
- [x] Annotated manual commands documented; lint, types and targeted regression pass.

## Scope and rollback

Allowed: recovery, orchestration/composition, related schemas/tests/docs/specs.
No live data changes, migration, automatic merge/push, target checkout update or new dependency.
Rollback code changes only; never delete sealed recovery facts.

## Research

Existing recovery/entry.py is pre-candidate Coder-only. RetryingOrchestrator refuses terminal Tasks;
ArtifactStore requires same-task parents. Copying original reports to a new Task would fabricate
provenance. A separate verification execution record must preserve original artifact identity and
must not claim a synthetic new four-role delivery. Joint completion requires an explicit validated
association, not merely rewriting the cached child checkpoint.
