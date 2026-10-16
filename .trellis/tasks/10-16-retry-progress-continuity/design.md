# Design and executable contract

## Exact seam and ownership

`src/ai_software_engineer/manager/execution_baseline.py`:
`ExecutionBaselineService.execute()` constructs `ExecutionBaselineBinding` after the
existing fresh authorization, exact source/workspace/proof and queue checks. For newly
produced STOPPED_FAILURE_RETRY bindings, leave superseded_progress_artifact_id absent,
just as CONTEXT_CAPACITY_RESUME already does. The trusted collector's current accepted
progress remains eligible. No alternate file discovery, new acceptance or history rewrite.

Implementation worker owns that source and focused tests in
`tests/manager/test_stopped_failure_retry.py`,
`tests/orchestration/test_baseline_history_inputs.py`, and if required the existing
`tests/manager/test_stopped_failure_public.py`. Root owns specs/task/production documents.
Any further source/test path must be explained before editing. Runtime/Schema/resolver
semantics and all other purpose families are out of scope.

## Matrix

| Input | Expected new binding / downstream behavior |
| --- | --- |
| Latest accepted step01 progress, exact same-base stopped native failure | No new retirement; real next request receives progress and completed01; selected excludes01 |
| Exact execute replay or another exact failure retry | Same reservation/replay semantics; no extra retirement/debit; unchanged accepted bytes |
| Missing accepted progress | No synthetic checkpoint; normal empty progress input |
| Unaccepted/foreign/source-mismatched/corrupt report or changed inventory | Existing collector/validation refuses or excludes; no new acceptance |
| SOURCE_REBIND/reapply or other recovery purposes | Existing explicit retirement unchanged |
| Historical binding already retired old progress, successor null | Old remains retired; newer null cannot revive its ancestor |
| New valid native progress superseding old retired progress | New successor may be current; historical record bytes stay unchanged |

Good: step01 stays completed after a newly produced compatible retry binding, and next
claimed request selects step02. Base: absence of accepted progress remains absence. Bad:
reader treats historical null as revocation of a previous explicit retirement, or auto-revives
raw source_artifact_ids. The fix does neither.

## Verification

Write a failing actual service/binding-to-runner regression before the production change.
Cover downstream inputs, continuation checkpoint/paths, completed and selected work-slice,
not merely the service's null field. Use existing typed stores and fake/native fixtures.
Keep ancestor-retirement, source rebind/reapply, candidate and independent role tests green.
If public isolated MySQL/native flow is expanded, run it serially under the already granted
test-environment authorization; no real provider or production SQL modification.

## Existing K1 and rollback

Bindings a083d424… and 7b486204… are immutable and retain their original retirement meaning.
At design time, Run0d6c… legitimately had selected01/02 and could establish a new accepted progress;
verify its actual completed set before claiming restored step continuity. Do not alter or
interrupt its request/checkout to implement this maintenance change. A new maintenance
deployment waits for an actual safe idle boundary and controlled restart.
