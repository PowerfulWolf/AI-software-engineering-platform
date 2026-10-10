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

`ExecutionCaptureStart.scope` is a full `ContinuationScope`, including the exact Requirement ID
and dispatch commit digest. The engineering wait collector receives the current native checkpoint
scope from the trusted Host and requires equality before it can reconcile a capture; matching only
Team/Project/Repository is insufficient. Requirement or dispatch drift remains a platform attention
record and cannot consume a continuation admission.

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
FileContinuationStore.put_capture_start(start: ExecutionCaptureStart) -> ExecutionCaptureStart
FileContinuationStore.capture_start(run_id: str) -> ExecutionCaptureStart
FileContinuationStore.put_capture_stop(stop: ExecutionCaptureStop) -> ExecutionCaptureStop
FileContinuationStore.capture_stop(run_id: str) -> ExecutionCaptureStop
NativeCoderContinuation.record_native_stop(request, root, *, process_stop,
    output_present, cause, original_error_code) -> None
DeliveryWaitFactCollector.collect(task: Task, step: QueuedRoleStep,
    guard: WorkerExecutionGuard) -> None
reconcile_capture(*, start, stop, task, task_revision, historical_claim,
    store, git, task_lock, validate_inputs, has_output, clock) -> ExecutionInterruptionReceipt
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

### Native start/stop publication and bounded reconciliation (2026-10-08)

`started()` seals `capture-start-<run_id>.json` before invoking Codex, within the real claim and
Task lock. The body retains the complete original request, historical claim, frozen Task intent,
revision/policy, full inventory, absolute owned worktree, scope and start time. The owned native
runner uses `run_observed(..., observer=...)` to seal `capture-stop-<run_id>.json` after the process
group is proven stopped and before the adapter returns or produces its interruption receipt.
Owner loss may publish the actual stop fact under the retained Task lock, but cannot publish a
verdict, mutate Task/budget, or invent a provider failure. Unknown cause remains null.

`DeliveryWaitFactCollector` is only called by the Host with an exclusive Task lock and MySQL
`idle_task_scope`. Its `expected_continuation_scope` uses the native child delivery ID and native
dispatch digest even when the product command addresses a joint parent. It can recover a sealed
final route result into the original invocation journal without a model call. It cannot treat a
fallback-only route chain as final. If no final exists, `reconcile_capture` requires the original
start/stop, known typed cause, output absent, historical claim, unchanged authorized inputs and
complete legal inventory before it seals a receipt. It never revives the expired old lease.

| Boundary | Required behavior |
|---|---|
| Complete final route chain, exact request/result identity | Seal original invocation outcome once; no new call or budget |
| Known native stop before receipt publication | Verify all before/after bodies, index/HEAD, scope, policy and inputs; seal immutable receipt |
| v2 clean/cache-only known failure | A fully verified empty-source capture is allowed; it is not Coder progress |
| v1 empty-source capture | Preserve historical v1 restriction and refuse fabricated checkpoint |
| Missing original claim or result identity mismatch | Typed collector rejection; HANDLE records platform attention |
| Still active claim or unavailable Task lock | Wait for execution; do not label record corruption or timeout |
| Host killed before stop publication, unknown cause, output already observed | Preserve wait; no synthetic stop, refund or new invocation |
| Start/stop tamper, symlink, scope/dispatch drift or incompatible time | Fail closed; source and audit remain unchanged |

The new ledger is additive. Old Tasks without start/stop records are not backfilled with guesses.
No migration or production SQL repair is required. Deploy only when idle and preserve immutable
ledgers on rollback. Future orphan-process supervision requires a separate trusted observer contract.
Tests: `test_wait_fact_collection.py`, `test_capture_reconciliation.py`,
`test_continuation_store.py`, `test_continuation_schema.py`, `test_codex_cli.py` and the real joint
Host composition test assert no new model call, Task/event mutation, budget debit, discarded draft,
or parent/child scope alias during fact collection.

