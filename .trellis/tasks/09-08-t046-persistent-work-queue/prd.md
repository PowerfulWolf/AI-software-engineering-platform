# T046 Persistent WorkQueue and Dispatcher

## Goal

Turn the existing pure workforce scheduler into a durable organization task pool. Planner owns
workflow and dispatch policy through typed facts; a deterministic Dispatcher service executes that
policy without requiring an always-on model conversation.

## Requirements

- Persist one queue item per executable delivery role Run, not one item per entire Task.
- Support READY, LEASED, RUNNING, WAITING_HUMAN, WAITING_DEPENDENCY, RETRY_SCHEDULED and CLOSED.
- Atomically claim work with a RoleAssignment, TaskLease and ModelSelection under MySQL/InnoDB.
- Renew leases with an owner token, release capacity on completion/wait, and reclaim expired work.
- Apply stable priority/risk/age ordering and Agent capability/capacity/independence constraints.
- Prefer an explicitly requested Agent for continuation only when that Agent is eligible and free.
- Keep Scheduler, ModelRouter, queue storage and Task delivery state as separate typed boundaries.
- Provide a bounded `DispatcherLoop.tick()` seam; process supervision and deployment stay external.
- Update README architecture, one-demand flow and Lease lifecycle explanations.

## Acceptance criteria

- [x] Queue identities allow multiple Coder/QA/Reviewer Runs for the same Task.
- [x] Concurrent MySQL claimers cannot receive the same WorkItem.
- [x] Only the lease owner can start, renew, complete, wait or retry a claimed item.
- [x] Expired LEASED/RUNNING work is reclaimed without losing its history.
- [x] A normal result closes the current item and can atomically enqueue the next role Run.
- [x] Dispatcher invokes Scheduler and ModelRouter, returning a typed dispatch or idle/refusal result.
- [x] Unit, contract, MySQL integration, lint and type checks pass.
- [x] README and Trellis contracts describe implemented behavior rather than future intent.

## Non-goals

- Kafka, Celery, Temporal or another distributed queue product.
- Single-Task DAG execution or parallel delivery roles.
- Automatic merge, push or deployment.
- Making an LLM session responsible for polling, locks, heartbeats or lease recovery.

## Rollback

Revert T046 queue modules/schema/docs. Existing dispatch and synchronous Task delivery remain usable;
the new MySQL tables contain additive organization scheduling facts and can be ignored safely.
