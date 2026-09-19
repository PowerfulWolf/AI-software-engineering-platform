# Production queue integration contract

## Architecture
Production retains its existing approved native/joint Manager entry and TaskOrchestrator authority. A bounded `RuntimeSession.run_step(task_id, control)` executes at most one delivery-role invocation. The initial probe may materialize the deterministic approved plan, then yields **before** the first delivery Context/knowledge consultation. The single Worker supervisor dispatches each yielded role through T046 and repeats bounded steps. CLI/Console result compatibility is retained; the current Console Manager thread supervises delivery. Independent process deployment and inter-Task concurrency are later rollout steps, not claimed by this increment.

## Python seams
- `RoleRunBoundary(task_id, role, attempt, checkpoint_sequence, source_revision)` identifies the next invocation, independent of random provider run IDs.
- `BoundedRunControl.before_run(...)` allows only the exact permit, once, and raises a typed boundary before any other delivery role; `before_write()` verifies ownership before artifact persistence, attempt reservation and Task events.
- `RuntimeSession.run_step(task_id, control)` returns the normal result or next boundary. Existing low-level `run_task` remains compatible.
- Production supervisor holds an exclusive per-Task process lock in its external sidecar, never the target repository. Queue authority remains required in addition to process exclusion.
- Worker starts and heartbeats its exact claim across Context creation, provider execution, Artifact validation/readback and Task transition. Lost renewal fails closed before subsequent accepted writes.

## Capacity handoff
The first production queue item explicitly adopts the Task under dispatch-authority then queue-authority lock order. Old dispatch facts stay immutable and retain scope/approval/frozen identity, but their ordinary delivery capacity reservations cease once adopted. Independent verification reservations remain active under their own lifecycle. Queue and legacy dispatch must read each other's active reservations under this same outer lock; assignment history from both remains relevant to independence. No mixed-version producers may execute during rollout.

## Frozen primary and explicit fallback

The dispatch actor and primary model cannot change. Existing explicit fallback remains an ordered
subset of the dispatch's immutable policy version; actual provider attempts retain their existing
ModelRouteAttempt audit. A recovery may narrow routes, never add/reorder providers or reasoning levels.
Legacy unspecified reasoning permits only one unambiguous configured route.

## Crash / validation matrix
| Case | Required outcome |
|---|---|
| Probe reaches Coder | No Coder Context, model call or claim fabricated |
| One permitted Coder finishes | Task can advance to QA, but no QA model invocation until a separate claim |
| QA failure or Coder continuation | Original finding/progress and bounded attempts retained; next Coder is separately queued |
| Renewal lost while model runs | No output sealing, Task advance or successful queue completion from the old owner |
| Lease expiry while completion waits for a SQL lock or writes | Fresh lock-scoped check and pre-commit check roll back close and next-step publication |
| Artifact sealed before state event | Reuse trusted artifact through original recovery validation; no repeat model call |
| State event committed before queue completion | Reconcile old claim and publish the next exact role without skipping its QA/Review gate |
| Lease expired with unknown provider side effects | Preserve dirty worktree; original native checkpoint/admission rules decide safe reuse |
| Knowledge gap | Exact QueueKnowledgeWaitPort releases claim; validated stored resolution is required to make ready |
| Duplicate resume | Per-Task exclusion plus queue claim fence prevent concurrent role execution |
| Existing DONE/BLOCKED/FAILED | No reactivation; replay terminal evidence only |

## Examples
Good: Coder and QA use distinct claims, each with durable receipts and heartbeat; Review alone can lead to DONE through existing gates.
Base: ordinary CLI still waits for its result, but every delivery invocation uses the queue.
Bad: wrapping only AgentAdapter.run (misses knowledge and sealing), or treating queue complete as a verdict.

## Persistence / rollback
Never rewrite existing dispatches, approvals, contexts or artifacts. Runtime metadata belongs to the external sidecar. New SQL/read contracts and migration are tested with isolated MySQL. Stop and drain old processes before rollout/rollback; preserve all queue history. No-active-claim alone is not enough for rollback: adopted nonterminal Tasks cannot be executed by the old binary. Drain with the new version or freeze delivery, following docs/t046-worker-operations.md.