Wrong: declare timeout after a restart because a lease expired or a process ID is absent.
Correct: reuse only the original owned runner's sealed stop and complete original inventory,
or find and verify the original final result; otherwise record a platform maintenance issue.

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
| Capture start has another Requirement or dispatch digest | Refuse reconciliation; preserve the wait and report platform attention |
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

## v2 multi-round and synchronous Responses continuation

The v1 matrix above remains the historical capability: it does not gain deletion,
rename, mode-change or synchronous execution authority. New v2 Tasks freeze their
own policy and publish per-Run append-only receipts/admissions; old v1 bytes/digests
remain unchanged. `CapturedMutations` contains complete before/after regular UTF-8
bodies and patches, including deletion, addition and 0644/0755 changes. Binary,
symlink, sensitive, denied, ignored-policy and drifting mutations are refused.

`agents.execution.ExecutionStop = NativeProcessStop | SynchronousToolLoopStop`.
The synchronous stop has `origin=synchronous_responses_tool_loop`, exact Task/Run
and `request_sha256`, unique `completed_operation_ids`, `kind`, `stopped_at` and
`stop_sha256`. It has no native PID/group fields. Only the trusted synchronous
Responses adapter can seal it after its local restricted registry operations have
all returned. `require_request(request)` checks the entire original request digest.
Unknown command completion, owner loss, Host interruption or a received final body
cannot create an absent-output continuation receipt. A provider failure uses
`kind=failed`; a local window limit uses `kind=local_execution_limit`. Both Python
and `execution-continuation.schema.json` require v2 and matching cause/stop kind.

`SubprocessCommandExecutor.run` raises `CommandExecutionUncertain` if it cannot
prove the owned command group and output drains stopped. It is deliberately not a
`CommandExecutionError`: the registry must not convert it to an ordinary tool
refusal. A reaped leader alone is insufficient. `QueuedDeliverySupervisor` seals an
owner-fenced `EXECUTION_UNCERTAIN` wait, releases the lease and preserves the Task
checkpoint/worktree. `PolicyBoundToolRegistry.write_file` preserves existing
regular permission bits (special bits refused), uses 0644 for new files, and applies
the mode before fsync/atomic replace. A mkstemp 0600 file must not become the source
file: it breaks complete mutation capture and executable source behavior.

Good: a Responses Coder writes a lawful file, receives a typed provider failure,
and its stopped synchronous loop produces a complete v2 receipt; a new claim and
Run/Context continue the same worktree. Base: a clean or v1 execution keeps its old
bounded behavior. Bad: the HTTP final body arrives at the deadline and the adapter
checks time first, incorrectly records output absent, then starts another model.
Returned successful bodies are classified before the limit check; a known final
whose finishing exceeds the window enters engineering investigation without a
receipt, candidate acceptance or repeated invocation.

Required increments: `tests/agents/test_responses_continuation.py`,
`tests/agents/test_http_deadline.py`, `tests/orchestration/test_synchronous_continuation.py`
and `tests/tools/test_registry.py`. Assert both the HTTP-return and decode-return
late-final boundaries, all completed operation identities, no same-Run dirty
fallback, provider versus local budget debit, v1/synchronous Schema refusal, mode
preservation and real executor uncertainty escaping the tool registry.

## Scenario: known stop with refused complete capture (2026-10-10)

### 1. Scope / Trigger

Use this contract when the original native runner has sealed valid `ExecutionCaptureStart` and
`ExecutionCaptureStop`, but no complete `ExecutionInterruptionReceipt` exists because capture
publication failed. A real local TIMEOUT, a stopped invocation, a complete reusable checkpoint and
a permitted recovery are four separate facts. Losing the latter facts must not turn a validated
stop into `STOP_UNRECORDED`, and knowing the stop must not grant recovery authority.

### 2. Signatures

