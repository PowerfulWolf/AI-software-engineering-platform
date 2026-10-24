# Same-Task execution baseline contract

## Unaccepted committed candidate recovery (2026-10-25)

### Historical candidate capture compatibility

Mutation capture keeps the existing one-megabyte per-file and patch limits, but
the aggregate body budget is four megabytes because each changed file can carry
both a base body and a current body. The earlier two-megabyte aggregate bound
could reject a clean, already committed multi-file candidate during a later
read-only recovery proposal even though its original sealed patch and every
file were individually within policy. Recovery must still reject binary,
oversized, secret-bearing, ignored non-cache, or changing files. JavaScript and
TypeScript source inspection recognizes only the small allowlisted local string
parser call shape (`token` from `detail`/`metadata`/`value`/`text` helpers);
unknown expressions and secret-producing namespaces remain conservative.

Regression points: `tests/context/test_source_secret_detection.py` covers the
false-positive parser variable and secret-producing negative case, while the
real candidate capture must re-read the exact 37-file K1 diff with both
`include_ignored=False` and `True` before the public plan is accepted.

### Scope / Trigger

Use only for an original completed `SUCCEEDED` Coder invocation whose
`implementation-report` was rejected for an unsupported artifact version after
a real clean candidate was committed. This is distinct from an accepted candidate,
a failed output, rejected progress or an unknown execution. Full contracts also
appear in `delivery-recovery.md` under rejected successful candidate report rescue.

### Signatures

`BaselineProposeCommand(purpose="rejected_candidate_rescue", target_base_ref=None,
input_mode="preserve_draft", expected_task_revision=..., expected_work_item_id=...,
expected_source_revision=...)` is target-free. The trusted collector derives
candidate, single parent, original claim, true owned stop and full patch.

`require_rejected_candidate_binding(plan, binding)` checks task/intent/base/branch,
scope, predecessor/sequence, original worktree, complete source artifact IDs,
resolved interruption receipts, previous task revision, superseded progress,
native-rule epoch, unchanged inventory, candidate/base and exact plan/facts.
Rehashing a contradictory binding grants no authority.

`BaselineInitialWorkspaceAdmission.retained_candidate_report_base(request,
workspace_root, artifact) -> str` returns the original execution base only after
reopening the latest trusted binding, actual SQL consumption and the current real
Coder claim. It rechecks the complete original-base candidate diff and bounded
unfiltered inventory. Ordinary Coder runs still require a new candidate commit.

`ProductionProjectDeliveryBackend.rejected_candidate_reentry_scope(checkpoint)
-> ContextManager[RejectedCandidateReentryProof | None]` seals current rescue facts
under the real Task process lock and unchanged idle queue fence.
`UnifiedProjectEntryService.retry_rejected_candidate_baseline(command, *, proof_scope)`
appends the missing Delivery cursor only for this exact public recovery route.

### Contracts

- Original Task/base, approved product/native rules, branch and immutable outcomes
  remain unchanged. Only append-only execution source advances to the existing
  candidate; no Git reset, rebase, reapply, new artificial commit or report rewrite.
- Exact ENGINEERING approval must PAUSE. Consumption closes the original work item
  and reserves one normal-work successor. A separate exact latest-bound RESUME is
  needed before a fresh claim/Run/Context; no transient refund or repeated debit.
- A rejected report can leave its child Delivery `BLOCKED/FAILED` while its original
  Task remains `IMPLEMENTING`. The public resume controller first checks the narrow
  rejected-candidate seam before the legacy stopped-execution route. It is never a
  generic terminal Task retry: Task `BLOCKED/FAILED/DONE`, accepted candidates,
  unrelated failures and mixed approval/recovery commands remain ineligible.
- A read-only latest-purpose check precedes all Task/queue fences. An absent or
  non-rescue latest binding returns no proof and preserves the existing route even
  when that route still owns an ACTIVE claim. The rescue path then rereads complete
  bindings under its lock and unchanged idle fence; this preflight grants no authority.
- `RejectedCandidateReentryProof` binds exact checkpoint digest, Task/revision,
  requirement/dispatch/repository, original parent WorkItem, next attempt and unchanged
  retry history, complete plan/binding and current successor. A still-paused successor
  returns an explicit continue diagnostic without appending a cursor or calling a model.
  Only the unique READY, unclaimed successor with its committed exact engineering
  release may append `DELIVERING`. Changed cursor/source/inventory or old release refuses.
- The cursor append occurs while Task/SQL proof fences are held. Both fences must be
  released before ordinary `resume()` invokes Supervisor admission/claim; fresh Coder,
  QA and Reviewer retain independent claims and artifact lineage.
- `idle_task_scope` continues to reject every ACTIVE claim. The specialized typed
  expired-owner settlement is possible only under the actual Task process lock,
  queue authority and locked Task/claim rows, with two complete current stop/proof
  readings. Initial immutable claim expiry and real renewed lease expiry are
  separate facts. Expiry alone does not prove stop. Settlement preserves the
  WorkItem, dispatch, Task and budget and appends its own immutable audit record.
- `WorkerExecutionGuard.check_task_scope(task_id)` checks the exact private held
  descriptor, visible path, task identity and inode. It grants no Worker execution
  authority; ordinary `check()` still requires a live Worker lease.
- Allowed report-only inventory differences are explicit bounded execution caches,
  each a regular file with mode 0644 or 0755. Symlinks, special permissions, source,
  index or full candidate changes refuse. SHA agreement does not replace these gates.

### Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Exact unsupported completed success, clean lawful candidate, true stop | Prepare target-free plan |
| Valid live claim, wrong task lock, missing stop, dirty candidate or publication | Refuse; preserve original facts |
| Renewed then actually expired original lease | Compare original snapshot with actual renewed lease, then audited settlement |
| Rehashed foreign scope/source/receipt/worktree/revision/predecessor | Refuse binding read and consumption |
| PAUSE consumed, no separate RESUME | Work item remains unclaimable |
| BLOCKED child, still-paused exact rescue successor | Diagnostic only; same child checkpoint and no model call |
| BLOCKED child, unique released unclaimed successor, Task still IMPLEMENTING | Append DELIVERING under proof fences, release fences, ordinary Supervisor |
| Non-rescue latest baseline with an ACTIVE old claim | No rescue proof; preserve original recovery route and strict idle policy |
| Terminal Task, foreign/old release, changed checkpoint or inventory | Refuse; no cursor append or dispatch |
| Unique consumed latest binding plus fresh current Coder claim | Revalidate full candidate before accepting a newly compliant report |
| Ordinary no-change Coder output | Reject unchanged |

### Good / Base / Bad Cases

Console protocol 11 uses `engineeringRejectedCandidatePauses(request)` to keep the
separate RESUME visible when the native Delivery still projects its historical
terminal failure. A successful exact EXECUTE result must contain the same typed
rejected-candidate PAUSE binding referenced by the current Coder
`EXECUTION_BASELINE_PAUSED` work item. Project/team/root, Task intent/revision,
source, plan/binding/disposition and unchanged inventory must agree. The click
handler reopens those current facts and capability/control gates. It never opens
the ordinary terminal recovery families or infers authority from lease expiry.
`rejected-candidate-rescue.test.cjs` checks stale clicks and binding/scope/wait drift.

Good: original base A and clean candidate B remain, a stopped old owner is audited,
one normal-work attempt is approved and separately resumed, then independent
QA/Review judge the fresh report. Base: no new proof fields means historical wire
hashes remain unchanged. Bad: fix the old JSON version, infer stop from a stale
heartbeat, restore an old claim or use a proposal as report-only permission.

### Tests Required / Wrong vs Correct

`test_rejected_candidate_baseline_service.py` uses actual Git and owned stop facts,
checks complete before/after preservation and rehashed cross-record rejection.
`test_rejected_candidate_baseline_mysql.py` checks real claim renewal, specialized
expiry, rollback, strict idle, single debit and PAUSE idempotence.
`test_rejected_candidate_admission_mysql.py` consumes, separately releases, dispatches
and starts a real new Worker before invoking the real admission checker; a stale
binding or changed source refuses. Adapter tests preserve ordinary no-change refusal.
`test_rejected_candidate_reentry.py` checks controller precedence, released/paused proof
gates, foreign Task/revision/dispatch/claim, changed cursor, mixed commands, terminal
Task refusal and non-rescue ACTIVE route preservation. Public
`test_public_rejected_candidate_recovery.py` covers both `pending_child` and
`blocked_child` with real Git/native stop/MySQL claims through exact PAUSE and separate
RESUME to fresh Coder, independent QA/Review and DONE, retaining original history.

