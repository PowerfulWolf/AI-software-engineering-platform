# Stopped invocation without a published outcome

## Blocked delivery re-entry and retained progress (2026-10-16)

A raw platform execution exception can leave delivery BLOCKED/INVARIANT_VIOLATION while the
actual Task remains IMPLEMENTING and its sole original claim is ACTIVE but expired. Public
Continue may re-enter only after a trusted typed stopped-execution pre-check validates the
original start/capture/stop, exact Task/revision/source/permissions/step/dispatch/historical
claim, absent outcome/any route/output/receipt/raw Run artifact, no effective/later claim and
current owned-session emptiness. It must not authorize from a summary string or widen ordinary
BLOCKED retry. Reconcile before collecting the fresh proof. The original Task flock guards
the proof read through the exact checkpoint append; release it before Worker reacquires it.
The production supervisor takes this flock before its Dispatcher tick. It is not a general
database fence for arbitrary external dispatchers. The later full rescue keeps its existing
Task/SQL fence and final-consumption validation; external writers must remain quiesced.

Append only an ordinary DELIVERING checkpoint, then reuse existing Dispatcher reclaim and
Worker lifecycle. Production retry delay can require two Continue operations. A fresh claim may
finish legitimate read-only knowledge preparation, but the immutable start without outcome
must prohibit another main Coder call and produce the existing owner-fenced engineering wait.
No new queue mutation, result, receipt, cause, refund or Task reset is introduced by re-entry.
The normal full rescue proposal still requires its idle Task/SQL fence and exact PAUSE/RESUME.

The internal signatures are
`ProductionProjectDeliveryBackend.stopped_execution_retry_scope(checkpoint) ->
AbstractContextManager[StoppedCoderExecutionProof | None]` and
`UnifiedProjectEntryService.retry_stopped_execution(command, *, proof_scope) ->
ProjectDeliveryResult`. The proof factory is trusted composition, never browser-supplied
proof data. `read_stopped_coder_execution(...) -> StoppedCoderExecutionProof | None` is shared
with the full baseline collector, which retains its original idle SQL transaction fence.
No new HTTP action or browser assertion that an execution stopped is introduced.

New same-base STOPPED_EXECUTION_RESCUE binding construction must not retire already accepted
compatible progress. Real downstream request checkpoint/paths and work-slice completed steps
remain available. Old explicit retirement bindings keep their original meaning; source rebind
or reapply continues to retire incompatible progress. No reader may revive a retired ancestor.

Regressions must exercise the real public blocked/native/MySQL path through original claim
expiry, fresh guarded claim and exact recovery, plus current-live/late-claim/result/route/
artifact/proof/scope drift refusals. Assert old record bytes, Task/attempt/source and role call
counts, retained accepted steps and independent same-candidate QA/Review. See maintenance task
10-16-stopped-blocked-reentry for exact executable matrix and rollback.

## Scope and contracts
A Coder may lose lease authority during local computer sleep. The owner fence must still reject
Task/result publication, while the trusted native runner stops and records its own real session.
A complete stop is not a Coder result, candidate, interruption cause or permission to continue.

For future guard failures, seal only a safe typed guard-abort reason with the exact existing native
capture stop. Do not retain exception messages/tracebacks or call fenced result publication after
authority was lost. Old absent optional fields preserve their original bytes/digests.
`ExecutionCaptureStop.execution_abort_reason` is an optional `ExecutionAbortReason` with fixed
`kind=lease_authority_unconfirmed` and optional `detail` in `local_expiry`, `renewal_exception`,
`heartbeat_stop_timeout`. Only typed `ExecutionAuthorityLost` from the trusted guard may supply it.
`WorkerLease.check` makes observed local expiry sticky; a late renewal cannot restore revoked
authority. The stop must have a complete owned-session proof, `error=WORK_INTERRUPTED`, no output
and `cause=null`; ordinary signalled exits retain their original classification. The reason is
an executor observation, never a model result or an automatic continuation cause.

