# Exhausted start-only UNKNOWN Coder recovery

## Scope and signatures

This contract applies only to a locally executed Coder whose original Run has a genuine
invocation-start and capture-start, no outcome or capture-stop, no accepted result or
checkpoint, and exhausted frozen ordinary work budget. The original execution remains
UNKNOWN. A current local survey plus an ENGINEERING principal's exact declaration can
contain the old execution; neither is a fabricated historical stop.

- `DeliveryWaitInvestigation.local_stop_confirmation_available` is a read-only, positive
  capability. False is omitted from historical wire and digest. The collector derives true
  only while the Task lock is held and the original claim, Run, policy, start-only capture,
  source and full workspace inventory match the current waiting Task.
- `HandleDeliveryWait.confirm_local_execution_stopped=true` and `local_stop_reference`
  must occur together. The reference identifies a trusted human reply or engineering
  resolution. HANDLE seals the time, authorized ENGINEERING principal and complete declaration
  in the settlement. After the SQL commit it idempotently records
  `HumanActionEvent(SUPPLY_EVIDENCE)` in the evaluation store, referencing that immutable
  resolution artifact and exact old Run; replay repairs a missing event without duplicating
  the Task transition.
- `LocalStopConfirmation` and `ContainedUnknownBudgetSettlement` are immutable typed
  records, separate from `StoppedUnknownBudgetSettlement` v1. The settlement includes the
  original start, capture-start, claim, current containment, human declaration, full
  retained capture, pre-terminal Task/WorkItem/role step, terminal event and digests.
- `MySqlRoleQueue.settle_contained_unknown_budget` performs the exact Task and queue CAS
  under the Task lock and idle queue fence. Its event is
  `CONTAINED_UNKNOWN_BUDGET_SETTLED`; Task becomes `BLOCKED` and WorkItem becomes `CLOSED`.
  The old Run's outcome, stop and checkpoint remain absent; no budget is refunded.
- `RecoverySource.contained_unknown_settlement_sha256` is an omitted-when-None exact source
  discriminator, mutually exclusive with stopped-UNKNOWN and context-capacity sources.
  A new same-Requirement `RecoveryPlan` requires `input_mode=coder_reapply`, independently
  approved target revision and complete old patch. New Coder, QA and Reviewer claims are
  still required.

## Admission, ordering and audit

The public INSPECT path never writes a declaration or settles a Task. The public HANDLE
path accepts only an explicit current user declaration and reference. It reopens the
complete original start/claim/capture, verifies no later outcome, stop, receipt, artifact,
route or writer, and performs a fresh bounded local execution survey. The service must
seal full current draft bytes and validate both Git and ignored legal files before SQL
consumption. It must reject any incomplete, changed, unsafe or out-of-scope inventory.

Write the human declaration and immutable settlement/capture before the SQL CAS, then
verify a replay against the terminal reducer, closed WorkItem, original unknown facts and
current complete source. Publish the investigation into `delivery-waits/wait-investigations`
before its handling so complete Team history can read it. A sealed exact replay may repair
an omitted read-only reference, but it cannot create another event, debit or result. HANDLE
returns `BUDGET_EXHAUSTED` without proposing a successor in the same Console Operation;
a new public Continue prepares the separately approvable plan.

The Console advertises operation contract version 12 for this new HANDLE request. It shows
the local-stop form only when version 12 or later and the current matching investigation has
`local_stop_confirmation_available=true`, the Coder WorkItem is an engineering wait and
the exact start-only/exhausted missing set is present. It requires a fresh user checkbox
and nonempty trusted reference; polling never pre-fills or submits either. On click it
rechecks the current proof SHA, original Run ID, WorkItem/disposition/checkpoint binding,
capability and control readiness before POST. A prior `PLATFORM_ATTENTION` must not show
a competing generic HANDLE button. A `BUDGET_EXHAUSTED` handling suppresses the form
and duplicate-submit guidance even if a temporarily stale WAITING projection remains.
UI display and client checks are not server authorization.

