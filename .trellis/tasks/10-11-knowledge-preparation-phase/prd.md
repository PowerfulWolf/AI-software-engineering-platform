# Knowledge preparation phase in delivery execution

## Goal
When a real current claimed Coder/QA/Reviewer is preparing organization knowledge,
show that step in Task and Requirement details. Do not claim that the main role
model has started until its exact immutable invocation start exists.

## Scope and allowed paths
Read-only Team view models, queue reader, Task reader, app.js, a new
team_view/knowledge_preparation.py, the RoleQueueView definition in published
snapshot Schemas, isolated Team view Python/DOM tests, this task directory and the
new core knowledge-preparation-phase spec. Parent owns knowledge invocation writes,
retry, authorization, production state and delivery operations. Shared edits by
other agents must be retained.

The minimal pure baseline overlay extraction in work_queue/baseline.py is allowed
to share the existing exact source-resolution algorithm with the reader. The
existing writer retains inherited-baseline authorization. No queue mutation or
new baseline authority is part of this task.

## Acceptance
- RUNNING and a currently valid SQL lease are required before any fine phase.
- Only immutable receipts matching this exact work item, task, role, attempt,
  checkpoint, dispatch, assignment and lease may establish a phase.
- Scope/source revision are checked; status and lease expiry are current mutable
  facts and are not compared to the frozen original QueueClaim as whole objects.
- Knowledge intent before main-role start means preparation; sealed knowledge
  outcome does not prove main-role execution. Exact main-role start takes priority;
  its matching outcome means local result saving/checking, never accepted verdict.
- Task, Requirement summary and activity preserve the same backend reason_code and
  Chinese reason/next action. Legacy valid claims without fine receipts render
  ROLE_WORK_CLAIMED / "已领取当前工作, 细分执行进度暂未上报", without claiming
  that the main role invocation has started.
- Missing legacy stores create nothing. Invalid records, hash mismatch, symlink,
  FIFO and oversized inputs fail closed; reading is bounded, fresh and read-only.
- Optional RoleQueueView.execution_phase is excluded when None so nested legacy
  dumps and immutable hashes stay stable. All relevant Schemas retain parity.
- Only incremental Python/DOM checks run; no full suite or production mutation.

## Rollback and existing data
No database migration, historical receipt backfill or state rewrite. Restarting an
idle upgraded frontend/read service is enough to expose new future receipts;
historical unknown calls remain neutral. Roll back the optional read projection
and frontend phase presentation while retaining all immutable invocation facts.