```python
validate_capture_stop(
    *, start: ExecutionCaptureStart, stop: ExecutionCaptureStop, task: Task,
    task_revision: int, historical_claim: QueueClaim, task_lock: ExecutionGuard,
    validate_inputs: Callable[[AgentRequest], None],
) -> None

DeliveryWaitFactCollector.observe_stop(
    task: Task, step: QueuedRoleStep, guard: WorkerExecutionGuard,
) -> ExecutionCaptureStop | None

DeliveryWaitService(..., fact_collector: WaitFactCollector | None = None,
                    stop_observer: WaitStopObserver | None = None)
WaitStopObserver = Callable[
    [Task, QueuedRoleStep, WorkerExecutionGuard], ExecutionCaptureStop | None
]
DeliveryWaitHandling.collection_failure: DeliveryWaitCollectionFailure | None
DeliveryWaitCollectionFailure.WORKSPACE_CAPTURE_REJECTED
```

`CaptureStopProcessUncertain` is an internal typed rejection for a live or uncheckable original
process group. `WaitWorkspaceCaptureRejected` is an internal capture refusal emitted only after
the full original stop validation and a recheck after capture fails. Neither carries rejected
source, filesystem paths or exception text into the wire diagnostic.

### 3. Contracts

- `reconcile_capture` and `observe_stop` share `validate_capture_stop`. It validates start/stop
  integrity; exact original request/Task/attempt/revision/frozen intent/policy; matching stop
  Task/Run/start digest; monotonic start/stop time; full original assignment/model/work-item and
  immutable lease/worker/claim-time fields; held Task process lock; unchanged accepted inputs;
  and the current owned process-group stop check. A Lease heartbeat may update `expires_at`;
  the other lease fields cannot drift. Expiry is never stop evidence.
- The Host gives the collector an exact native child `ContinuationScope`, including Requirement
  ID and dispatch digest. Parent Requirement addressing cannot replace that child identity.
  The Host runs both collection and stop observation within `queue.idle_task_scope`, while the
  service holds `WorkerExecutionGuard.task_scope`. A live claim or process refuses observation.
- `observe_stop` only reopens original invocation/capture records. It does not recover a final
  route, scan/copy source bodies, publish a receipt, modify Task/queue/budgets or invoke a model.
  INSPECT may seal its ordinary immutable investigation, but cannot reconcile missing capture.
- A valid stop alone may set investigation `process_stop_sha256` and the actual `retry_cause`.
  Missing outcome and complete checkpoint remain missing, and `permitted_resolutions=()`.
  Stop observation does not require absent output; it proves no output acceptance. HANDLE's
  full reconciliation still separately requires known cause/error, absent original/accepted
  output, complete legal capture/current inventory and all normal receipt checks.
- A `WorktreeCaptureRejected` or mutation-inventory refusal after validated stop becomes
  `collection_failed=true`, `collection_failure=WORKSPACE_CAPTURE_REJECTED`,
  `status=PLATFORM_ATTENTION`, no resolution and `CHECKPOINT_UNAVAILABLE`. An unknown result
  stays `OUTCOME_UNKNOWN`. The fixed Chinese report names complete-progress sealing as the
  problem; it does not advertise a missing stop or copy the rejected body/error.
- Typed collection failure requires a stop digest, checkpoint missing, no `STOP_UNRECORDED`,
  no permitted resolution and no resolution. The optional field is omitted when None from
  wire and model dump; `delivery_wait_handling_record_key` adds the field only when present.
  Old absent-field bytes, hashes and record keys remain readable. New failures participate in
  a new immutable identity rather than changing old reports.
- `engineering-wait-resolution.schema.json` and its `console-operation.schema.json` embedded
  definitions carry the same enum and conditional failure validation. Synchronize generated
  definitions without erasing unrelated hand-written contract matrices. History consumes the
  sealed handling record and records the safe code without producing any execution authority.