Wrong: bypass the idle check because `expires_at < now` or require the maintenance
collector to invent a Worker lease. Correct: verify a real Task lock and exact stopped
execution in the narrow audited settlement, then enter the unchanged idle fence.

## Claimed final-input capacity and same-Task PAUSE/RESUME (2026-10-12)

`BaselineExecutionFacts.context_capacity_receipt_sha256: Sha256 | None` is an additive,
absent-by-default digest. `BaselineInvocationProof.proof_kind=claimed_context_capacity` retains
every exact historical capacity receipt without fabricating an invocation or native stop.
`ProductionBaselineFactCollector` reads the complete sealed final-input Context, immutable
original claim and historical queue step, original Task intent and source, and the full latest
baseline authorized before that claim. Prior bindings are read and validated in full; a later
binding cannot replace the original Run input. Original preflight READY remains READY.

The no-start check rejects any exact Run invocation/outcome, provider route, accepted artifact,
native capture-start/stop, receipt or admission. Corrupt/orphan native records and inaccessible,
symlink or non-directory ledger roots fail closed; absence is never inferred from unreadable
records. Historical lease expiry is not a stop proof and cannot serve as an observation upper
bound because heartbeats renew the live lease without rewriting the original immutable claim.

The current queue disposition must reference the unique latest receipt for its actual dispatch
sequence and exact Task snapshot/revision/source. Public `propose_execution_baseline` then uses
the existing source-rebind plan with a different trusted target source, full draft/inventory and
native rules. Capacity facts require an already-applied `uninvoked` work reservation with the
same Task attempt. Public execute requires exact PAUSE; ordinary explicit continue rechecks the
latest complete binding and releases only that held work generation. The new dispatch has a new
claim, Context and Run, no refund or attempt increment. Independent QA/Review remain mandatory.

| Facts / command | Expected result |
| --- | --- |
| Exact Coder no-start receipt and complete Context/claim/source/baseline | Original Task plan; PAUSE before explicit RESUME |
| One or repeated capacity waits, each followed by a different approved target source | Same Task/attempt/branch; new claim/Run per resume; immutable prior receipts |
| Missing/foreign/re-sealed receipt, missing Context or conflicting invocation/native record | Refuse; unchanged Task/events/queue/workspace/history |
| Immediate RESUME execute or another recovery proof mixed with capacity | Refuse before queue/source mutation |
| Old Facts/proof without new optional digests | Original serialized bytes and digests unchanged |

Good: preserve the original capacity receipt and lawful draft, inspect an exact target-source
plan, approve PAUSE and explicitly continue the held generation. Base: historical preflight or
real stopped invocation proofs retain their prior behavior. Bad: relabel READY preparation as
WAIT, infer no-start from a missing start while a stop/receipt exists, or refund uninvoked work.

Incremental tests: `tests/manager/test_public_context_capacity_baseline.py` uses a real isolated
MySQL claim and public Host flow through different Coder/QA/Reviewer to DONE; schema/model
negative tests in `tests/contracts/test_context_capacity_baseline_schema.py` and canonical fresh
regeneration tests preserve every embedded guard. No production SQL migration or history rewrite
is required. Existing exact nonterminal capacity waits use a reviewed source update proposal,
PAUSE approval and explicit continue after loading the compatible idle runtime. Older BLOCKED
Tasks need their separate terminal recovery contract. Retain the additive reader after any new
binding or decision is published; use a forward fix instead of erasing records or resetting Git.

## Scope and signatures

This contract covers an engineering-controlled source update after Coder execution has begun.
Platform runtime replacement and target-repository source updates are separate operations. A
runtime upgrade alone does not change the approved Task, Git base, candidate or role inputs.
The public Host/Console command supplies exact identity and target SHA only; it cannot assert
process stop, claim absence, permissions, successful verification or trusted execution facts.

```python
ProductionBaselineFactCollector.execution_scope() -> ContextManager[None]
ProductionBaselineFactCollector.collect(target_base_ref) -> BaselineExecutionFacts
ProductionBaselineFactCollector.source_worktree(facts) -> WorktreeRef
ProductionBaselineFactCollector.completed_task(binding) -> Task
ProductionBaselineFactCollector.publish_completion(plan, binding) -> None
ExecutionBaselineService.propose(target_base_ref, *, input_mode) -> ExecutionBaselinePlan
ExecutionBaselineService.execute(plan_sha256, *, authority) -> ExecutionBaselineBinding
TeamHost.propose_execution_baseline(command: BaselineProposeCommand, *, project_id) -> ExecutionBaselinePlan
TeamHost.execute_execution_baseline(command: BaselineExecuteCommand, *, project_id) -> ExecutionBaselineBinding
load_sealed_preparation(workspace, preparation_sha256, *, organization) -> PrepareProjectResult
StoredCoderExecutionInputResolver.current(task, *, implementation, progress) -> CoderExecutionInput
resolve_coder_execution_input(task, *, implementation, progress, baseline, baseline_history=()) -> CoderExecutionInput
CoderExecutionInput.superseded_artifact_ids -> frozenset[ArtifactId]
CoderExecutionInput.progress_supersedes -> ArtifactId | None
latest_accepted_artifact(artifacts, artifact_type, *, trusted_order=None, excluded_artifact_ids=frozenset())
StoredCoderExecutionInputResolver.required_context(source) -> str | None
BaselineRunContextBuilder.build(task, agent, *, attempt, candidate_revision, input_artifacts)
execution_baseline_from_context(context, request, task) -> ExecutionBaselineBinding | None
```

Wire models are `execution-baseline-plan.schema.json` and `execution-baseline.schema.json`.
`BaselineProposeCommand` binds delivery/Task, intent, revision, WorkItem, original source, immutable
full target SHA and input mode. `BaselineExecuteCommand` binds the Task and exact plan digest.
Trusted composition independently resolves the current Requirement and operator duties.
`BaselineOperatorAuthorization` is an actual engineering decision; an `EngineeringAdmission`
must have exactly the versioned `EXECUTION_BASELINE_REBIND` capability and exact plan/facts.
An Agent/model cannot submit either trusted facts or an engineering principal.

## Contracts

### Complete binding reads and standalone Context

`FileExecutionBaselineStore.bindings_for_task(task_id)` reads and validates each exact
`ExecutionBaselinePlan` once, then uses private
`_required_patch(binding: ExecutionBaselineBinding, plan: ExecutionBaselinePlan) -> str`.
The caller still validates the complete binding/predecessor, exact start/embedded plan,
facts, independent authority and native-rule epoch. The private helper checks exact
plan digest, complete retained patch URI, UTF-8 SHA/byte length, Task, input mode and
purpose. It returns the complete patch without creating a discarded Context string.
No plan, authorization or result survives this call as a cache.

Public `required_context(binding)` independently validates binding integrity and
freshly reads `plan(binding.plan_sha256)` on **every call**, then uses the same private
patch check and unchanged complete Context text. `put_binding` retains its existing
public Context check. Missing start/authority, bad predecessor/epoch, wrong plan identity,
patch URI/hash/bytes, Task/mode/purpose still reject; no historical facts are rewritten.

Good: a full read uses one plan read per binding and retains all authority reads.
Base: two independent Context reads read the plan twice. Bad: use a previous request's
plan or skip exact patch references because a complete binding was once observed.
`tests/manager/test_baseline_read_reuse.py` counts real store reads and verifies full
Context equality, immutable bytes and refusal cases. Existing complete baseline, native
rule and paused-binding regressions remain required. No migration; rollback restores
duplicate plan reads without changing an execution or approval.

### Original intent, branch and role lineage

- Keep the same Task, original semantic branch and `coder-attempt-01` worktree. No `-recovery`
  branch or successor Requirement is created for an eligible nonterminal source update.
- Original `Task.base_ref`, Product/Design/Plan approval, scope, acceptance criteria, permissions,
  retry policy and historical Artifacts remain immutable. The approved base and current execution
  base are distinct fields in append-only `ExecutionBaselineBinding` history.
- Bind sequence, exact predecessor, original source, old/new execution base, execution-input SHA,
  superseded implementation/progress IDs, retained full patch, authority, plan/facts, before/after
  inventory and timestamp. New input commits are execution inputs, not accepted candidates.
- Explicitly supersede old implementation and progress only through this binding. Select new
  accepted Artifacts normally thereafter. Retain every old feedback and Artifact. Only exact
  interruption receipt digests in the verified binding are resolved; source differences alone
  cannot suppress an old uncertain invocation.

### Trusted quiescence and versioned native rules

- Hold the Task process lock before the queue authority/Task-row SQL fence, matching Worker lock
  order. The fence excludes **all** ACTIVE claims, including expired claims. A missing heartbeat,
  expired lease or caller-supplied boolean cannot prove that a subprocess has stopped.
