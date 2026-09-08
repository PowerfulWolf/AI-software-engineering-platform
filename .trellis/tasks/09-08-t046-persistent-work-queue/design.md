# Design

## Ownership model

Project Manager sets business priority and escalation policy. Planner creates the ExecutionPlan and
typed queue-routing intent. `DispatcherLoop` is a deterministic application service that repeatedly
executes one bounded tick. It is supervised by the Team Host or an external process manager; it is
not an AgentProfile and never keeps an LLM conversation alive.

## Contracts

`WorkItem` becomes a Run-level scheduling fact with a stable `id`, `role`, `attempt`,
`checkpoint_sequence`, `dispatch_sequence`, repository scopes and optional Agent affinity. Every
requeue increments `dispatch_sequence`, so deterministic Assignment/Lease IDs are new without
changing the logical Run identity. Task delivery status remains a
separate aggregate.

```python
PersistentWorkQueue.enqueue(item: WorkItem) -> WorkItem
PersistentWorkQueue.list_schedulable(*, now: datetime, limit: int) -> tuple[WorkItem, ...]
PersistentWorkQueue.claim(command: QueueClaimCommand) -> QueueClaim
PersistentWorkQueue.start(work_item_id, *, lease_id, owner_token, now) -> WorkItem
PersistentWorkQueue.renew(work_item_id, *, lease_id, owner_token, now, expires_at) -> TaskLease
PersistentWorkQueue.complete(command: QueueCompletionCommand) -> QueueCompletion
PersistentWorkQueue.wait(command: QueueWaitCommand) -> WorkItem
PersistentWorkQueue.retry(command: QueueRetryCommand) -> WorkItem
PersistentWorkQueue.reclaim_expired(*, now: datetime, retry_at: datetime) -> tuple[WorkItem, ...]
DispatcherLoop.tick(*, now: datetime) -> DispatcherTickResult
```

## Transaction and validation matrix

| Operation | Transaction guard | Invalid input/result |
|---|---|---|
| enqueue | unique item ID and unique `(task, role, attempt, checkpoint)` | exact replay returns existing; changed replay conflicts |
| claim | `SELECT ... FOR UPDATE SKIP LOCKED`, scheduler decision rechecked | unavailable work or capacity returns idle/refusal |
| start/renew | item row lock plus exact lease/owner match | stale owner conflicts; no mutation |
| complete | item and lease row locks; close current plus optional next enqueue | wrong owner/status or duplicate changed next item rolls back |
| wait/retry | item and lease row locks; clear active capacity | missing reason/time or wrong owner rolls back |
| reclaim | locked expired active leases | item becomes RETRY_SCHEDULED and old lease is closed |

## Good / Base / Bad

- Good: two dispatchers compete for one READY item; only one receives a durable claim.
- Base: no schedulable or eligible work returns an auditable idle/refusal result without mutation.
- Bad: a stale worker completes a Run after its lease expired or was reassigned; completion is rejected.

## Consistency boundary

Queue lifecycle facts live in MySQL. Run artifacts remain immutable in the ArtifactStore. The caller
must seal and re-read the result Artifact before `complete`; the queue completion records its ID and
digest as evidence. Closing current work and publishing the next WorkItem happen in one DB transaction.
