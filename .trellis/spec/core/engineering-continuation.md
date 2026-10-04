# Engineering continuation contract

## Scope and signatures

Ordinary new Coder Tasks may adopt `InterruptionContinuationPolicy` v1. This capability permits
one checked continuation of a stopped first invocation, not candidate approval, permissions
expansion, terminal reset or arbitrary dirty adoption. Production preview and dispatch commit
must freeze the same policy; absence remains absent in old Task/approval wire bytes.

`WorkspaceMutationInventory` records bounded no-follow final file observations, including ignored
files. `ExecutionInterruptionReceipt` binds the original request/claim, Task intent, policy,
stopped-process evidence, complete capture, before/after inventory digests and mutation paths.
`ContinuationAdmission` binds that receipt to one new request/WorkItem/Lease. Its authorization
source is organization policy, never a fabricated human verdict.

```python
CoderInterruptionControl.prepare(request, root) -> str | None
CoderInterruptionControl.started(request, root) -> WorkspaceMutationInventory | None
CoderInterruptionControl.interrupted(request, root, *, before, cause,
    original_error_code, process_stop, output_present) -> InterruptionObservation
NativeCoderContinuation.finished(request, root, *, before: WorkspaceMutationInventory | None) -> None
NativeCoderContinuation.resume(task, repository) -> int | None
NativeCoderContinuation.next_attempt(task, result, repository) -> int | None
FileContinuationStore.initialize(root, *, task_id) -> FileContinuationStore
FileContinuationStore.put_receipt(receipt) -> ExecutionInterruptionReceipt
FileContinuationStore.put_admission(admission) -> ContinuationAdmission
```

`finished` verifies the exact invocation inventory and original source HEAD before platform
candidate publication, including ignored writes and explicit denies in otherwise permitted cache
paths. Native success/structured output never bypasses this check. `resume` binds a required
`original_work_item_id` in the receipt to a reclaimed original WorkItem with a new real claim and
exclusive Task lock; it rechecks stopped execution, full capture/current inventory, frozen intent
and absence of accepted output before replaying the budget transaction without a model invocation.
The old lease identity is historical evidence, not a requirement to revive that expired lease.

`FileContinuationStore(root, task_id=...)` is read-only construction; `initialize` explicitly
creates the trusted private directory. `receipt.json` and `admission.json` are immutable,
schema/hash-validated, exact-replay-only files. A different new Run cannot consume the same
admission. Missing facts, symlinks, drift or conflicting writes fail closed.

## Runtime and scheduling contracts

- The native runner must prove the owned process group stopped. Lease expiry is insufficient.
- Capture is execution evidence, never a CoderProgress or implementation report. Unknown output,
  changed HEAD, unsupported mutation or unsafe paths cannot enter automatic continuation.
- Git inventory alone is not complete mutation evidence. Include ignored/protected changes and
  reject final mutations outside policy/capability; do not claim OS pre-write isolation.
- Dirty interruption emits `WORK_INTERRUPTED`, FAILED and nontransient. Inline fallback must not
  switch routes for it; another model invocation requires new Run/Context/claim.
- Local window consumes ordinary work budget; explicit typed provider failure consumes transient
  allowance through atomic retry accounting. Unknown interruption does not refund or fabricate cause.
  Persist the final permitted provider failure even when its exhausted allowance cannot reserve a
  successor. A crash after that transaction replays the exact failure fact and never obtains a
  duplicate debit or free replacement Run.
- A receipt committed before budget reservation or queue finish can be replayed under the same
  original WorkItem's reclaimed ownership; both before/after-budget crash windows publish only the
  attempt-2 scheduling boundary. Exhaustion preserves the original failure and refuses invocation.
- An admission published before a replacement invocation crash cannot be rebound to a new lease
  or Run. There is no durable invocation-start guard proving that no model was called. Preserve
  the draft/admission and route to existing engineering handling; unknown invocation never refunds
  budget or creates a second automatic admission. Exact same-claim replay remains idempotent.
- TaskOrchestrator keeps the last delivery checkpoint; Supervisor atomically finishes the old item
  with the next RoleRunBoundary and Dispatcher issues fresh ownership. No new branch/Task for a
  safely authorized ordinary interruption. Historical terminal Tasks retain successor recovery.
- Wait/queue facts carry engineering/product/team responsibility; UI derives current execution
  independently of delivery stage and keeps complete history. Missing heartbeat is UNKNOWN.
- Candidates still require platform commit policy and independent QA PASS / Review APPROVE on
  the same SHA. This capability never alters their permissions or verdicts.

## Validation matrix

| Facts | Required result |
|---|---|
| First Coder stopped, text draft, same scope/source, frozen policy and remaining budget | Checked same-Task continuation with new identities |
| Existing legal CoderProgress | Existing progress path, no invented receipt |
| No policy on legacy Task | No implicit automatic draft authority; old digest unchanged |
| Missing stop evidence, live process, unknown output, HEAD moved | Preserve and refuse automatic invocation |
| Ignored Trellis/deny mutation, unsafe capture, deletion/rename/mode change | Reject capability admission |
| Changed capture/policy/claim, duplicate admission with different Run | Refuse; no provider call |
| Completed draft then candidate | Normal independent verification, no repeated Coder |

Good: exact draft survives restart and new claim completes on the same branch.
Base: ordinary clean transient and historical recovery remain unchanged.
Bad: mark dirty failure transient and immediately call a fallback under the same Run.

## Tests, rollout and rollback

Required assertions live in `tests/orchestration/test_native_continuation.py`,
`test_continuation_records.py`, `test_continuation_store.py`,
`tests/work_queue/test_owned_execution.py`, `tests/contracts/test_continuation_schema.py`
and `tests/manager/test_production_continuation.py`. They cover one-use lineage, complete
inventory bodies, provider exhaustion and post-commit replay, reclaimed original WorkItem,
ignored/protected successful output rejection, real process stop, new real claim and independent
same-SHA QA/Review. Receipt/admission history is verified by
`tests/team_view/test_continuation_history.py`.

Wrong: infer a stopped process from lease expiry, mark a dirty failure transient, accept a hash
without its body, or skip final inventory validation because the model returned valid JSON.

Correct: owned-runner stop body plus bounded complete inventory and frozen policy precede
receipt; a new claimed invocation receives a one-use admission; final inventory is checked
before candidate commit. Unsupported or uncertain invocation state remains an engineering issue.

Incremental contract/Git/Codex/fallback/retry/queue/public-entry/Console/DOM tests must assert
positive and refusal outcomes plus budget idempotency across write/crash windows. No production SQL
repair, history rewriting or dirty cleanup. Deploy while idle. Revert code only while idle and retain
new immutable policy/receipt readers; older policy-less Task facts remain valid.