- Match original dispatch intent, accepted Artifact receipts/digests, current event revision and
  unique non-CLOSED Coder WorkItem/immutable RoleRunBoundary. Deny another repository, role,
  allocation, candidate source, scope or write policy.
- Verify every historical invocation's exact start and original real claim. Require a definitive
  sealed result or an exact Native interruption receipt with owned process-stop evidence. A claim
  without a start requires a sealed claimed preflight stop; unrecorded legacy execution remains
  an engineering wait. A successful unaccepted result must be replayed through ordinary gates
  before proposing a baseline; a source rebind cannot discard the result or invent a verdict.
- Attribute ownership to the exact immutable WorkItem ID, not just role/attempt: another
  checkpoint can legitimately reuse those values. Reopen a historical invocation's source
  through its request's exact baseline digest; the newest source overlay cannot reinterpret
  an old Run, start or stop proof. Repeated preflight WAIT/RESUME rounds require a separately
  validated stop marker for every original non-invoked lease, each matched to the source that
  preceded its SQL CLAIMED event. Preserve all marker digests in the quiescence proof; do not
  reject valid history merely because it has multiple markers or an older execution source.
- `work_queue/baseline.py::effective_step(..., baseline_sha256, latest=False)` also accepts a
  downstream role's inherited baseline only through the immutable `parent_work_item_id` chain
  to the exact consumed binding. Every link must retain Task, Repository, root scopes and dispatch
  allocation; the nearest consumed epoch must match the requested digest. Missing/cyclic parents,
  unrelated/older bindings and a changed anchor source/predecessor digest are corruption. Keep
  the descendant's own candidate boundary unchanged. `tests/work_queue/test_baseline_history.py`
  covers these positive and negative contracts; the full native public fixture reads all roles.
  `role-queue-execution.schema.json` must match the complete runtime union, including the existing
  `QueuedWorkItem.wait_disposition`; `tests/work_queue/test_execution_contracts.py` checks parity.
- An initial preflight wait can precede creation of the Coder checkout. Create that first clean
  original-branch checkout only for trusted uninvoked original-base facts with no Coder invocation
  start, interruption receipt, implementation/progress Artifact or previous baseline binding.
  Git must still refuse any surviving branch/path. A missing previously started checkout is an
  engineering wait and must never be reconstructed as clean.
- Reopen the exact sealed preparation/profile/runtime binding/compiled baseline from the
  original checkpoint. Validate all Team/Project/Repository identities and stored hashes with
  bounded regular-file reads. Do not rediscover mutable checkout rules or prepare a new epoch
  as a substitute for the approved inputs. A newly proposed target is checked separately.
- Read target native-rule contents from its immutable Git tree. Reuse `native_rule_kinds()` and
  enumerate the full target tree so new AGENTS, CI, CONTRIBUTING, README, editor or Trellis rules
  cannot evade comparison. Require the exact current source set, paths, kinds and content hashes.
  Reject symlink/gitlink/non-UTF-8/over-budget rules. Changed project rules require a separate
  explicit engineering decision through the inspectable rule-epoch contract below; a source-only
  admission cannot silently adopt them. Structured PROJECT SpecRule provenance remains frozen;
  source changes requiring recompilation are refused rather than treated as opaque text approval.
- Seal an inspectable `BaselineQuiescenceProof`, not just an unexplained hash. Git HEAD/dirty
  capture and inventory belong to the exact plan/adapter; collect's stable Task/queue/native
  facts must not change during an already-authorized Git mutation.

### Git preservation and crash replay

- Seal dirty HEAD-to-worktree capture and complete old-execution-base-to-candidate-plus-draft
  capture, including regular text addition, modification, deletion and executable-mode change.
  Capture both complete bodies, index and final inventory before writing Git.
- Preview committed work with bounded deterministic merge-tree/commit-tree. Preview draft
  reapplication through an independent temporary index. Reject unknown unsafe mutations,
  write-policy violations and content drift. No speculative merge changes the original checkout.
- Persist exact plan, authority and operation-start **before** mutating the existing worktree.
  Preserve old candidate reachability in a private ref. Restore only the exact sealed draft,
  CAS the original branch, safely update its index/worktree, then apply the prechecked draft.
- Replay only recognized exact states: original full draft, original clean source, moved ref with
  old index/worktree, or new input with the exact full draft. Unknown files, collisions, ignored
  protected changes or other HEAD/index/content states are retained and refused. Never force
  reset/clean a worktree to make it fit the plan.
- A conflicted preserve plan remains refused and immutable. `coder_reapply` requires a newly
  proposed exact plan and separately matching authority; it starts from the clean target and
  delivers the **entire** original candidate-plus-draft patch as required Coder Context. Old
  authority cannot authorize silent mode changes or truncated patch adoption.

### Queue accounting and all-role inputs

- `BaselineExecutionFacts.continuation` binds current attempt, original Run/start/outcome/receipt,
  retry cause, exact retry-failure fact, next execution identity and prior reservation status.
  An already invoked local window consumes the next ordinary work attempt. A typed provider
  interruption consumes its exact transient failure and next identity. Uninvoked or already
  reserved work keeps its existing identity. No refunds, free replacement calls or budget reset.
- Publish Git completion and consume scheduling within the same Task process lock and original
  queue-authority/Task-row SQL fence. Do not open a competing SQL transaction for consumption.
  An invoked step needing another attempt gets a new immutable WorkItem/step and closes the old
  item. An uninvoked or already reserved step retains its unique role/attempt/checkpoint identity
  and appends a typed source overlay with the exact predecessor step digest; the original boundary
  remains unchanged. Increment dispatch_sequence before READY so prior preflight ownership cannot
  be reused. Every subsequent model/knowledge role gets a real new claim, Run and Context.
- Use the same current execution-input resolver for Coder checkpoint recovery and invocation
  permits. Comparing the former with Task.base_ref after a rebind would emit an artificial
  same-identity boundary and make the WorkItem its own parent. Task delivery stage and original
  event revision stay at their latest legitimate checkpoint throughout source publication.
- Completed binding replay validates current frozen intent through `completed_task`; it does not
  recollect the old queue/source/counters after queue consumption or subsequent legitimate roles.
  Pre-publication execution still requires exact plan/facts and Git state. Replaying the operation
  and queue consumer must be independently idempotent across their crash boundary.
- Coder, QA and Reviewer requests carry the same exact baseline digest and execution base.
  Required Context uses the versioned [mode-aware baseline reading contract](baseline-context-projection.md).
  New `preserve_draft` inputs carry the complete binding and exact retained-patch reference after
  full store/authority/body validation; every v2 consumer requires that independent complete-store
  verifier. `coder_reapply` and historical v1 contexts retain the entire old patch and SHA/byte
  checks. Required information is never truncated to fit; insufficient input capacity becomes an
  actionable engineering wait.
- Insert this required baseline section before knowledge consultation so consultation binds
  the complete engineering input. The outer runtime guard must recognize the exact already
  sealed section and return the finalized Context unchanged. It must not append a second
  section or change the final Context ID after consultation. Keep the KnowledgeDeliveryGate's
  exact parent-plus-consultation lineage check; do not weaken it to accept arbitrary additions.
- QA/Review keep the actual candidate SHA as their request/context source. `BoundCandidateSource`
  verifies the trusted baseline Context against the typed request before selecting the execution
  base for the complete candidate diff. Plan.source remains the original approved base. Native
  verification rechecks that the request binding equals the current trusted store binding.
- Coder cannot change verdicts. QA PASS and Review APPROVE are independent and use the same final
  candidate SHA. Upstream baseline changes must not be mistaken for Coder changes or new findings.

### Sealed provider failure accounting

`ProductionBaselineFactCollector._reservation(task, item, receipts, ...) ->
BaselineExecutionReservation` may classify a sealed original outcome with no interruption receipt
as `provider_transient` only when both `outcome.result.error.transient is True` and
`outcome.result.error.code.value in TRANSIENT_CODES`. The error category alone is insufficient:
`PROVIDER_UNAVAILABLE / transient=false`, including an unclassified truncated native diagnostic,
cannot reserve a successor or append `DeliveryRetryFailure` through a source update.

This check preserves the independently verified interruption-receipt and stopped-provider-proof
paths. It grants no extra work allowance and does not reinterpret the original result. Every
proposal still verifies real Task/claim/source/stop/workspace facts before accounting. The ordinary
wait investigation and baseline accounting must agree about a direct outcome's transient flag.

| Original sealed outcome without receipt | Required result |
| --- | --- |
| Allowlisted error, transient=true, remaining frozen service-fault allowance | Exact provider reservation; work count unchanged; replay adds no second debit |
| Allowlisted error, transient=false, work remaining or exhausted | Refuse; preserve original Task/outcome/files; no provider reservation |
| Nonallowlisted error, transient=true | Refuse; the flag cannot expand the error allowlist |
| No original outcome or legal stopped-provider proof | Existing exact continuation contract; do not invent failure classification |

