# First main Coder seed admission

## Scope and failure mode

Knowledge preparation runs before the main role invocation. A preparation failure advances the
execution identity/attempt without starting the main Coder. Consequently `attempt > 1` cannot
prove that an approved recovery seed was admitted. A clean seed could otherwise bypass current
approval validation; a dirty approved seed could be rejected by the ordinary clean-input gate.

`DeliveryInvocationStart` records the exact claimed main role boundary before adapter admission.
It does not prove that a provider subprocess started. A completed model-route list likewise
does not include a still-running main call. Do not infer Popen start/stop from either fact.

## Signatures and composition

```python
RequestWorkspaceAdmission.for_request(request: AgentRequest) -> InitialWorkspaceAdmission | None
workspace_admission_for_request(admission, request) -> InitialWorkspaceAdmission | None
authorize_workspace_admission(admission, request, workspace_root) -> None
ClaimedRecoveryInvocationHistory.prior_main_outcomes(request) -> tuple[DeliveryInvocationOutcome, ...]
ClaimedRecoveryInvocationHistory.has_accepted_input(request, outcomes) -> bool
RecoverySeedService.for_request(request) -> InitialWorkspaceAdmission | None
RecoverySeedService.authorize(request, workspace_root) -> None
RecoveryInterruptionService.for_request(request) -> InitialWorkspaceAdmission | None
```

`FirstCoderRunWorkspaceAdmission` delegates selection to the typed request-scoped port. A delegate
without this port stays authoritative on every call. Neither adapter lifetime nor attempt number
silently disables it. Same-Task baseline admission remains authoritative on every run.

The production Supervisor already binds the actual `WorkerExecutionGuard` for the entire claimed
runtime call. Recovery history uses that typed guard (or an explicitly supplied trusted guard),
never a model-supplied claim or a mutable first-call flag. An unbound/missing/lost Worker rejects.
No extra factory or backend execution path is introduced.

## Admission rejection and control signals

Selection and authorization occur before any provider call. `WorkspaceAdmissionRejected`
is an `InterruptionAdmissionRejected` port error, mapped by both Codex and Responses to
`WORK_INTERRUPTED`, `transient=false`, with the fixed Chinese explanation that no model was
called and the workspace is preserved. A gate `ValueError` is never reported as invalid model
output; corrupt/missing trusted records and rejected recovery facts use the same typed gate.
`RecoveryWorkspaceAdmissionRejected` also remains a `RecoveryRejected` for direct domain callers.

`reject_invalid_admission` converts only enumerated validation/storage/policy errors. It first
preserves the exact `ContinuationExecutionUncertain`, `DeliveryQueuePending` (including
`QueueLeaseLost` and `DeliveryWaiting`) and `KnowledgeGapRaised` objects. Unexpected runtime bugs
also propagate; no broad `except Exception` turns ownership loss or a pending decision into an
Agent result. The shared adapter helper converts only `ValueError`; recovery services own their
specific trusted-error conversion. Neither transient fallback nor a later provider may run after
any rejected/uncertain admission.

## Durable input contracts

1. Read only queue items indexed by this exact Task. For each Coder item, read its exact invocation
   start/outcome key. Do not scan repository-wide invocation files.
2. Verify queue admission Task/Repository/allocation and each immutable step Task/work/role/attempt/
   checkpoint/source. Resolve the original source with `step_for_invocation`, preserving baseline
   epochs rather than comparing every historical run with the latest source.
3. Load `original_claim(start.lease_id)` from the immutable CLAIMED event. Bind Task, Repository,
   WorkItem, role, execution identity and checkpoint, and explicitly require the returned
   `claim.lease.id == start.lease_id`. A lookup key or assignment for another run is insufficient.
4. The current start must equal the complete current request and claimed lease. Exclude only that
   exact start from prior consumption. Missing/current-completed/mismatched starts reject.
5. A prior start without a validated matching outcome is uncertain. Preserve it, refuse replay and
   never backfill recovery admission. A knowledge-only prior item with neither start nor outcome
   does not consume the seed gate.
