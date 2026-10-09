# Same-Task execution baseline contract

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
  Required Context contains the verified binding and complete retained patch, with SHA/byte
  checks. It is never shortened to fit a budget; insufficient input capacity becomes an
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

### Accepted artifact order and retained candidates

`compare_artifact_order()` and `latest_accepted_artifact()` are the shared write/read-side
selectors. Only sealed artifacts qualify, including a singleton. A common verified durable
stream orders by sequence/ordinal; otherwise platform `integrity.validated_at` is the legacy
publication clock. Equal publication time requires the full parent/supersedes graph. Provider
`created_at`, file iteration order and random artifact IDs cannot establish current work.
Duplicate identities, cycles and multiple incomparable latest artifacts fail closed.

Resolve the trusted baseline first and exclude its exact superseded implementation/progress
before comparing active Coder progress. Pass the complete accepted history to transitive lineage
comparison. Runtime dispatch, initial draft admission and baseline recollection use the same
selection rule; a replaced old candidate cannot hide a legitimate new-baseline checkpoint.

A terminal blocked handoff advertises only a valid accepted implementation's candidate SHA.
The new execution input and a binding-superseded implementation are not candidates, even when
their source differs from immutable `Task.base_ref`. Waiting and StateEvent source still record
the actual current execution input or independent verifier candidate.

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
