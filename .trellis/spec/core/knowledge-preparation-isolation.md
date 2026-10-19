# Stored knowledge preparation: current engineering isolation

## Scope and trigger

Use this maintenance path only for a nonterminal `IMPLEMENTING` Task whose exact inactive
Coder WorkItem waits in `SERVICE_PAUSED`, has one real original claim and one sealed legacy
knowledge intent/outcome, and has no main-role invocation. The legacy outcome is
`FAILED/SERVICE_PAUSED`, nontransient, with neither execution observations nor a prospective
pre-admission receipt. Missing observations remain **UNKNOWN** historical execution facts.
The forward-only contract is [knowledge-preparation-pause.md](knowledge-preparation-pause.md).

Current containment is a new, explicit `ENGINEERING` decision. It does not establish that
the old transport never started or that an old process stopped, and cannot reuse a prior
local-only declaration for a different invocation. Knowledge preparation is read-only;
the decision still requires complete preservation of the current Coder tree and all
accepted/inherited progress. Same Requirement, Task, frozen base, branch and worktree remain.

## Signatures and wire contracts

```python
BaselineProposeCommand(purpose=BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION, ...)
BaselineExecuteCommand(
    continuation_mode=BaselineContinuationMode.PAUSE,
    confirm_current_knowledge_execution_isolated=True,
    expected_plan_sha256=exact_plan_sha256,
    reference=current_engineering_reference,
    ...,
)
host.continue_execution_baseline(BaselineContinueCommand(...))

read_unknown_knowledge_preparation(
    *, state, task, item, scope, requirement_id, queue, require_step, no_start_reader
) -> tuple[KnowledgeInvocationOutcome, QueueClaim, QueuedRoleStep, str]
require_current_isolation_boundary(
    proof, *, observer, boot, repository_root, worktree_root
) -> None
require_knowledge_isolation_binding(plan, binding) -> None
```

`KnowledgePreparationIsolationProof` (`kind=knowledge_preparation_isolation_v1`) binds the
complete original `QueueClaim`, `QueuedRoleStep`, knowledge intent/outcome, verified context
SHA, native and knowledge Requirement IDs, Task intent/revision, WorkItem/checkpoint,
dispatch SHA and `EngineeringScope`. It includes current boot identity and exactly two
repository-root plus two Coder-worktree OS surveys. All four must be idle, after the old
outcome, and use one machine, boot session, account and scanner boundary. Its canonical
`proof_sha256` covers every field. Constants are `historical_execution_status=UNKNOWN`,
`ordinary_work_consumption=1`, `no_transient_refund=true`.

`BaselineExecutionFacts.knowledge_isolation`, reservation/binding
`knowledge_isolation_sha256`, and execute/authorization
`confirm_current_knowledge_execution_isolated` are omitted when absent. Old records retain
their previous wire bytes and digest behavior. Schemas include
`knowledge-preparation-isolation.schema.json` and the execution-baseline, queue-consumption,
Console-operation and deletion-cleanup contracts generated from the canonical models.

The reservation has only `retry_cause=knowledge_isolation`, `next_execution_attempt=current+1`
and the exact proof SHA. Original main Run/start/outcome/receipt, transient failure/refund,
other proof families and `reservation_already_applied=true` are forbidden. Confirmation is
exclusive, exact-plan bound, and accepted only with `PAUSE` and trusted ENGINEERING authority.

## Validation and execution order

1. The collector reopens complete original journal bytes, verifies filename/envelope/digests,
   exact Requirement scope, frozen snapshot and original claim context. Validate the original
   immutable claim/step, dispatch and checkpoint; reject main-role start/outcome contradictions.
   Inspect every intent belonging to that real lease, including an alias WorkItem or pending
   second call. A single selected WorkItem does not authorize ignoring another lease use.
2. Collect the four current idle surveys and unchanged boot identity. Build the exact plan
   with complete original and inherited patch bodies, tree inventory and source/native-rule
   identities. The caller cannot choose a new target or `coder_reapply` for this purpose.
3. Execute through the existing public Host and baseline service. Reread original facts and
   fresh OS surveys before and after preservation; compare full tree and patch/inventory.
   The binding must retain source/base/inventory, all source artifacts and accepted progress,
   supersede neither implementation nor progress, and carry the exact proof SHA.
4. Under existing MySQL task/queue fences, validate the exact original claim snapshot, step,
   wait disposition, source, allocation/generation and unused ordinary budget. Atomically
   consume one ordinary work allowance, close the old WorkItem and create a fresh PAUSED
   WorkItem. Record `KNOWLEDGE_PREPARATION_ISOLATED`; preserve the old UNKNOWN journal.
   Exact replay returns the original consumption without another attempt or WorkItem.