Good: a typed transient provider outage keeps its own bounded accounting even at the ordinary work
limit. Base: existing local interruption receipts consume ordinary work exactly as before. Bad:
use a source-rebind approval to refund an unknown nontransient failed call.

`tests/manager/test_execution_baseline_reservation.py` seals real typed outcomes and reads them
through the production collector's reservation path. It checks all four allowed codes, true/false
flags, exhausted/remaining ordinary work, unsupported codes, exact retry replay, unchanged original
Task/retry facts and immutable saved bytes. Existing invocation and stopped-provider tests retain
their independently checked authority boundaries.

存量数据处置: no SQL migration or historical rewrite. Loading this guard while idle prevents new
misclassified reservations; it does not retroactively refund or repair a published reservation.
The current nontransient stopped K1 execution retains its original failure and exhausted frozen
budget and requires its own exact authorized engineering disposition. Reverting this guard leaves
wire records compatible but reintroduces unsafe code-only classification; do not use rollback to
resume a rejected failure.

### Accepted artifact order and retained candidates

`compare_artifact_order()` and `latest_accepted_artifact()` are the shared write/read-side
selectors. Only sealed artifacts qualify, including a singleton. A common verified durable
stream orders by sequence/ordinal; otherwise platform `integrity.validated_at` is the legacy
publication clock. Equal publication time requires the full parent/supersedes graph. Provider
`created_at`, file iteration order and random artifact IDs cannot establish current work.
Duplicate identities, cycles and multiple incomparable latest artifacts fail closed.

Resolve the complete verified baseline chain first and accumulate every binding's exact
superseded implementation/progress IDs. A later binding with an absent superseded field does
not reactivate an artifact superseded by an ancestor. Exclude these IDs from eligible candidates
before selecting latest implementation/progress; retain the complete accepted artifact history
for integrity and transitive lineage checks. New progress must still match the current source;
source inequality alone is never grounds to ignore an artifact. The latest nonempty superseded
progress ID remains the exact supersedes fallback for the first new checkpoint.
Exclusion follows each retired artifact's explicit same-Task, same-kind `supersedes` ancestors,
so removing the latest checkpoint cannot revive any checkpoint it already replaced. Ordinary
parent references are not retirement edges: they remain available for ordering and historical
QA/Review finding routing. A real new successor to a retired checkpoint remains eligible.
Pass the complete accepted history to transitive lineage
comparison. Runtime dispatch, initial draft admission and baseline recollection use the same
selection rule; a replaced old candidate cannot hide a legitimate new-baseline checkpoint.

A terminal blocked handoff advertises only a valid accepted implementation's candidate SHA.
The new execution input and a binding-superseded implementation are not candidates, even when
their source differs from immutable `Task.base_ref`. Waiting and StateEvent source still record
the actual current execution input or independent verifier candidate.

`StoredCoderExecutionInputResolver` obtains the complete store-validated binding history;
domain resolution rechecks Task/predecessor/latest identity and derives the two ordered
`superseded_*_artifact_ids` tuples without changing wire records. Runtime source collection,
workspace admission, Coder requests and blocked-result reconstruction first resolve the baseline
with no role artifact, then select eligible artifacts using those exclusions. Exact retired
implementation remains available only as historical verifier feedback and expected supersedes,
never as a current execution source or recoverable/deliverable candidate.

Wrong: select latest progress, discard only `history[-1].superseded_progress_artifact_id`, then
compare source; a later empty field resurrects earlier retired work. Correct: validate full binding
history, select candidates with its cumulative exclusions and complete accepted supersedes graph,
then enforce active progress source equality. Missing history/foreign Task/changed digest or a
genuinely mismatched active checkpoint still fails closed.

| Repeated baseline history | Required behavior |
| --- | --- |
| B1 retires P0, B2 has no progress ID, P0 and four replaced predecessors remain stored | None is an active checkpoint; continue B2's preserved input |
| New P1 on B2 source explicitly supersedes P0 | P1 remains active; normal progress lineage is retained |
| Unrelated old-source progress not retired by exact binding/supersedes chain | Reject with Chinese source mismatch; retain all evidence |
| Retired implementation I0 followed by empty B2 field | No candidate recovery/handoff from I0; its QA/Review findings still reach Coder |
| Excluded records hide invalid integrity/duplicate/cycle or cross-kind supersedes | Reject; exclusions cannot bypass validation |

Incremental regressions: `tests/orchestration/test_baseline_history_inputs.py`,
`test_baseline_exclusion.py`, `tests/manager/test_paused_baseline_service.py`,
`test_terminal_candidate_reconstruction.py`, and the `first_checkpoint=True` public native
Host flow in `test_legacy_rescue_delivery.py`. The latter must keep exact old artifact bytes,
Task/approval/worktree/budgets and independent same-candidate QA/Review after two PAUSE bindings.
`tests/team_view/baseline-progress-failure.test.cjs` checks Chinese presentation of the historical
exact English error while keeping immutable Operation audit text unchanged.

Existing K1 failed before continuation authorization or SQL release: no record migration,
Task reset, new approval or source update is needed. Read-only verify current binding/worktree
inventory/hold, load the fixed service while idle, refresh the original Requirement and explicitly
continue its latest paused binding. This fix changes no persisted Schema/bytes/digests; a code
rollback remains possible while idle but reintroduces this selection failure.

## Validation matrix

| Input or crash | Required behavior |
| --- | --- |
| Eligible stopped Coder, candidate plus dirty text, exact target/rules/authority | Preserve all work on the same Task/branch/worktree |
| Full candidate diff after rebind | QA/Review compare new execution base to the same candidate; original Plan base unchanged |
| Conflict under preserve plan | Keep refused plan and work; require a new exact coder-reapply plan and authorization |
| Target adds/changes/deletes AGENTS, CI or Trellis rules | Seal inspectable exact before/after epoch, reject source-only authority, require matching rule-change digest |
| Any ACTIVE claim or held process lock | No Git mutation; keep engineering wait |
| Unknown invocation or claimed run without durable start/preflight | No model call or source rebind |
| Success result awaiting acceptance | Replay original result first; no silent baseline overwrite |
| Crash after ref/index/draft Git writes | Reconcile exact admitted state; one binding and no duplicate mutation |
| Binding published, queue consumption pending | Replay completed binding without recollecting obsolete facts; consume queue once |
| Queue consumed or later roles changed attempts/source | Same binding replay; no second debit or approval |
| Stale request/Context digest, altered patch body or original scope | Reject even when attacker recomputes section SHA |
| Provider vs local interruption | Exact distinct accounting; no free work allowance |

Good: upgrade the platform runtime, propose an exact compatible repository-source update,
record authorized engineering intent, preserve draft, issue fresh ownership, and verify one final
candidate through independent QA/Review. Base: ordinary new Tasks need no baseline record and
retain their original wire bytes and selectors. Bad: rewrite Task.base_ref, call git reset/clean,
accept an arbitrary dirty directory, infer stopped execution from lease expiry, or run verifiers
against the original base after importing upstream changes.

## Tests, existing data and rollback

Incremental tests: `tests/manager/test_execution_baseline.py`,
`test_execution_baseline_context.py`, `test_execution_baseline_native_rules.py`,
`test_execution_baseline_reservation.py`, `test_execution_baseline_invocations.py`,
`test_sealed_preparation.py`, existing `tests/agents/test_candidate_source_binding.py`, and
`tests/manager/test_production_execution_baseline.py`. The public Host tests advance the main
checkout, preserve the original Task/branch/worktree and full stopped draft, execute exact
preserve/reapply plans, obtain real new claims, and require independent QA/Review at the same new
candidate and execution base. Repeating the public operation after DONE makes no new model call.
Repeated public preflight waits exercise two upgrades on the same WorkItem, three real distinct
claims, exact original/intermediate/current sources, and zero delivery model invocations.
Required assertions include stale authority, complete patch/hash validation, drift retention,
Git post-write crash replay, all three required role Contexts, new-base candidate diff,
independent final same-SHA verdicts, exact work/transient accounting and queue-consumption replay.
Schema contract tests must reject unknown authority/fields, mutable refs and contradictory
reservation/body identities and verify old optional fields remain absent.

No direct SQL rewrite or requirement recreation. Deploy the compatible runtime while idle.
Eligible existing nonterminal Tasks use the public engineering investigation/proposal/decision
path. Legacy Tasks lacking trustworthy invocation/claim/stop facts remain visible engineering
waits with retained history; the platform must describe the missing proof instead of inventing it.
Deleted Requirements remain tombstoned and are never restored by this operation.

