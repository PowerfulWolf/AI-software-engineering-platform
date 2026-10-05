# Historical native child membership in the Requirement read model

## Problem and goal

The K1 same-Requirement upstream correction clears current children and plan. The reader currently
forgets the old native child's parent and lists its retained BLOCKED audit checkpoint as another
standalone Requirement with the same title. Preserve permanent identity membership through all
validated joint journal history, while deriving current execution only from the latest checkpoint.

## Scope and allowed paths

- `src/ai_software_engineer/team_view/reader.py`
- `src/ai_software_engineer/team_view/app.js` (root-owned frontend current/history composition)
- `tests/team_view/test_live.py` and narrowly necessary related read-side tests
- `tests/team_view/historical-child.test.cjs`, `tests/team_view/browser/historical-child.test.cjs`
  and related `delivery-status`, `engineering-wait`, `knowledge-gap`, `operation-progress` fixtures
- `.trellis/spec/core/live-team-view.md`
- `.trellis/tasks/10-05-historical-child-membership/`

No production operations, SQL/journal/verdict edits, Requirement deletion, runtime restart or schema
changes. Do not change Coder/QA/Reviewer authority or match Requirements by title.

## Acceptance

1. Clearing current plan/children keeps the old native child attached to its exact original parent;
   the Requirement list contains the parent once and the child remains available as audit work.
2. Current scope delivery IDs, blockers, header and member queues only use current child/plan facts.
   A later child can coexist with the historical child without the old blocker contaminating it.
3. Exact unit/root/repository/checkpoint ancestry and parent ownership are verified over all journal
   history. Missing, cross-scope, replaced/future or ambiguous child references fail closed.
4. A genuinely independent same-title native Requirement remains visible.
5. Snapshot reads leave all Project/Team files unchanged; retired parent children remain excluded.
6. Requirement header/flow, member current/blocked queues and current work counts exclude historical
   child sources, while a folded historical-delivery list links to their unchanged failure details.

## Incremental validation

Run new `tests/team_view/test_live.py` historical-membership tests first (red, then green), relevant
existing joint/retirement/current-work/queue tests, Ruff on changed Python and strict mypy on owning
modules. Run the new Node/Chrome historical-child tests and related affected frontend tests. Do not
run the full suite. Use an isolated test DSN only if the existing MySQL regression is selected;
no production DSN can be used by tests.

## Existing-data disposition and rollback

This is a read-side correction. K1 immutable parent/native history is sufficient, so no store rewrite
or deletion is needed. Deploy while execution is idle, reload the reader/Host through the trusted
service composition and refresh the same Project. The original Requirement identity remains the
delivery target. Roll back reader code while idle, keeping every historical/current checkpoint.