Add `purpose=stopped_execution_rescue` to the existing baseline proposal/execute/release flow.
The trusted collector supplies a typed stopped-Coder proof containing original invocation/start,
capture-start, capture-stop and historical claim identities. It must prove no final outcome,
output, artifact or continuation receipt; a complete valid owned-session-empty stop proof is
mandatory and independently rechecked. Current active claims and live/unverifiable sessions refuse.
The cause may remain unknown; no retrospective owner-loss or provider assertion is required.
The absent artifact refers to this invocation and later conflicting publications; prior accepted
plan/progress/history remain. Reopen the full model-route ledger: this capability rejects any route
record for the Run, including FALLBACK/remote/unknown records. A sealed route result must take its
existing result-replay route. One local session proof cannot cover another execution boundary.
Recheck outcome, route, this-Run artifact/publication and receipt absence at proposal, execute and
the final new queue-consumption callback, alongside the repeated complete inventory check.

A later ordinary Continue may hold a distinct real claim, finish read-only knowledge preparation,
then hit the durable invocation fence because the same WorkItem already has a start and no outcome.
That claim is neither an unclaimed item nor failed knowledge preparation. Cover it with a separate
exact current engineering observation proof; never loosen
`read_failed_knowledge_claims` to call RETURNED knowledge a failure. Any current observation must
belong to the newly sealed investigation/plan and must not impersonate a historical refusal record.
Its deterministic digest binds the verified snapshot; it does not claim a backdated event time. Bind the earlier
blocking start, complete later claim/Context and returned knowledge executions, independently
confirmed execution stops, current owner-fenced waiting facts and full no-new-call publications.
Only the exact verified claim leases may be removed from the preflight-unknown set. A stray,
unfinished, foreign, remotely unconfirmed or ambiguously invoked claim must still refuse.

Proposal omits target_base_ref and forbids coder_reapply. Backend freezes the current execution
base. Complete retained source, frozen write/deny permissions, HEAD/index/branch, text/secret/mode,
noncache coverage, and double inventory freshness checks remain mandatory.

Execution requires a new exact engineering operator decision, same base/source, preserve_draft,
PAUSE, unchanged complete before/after inventory and native-rule epoch. No organization-policy
automatic admission, legacy historical-attestation method, native-rule change, provider retry
failure or refund is allowed. Consume one ordinary work attempt under the existing idle Task/SQL
fence, reserve a distinct paused WorkItem once, then require a separate exact latest-bound RESUME.
Do not fabricate an outcome, alter original stop bytes, or change frozen product/permissions.
Record an idempotent `HumanActionEvent(SUPPLY_EVIDENCE)` referencing the exact operator authority
URI/SHA. This engineering intervention remains visible to Evaluation and does not count as autonomous.

## Validation matrix
| Case | Required behavior |
| --- | --- |
| Exact no-output stopped native Coder + absent outcome + full legal draft | Prepare exact new engineering plan |
| Stop without complete owned-session proof, failed recheck, active claim/session | Refuse before capture effects/queue reservation |
| Existing outcome/output/artifact/receipt | Use its existing route; never stopped rescue |
| Any route record, including late result/fallback after proposal | Reject new consumption; prefer exact existing result recovery |
| Foreign request/claim/Task/scope, corrupt digest or changed inventory | Fail closed, preserve original facts |
| Secret/link/binary/unauthorized/omitted ignored noncache source | Refuse, retain现场 |
| Exact operator PAUSE then explicit RESUME | New ordinary work claim/context/run; native QA/Review |
| Automatic authority, target override, reapply, RESUME execute, budget exhausted | Reject without new execution or refund |
| Historical optional field absent / exact operation replay | Original digests / idempotent single reservation |

Good: actual stopped execution, new exact engineering decision, same Task and complete draft.
Base: unknown cause remains unknown. Bad: classify lease expiry as provider timeout, resurrect
expired lease, manufacture Coder result or expand frozen interruption allowed_causes.

## Public signatures and implementation seams

`manager/baseline_production.py::BaselineProposeCommand` and
`web_console/models.py::ProposeExecutionBaselineIntent` accept the new purpose through the
existing `POST /api/v1/operations` endpoint. Console `/api/v1/console` reports
`operation_contract_version=10`; the browser must recheck that capability on retained controls.

| Intent action | Required exact input |
| --- | --- |
| `PROPOSE_EXECUTION_BASELINE` | `project_id`, `delivery_id`, `expected_checkpoint_sha256`, `task_id`, `expected_task_intent_sha256`, `expected_task_revision`, `expected_work_item_id`, `expected_source_revision`, `purpose=stopped_execution_rescue`, `input_mode=preserve_draft`; omit `target_base_ref` |
| `EXECUTE_EXECUTION_BASELINE` | Current Requirement checkpoint, original `task_id`, `expected_plan_sha256`, engineering `reference`, `continuation_mode=pause` |
| `RESUME_EXECUTION_BASELINE` | Current Requirement checkpoint, original Task intent/revision, paused WorkItem/source, latest `expected_execution_baseline_sha256`, `expected_disposition_sha256` and separate engineering `reference` |

