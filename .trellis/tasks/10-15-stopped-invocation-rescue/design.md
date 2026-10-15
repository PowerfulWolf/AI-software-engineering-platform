# Stopped Coder outcome-gap recovery design

## Scope / trigger

A local Coder can lose its owner authority before final result publication. The trusted native
runner may still finish stopping its owned session and seal a valid `ExecutionCaptureStop`.
The current K1 has that stop fact, no output/outcome/checkpoint, and an unknown historical cause.
The old interruption path requires a known cause; legacy rescue requires the original stop to be
missing. Neither route can honestly accept this state.

Keep the original Requirement, Task, frozen intent/permissions, branch and complete legal draft.
Add a separate engineering disposition; do not change old failure classifications, reconstruct
results, revive an expired lease, create a duplicate Task or grant a new model retry allowance.

## Signatures

```python
TeamHost.propose_execution_baseline(
    command: BaselineProposeCommand, *, project_id: str
) -> ExecutionBaselinePlan
TeamHost.execute_execution_baseline(
    command: BaselineExecuteCommand, *, project_id: str
) -> ExecutionBaselineBinding
TeamHost.continue_execution_baseline(
    command: BaselineContinueCommand, *, project_id: str,
    require_existing_authorization: bool = False,
) -> DeliveryResumeResult | JointDeliveryResult | ProjectDeliveryResult
```

All three public commands require an operator with `ENGINEERING` duty. Console contract 9 wraps
them in `POST /api/v1/operations` intents, adding exact `project_id`, `delivery_id` and
`expected_checkpoint_sha256`. Polling or preparing an Operation supplies no approval.

| Action | Required recovery fields |
| --- | --- |
| `PROPOSE_EXECUTION_BASELINE` | `purpose=stopped_execution_rescue`, `input_mode=preserve_draft`, original `task_id`, `expected_task_intent_sha256`, `expected_task_revision`, `expected_work_item_id`, `expected_source_revision`; omit `target_base_ref` |
| `EXECUTE_EXECUTION_BASELINE` | original `task_id`, exact `expected_plan_sha256`, human `reference`, `continuation_mode=pause` |
| `RESUME_EXECUTION_BASELINE` | original `task_id`, current intent/revision/WorkItem/source, latest `expected_execution_baseline_sha256`, exact paused `expected_disposition_sha256`, separate human `reference` |

Do not supply the legacy boot/local-stop declarations or provider-prerequisite repair confirmation
for this purpose. The service fixes the target to the currently effective execution base.
`coder_reapply`, source/native-rule changes and immediate RESUME on execution are rejected.

## Trusted proof and data flow

`WorkerLease.check()` can raise `QueueLeaseLost` with `ExecutionAbortReason` containing only
`kind=lease_authority_unconfirmed` and optional `detail=local_expiry|renewal_exception|heartbeat_stop_timeout`.
The native observer seals that bounded reason with the actual stop before rethrowing lost authority.
It cannot publish/cache an `AgentResult` through the old owner fence. Existing optional-field-absent
wire bytes and digests remain unchanged; no exception text, PID inference or lease expiry itself
becomes a stop proof or provider cause.

`ProductionBaselineFactCollector._stopped_execution(task, item, step)` builds
`StoppedCoderExecutionProof(kind=stopped_coder_execution_without_outcome)` from exact immutable
`DeliveryInvocationStart`, `ExecutionCaptureStart` and `ExecutionCaptureStop`. The proof requires:

- A real historical Coder claim and exact request, Task revision, native scope and dispatch identity.
- `process_stop.kind=failed`, a nonzero return code and complete `owned_session_empty` session proof;
  the trusted collector independently rechecks actual session cessation.
- `cause=null`, `output_present=false`, no original final route/outcome/receipt or adopted output.
- Complete legal source bodies, stable before/after inventories and unchanged HEAD/index/branch.
  Only immutable previously authorized retained source paths may supplement ordinary inventory;
  arbitrary ignored files do not gain write authority.

Proposal bypasses the old interruption-receipt reconciliation route. It directly validates the
stopped proof, because unknown cause must remain unknown. Read-only current-session/queue checks
refuse live claims, active sessions or unverifiable stop observations.

An ordinary continuation can legitimately reclaim the same WorkItem, finish read-only knowledge
preparation and then encounter the existing write-once unknown invocation. Such a claim is neither
a failed knowledge call nor an original main-model invocation. The collector forms a current
`ReplayGuardedClaimObservation` instead of inventing a historical replay-refusal event. It binds
the extra `lease_id`, immutable claim identity, exact earlier `blocking_start_sha256`, complete
`RETURNED` knowledge intent/outcome/execution-record digests, complete original Context digests
and its own `observation_sha256`. The unique earlier start must belong to the same
WorkItem/role/attempt/checkpoint/source, precede the extra claim in both time and dispatch generation,
and remain without outcome. Its independently contained original execution remains mandatory.