Rollback before new bindings may revert the compatible code while idle. Once new bindings,
required role Contexts or queue-consumption records exist, retain their readers and prefer a
forward fix. Reverting code does not undo a target-source update or erase its authoritative
facts; a further source change is another exact append-only engineering plan.

## Preserved-input pause, rule review and explicit continuation (2026-10-09)

This is a general target-repository flow, including self-hosted ASE. Upgrading the running ASE
service alone never changes an unrelated target's source. New Console decisions explicitly set
`continuation_mode="pause"`; omitted historical fields retain `resume` semantics and exact bytes.

```python
ExecutionBaselineService.continue_execution(binding_sha256, *, authority: BaselineContinueAuthorization) -> bool
ProductionBaselineFactCollector.publish_continuation(binding, authority) -> bool
MySqlRoleQueue.release_baseline_pause(binding, authorization, *, cursor=None, validate_new_release=None) -> bool
StoredCoderExecutionInputResolver.native_rule_epoch(source) -> NativeRuleEpoch | None
FileExecutionBaselineStore.native_rule_epoch(sha256) -> NativeRuleEpoch
TeamHost.continue_execution_baseline(command: BaselineContinueCommand, *, project_id)
build_native_rule_change(*, git, records, scope, task_id, source_revision, target_base_ref,
                         source_rules, target_rules, structured_project_rules=()) -> NativeRuleChangePlan | None
NativeRuleEpoch.inspect_change(path) -> NativeRuleChangeInspection
```

### Durable pause and exact release

- `BaselineOperatorAuthorization.continuation_mode` is sealed in the binding. PAUSE consumes the
  legitimate original reservation once but publishes `WAITING_HUMAN` with classification
  `EXECUTION_BASELINE_PAUSED` and the exact `execution_baseline_sha256`, never READY.
- Source updates while paused must remain PAUSE, checked before Git mutation. They extend the
  same Task/branch/worktree and update the hold to the latest binding; no second work reservation.
- Dispatcher, `make_ready`, generic `resolve_wait`, Manager handle/resolve and ordinary delivery
  Continue cannot release this hold. The UI shows saved progress and pause, plus distinct update
  and explicit continue controls. The Task retains its legitimate delivery checkpoint.
- `RESUME_EXECUTION_BASELINE` supplies delivery/task IDs, `expected_task_intent_sha256`, Task
  revision, current WorkItem/source, binding digest, disposition digest and human reference. Host
  derives inventory, principal and time from trusted inputs; the command cannot declare idle.
- Persist the immutable `baseline-continuations` authorization before SQL release. First release
  validates latest consumption, original intent, unique paused Coder item, full exact source,
  Task/event revision, disposition and all ACTIVE claims under the existing Task/queue fence.
  The collector's `validate_new_release` rechecks current invocation facts, HEAD/path, full file
  inventory, empty staged index and prepared dirty Git tree in that same fence.
- A crash after authorization but before SQL commit must repeat that fresh validator; exact
  committed release replay returns False without recollecting legitimately progressed work.
  First release atomically appends typed `BaselineQueueRelease`, increments dispatch generation
  once and makes READY. Only True causes synchronous Host resume. It is not a new attempt or
  budget refund. `work_queue_baseline_releases` is additively initialized by the existing queue
  schema initializer; no historical row transformation or direct SQL recovery is needed.

### Exact native-rule epoch and human inspection

- `BaselineExecutionFacts.native_rule_change` is absent when unchanged. When present it binds
  sorted complete source/target reference digests, scope, Task, immutable target Git SHA and all
  additions/modifications/deletions to `change_sha256` and an immutable `epoch_sha256`.
- Private `baseline-native-rules` records store complete source/target rule bodies read from
  immutable Git commits. Each original source SHA/length is retained independently from the
  redacted body SHA/length. Boundaries: 1 MB/file, 8 MB/raw version, 16 MiB/serialized epoch;
  symmetric secure KnowledgeRecordStore read/write budget is 20 MB. No truncation or mutable
  checkout substitution. Symlink/gitlink, invalid UTF-8, missing source and over-budget input fail.
- Human execute authority must include `approved_native_rule_change_sha256` matching the exact
  plan. Missing/wrong/stale digest or old organization source-rebind capability fails before Git.
  Store readers verify authority, mode, source/target revision, full epoch, complete diff and
  inherited epoch lineage; a later code update with unchanged rules keeps the accepted epoch.
- GET `/api/v1/operations/{operation_id}/native-rules?path=...` opens only the validated successful
  proposal's Team/Project registered sidecar and exact stored plan/epoch, without constructing
  Host, registering, preparing or reconciling. Only a stored changed path is accepted. Response
  supplies full redacted before/after text and exact unified diff; UI uses textContent and retains
  the user's open review during polling. It does not expose secrets or arbitrary host paths.
- Coder/QA/Reviewer Context and knowledge consultation select the same complete active epoch.
  Original RepositoryProfile/preparation/compiled policy remain historical approved provenance;
  required `source:execution.native_rules` identifies current rules. Added rules enter and deleted
  rules disappear in both flows. Final Context validation rejects fake markers/body/hash, mixed
  scope/Task/epoch and incomplete native sources. No role gains permission to alter hard policy,
  structured rules, Task scope or verdicts by adopting opaque native text.

### Validation, existing records and rollback

| Case | Required result |
| --- | --- |
| PAUSE save, independent dispatch tick | No role claim/model call; exact durable human hold |
| Source update while PAUSE | Same identity/budget, latest binding and hold; no automatic call |
| Wrong/absent rule digest | No Git/binding/queue mutation |
| Stale binding/disposition/revision/source | Continue refused; original work preserved |
| Auth saved then crash, changed files/index | Pending replay refused before READY |
| SQL release committed then replay | False, no second dispatch increment or model call |
| Changed structured PROJECT provenance | Explicit recompile/scope decision required; no silent policy update |
| Complete public pause/update/review/continue | Independent Coder/QA/Reviewer with one exact epoch and final candidate |

Tests: `tests/work_queue/test_baseline_pause_mysql.py`, native epoch/context tests, public Host
baseline delivery and legacy rescue tests, HTTP native inspection tests and Chrome legacy-rescue
fixtures. Run these incrementally, plus changed-file Ruff/Mypy and schema parity; full-suite run
is left to the user. Good: preserve then review upstream code/rule changes and explicitly continue.
Base: unchanged rules and historical absent fields retain exact behavior. Bad: disable only Host
resume, manually rebase a retained worktree, use ordinary Continue to release the hold, or replace
original preparation/rules in place.

Existing READY legacy rescue proposals remain usable: after loading compatible code, approve
that exact proposal with PAUSE, inspect the new hold, propose an available exact target revision,
review/approve its rule changes and preserve PAUSE, then explicitly continue. A separate clone
must first obtain target Git objects through repository administration; missing objects never
justify manually rebasing the Coder workspace or recreating its Requirement. No production K1
approval, SQL rewrite, new Requirement or source mutation is performed as part of this fix.
Before new records, an idle code rollback is possible. Once pause/epoch/release records exist,
keep their readers and prefer a forward fix; old versions cannot safely interpret the new holds.

Continuation's service-level True also covers a saved exact SQL release whose current item
still equals its immutable READY result, source and dispatch generation. This permits replay
of the crash between release commit and synchronous Host kickoff. Pending kickoff repeats the
fresh file/index/tree and local-stop validator; unrelated READY work, an ACTIVE claim, a later
wait or completed work is never kicked by the old authorization. Console may pass the internal
`require_existing_authorization=True` only for an outer-checkpoint-changed replay; absence of an
already saved exact decision refuses stale first submissions.

Wrong: `consume_baseline(...); skip_host_resume()` while the queue remains claimable, or resume
all exact old decisions after they have legitimately progressed. Correct: publish PAUSE in the
fenced queue, review exact immutable rule differences, release the latest authorized hold, and
only kick a new or exact verified still-unstarted release.

## Proposal-only collection of original stopped execution facts (2026-10-10)

`ProductionBaselineFactCollector.bind_proposal(command: BaselineProposeCommand) -> None`
binds the explicit command to one production proposal. `BaselineProposeCommand.require_current`
checks the exact Task intent/revision, WorkItem and current execution source while the existing
Task process lock and SQL idle fence are held, before any missing receipt/outcome is published.
Its signature is `require_current(task: Task, revision: int, work_item_id: str,
source_revision: str) -> None`. Host first validates the public Requirement/Task association
with `_baseline_native_checkpoint`: a joint parent must contain exactly one matching native
Task. It binds a typed internal command copy using that native child's delivery ID before
`ExecutionBaselineService.propose`; the original public command still validates the returned
plan. ContinuationScope retains its original native Requirement/dispatch identity, never the
parent ID. An unrelated parent is rejected before receipt/outcome publication. Request data
cannot assert execution stopped or grant mutation authority.

