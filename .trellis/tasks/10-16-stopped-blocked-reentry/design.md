# Design and validation matrix

Reuse the existing stopped-Coder proof; optionally extract a shared read-only helper from
ProductionBaselineFactCollector._stopped_execution into stopped_execution_checkpoint.py.
The full baseline collector retains its original idle SQL fence. The pre-reclaim reader uses
the real Task flock and reads current queue state, without mutating it or nesting Worker flock.

Internal backend method:
`stopped_execution_retry_scope(checkpoint: ProjectDeliveryCheckpoint) ->
AbstractContextManager[StoppedCoderExecutionProof | None]`.
Only BLOCKED/FAILED delivery with failed_stage=DELIVERING, INVARIANT_VIOLATION, no candidate
and actual Task IMPLEMENTING is eligible. Validate the exact original Task/source/permissions,
dispatch/step/claim, unique open Coder WorkItem, no effective current or successor claim,
original start+capture stop, no outcome/route/receipt/raw artifact/conflicting publication and
current original-session emptiness. Do not authorize by the failure-summary string.

DeliveryResumeController passes the trusted backend scope to the explicit
`retry_stopped_execution(command, *, proof_scope=...)` entry method. Reconciliation runs
before the fresh proof is collected. The scope holds the real Task flock through exact current
checkpoint, Task/revision and source validation and the ordinary DELIVERING checkpoint append.
It then releases the flock before entering existing resume flow so normal Worker can acquire it.
General retry_interrupted_stage remains unchanged. The production supervisor takes this flock
before Dispatcher tick; it is not a general SQL fence for arbitrary external dispatchers. External
writers must remain quiesced and the later full rescue retains its Task/SQL final-consumption fence.
Dispatcher performs existing expired-lease/retry
transactions; production's1-second backoff may require a second Continue. The durable invocation
guard rejects main Coder replay, and existing Worker wait seals/relinquishes the new claim.

| Case | Required result |
| --- | --- |
| Exact stopped unknown run, blocked delivery, expired original claim | Public re-entry; existing reclaim→fresh claim→guard→wait, zero repeated main Coder calls |
| Unexpired current lease, later claim, unknown/live session or mismatched proof | No re-entry/state/queue/model change |
| Route/outcome/output/receipt/raw original-Run artifact appears | Refuse; use existing result/fact route |
| General blocked Task/stage or another role/source/candidate | Existing behavior unchanged |
| Existing accepted compatible progress, new same-base stopped rescue binding | Preserve progress; real next request keeps completed steps and paths |
| Closed successor with old clock/counters but a direct parent edge | Refuse by durable lineage; do not rely on claim wallclock |
| Old retired ancestor / source-changing recovery | No revival; existing retirement semantics |
| Exact public PAUSE/RESUME replay | Single reservation/debit, same Task/draft, independent QA/Review |

Good: a stopped original execution becomes an honest waiting WorkItem and an explicitly
approved same-base rescue continues with retained completed steps. Base: normal live delivery
and existing stopped-rescue waits follow current contracts. Bad: broad retry, direct SQL
repair, fabricated output/cause/refund, or old accepted progress silently retired again.

Use the existing public stopped-execution-delivery native/MySQL fixture, including real
process stop, full inventory, replay-guarded knowledge claims and independent role history.
Keep exact negative tests at the extracted proof/pre-reclaim seam and existing final-consumption
late artifact tests. No production provider call is a unit/e2e test substitute.