5. A separate exact `RESUME` revalidates the current containment and preserved tree, then
   releases only the paused successor. Scheduler obtains a fresh claim/Run/Context. Coder
   receives preserved progress; only the platform CandidateCommitSkill creates a candidate.
   Independent QA and Reviewer must inspect that same candidate before DONE.
6. Historical reopening follows stored binding → exact plan → real ENGINEERING authorization
   → isolation proof and rereads the old immutable claim/context/journal. The contained
   unknown claim cannot poison another proved claim, and no Task WorkItem/claim is skipped.
   Build the exact isolated-lease set only from this validated current/historical proof map,
   then pass it explicitly to failed-knowledge, replay-fence and legacy-capacity-snapshot
   readers. Every other intent retains complete validation, including foreign or claimless
   calls. Capacity callbacks capture this set per reader; no ambient mutable skip registry.

## Validation and error matrix

| Input or current facts | Required result |
|---|---|
| One exact legacy unknown pause, current idle boundaries, ordinary budget available | Prepare plan; explicit approval produces PAUSE and one fresh ordinary identity |
| Missing/false confirmation, RESUME at approval, other confirmation supplied | Reject before mutation |
| Foreign joint/Task alias, claim/context/snapshot/source mismatch | Reject; no claim or historical scope is inferred |
| Extra intent on original lease, including alias WorkItem or pending call | Reject the single-call proof |
| Native/HTTP observations, forward pause receipt, missing outcome, main-role invocation | Reject this proof family; preserve original facts |
| Live process, incomplete scan, changed boot/account/scanner/path | Reject proposal/execute/resume; keep draft and pause |
| Changed native rules, source/base, mutation inventory, progress or inherited body | Reject stale plan/binding; no rebase or supersession |
| Ordinary work exhausted | Reject without transient refund or another execution identity |
| Binding proof SHA/purpose/authority/inventory mismatch | Reject in store and queue model, including read/replay |
| Same WorkItem reused as successor or stale original queue facts | Reject queue consumption atomically |
| Exact execute replay | Same binding and consumption, one ordinary allowance only |

## Good, base and bad cases

- **Good:** accepted Coder progress is preserved, old knowledge pause stays UNKNOWN, current
  exact ENGINEERING containment approves PAUSE, separate RESUME produces a candidate and
  independent QA/Review complete on the same Task with one additional ordinary work attempt.
- **Base:** approval succeeds but delivery remains paused until the existing RESUME command;
  a process restart rereads the same proof chain and complete tree before allowing dispatch.
- **Bad:** treating `executions=[]`, a released Lease, READY service, error text or elapsed
  time as historical no-start; inventing a forward receipt; refunding unknown work; reusing
  a foreign declaration; discarding accepted progress; accepting an uncommitted draft as QA
  input; bypassing native QA/Review or rebuilding the Requirement merely to erase history.

## Required verification and stock-data handling

`tests/manager/test_knowledge_isolation.py` covers exact proof/reservation, real Git preservation,
exclusive confirmation, current live/boundary refusal, scope and same-lease alias refusal,
budget exhaustion, absent-field compatibility and queue binding guards.
The capacity and replay tests additionally prove that exact isolated UNKNOWN exclusion
permits the older proved claim while a second unproved foreign claim still rejects the read.
`tests/manager/test_knowledge_isolation_public.py` uses an isolated identity-checked MySQL
database with real Host, journal/context, queue/claim, Git candidate and independent verifier
evidence. Current OS observations use an explicit observer seam; they are fixture facts,
not evidence about any production machine. Verify pause/ordinary accounting, exact replay,
separate resume, unchanged old journal and same-Task QA/Review completion.

No bulk SQL migration or outcome rewriting is needed. For each stored Requirement: inspect
the precise Task/WorkItem/lease/journal; preserve all immutable records and complete patches;
prepare this exact plan from fresh current OS surveys; persist a current trusted ENGINEERING
reference through public execute; validate one paused successor and unchanged history; then
invoke public RESUME and check a new claim. If any proof is missing or a process is live,
leave the WorkItem waiting. Never directly reset Task status or edit old result/stop facts.

Rollback before consumption leaves the original wait and complete draft unchanged. After
consumption retain the new PAUSE and all immutable audit records; correct the platform or
prepare a newly authorized plan. Do not reverse counters, delete history or dispatch the old
claim. Platform rollback must keep unknown-proof admission fail-closed.