`CapacityInputReader.require_claim_not_started(..., prior_invocation_fence=PriorInvocationFence)`
allows only that exact verified earlier start/capture while checking the reclaimed claim. Complete
current native/route/raw-artifact/receipt scans must reveal no new main invocation attributable to
that claim, and all knowledge executions must have genuinely ended. Missing knowledge outcomes,
foreign Context, new raw artifacts/native captures or any ambiguous ownership refuse. This is a
present engineering deduction from the mandatory write-once call fence; it does not assert that
`prepare()` was historically reached or write a backdated refusal. The same observation family
handles both existing and future reclaimed claims without rewriting old records.

The data flow is original Task/start/capture/claim → trusted proof and complete patch → exact
operator plan authority → paused baseline binding/queue consumption → separate continuation
authority/release → fresh native claim/Context/Run → same-candidate independent QA and Review.

## Persistence, accounting and replay

Reuse append-only `state/execution-baselines/<task_id>` plans, authorities, operation starts,
bindings and continuations. `facts.stopped_execution`, reservation/binding
`stopped_execution_sha256` and `retry_cause=stopped_execution_unknown` bind the exact proof.
The MySQL `work_queue_execution_baselines` transaction retains the old WorkItem and reserves one
distinct next ordinary work attempt in `WAITING_HUMAN`; no DDL, provider retry failure or refund.
Task delivery status remains its existing checkpoint.

`BaselineQueueConsumption` checks exact plan/binding/proof, different next WorkItem and unchanged
input. Queue consumption and authority publication replay without duplicate reservations.
The subsequent `BaselineContinueAuthorization` and `BaselineQueueRelease` bind the latest paused
binding/disposition and complete inventory; release uses the already reserved attempt. Generic
Continue cannot release an `EXECUTION_BASELINE_PAUSED` hold.

`EngineeringHumanActionRecorder` appends `evalevt_stopped_<binding-prefix>` with
`HumanAction.SUPPLY_EVIDENCE` and the immutable authority URI to the original evaluation case.
The deterministic event identity makes replay idempotent. ADR recomputation must retain
`HUMAN_INTERVENTION`. Historical invocation traversal accepts this proof while still showing the
original outcome and interruption receipt absent; fresh Coder/QA/Review require actual outcomes.
`BaselineInvocationProof.replay_guarded_claims` binds each current reclaimed-claim observation to
that original start. Complete quiescence-record hashing and repeated collection revalidate its
claim/knowledge/Context/negative-scan facts; sorted exact digests avoid a volatile observation
timestamp changing the approved facts on every read.

## Validation / error matrix

| Input or state | Result |
| --- | --- |
| Exact stopped no-output unknown Coder and legal stable draft | Prepare a same-base engineering plan |
| Missing/foreign/corrupt capture, output/outcome/receipt now present | Refuse before source or queue effects |
| Missing session proof, live lease/session, fresh cessation recheck fails | Preserve现场 and wait for engineering |
| Extra claim with full RETURNED preparation behind exact earlier unknown invocation | Current replay-guarded observation; no historical refusal is added |
| Extra claim missing preparation outcome/Context or carrying new native/route/raw-artifact/receipt facts | Refuse; successful knowledge alone cannot prove no main call |
| Secret, binary, link, protected or omitted noncache source | Refuse complete capture; never delete files to pass |
| Automatic engineering admission or wrong confirmation family | Refuse; human exact plan authority required |
| Target override, reapply, native-rule change or immediate execute RESUME | Refuse; keep original scope and source |
| Remaining ordinary work exhausted | Refuse; no transient refund or Task reset |
| Valid exact PAUSE followed by latest-bound RESUME | Reserve once, separately release, native delivery |
| Stale binding/disposition/checkpoint/Project or duplicate operation | Reject stale inputs or replay exact immutable decision |

## Verification and rollback

Use the real native guard-abort regression, typed proof/tamper and schema matrices, isolated-MySQL
service/queue tests, and the public Console fixture through original-Task DONE. The fixture uses
offline scripted models, real local processes/Git/claims, distinct Coder/QA/Reviewer identities
and candidate-bound evidence. Browser tests cover contract 9, exact matching, stale/disconnected
approval refusal and the separate continue action. Actual run results belong in
[verification](verification.md), not assumptions in this design.

Good: seal a real stop and approve complete retained input as a new ordinary attempt.
Base: local sleep is supporting diagnosis; the historical outcome/cause stays unknown.
Bad: invent a timeout or original checkpoint, infer stop from PID absence, refund work or widen scope.

Rollback requires controlled pause/drain and compatible readers for all newly sealed records.
Do not delete bindings/audit/drafts, edit old capture bytes or restart an obsolete runtime that
cannot validate the appended purpose. Production recovery uses only public proposal → PAUSE → RESUME.