For `source_rebind` with an unresolved `EXECUTION_UNCERTAIN`/`PLATFORM_BUG` Coder wait, the
collector reuses `DeliveryWaitFactCollector.collect(task, step, guard)` before loading receipts.
It supplies the exact native Team/Project/Repository/Requirement/dispatch scope and reuses the
held guard/fence without entering a second SQL idle scope. It can only append original durable
route outcomes or complete legal interruption receipts. It does not call HANDLE, resolve a
wait, change Task/queue/retry budget, publish READY, mutate the Coder branch or call a model.
Normal proof/reservation/capture/preview validation then builds the proposal.

| Proposal input | Required result |
| --- | --- |
| Exact v2 start/stop, legal full source, missing receipt | Seal one receipt and proposal; unchanged Task/events/queue/budget/worktree |
| Repeat exact preparation | Reuse receipt; no new execution, debit or receipt |
| Stale intent/revision/WorkItem/source | Reject before missing facts are written |
| Live/unknown process, absent cause/code, changed scope/claim/source, sensitive or drifting source | Existing receipt refusal; original wait and files remain |
| Original successful result | Preserve/recover result; reject baseline overwrite and require ordinary result acceptance |
| PAUSE hold, ordinary preflight, execute/continue recollection or legacy rescue | No proposal reconciliation or reinterpretation of historical invocation start |

## Completed native output unavailable (2026-10-11)

A FAILED WORK_INTERRUPTED/nontransient/no-artifact result may coexist with a separately
sealed native completed returncode0/output_present=true stop. Its output content remains
unknown. The baseline-only `completed_output_unavailable` reservation binds the exact
original outcome/capture start/stop/claim; it does not fabricate an interruption, artifact,
cause or provider refund. The final plan additionally validates original-before/current
complete inventory, all mutations and full draft fingerprints. Consumed rejected-output
decisions may retire only their exact old artifact IDs from current execution reads;
raw publication receipts remain and current-run publication always prevents this capability.

Existing SOURCE_REBIND still changes its target. Separate `completed_output_rescue` freezes
the current trusted base without user SHA entry, preserves HEAD and complete draft, and
requires exact human PAUSE before explicit latest-bound RESUME. Neither route changes original
unknown output or normal-work accounting. Old absent fields preserve canonical hashes. Full signatures, validation
matrix and stock-data handling are in
[`completed-coder-output-unavailable.md`](completed-coder-output-unavailable.md).

Good: prepare an exact new source while sealing a genuinely stopped draft, execute the approved
plan with PAUSE, inspect native-rule changes and explicitly RESUME. Base: existing complete
receipts and clean preflight keep their prior behavior. Bad: call HANDLE merely to seal facts
and unintentionally resume on the old source, infer a stop from queue expiry, or reclassify a
successful output as a failure.

Incremental tests: `tests/manager/test_baseline_wait_fact_collection.py` and the public missing
receipt PAUSE flow in `tests/manager/test_production_execution_baseline.py`. Assert command
rejection before publication, complete capture, idempotency, no nested queue lock, zero calls
before explicit continuation and independent final same-candidate QA/Review.

Existing waits need no SQL migration, in-place receipt/report rewrite or Requirement recreation.
After loading the compatible runtime while idle, prepare a source-update proposal for the same
Requirement and exact current WorkItem using an immutable target SHA available in its registered
repository, review/approve exact source and native-rule changes with PAUSE, then explicitly
continue the latest preserved binding. Old failures and original stop records remain immutable.
Before source execution, code rollback leaves sealed original receipts usable by the existing
handling/baseline paths. Once PAUSE/binding/continuation records exist, retain their readers and
prefer a forward fix; do not erase facts or reset the worktree to enable rollback.

Read-side pending kickoff: `RoleQueueView.pending_baseline_continuation` contains only a saved,
validated `BaselineContinueAuthorization` whose exact latest binding/file record and SQL release
still match the current READY snapshot and Task revision, with no ACTIVE claim. The read helper
uses the existing read-only transaction and private read-only stores; it neither constructs queue
services/Host nor initializes schema. Older stores without the additive release table return no
hint. Task/Requirement UI shows actionable engineering wait and “继续已授权执行”, reusing the
saved reference and exact decision fields. A mere authorization file, claimed work, a changed
READY generation or later wait cannot produce this hint. This closes the service-restart gap in
v0.1's synchronous Supervisor: telling users to wait for unattended dispatch would leave it idle.
Multi-repository plans retain independent review/open/consent state, pruning only plans no longer
present in a completed detail render; reading a second repository cannot clear the first approval.


## Unified completed, unaccepted Coder draft input

`CompletedCoderOutputUnavailableProof.reason` is derived from the immutable original error:
WORK_INTERRUPTED → completed_output_unavailable, INVALID_OUTPUT → completed_output_rejected.
The latter is ordinary work, not a transient refund or accepted progress. Facts/Plan retain the
full original proof and complete draft; the queue validates exact reason agreement. Both same-base
rescue and explicitly selected SOURCE_REBIND use the existing flow. Newly rejected SOURCE inputs
must carry the proof digest in Binding, match the exact saved plan and engineering operator
approval, and remain PAUSE until the separate latest-bound continuation decision. Old SOURCE
bindings without that optional digest retain their previous reading and authority semantics.

Production consumption rechecks old execution facts separately from the real resulting workspace.
Same-base inputs require unchanged complete inventory and both captures; SOURCE inputs may change
before/after during the trusted Git rebase, but must match the resulting Binding after inventory,
source/branch, full prepared patch and clean index. Preserve the original failure, source lineage,
Task/event history, normal work counters and complete ignored inventory. No new Task, purpose,
process-stopped Boolean, accepted artifact or role verdict is introduced. The completed-output
spec owns the detailed guards, public validation matrix, existing-data handling and rollback.
## Historical knowledge-only preparation failures

`ProductionBaselineFactCollector._invocations` partitions each immutable historical claim by
its actual main invocation, claimed Context capacity receipt, failed knowledge preparation,
or preflight checkpoint. Absence of a main start is never sufficient proof. The internal
`read_failed_knowledge_claims` reader locates only the exact Team/Project/Repository/Task/role
lane for the trusted approved Requirement and documented legacy Task scope. A returned-only knowledge
lane cannot acquire failure authority; it remains subject to the ordinary invocation/preflight
checks.

When at least one selected claim has a FAILED knowledge outcome, all records in the applicable
lanes must retain their exact content-addressed keys, complete intent/outcome associations and
independently reread structured observations. Every lane intent must have a genuine original
claim, historical step, original source, full Context/Task/claim section, and exact frozen
knowledge snapshot. A record cannot become legitimate merely because its lease differs from
the currently selected WorkItem. Missing/foreign ownership, orphan records, extra unfinished
routes, resealed incorrect snapshot keys and altered source/Context identities reject.

Each native knowledge completion must retain its actual local process-stop proof and pass the
existing stopped-session verifier. An HTTP round-trip receipt proves only that the local
synchronous transport returned; it does not assert that a remote model stopped. Knowledge
preparation remains read-only and its FAILED outcome is never a code verdict.

The shared `CapacityInputReader.require_claim_not_started(UninvokedClaimBoundary)` then performs
the existing complete main start/outcome, model route, native capture/receipt/admission and raw
artifact contradiction scan for the exact original claim. This internal boundary is derived
from validated historical facts, never published as a fabricated capacity or stop receipt.
Capacity recovery still enters through `require_not_started(ContextCapacityReceipt)` and retains
its full independent capacity identity/Context/claim validation. Later main invocations require
their own genuine claim/source provenance; a different Run or Context alone cannot hide an alias.

`BaselineInvocationProof.knowledge_only_claims` is an internal quiescence summary of original
claim, intent, outcome and observation digests. Its empty default is omitted so previously
published quiescence wire bytes/hashes remain unchanged. The new `claimed_knowledge_failure`
proof kind cannot carry a main start, main outcome or interruption receipt. Public Commands,
plans, bindings, approvals, attempt reservations and static JSON Schemas remain unchanged.

Validation: `tests/manager/test_baseline_knowledge_claim_proof.py` covers complete independently
sealed HTTP observations, a real offline native process and owned stop, missing outcome/record,
wrong key, orphan outcome/observation, foreign claim, source/snapshot drift and the public
knowledge-failure → claimed capacity stop → exact source-rebind PAUSE/RESUME → independent
Coder/QA/Review delivery path. Existing invocation and capacity public tests protect historical
overlays and complete no-start refusals.

