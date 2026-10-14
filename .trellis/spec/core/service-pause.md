# Controlled execution pause for service restart

## Scope / signatures

`ServicePauseControl.request(*, request_id=None, instance_id=None)` closes future call admission
and starts a fixed finite completion window. `check_service_pause()` runs before new native/HTTP
calls, roles, fallback routes, knowledge calls and retry loops. `ServicePauseControl.due_request()` is only for
an actual already-owned runner; it does not grant PID selection or command authority.
`ServicePauseControl.cancel()` reopens service admission after timeout-only RESUME; sealed
execution pauses remain durable. Repeated drain requests do not reset the first deadline.

## Contract

`NativeProcessStop.kind=service_pause` has a complete real OwnedSessionStopProof. `SERVICE_PAUSED`
is nontransient and never classified as TIMEOUT/provider failure. Operation/run/knowledge records
must finish before READY. Pause does not cancel writes needed for finalization or owner checks.
No stopped provider/result may silently be called again with an old Run, Context or Lease.

Coder `ExecutionCaptureStop`/`ExecutionInterruptionReceipt` may observe service_pause with exact
SERVICE_PAUSED error and matching native stop or a genuinely returned synchronous Responses tool loop. Old `InterruptionContinuationPolicy.allowed_causes`
is unchanged; automatic continuation refuses that cause before reserving budget. An exact approved
execution-baseline plan can preserve/reapply the verified draft using an ordinary work reservation.

## Validation matrix / Good, Base, Bad

| Input | Required result |
| --- | --- |
| Idle host | quick READY and one replacement |
| Current valid role finishes in window | persist/accept normally; next role remains unclaimed |
| Native still running after window | actual owned stop + final records + released wait; no verdict |
| HTTP call outstanding | await real return; no abandoned thread or assumed remote cancellation |
| Repeated shutdown or canceled client | original deadline/save/ownership remain |
| Stop uncertainty, pipe retained, receipt/store failure | REFUSED; old Host retained |
| service_pause cause under old frozen policy | no automatic dirty admission, no budget refund |
| exact current approved baseline plan | original Requirement continuation with fresh execution identity |

Good: preserve legal source draft, release old ownership, load successor service and approve current
engineering plan. Base: completed artifacts and independent QA/Review gates are unchanged. Bad:
manufacture TIMEOUT, clear a live registry, update Task status directly, or replay unknown invocations.

## Tests / existing data / rollback

Tests exercise real local sessions, scope isolation, stop proof persistence, missing evidence,
role/retry boundaries, exact pause cause schema parity and retained original approvals/worktree.
Existing records are not rewritten; absent new fields retain old bytes/digests. Deploy through
verified existing lifecycle, then read and resume the original K1 through public authorized APIs.
Rollback only after controlled stop, preserving additive records and a compatible reader.

## Admission and epoch races

`ServicePauseControl.admission()` serializes short native spawn/Dispatcher claim with request; it must
never enclose an entire HTTP/model call. Stop decisions retain an immutable `PauseRequest` epoch.
A concurrent timeout-only RESUME reopens future admission but cannot erase that original stop or
associate it with a later request. Native stop-store failure marks ownership uncertain and keeps
READY refused. Helper threads reactivate the exact Operation pause scope via OwnedOperationContext.

## Claimed-but-uninvoked recovery

`SerialOrchestrator._run_agent` creates the durable `DeliveryInvocationStart` after the
role claim and before provider admission. If the pause epoch closes at that boundary, it
writes a `DeliveryInvocationOutcome` with `AgentFailure(code=SERVICE_PAUSED, transient=false)`
and `PausedInvocationProof(admission_closed=true, process_stop=null)`. The queue wait stores
that exact `invocation-outcome://` fact and releases the owner-fenced lease. A Coder outcome
can only be consumed by an approved `ExecutionBaselinePlan`; it never enters the old generic
continuation policy. QA/Reviewer outcomes may use `DeliveryResolution.retry_cause=service_pause`
only with the matching `verifier_pause` proof and a fresh work attempt.

`PreflightInvocationControl._prepare_verifier` catches a pause before native verification
starts, writes a `VerifierPreparationCheckpoint(result=WAIT, failure_reason=SERVICE_PAUSED)`
and emits one `verifier-preparation://<checkpoint_sha256>` evidence ID. The investigation
requires the original claim, current candidate, and native observation to match before
`RESUME_UNINVOKED` or `RETRY_VERIFIER_PREPARATION` is offered. A missing marker remains
`INVOCATION_UNRECORDED` and cannot be resumed by changing the wait text.

Command evidence catches both `CommandServicePaused` (an owned process was stopped) and
`ServicePauseRequested` (the next command was denied before spawn). It seals
`CommandOutcome.SERVICE_PAUSED` and confirms the evidence store before releasing the owned
session registry. A denied command has no process stop proof; an active command must contain
the real `OwnedSessionStopProof`. Native UI launch uses the same short `pause_admission`.

Validation commands:

```text
PYTHONPATH=src .venv/bin/pytest tests/manager/test_verifier_preparation.py tests/manager/test_delivery_wait.py
PYTHONPATH=src .venv/bin/pytest tests/execution/test_service_pause.py tests/execution/test_owned_record_finalization.py
PYTHONPATH=src .venv/bin/pytest tests/contracts/test_owned_session_stop_schema.py tests/contracts/test_repair_schema_generation.py
PYTHONPATH=src .venv/bin/mypy src
```

A fallback pause records `admission_closed=true` only if no route was ever admitted. If earlier
routes actually returned, it seals a synchronous loop stop with their completed `model-route.N`
IDs and retains all route-attempt records. Such a returned-route proof can support an exact
approved Coder baseline and ordinary work reservation, but cannot authorize generic Coder
retry. A missing first Coder checkout may be created only when every original Coder invocation
is independently confirmed no-start and no candidate, progress, baseline, receipt or branch
survives. It cannot reconstruct a lost started or dirty worktree.

## Same-baseline Coder approval

`ExecutionBaselineBinding.service_pause_outcome_sha256` is absent from old records and their digest.
For SOURCE_REBIND, `execution_base_ref == prior_execution_base_ref` is allowed only when the exact
approved Plan contains a `facts.continuation.retry_cause=service_pause` reservation with that outcome
SHA. Source/target native rules must be identical, input mode must preserve_draft, and prepared HEAD
and full dirty patch must match the original worktree with no conflict. Execute verifies the exact
inventory and seals a binding without changing HEAD or the dirty tree. Queue consumption verifies the
binding's outcome SHA equals the approved reservation before reserving a fresh ordinary work attempt.
Generic continuation and old frozen permissions remain unchanged; missing proof or mixed rescue
proofs refuse. Real-Git and isolated MySQL tests cover same-base Plan→approval→binding→consume→release
and fresh fenced claim, replay without new counters, unchanged source draft and historical events.