6. Before the first main provider call, revalidate exact plan, dispatch/sealed Task, seed capture,
   Context Task/role/source/**actual request attempt**, permissions and workspace. Publish the
   immutable recovery invocation under the real Worker write fence, rechecking history there.
7. Once the original seed has a matching definitive main outcome, subsequent runs use normal
   source/accepted-progress/candidate checks. They do not reapply or republish the original seed.

## Legacy results and replacement admission

A missing old recovery invocation receipt is not repaired by inventing one. A later accepted
progress/candidate may use ordinary input checks only when its main outcome, original claim,
accepted publication and stored artifact agree on Task, run, Context, work, lease, checkpoint,
dispatch generation, artifact identity and digest. The current request must explicitly reference
that progress/candidate and its source. Unaccepted output or a filesystem artifact alone is
insufficient; retired rejected publications remain excluded by `AcceptedArtifactStore`.

The old separately approved replacement path also uses the request-scoped port. A missing replacement
receipt still requires its original authorization gate. After a replacement finishes, only the
exact replacement request/lease/work from its receipt and interruption plan, together with a
matching main outcome and accepted input, permits ordinary progress or QA/Review remediation.
An original unknown start at the same key is not a replacement result. Never overwrite it.

The newer `NativeCoderContinuation.prepare` remains the first adapter input gate. A valid one-use
continuation can rely on its original claimed start, real stop/session proof, complete preserved
inventory and current authorization without inventing a historical seed receipt. This task does
not change that contract, refund budget, reset Tasks, approve scope or bypass QA/Review.

## Validation matrix and executable points

| Input | Required result | Tests |
|---|---|---|
| Knowledge-only attempt 1, first main at attempt 2 | Revalidate seed and publish real admission | `test_first_real_seed_admission.py` |
| Same case, authority/context/source/claim drift | No seed receipt or provider call | new seed tests + `test_first_real_coder_admission.py` clean/dirty Codex/Responses |
| Current start exists, no prior main | Current start does not falsely consume seed | seed tests |
| Same-work valid claim returned under wrong lease key | Reject before consuming seed or accepting legacy input | `test_original_claim_returned_under_foreign_lease_key_is_rejected` |
| Prior main start has no outcome | Refuse replay/backfill with typed uncertainty | seed tests + existing invocation journal tests |
| Fresh adapters after accepted progress/candidate | Ordinary input checks; same durable facts | seed tests + initial-admission/failure/fallback tests |
| Legacy missing seed receipt, exact accepted input | Ordinary gate, old receipt remains absent | seed tests |
| Legacy missing receipt, unaccepted output | Refuse; preserve history | seed tests |
| Replacement exact completed progress/candidate | No repeated one-use replacement admission | replacement-selector tests |
| Replacement output lacks accepted publication | Refuse | replacement-selector tests |
| Seed selection/authorization rejects before provider | Chinese WORK_INTERRUPTED, nontransient, zero provider calls | `test_first_real_coder_admission.py`, both providers and both phases |
| Claim lost, unknown stop, queue/knowledge wait, unexpected runtime bug | Original signal propagates, zero provider calls | same parameterized adapter tests |
| Offline native recovery | Real Git/claim/Context/seed and independent QA/Review | selected `test_execution.py`/`test_interruption_native.py` integration tests |

No wire schema or durable migration changes. Validation remains incremental. Full regression belongs
to the user-requested release check; do not run it for this localized repair.

## Existing-data treatment and rollback

For current K1 `task_recovery_45588301d1b35b02f44762650b6195e4`, the recorded attempt-2 main
`run_e197336456dc4dd683e2245194ad6fcc` has a genuine matching FAILED/WORK_INTERRUPTED outcome.
Its exact native capture stop is `local_execution_limit`, 2026-10-12T03:47:08.182689Z, with a
verified owned-session proof (`f5af03c8f185e5a4ae2738bb6f902ac16af1fb8134e31a4a05ef7478522200ea`).
The missing old recovery invocation remains missing. Its already authorized native continuation
preserves the same Task and workspace; attempt 3 reached preparation and then waited for the
separate input-capacity issue before any main model start. Do not restart or replace that Task to
apply this repair. After the capacity issue is handled through its exact public path, fresh current
claim/stop/inventory checks remain required; any later accepted candidate still needs independent
QA/Review at the same SHA. This code task did not mutate production facts or approve delivery.

Rollback is reverting this code commit before a new execution. No record needs rewriting; retain
all receipts created by the fixed version, which use the unchanged schema. Rolling back does not
authorize replay of an already admitted invocation.