`manager/stopped_execution_checkpoint.py::StoppedCoderExecutionProof` seals only original
invocation/start/stop facts. `ProductionBaselineFactCollector._stopped_execution` reopens their
full stores and checks the raw ArtifactStore, including artifacts without an accepted publication;
an accepted-only projection cannot prove absence. `ExecutionBaselineService.execute` repeats
the collector observation; `ProductionBaselineFactCollector.publish_completion` supplies
the final validation callback to the owner-fenced queue transaction. New input cannot be accepted
from the browser's claim that a process stopped.

`manager/knowledge_invocation_proof.py::ReplayGuardedClaimObservation` is the current
observation contract, exported as `schemas/replay-guarded-claim-observation.schema.json`.
Its `blocking_start_sha256` binds the earlier complete invocation start;
`lease_id`/`claim_sha256` bind the exact later historical claim. Nonempty
`intent_sha256s`, `outcome_sha256s`, `execution_record_sha256s` and `context_sha256s`
tuples bind the complete returned knowledge and independent execution/Context facts.
`observation_sha256` seals these fields with deterministic SHA-256; it does not add a
historical refusal event or event timestamp. `BaselineInvocationProof.replay_guarded_claims`
permits these observations only for `proof_kind=stopped_execution_without_outcome` or
`legacy_execution_contained`, rejects duplicate lease IDs and validates each digest.
The final new-consumption callback recomputes the full invocation/claim observation
set under the existing Task/queue fence and compares it with the sealed investigation.
Any late raw artifact, route, native execution or conflicting publication must reject
consumption before a successor reservation, while preserving the original workspace.

The binding and `BaselineQueueConsumption` carry `stopped_execution_sha256`; the reservation
uses `retry_cause=stopped_execution_unknown`. Unknown/foreign/stale inputs fail closed as the
existing typed baseline/queue errors, with no new execution, quota refund or source edits.
`EngineeringHumanActionRecorder.record` appends `evalevt_stopped_<binding-prefix>` referencing
the immutable operator authority. A replay must preserve one event and one work reservation.

## Required verification
Real native guard-abort tests, direct and fresh-generated nested Schema guards, proof/tamper
matrix, complete retained ignored source, paused service/queue replay, offline public original-Task
Coder/QA/Review DONE fixture. No production model call is a test substitute.
The public entry is
`tests/manager/test_stopped_execution_delivery.py::test_public_stopped_unknown_coder_pauses_then_independently_delivers_original_task`:
the `delivery` parameter covers exact PAUSE/RESUME through independent QA/Review to DONE;
`late-artifact` seals a raw original-Run artifact inside the final consumption callback
and verifies real validator rejection, zero consumption/new work/model calls, and unchanged
Task/events, earlier artifacts/history, draft, HEAD/branch and index. The negative case
retains the newly injected immutable fact and does not delete it to retry recovery.

## Existing data and rollback
K1 attempt4 has a valid owned-session-empty stop at 2026-10-15 15:57:37+08, output=false,
no outcome. Its original PROVIDER_ERROR/cause=null classification is retained, not reinterpreted.
The observed local sleep interval and lease expiry are supporting diagnostics only.
First call public `CONTINUE_DELIVERY` once with the current Requirement checkpoint. The ordinary
Dispatcher expires/reclaims only the stopped nonlive claim; `DurableInvocationControl.prepare`
finds the original start and absent outcome, forbids a second model call and publishes engineering
`WAITING_DEPENDENCY`. Fresh summary/detail facts supply the resulting Task revision, WorkItem and
exact Requirement checkpoint/disposition. No direct queue row edit is allowed.
After controlled deploy, public proposal → exact engineering PAUSE → separate RESUME recovers it
only if full current checks and remaining work pass. No DDL/direct SQL/historical result rewrite.
After consuming a new purpose, rollback must retain compatible readers and controlled pause;
an older runtime that cannot read the new purpose/binding must refuse. Retain new records/readers
and never delete draft input to make an old runtime accept it.