### 4. Validation & Error Matrix

| Original facts / operation | Required result |
|---|---|
| Exact stop, local TIMEOUT, complete legal capture and remaining frozen authority | HANDLE may seal receipt and use the ordinary exact policy resolution |
| Exact stop, capture refused | Safe typed capture failure; stop digest retained; outcome/checkpoint missing; no resolution |
| Exact stop, INSPECT only | Read stop and seal investigation; no receipt, role invocation or budget debit |
| Real stop with unknown cause or observed output | Stop may be reported; reconciliation still refuses automatic continuation |
| Missing/tampered start or stop, different native Requirement/dispatch, Task/claim drift | No known-stop proof or recovery; original records and draft remain |
| Lease expiry changed by legitimate heartbeat only | Stop identity remains valid; expiry does not itself prove stopping |
| Lease acquired-at, worker, model or original claim drift | Reject observation; no new receipt or authority |
| Active queue claim or original group live/uncheckable | Execution wait; no capture-failure claim, model restart or stop assertion |
| Failure code unknown, missing stop, false collection_failed or absent checkpoint missing | Pydantic and published nested/standalone Schema reject |

### 5. Good / Base / Bad Cases

Good: the runner actually times out and seals a real stop; capture later succeeds after a platform
fix, and HANDLE generates a new receipt and frozen-policy decision for the same Requirement.
Base: capture still refuses; the user sees the known stop and precise sealing issue, with all
draft/audit facts retained. Bad: treat stopped status as a complete checkpoint, refund a local
window as a provider failure, or reset/recreate the Task to evade an incomplete capture.

### 6. Tests Required

- `tests/manager/test_wait_fact_collection.py` uses real Git v2 source capture: a sensitive body
  refuses sealing while valid original start/stop remain unchanged. Assert known stop/cause,
  no copied body/path, no receipt/resolution, no Task/event/budget mutation and exact replay.
  INSPECT must independently retain the stop without creating capture. The authority matrix
  rejects Requirement/dispatch, model, immutable lease, worker, Task and current-group drift;
  legitimate heartbeat expiry remains valid and a missing Task lock rejects.
- `tests/orchestration/test_capture_reconciliation.py` keeps the shared validator and full
  receipt gates exercised for v1/v2, output/cause/lock refusal, source/HEAD/claim/permission
  drift and final-inventory races. Stop-only support must not relax these receipt gates.
- `tests/manager/test_delivery_wait.py` covers an active claim as execution waiting and
  absent-field historical handling keys/digests. Capture diagnosis cannot authorize a retry.
- `tests/domain/test_delivery_resolution_schema.py` and the capture fixture validate both
  standalone and Console-embedded failure shape, including unknown/false/missing-field refusal.
- `tests/team_view/test_engineering_history.py` keeps safe diagnostic/history/store-key linkage
  and asserts unchanged read-side file inventories.

### 7. Wrong vs Correct

Wrong: `receipt is None` therefore report that the original stop is unrecorded; or if the stop
is found, offer RETRY directly. Correct: validate and report the original stop independently,
keep checkpoint/outcome missing, and let HANDLE satisfy the separate complete-receipt gates.

### 存量数据处置与回滚

No SQL migration, stop fabrication or in-place report rewrite. For an existing exact K1 wait,
load the fix while idle, preserve its worktree/ledgers, then HANDLE the same Requirement and
current WorkItem binding. Complete sealing yields new immutable proof/receipt/handling facts;
old failed handling, invocation, claim and role history remain. If capture still refuses, repair
the typed sealing issue before retrying; do not approve a stop-only proof or delete the draft.

The optional diagnostic is backward-readable by the new runtime, not forward-readable by an
older strict `extra=forbid` runtime. After new failure records exist, a behavior rollback must
retain the new diagnostic domain/schema/history readers. Do not delete or rewrite audit records
to make an older binary accept them. Reader rollback without compatibility must fail closed.