存量数据处置：不修改 Task、Operation、claim、审批、重试账本或旧知识记录，不回填 stop，不退款。
当前 K1 已有可信的知识-only失败事实可以在发布后被重新读取；在原需求重新准备精确代码基线
方案，核对并批准暂停，再明确继续即可。若原记录缺失或矛盾则继续保留现场并拒绝，不重建需求。
本次实现与测试不操作生产。回滚在新方案前撤销代码提交；已经持久化的追加摘要和工程审计历史
必须保留，回滚本身不授权重新调用模型或重放已消费审批。

### Joint parent knowledge scope is separate from native execution scope

```python
TeamHost._baseline_knowledge_context(project_id, delivery_id, native) -> tuple[ContextSource, ...]
ProductionProjectDeliveryBackend.execution_baseline_service(...,
    knowledge_context_sources=()) -> ExecutionBaselineService
recovery_knowledge_requirement_id(config, plan, native, *, load_allocation) -> str | None
ProductionBaselineFactCollector(..., requirement_id, knowledge_requirement_id=None)
```

The Host resolves the actual current public joint Requirement and exactly one child whose
complete native checkpoint equals the selected delivery. Only its canonical approved Context
sources cross this composition seam. The baseline backend derives the knowledge parent ID
from these trusted sources or the exact sealed recovery plan/Task/authorization association;
the API does not accept a lane ID. Different parent IDs refuse. A native single-repository
delivery without a joint parent retains the actual Task knowledge scope. The collector uses
this separate ID only for the bounded knowledge-lane reader. Proposal, continuation, native
stop, dispatch and operator approval identities keep the native child ID unchanged.

For a recovered joint child, the frozen `RecoverySource.parent_checkpoint_sha256` is often
an ancestor of the current parent because delivery facts have advanced. Requiring equality
with current strands legitimate work; dropping the digest admits unrelated history. The
baseline-only reader exhausts the full verified joint journal, requires exactly one frozen
digest and unchanged Team/Project manifests, scope, Product/approval, design and plan between
that snapshot and current. It reads the complete native journal and verifies exact old-child,
interruption, current-child and latest native checkpoint ancestry, the same unit/root/repository,
original interrupted Task and stage references, and the exact new recovery Task. The backend
also rereads the sealed recovery Task record, including its plan and engineering authorization,
and matches its full Task and record digest to the immutable dispatch.

`RecoverySource.preparation_sha256` references the original approved READY request preparation;
the native interruption checkpoint may instead reference a successor allocation's target
preparation. Read the exact original preparation and request, verify their complete digest and
registered Team/Project/Repository/root/sidecar bindings, then reuse
`allocation_preparation_sha256` with the exact original dispatch. Its converted digest must
equal the interruption checkpoint preparation. The original dispatch itself must retain its
exact key/digest/Task/repository/request. Directly comparing the two preparation fields would
reject legitimate recovered sources; accepting any unrelated preparation would weaken lineage.

This helper returns only the parent ID. It does not reconstruct Context, upgrade knowledge
snapshots or broaden `recovery.context.approved_parent_context` for a new recovery execution.
Normal resumed delivery still builds its own fresh claimed Context from approved stage
sources and the full authorized execution baseline; historical Context bytes remain untouched.

| Facts | Result |
| --- | --- |
| Real public joint parent-bound FAILED knowledge preparation, later capacity wait | Same original Task source-rebind PAUSE/RESUME; independent QA/Review |
| Exact sealed recovery parent is a validated ancestor with unchanged approved stage inputs | Read actual parent lane; preserve frozen parent digest and old Context |
| Foreign/ambiguous parent or child, missing ancestor, changed approval/plan/manifests | Refuse before publishing a proposal or changing queue/source |
| Stale native cursor, unrelated Task or source stage references | Refuse exact lineage |
| No joint parent, existing native/legacy Task lane | Existing scope and wire behavior |

Incremental tests: `test_baseline_knowledge_parent_scope.py` uses the public joint create/reply/
approve path and real isolated MySQL claims plus structured HTTP 503; `test_baseline_recovery_knowledge_scope.py`
tests exact ancestor retention and seventeen wrong-identity/authority/prefix/preparation cases. The production
reader can additionally replay existing typed knowledge facts read-only, without constructing a
Host, invoking a provider, publishing a quiescence record or initializing SQL schemas.

存量数据处置：只修定位，原 K1 知识 parent 与旧恢复批准都保留；没有改库、停止记录回填或
counter重算。发布后在原需求重提精确方案，独立确认并批准 PAUSE，再从原需求明确继续。
无可信原记录仍拒绝。回滚保留所有已有 immutable 记录与审批，新记录已发布后需要兼容 reader。

### Exact legacy raw claim recovery after heartbeat renewal

```python
read_capacity_claim_snapshot(*, state, task, marker: ContextCapacityReceipt,
    historical: QueueClaim, scope: EngineeringScope, requirement_id: str,
    queue: KnowledgeProofQueue, require_step) -> QueueClaim
CapacityInputReader(..., legacy_claim_snapshot: typed_callback | None = None)
```

Old capacity receipts hash the original full `guard.lease.claim`, while legacy SQL claim readers
used the live lease expiry updated by heartbeat. Stable ownership equality cannot prove those
missing raw bytes. The baseline collector supplies a trusted typed resolver only when the
receipt raw SHA differs. The resolver first reads a fully validated `OriginalClaimRecord`:
only explicit absence of an immutable original snapshot permits this legacy path. A new
snapshot's contradictory raw SHA refuses immediately; knowledge cannot replace the immutable
original claim, even when only expiry differs. Missing custom queue methods are not interpreted
as legacy provenance.

The shared completed-knowledge reader validates only the exact trusted approved parent and
legacy Task lanes. It retains all prior content-addressed key, complete intent/outcome, orphan
and independently reread observation/route checks, exact real SQL claim and historical source,
full original Context/Task/claim and frozen knowledge snapshot, and genuine native stop checks.
For the selected claim, all completed phases must have one exact binding and byte-identical
full claim snapshots; completion must precede the capacity observation. The full snapshot's
raw SHA must equal the original capacity receipt SHA, and the complete snapshot must equal
SQL history with only the renewable expiry adjusted. A normalized identity hash alone is
insufficient. The capacity reader independently checks its final Context, original complete
permissions, Task/source/step and all main-call no-start contradictions; its lease ID is now
also an explicit exact identity field.

A successfully RETURNED knowledge result supplies original immutable snapshot evidence but
never a FAILED knowledge-only quiescence proof. `read_failed_knowledge_claims` retains its
selected FAILED gate. Knowledge preparation's base Context and final capacity Context can
legitimately have different IDs after knowledge sections are appended: verify each complete
Context independently against the same real claim, original Task and source, never equate IDs
or mutate either Context. No model call, fabricated stop, counter refund, verdict or recovery
approval is introduced by these readers.

| Legacy/raw input | Required outcome |
| --- | --- |
| Exact independently sealed RETURNED/FAILED knowledge snapshot + actual SQL renewal | Original raw bytes usable for capacity identity; no extra execution authority |
| Two completed phases with identical original snapshots | Deduplicate exact object |
| Two phases with distinct original expiry or binding | Refuse ambiguous raw history |
| Missing snapshot/outcome/observation; foreign lane/claim; modified ownership/time/source/Context | Refuse, preserve original work |
| New event has an immutable snapshot but receipt raw SHA differs | Refuse replacement; no legacy fallback |
| Old verifier receipt has no independently sealed full snapshot | Existing exact raw validation refuses; do not synthesize expiry |

Raw-consumer audit: `work_queue/preparation_resume.py` and `execution_store.py` verifier capacity
checks remain exact and gain stable initial bytes for new events through `original_claim`.
They gain no legacy normalization-only exception. Retrospective `recovery/context_capacity.py`
retains its explicit legacy origin; preparation progress is an audit hash of the actual initial
claim. `recovery/workspace_snapshot.py` intentionally hashes a full consistent **terminal** SQL
claim row/event, including record digest; it requires no active claim and released/expired
state, where renew is impossible. That terminal observation is distinct from an original claim
hash and its whole-row evidence semantics remain unchanged.

存量数据处置：不改 Task、Operation、旧 CLAIMED event、capacity receipt、Context、知识记录或审批；
不回填停止、不退款、不重建需求。原 K1 的 attempt 3 有两个真实 RETURNED 知识 phase，完整原 claim
raw SHA 与原 capacity receipt 精确一致；与当前 SQL 只续租 expiry 不同。兼容版本加载后可在原需求
重新准备精确基线方案；仍须通过真实任务锁/SQL屏障、完整现场检查、准确 PAUSE 批准和明确继续。
生产只读重放通过不等于真实 proposal fence 或执行批准已经通过。无独立原快照的旧 verifier
恢复仍拒绝，需独立可信完整事实或显式工程路径，不能用 stable hash 代替缺失原记录。
回滚：新事实发布前撤销代码即可保留旧数据；新增完整 CLAIMED snapshot 后须保留兼容 reader，
优先向前修复，保留所有 immutable 审批、worktree/分支/草稿和重试历史。