The retained Run-local capture is relative to the final Coder Run's input HEAD. A separate
Task-base-to-current capture includes every earlier accepted Coder commit and any final
dirty file. Recovery proposal, approval and dispatch independently compare the Run-local
capture to the settlement and the full capture to the current source. In K1, the final
Run-local patch may be empty while the complete Task-base patch contains earlier commits;
the successor must receive the complete patch. No source refresh, scope expansion or
protected-path write is inferred from this containment.

### Historical candidate after QA feedback

A terminal Delivery may still project the last accepted `candidate_revision` after QA FAIL or
Review REJECT returned work to Coder. That revision is historical input to the later Coder,
not a current candidate ready for another QA/Review. When the current checkpoint has the
exact contained-UNKNOWN budget summary, `DeliveryResumeController.resume` must route to
Coder recovery before its generic terminal-candidate verification branch. The exact source
reader may accept a historical candidate only after it verifies the immutable
settlement, current blocked Task and full event chain: a non-null projected candidate equals
the latest `candidate_ready`/`candidate_recovered` event; an omitted projection is allowed
when that event stream itself proves the candidate. A sealed QA FAIL or Review REJECT
returns to Coder, and that later Coder ends in the settled `BLOCKED` event. The existing
`NativeRecoverySourceReader._sql` post-feedback candidate guard and current capture/claim/
source checks remain mandatory; a candidate with no later Coder interruption still goes
through independent candidate verification. A forged or mismatched candidate is refused.
The feedback event must reference exactly one sealed verifier artifact of the correct type,
verdict, Task and candidate SHA, with the candidate implementation as parent (or the
accepted QA PASS as the rejected Review's parent); producer roles and Agents remain
independent. A bare event reason is insufficient.
An accepted QA or Review report may supersede an earlier same-role report, including from
an earlier candidate. Follow the sealed `supersedes` chain with a finite bound and reject
cycles, foreign Task/role, repeated Run and broken historical parent lineage. The current
feedback still binds the latest historical candidate and exact accepted parent. Requiring
`supersedes=null` would reject legitimate same-candidate verification retries.

The affected signatures are `DeliveryResumeController.resume(ResumeProjectDelivery)`,
`ContainedUnknownRecoverySourceReader.discover(RecoveryScope)`, and
`NativeRecoverySourceReader._sql(checkpoint, history, ...)`. The trigger binds the current
child `ProjectDeliveryCheckpoint.failure_summary`, `candidate_revision`, `task_id` and
`task_revision` to the settlement's terminal Task/event. Merely seeing a non-null
`candidate_revision` never grants verification or recovery authority. The public command
remains `CONTINUE_DELIVERY` against the joint parent's exact checkpoint digest; no API or
Schema field changes.

The old QA verdict, candidate and UNKNOWN Run remain immutable. The new plan must carry
the complete Task-base patch and verification feedback into `coder_reapply`; approval and
new independent Coder, QA and Reviewer claims remain separate. A parent joint Requirement
may need one public Continue to observe the newly blocked child and a subsequent Continue
with the new parent checkpoint to propose this plan; each Operation has its own key.

Good: the latest candidate event equals the non-null projected revision, QA FAIL routes to Coder,
and that Coder's start-only UNKNOWN settles; the second public Continue yields a distinct
approvable Coder recovery plan. Base: a terminal candidate with no later Coder interruption
continues to independent verification; a null projection with verified event lineage remains
eligible for the same Coder recovery. Bad: a stale or forged candidate revision, absent/foreign
verifier artifact, invalid verdict, cyclic/foreign supersedes chain, missing feedback
transition, or a different settlement must
fail before plan publication.
Wrong: `if checkpoint.candidate_revision: verify_candidate()` before checking the exact
settled later Coder. Correct: classify the current settled Coder source first, then use
the candidate event only as verified historical lineage.

Required regression coverage exercises the public parent Continue after a real settled
post-feedback child, checks the plan's source settlement digest, historical candidate,
complete Task-base patch and unchanged old Task/Run/verdict bytes, and rejects candidate
drift, missing feedback, foreign/invalid verifier artifact or verdict without a new plan or
provider call. Pure source/router tests
supplement this full-chain test; they cannot replace it.

The `contained-unknown-budget-{settlements,captures,handlings}` groups, their exact storage
keys and ownership are part of physical Requirement deletion. The deletion verifier must
reject a record with a foreign Task/Requirement, invalid digest, mismatched handling key or
missing settlement. Historical stopped-UNKNOWN v1 records and schemas retain their bytes.

## Validation matrix

| Input | Result |
| --- | --- |
| Exact start-only local Coder, exhausted budget, complete lawful draft, explicit ENGINEERING declaration | One terminal `BLOCKED` settlement, old Run UNKNOWN, same-Requirement recovery proposal available through a later Continue |
| Valid original capture-stop exists | Use the existing stopped-UNKNOWN path; never classify as start-only |
| Budget remains or current claim/writer exists | Refuse terminal settlement; retain original Task and wait |
| Outcome, route, accepted artifact, receipt, stop or checkpoint appears late | Refuse and preserve those original facts |
| Missing or mismatched original start/claim/capture, policy, source, inventory or local survey | Refuse without SQL consumption or new authority |
| Declaration omitted, reference omitted or principal lacks ENGINEERING duty | Refuse; GET/UI cannot supply it implicitly |
| Exact replay after crash or SQL commit | Verify current facts and return the original settlement; do not append another event |
| Earlier committed code and empty final Run-local patch | Keep the full Task-base patch for Coder reapply |
| Historical candidate, QA FAIL/Review REJECT, then settled UNKNOWN Coder | Route to exact Coder recovery; verify candidate/event lineage and preserve complete patch and feedback |
| Candidate has no later Coder failure, or projected revision differs from event | Keep candidate verification or reject mismatched source; no Coder recovery authority |
| New plan lacks exact approval or independent QA/Review | Do not dispatch or mark DONE |

Good: a current human declaration closes only the exhausted old work and an exact successor
reapplies all retained code under a new approval. Base: older stopped-UNKNOWN v1 and normal
legacy start-only with remaining budget keep their original route and wire. Bad: invent a
capture-stop, refund attempt 11, mutate the old verdict, accept only the empty final patch,
or perform recovery in the same HANDLE Operation.

Browser interaction verification uses an isolated test host. The Playwright fixture must
refuse to launch any installed macOS system browser channel on an interactive workstation by default;
only `ASE_UI_ALLOW_SYSTEM_CHROME=1` permits an explicit isolated-host run. This guard runs
before `chromium.launch`, reports a test failure rather than a false PASS, and has a pure
Node regression. JS syntax and DOM-source checks do not replace real browser verification.

## Existing K1 and rollback

K1's last Coder Run has start and capture-start without outcome/stop/checkpoint. A separate
trusted user reply confirms same machine/account, no remote execution, all derived tools
ended and no future old-workspace writer; the reference is recorded only through public
HANDLE after this contract is released and a fresh read-only investigation allows it.
No direct SQL edit or new Requirement is needed. The old Task must become `BLOCKED` with
UNKNOWN history preserved before a new exact recovery plan is reviewed and approved.

K1's post-feedback Task retains an earlier candidate in its Delivery cursor. An initial
public Continue after settlement synchronized the parent to `BLOCKED`; the next Continue
was rejected by the generic candidate gate before any plan or Task was created. After this
route fix, submit a fresh public Continue against the current parent checkpoint. The failed
Operation remains in history. No database rewrite or replacement Requirement is required.

Before SQL consumption, rollback the maintenance release at an idle service boundary.
After consumption, retain compatible readers or deploy a forward repair; reverting to a
binary that cannot read the new settlement is not a safe way to erase it. Capture, audit,
Task and queue records must remain available for exact replay and physical deletion.