## Same-source context capacity continuation (Console contract v8)

```python
BaselinePurpose.CONTEXT_CAPACITY_RESUME = "context_capacity_resume"
BaselineProposeCommand(..., purpose=CONTEXT_CAPACITY_RESUME,
    target_base_ref=None, input_mode=PRESERVE_DRAFT)
ExecutionBaselineBinding.context_capacity_receipt_sha256: Sha256 | None = None
require_context_capacity_binding(plan: ExecutionBaselinePlan,
    binding: ExecutionBaselineBinding) -> None
```

After a real platform input/configuration repair, capacity waiting can continue without changing
target-project code. It must use this distinct purpose. `SOURCE_REBIND` continues to require a
different execution base and must reject a same-base proposal. Public callers omit the target
or pass `None`; an explicit caller SHA, even the current SHA, refuses. The trusted collector
derives the existing execution base. No public receipt digest, stopped Boolean or attempt override
is accepted. The additive Console operation capability is version 8; an older server cannot
advertise a usable capacity-resume action.

The Plan requires the exact current `claimed_context_capacity` receipt and complete historical
no-start verification described above: original raw claim, full Context/Task/permissions/source,
actual queue reservation, all main invocation/provider/native/artifact contradictions and the
historical baseline selected at original claim time. A capacity receipt never proves an unrelated
execution stopped. Missing or contradictory records still refuse. A prior independent QA FAIL
or Review REJECT remains a role verdict and cannot become a no-start result for the current Coder.

For this purpose, `target_base_ref` equals the currently resolved execution base, prepared source
equals the exact current capture source, and both dirty and complete committed-plus-dirty captures
remain intact. The source can be a committed candidate descendant of the base; equality of source
and base is not required. Native rules cannot change, and source/target native-rule digests remain
equal. Only `preserve_draft` is valid. The Git mutation adapter is skipped: no rebase, patch replay,
reset, index change or branch replacement occurs. Full legal captures and complete inventory are
reread under the existing process/SQL fences before and after operation publication.

Only an exact `BaselineOperatorAuthorization` with `continuation_mode=pause` is accepted.
Automated admission and combined immediate RESUME refuse. The Binding preserves execution base,
source, branch/worktree and before/after inventory, records the exact Plan receipt digest, and
leaves both superseded implementation/progress IDs `None`. Accepted candidate and active progress
therefore remain active under their existing publication order. Existing QA/Review findings,
recommendations, commands, evidence and Context inputs continue to reach Coder; no role verdict
or artifact is rewritten. Full plan/binding association is enforced when producing the Binding,
reading its immutable store and consuming it in the queue. A rehashed foreign receipt, source or
artifact inventory cannot graft authority onto an otherwise locally valid Binding.

The continuation reservation must be `uninvoked`, `reservation_already_applied=true`, with
`current_attempt == next_execution_attempt == task.attempts`. Queue consumption keeps the same
WorkItem identity and frozen attempt, advances only its dispatch generation, and records an
engineering pause. It does not update Task, add/refund work, reserve another attempt or alter
retry budgets. Separate RESUME requires the latest exact Binding, original Task revision,
source, paused disposition and complete unchanged inventory, then performs the existing fresh
claim/Context/Run path. The complete baseline store and `BaselineInitialWorkspaceAdmission`
remain the dirty-workspace gate. Old native receipts may be retired only by the exact Binding;
their immutable records stay in history. The new real final input must be measured again before
provider start. A successful recovery plan does not itself prove that the new input fits.

The optional Binding field uses `exclude_if=None`; old absent/default/explicit-null inputs retain
their canonical omitted wire form and previous SHA. A non-null digest requires explicit new
purpose in static Schemas; other purposes cannot carry it. Canonical generator guards apply to
Plan, Binding, proposal and embedded Console/queue definitions. Cross-record receipt, capture,
authority and reservation relations remain trusted typed service/store/queue checks.

| Input or action | Required outcome |
| --- | --- |
| Two real owned native stops, then claimed final-input capacity before model start | Same Task/WorkItem/attempt, exact PAUSE then separate RESUME; independent QA/Review |
| Accepted progress, prior candidate and real QA FAIL, newer accepted fix progress, then capacity | Preserve candidate/progress and complete finding/evidence inputs; finish same Task |
| Committed descendant source plus legal dirty progress | Exact source/base preserved independently; no source flattening |
| Caller target, `coder_reapply`, native-rule change or same-base `source_rebind` | Refuse before usable proposal or unsafe mutation |
| Automated approval, direct RESUME, stale facts/receipt/source/inventory or foreign artifact set | Refuse; retain original queue and files |
| Binding lacks new purpose but has non-null capacity digest | Model and external Schema refuse |
| Historical Binding absent/default/null capacity digest | Previous serialization/hash and source-update behavior |
| New capacity wait after a previous resume | Require that new generation's actual receipt and fresh measurement; no old approval reuse |

Consumer audit: `domain/execution_baseline.resolve_coder_execution_input` and
`orchestration/runner._current_coder_input` preserve accepted progress/candidate because new-purpose
bindings supersede neither. `orchestration/execution_baseline.BaselineRunContextBuilder` keeps
the existing verified preserved-worktree projection. `context/execution_baseline` and
`capacity_input_reader._CapacityBaselineVerifier` reread the complete store and exact historical
epoch; their authority is not a purpose string. `recovery/baseline_source` reads the same validated
store and reservation without widening its separate legacy terminal exception. Store and queue
call the shared plan/binding guard. Console proposal/execute guidance, scoped operation summaries,
Team engineering history and frontend purpose matching render retained code/progress and the
separate continue step in Chinese. Binding-only operation summaries use a purpose only when the
result belongs to the queried Requirement; full stored Operations are never rewritten.

Historical finalized candidate outputs have an additional exact provenance gate. The platform
CandidateCommitSkill changes an implementation-report's output `source_revision`/`commit_sha`
to its candidate SHA; the immutable original Context and invocation request correctly retain
the input SHA. Capacity investigation must not require those two distinct facts to be equal.
Only `ImplementationReportArtifact` may resolve its input SHA through the unique full original
invocation start, matching successful outcome and exact SQL accepted publication. The outcome's
full artifact content digest must equal the final sealed artifact, with only its seal integrity
fields excluded by the standard artifact digest. Validate producer Run/role/Agent, original
claim/step/attempt/checkpoint, permissions, full Task/Context and historical baseline; check seal
and claim/start time ordering. The SQL receipt must pin exact Task/WorkItem/lease/generation,
Run/Context, output source and artifact digest. Missing, foreign, ambiguous or rehashed altered
records refuse. Git ancestry, equal Task ID or a candidate-looking SHA alone grants no exception.
All ordinary route/progress source equality checks remain, and a current capacity Run/Context/
lease or same-claim output still refuses before this historical candidate helper can authorize
anything. `test_capacity_candidate_provenance.py` covers resealed source/Context/Run/evidence,
missing/duplicate start, missing/foreign outcome, foreign publication and same-claim negatives.

Incremental verification lives in `test_same_base_capacity_baseline.py` (real isolated MySQL,
owned subprocess stops and public Host delivery), `test_capacity_preserved_feedback_public.py`
(accepted progress/real QA feedback through public delivery), `test_capacity_baseline_preserved_inputs.py`
(typed service/store/Context graft and stale checks), `test_same_source_capacity_schema.py`,
operation-summary/transport tests and engineering-history tests. Unit factory artifacts are not
presented as production accepted facts. Provider outputs are fake in fixture delivery; the real
production application remains independently supervised.

存量数据处置：无需 SQL migration，不修改原 Task、WorkItem、capacity receipt、Context、claim、
审批或重试账本，不重建需求。加载兼容版本并实际修复平台输入/配置后，在原需求准备“保留进度继续”
方案，核对原代码、全部现场和调用前停止事实，精确批准并保持暂停，再单独点击“继续原需求”。
新执行仍需独立领取、重新测量容量并经过 QA/Review。旧同基线 source_rebind 方案不静默转换；
以新 purpose 重新准备方案。代码测试与生产审批分开，本实现不操作生产。回滚在新记录发布前可
撤销代码；新 purpose Binding/审批已发布后必须保留兼容 reader，优先向前修复，保留全部历史。
