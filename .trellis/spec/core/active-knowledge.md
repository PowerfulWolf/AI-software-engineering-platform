# Active knowledge contract (T048)

## Rejected assessment recovery contract (2026-10-16)

Route-aware HTTP completion and exact existing generic-wait recovery are extended by
[`http-knowledge-rejection-recovery.md`](http-knowledge-rejection-recovery.md). Native
execution still requires real owned stops; HTTP synchronous completion is a distinct fact.

A RETURNED knowledge invocation only proves model output publication. Exact same-run READ
membership and redaction validation remain mandatory. CLAIM_WITHOUT_READ and
ASSESSMENT_REQUIRES_REDACTION on a safely sealed and fully revalidatable RETURNED result
must be precise nontransient/nonretryable INVALID_OUTPUT, with an independently revalidatable
rejected-returned observation. Preserve original RETURNED
bytes; do not invent FAILED outcomes or READ evidence. Claimed delivery enters a real owner-fenced
wait and releases capacity. Generic KnowledgeError is a PLATFORM_BUG wait without semantic retry
authority; KnowledgeGapRaised retains its distinct committed gap wait.
The earlier invocation payload secret guard may reject before RETURNED publication. Preserve
its intent and UNKNOWN status, do not persist unsafe response text or manufacture an outcome,
and grant no semantic retry authority without complete safely sealed facts.

Recovery uses a separate rejected-knowledge proof/resolution through existing Inspect/Resolve/
Continue operations. It binds full original scope/claim/Context/snapshot/READ/native completion,
fixed semantic reason, exact route-aware completion, no-main/route/output/accepted facts and complete unchanged draft input.
Main-fact exclusions bind the target original WorkItem/claim and carry successors, not the
whole Task history. Earlier main runs and accepted progress remain valid; completed knowledge
routes and their independent receipts are required evidence, not forbidden main execution.
It consumes one frozen ordinary work attempt under final Task/SQL fences with new work/Run/claim,
without provider refund, timeout expansion or weakening citation guards. A legacy blocked expired
claim may only reenter under an exact sibling no-main proof; Dispatcher reclaim then a real
fresh-owner carry refusal enters wait before any new knowledge/main call. Unknown/live/late/
foreign/tampered facts refuse. No generic BLOCKED retry or expired-owner mutation is permitted.
The first supported engineering replacement is Coder/IMPLEMENTING only. QA/Reviewer knowledge
consultations still receive exact failure/wait facts but this action grants no verifier retry.
A complete trusted execution-baseline `after_inventory_sha256` must match current file bytes,
modes and ignored/untracked inventory; without that baseline only a clean checkout qualifies.
A later accepted-progress inventory differing from the baseline needs a separately provable
recovery path; this guard does not treat an arbitrary dirty checkout as a checkpoint.

### Executable ports and durable records

- `knowledge.assessment_rejection.derive_rejected_assessment(records_root, binding)
  -> RejectedKnowledgeAssessment` reopens both RETURNED outcomes, actual execution receipts,
  original Task/Context consultation input and structured request digests, complete READ/search
  membership, source visibility and native session emptiness. It never writes the old records.
- `KnowledgeAssessmentRejected(reason, observation=None)` is a nontransient INVALID_OUTPUT.
  A missing complete observation grants no retry: the actual Worker records PLATFORM_BUG using
  its current queued source. Generic KnowledgeError follows the same owner-fenced release.
  A proven semantic rejection remains an engineering wait even at the last frozen work budget;
  Inspect reports BUDGET_EXHAUSTED and offers no necessarily failing continuation.
- `manager.rejected_knowledge_preparation.rejected_assessment_for_work` reads only the exact
  approved Requirement/Task lanes. Empty-query consultations, valid assessments, original FAILED
  and incomplete invocations remain under their existing gates, with no extra model invocation.
- `ProductionProjectDeliveryBackend.rejected_knowledge_retry_scope(checkpoint)` holds the actual
  Task flock through repeated proof and checkpoint append. Sealed recovery/joint lineage derives
  the exact parent Requirement; `require_delivery_requirement_scope` verifies any legacy mapping.
  A nonmatching candidate yields None so other existing recovery routes remain reachable.
  Confirmed semantic candidates with exhausted work/identity budgets refuse before append.
- `UnifiedProjectEntryService.retry_rejected_knowledge_preparation(command, proof_scope=...)`
  only appends DELIVERING for an IMPLEMENTING no-candidate invariant failure; it releases the
  flock before ordinary dispatch. It never reconciles expired SQL ownership itself.
- `carry_rejected_knowledge(task, step, claim, records, state, queue, artifacts, git, scope,
  requirement_id)` requires the actual Worker guard and exact canonical claim before publication.
  A live ownership fence encloses directory/record writes. Every original/intermediate/current
  claim has no main invocation, raw or accepted artifact, route or tool execution. Up to 512
  strictly increasing real claims are supported; each completed intermediate carry must match
  the same observation and precede the next claim. Unknown intermediate ownership refuses.
  Current carry publication is idempotent across a crash before the wait transaction.
- Existing `InspectDeliveryWait` / `HandleDeliveryWait` / `ResolveDeliveryWait` use the new
  `RETRY_REJECTED_KNOWLEDGE_PREPARATION` enum and `rejected_knowledge` proof. Evidence includes
  original/current claim digests, Run/Context, complete inventory/capture digests and ordered
  `carry_history_sha256s`. Absent optional fields are omitted to preserve old wire digests.
  Resolve recomputes under the Task lock and final MySQL fence; replay returns the same successor
  and cannot debit work twice. The frozen timeout and provider failure facts remain unchanged.

Schemas: `rejected-knowledge-assessment.schema.json`, `rejected-knowledge-carry-refusal.schema.json`
and the engineering resolution/Console embedded graphs. Run
`PYTHONPATH=src python scripts/sync-rejected-knowledge-schemas.py`; a second run must change no
schema bytes. This focused generator preserves unrelated handwritten if/then guards.

### Validation matrix and commands

| Case | Required fact/result |
| --- | --- |
| Good: native semantic refusal, exact original input and independently ended execution | Original RETURNED retained; owner wait releases all Lease capacity |
| Base: empty queries, valid consultation, stopped local-limit or incomplete earlier result | No semantic carry; original gate remains authoritative; zero extra calls |
| Legacy positive including a joint parent | Task-lock proof precedes append; fresh real owner refuses before any new call |
| Crash after carry but before wait, followed by another blocked public reentry | Revalidate every intermediate carry; next owner releases; zero duplicate model calls |
| Exact decision then repeated consumption | Ordinary work +1 once; new work/claim/context; same source/progress/history |
| Foreign parent, live owner, missing READ/stop, raw output/late main, draft drift or exhausted budget | Refuse without a new delivery/queue/model fact |
| Decision published for a joint child | Investigation/handling/resolution all use the same parent/native scope in history |

Contract tests: `tests/knowledge/test_assessment_rejection.py`,
`tests/manager/test_rejected_knowledge_guard.py`,
`tests/manager/test_rejected_knowledge_delivery_entry.py`,
`tests/work_queue/test_rejected_knowledge_contract.py`.
Run isolated native/MySQL tests serially with the identity-checked `ASE_TEST_MYSQL_DSN`:
`tests/manager/test_rejected_knowledge_native_entry_mysql.py`,
`tests/work_queue/test_rejected_knowledge_mysql.py`,
`tests/work_queue/test_rejected_knowledge_replacement_mysql.py`.
The replacement test uses the real Supervisor and independently assigned Coder/QA/Reviewer;
fixtures are delivery-mechanism evidence, not proof that production K1 has completed.
Read-side regressions are `tests/team_view/test_engineering_history.py` and
`node --test tests/team_view/engineering-wait.test.cjs`.

### Existing-data treatment

No schema/database migration, old outcome rewrite, transient refund or terminal reset is used.
For a precise legacy blocked case, public Continue establishes reentry, fresh ownership enters
wait, Inspect/Handle seals the exact engineering decision, then normal Continue runs fresh
knowledge preparation and delivery. Preserve all historical blocked/UNKNOWN/progress records
and original checkout bytes; final delivery still requires independent QA and Review.

## Scope and signatures

`KnowledgeRetrieval.search(snapshot, query, limit) -> tuple[KnowledgeHit, ...]` and
`KnowledgeRetrieval.read(snapshot, citation) -> KnowledgeChunk` are deterministic
read-only adapter ports. `KnowledgeSkillRegistry.search_knowledge/read_knowledge`
bind them to `KnowledgeRunBinding` and immutable evidence publication. Agent inputs
never accept paths. Snapshots are created by the application from verified selected
documents, active applicable Specs and discovered native rules, not by Agents.

## Invariants

- Owner, repositories, roles, exact document SHA and snapshot SHA are checked before
  returning text; descriptive knowledge remains distinct from native rules and Specs.
- Search/read/refusal evidence is appended before returning. Reads require an exact
  prior search hit from the same run. Replay with changed operation content fails.
- A new selection cannot rewrite a frozen requirement. Retired/replaced documents
  cannot enter new snapshots; historical snapshots retain exact verified bytes.
- Gap, route, resolution and resume records preserve original run and evidence.
  Human-owned BLOCKING gaps prevent progress until an exact approved resolution is present,
  except the explicit, scoped upstream investigation handoff described below (not approval).
  A gap with `gap_owner=REPOSITORY` may continue only when runtime composition has explicitly
  bound the exact repository revision to a read-only model client. The final role prompt must
  require repository inspection and must not ask the user to paste source or READ output.
- Workflow definitions are Team-owned, versioned and role-scoped. Learning proposals
  are not executable registrations. Missing evidence/version drift rejects a gate.
- Knowledge is redacted before reaching an Agent or evidence record; raw digests remain
  provenance, and redacted chunk digests describe the bytes actually delivered.
- Source role restrictions survive snapshot compilation, including nested `context.team` and
  structured Specs. Parent/child roles intersect; no intersection means exclude, not unrestricted.
  ORCHESTRATOR-only sources do not map to an arbitrary Team role. A Spec targeting a different
  repository is excluded, never turned into wildcard scope by an empty ID intersection.
- `KnowledgeSkillRegistry.available_documents() -> tuple[KnowledgeDocument, ...]` supplies the
  same role-filtered inventory for consultation metadata and search/read. Titles and IDs are
  information too: filtering retrieved body text alone is insufficient.

## Validation matrix

| Case | Outcome |
| --- | --- |
| Good: selected answer and exact citation | bounded hit/read and durable evidence |
| Base: no answer | empty search and structured Gap |
| Bad: cross Project, unselected or modified document | refusal evidence, zero text |
| Invented or another run's citation | refusal, no read |
| Changed operation replay | conflict, first evidence preserved |
| Approved resolution after restart | new run referencing Gap, resolution and old run |
| Missing Skill evidence or different definition version | reject stage gate |
| Coder-only source queried by QA, including nested wrappers | no hit/read and no discovery title |
| Disjoint wrapper/Spec roles or foreign-repository Spec | excluded, not broadened to all roles/repos |

## Verification

Shared baseline/index contract tests, immutable-store tamper/replay tests, role
permission tests, knowledge effectiveness fixtures and delivery integration tests.
No Task migration or destructive data conversion is needed for existing requirements.

`tests/knowledge/test_source_scope.py`, `test_delivery_context.py` and `test_consultation.py`
exercise native/Team/Project sources, nested wrappers, foreign Specs and metadata visibility.
Good: Coder sees its scoped reference; QA cannot discover its title. Base: unrestricted sources
keep their prior serialized roles. Bad: `roles=()` after losing a restriction, or `repository_ids=()`
after intersecting away every allowed repository. Never rewrite a stored historical snapshot to
hide prior visibility; current incompatible scoped snapshots must fail closed under existing guards.

## Evaluation and completion evidence

### Complete knowledge invocation receipts

`KnowledgeInvocationJournal(records, *, claimed: Callable[[], QueueClaim] | None).call(
binding, phase, *, client, instructions, input_payload, output_schema, timeout_seconds)`
persists an exact `KnowledgeInvocationIntent` before invoking a model. The request digest covers
instructions, payload, output schema and finite timeout. Delivery composition supplies the actual
Worker claim through `KnowledgeRunContextBuilder(..., invocation_claim=knowledge_claim)`; the
stored claim must match Task, role and repository. Upstream stages retain their existing exact
reservation/approval gates and do not fabricate Delivery claims.

Records live under `knowledge_records/invocations/<scope digest>/`. The scope is exactly Team,
Project, Requirement, repositories, Task and role; Run, Context, source revision and lease are
deliberately excluded. `invocation_scope_lane_sha256(...)` is shared with read-side consumers;
callers must not construct fake bindings to locate a lane. The immutable intent/outcome key is
`run_id + ':' + phase`. `KnowledgeRecordStore.list(..., limit=512)` checks matching filenames
before decoding any record, and rejects oversize lanes rather than returning a partial history.

Each actual route saves a typed admission under the current execution guard before native spawn
or HTTP transport. The owned runner saves `NativeProcessStop` before translating timeout,
nonzero exit or invalid JSON. A dedicated `StructuredNativeNotStartedReceipt` is valid only
when the owned runner proves `Popen` did not return a process; it has no PID or synthetic stop.
Post-spawn ownership errors require actual controlled cleanup and remain execution-uncertain.
HTTP round-trip receipts describe local synchronous transport completion, never remote stop.
See [structured execution observation](structured-execution-observation.md).

`KnowledgeExecutionRecord` independently seals each admission/completion before the final
`KnowledgeInvocationOutcome` (RETURNED/FAILED). Outcome embeds the exact intent, bounded and
redaction-checked result or typed error metadata, and all complete route records. Both outer
store digest and inner integrity/identity are checked on replay. Successful fake clients may
have empty observations; that is data, never proof of native stop or authority to recover.

| Case | Result |
| --- | --- |
| Exact complete success or failure after restart | Revalidate independent records and replay; no new model call |
| Changed input, schema, timeout, Context or source in the same Run | Reject exact replay; preserve original facts |
| Intent without complete outcome | Refuse original Run and new Run/Context/source in the same lane |
| Actual stop saved, outcome publication fails | Retain stop independently; do not infer an accepted result |
| Owner lost while a route is in progress | Preserve actual completion; prohibit new fallback admission and outcome mutation |
| Observation write fails | Execution-uncertain, no fallback and no provider transient refund |
| Missing executable before spawn | Typed NOT_STARTED; a still-authorized configured fallback may proceed |
| Secret-bearing result or corrupt receipt/hash | Reject publication/replay without exposing original payload |

These receipts do not authorize automatic retries, new claims, approvals, candidates, verdicts
or terminal Task revival. Local execution limits remain distinct from provider transient
failures. A same-Task automatic continuation additionally requires real claim authority,
frozen budget and original workspace validation; a stop digest alone is insufficient.

Required regression coverage: `tests/knowledge/test_invocation_receipts.py`,
`test_invocation_native.py`, `test_schema_parity.py`, and
`tests/agents/test_structured_observation.py`. Exercise all seven roles, real process fixtures,
cross-process replay, incomplete records, write failures, fallback fencing and original error
metadata. Old consultations/model-call/gap bytes and digests are unchanged. Old unknown executions
receive no synthetic backfill; use the existing public exact recovery path. Active executions
are not hot-loaded or rebound when deploying this change.

`KnowledgeModelCall` persists actual provider/model, usage, duration and output digest for each
consultation call. `KnowledgeEvaluationReport` uses nullable metrics when their denominator is
zero; omitted nulls must round-trip through the standard `DomainModel.to_wire` contract.
The offline paired corpus derives citations and usage from actual consultation records, tests
conflicts/retirement/scope leakage, and exercises approved Resolution → Learning proposal →
separate human publication → new Requirement retrieval. It is deterministic fixture evidence,
not a measurement of live-provider decision quality.

`KnowledgeDeliveryGate` resolves sealed parent artifacts before QA, Review and DONE, verifies
candidate equality, acceptance/test coverage and independent producers, and saves exact artifact
digests in `DeliveryWorkflowProof`. Registry validation binds each skill to the proof's target
stage; a valid implementation proof cannot serve as review or completion evidence.

`KnowledgeHumanActionRecorder.record(task, case_id, events)` runs after CaseStarted and before
delivery resumes. It publishes idempotent standard `HumanActionEvent(CLARIFY_REQUIREMENTS)`
for approved Task resolutions and inherited Requirement resolutions. ADR therefore records human
intervention instead of counting the recovered delivery as autonomous. No historical event is
rewritten. The knowledge-specific approval event remains the exact-resolution audit source.

## Production context and recovery boundary

`KnowledgeRunContextBuilder.build` runs a bounded knowledge consultation before the final
Delivery `AgentRequest` exists. It persists the consultation as an explicit section of a new
`ContextBundle`, with normal token accounting and content-addressed identity. The consultation
has its own run bound to the parent context, Task, role and frozen snapshot; the role's final
Artifact references the enriched Context. A prompt builder must never append unmanifested
knowledge after this boundary. Approved resolutions form a new parent context and consultation
run, retaining the original run and gap. Repository-native rule bytes retain their source IDs.
Full frozen sources always feed `snapshot_from_sources`; replacing them with prompt pointers
would destroy body search and change the snapshot identity used by approved gap resolutions.

Production prompt compaction is a separate `native_rule_prompt_sources` projection, enabled
only alongside active consultation. All AGENTS.md bodies remain inline; other native rules
carry `native.reference.*` URI/redacted-body digests. After consultation, compact Contexts add
required `knowledge.reads` before the receipt. `retrieved_context_section(consultation, records)`
verifies immutable READ evidence against its binding, snapshot, role visibility, prior search
hit and exact frozen chunk, then deterministically deduplicates citations. Reads have ordinary
Context token accounting and hashes. Missing/mismatched evidence or overflow fails closed.
The delivery gate recomputes the same section and permits exactly parent + reads + receipt;
legacy contexts without reference projection retain the parent + receipt contract. Original
snapshots, gap resolutions, consultations and Artifact Context IDs are never rewritten.

Regression coverage: `tests/manager/test_joint_context_limits.py` exercises full joint stage
payloads, profile/baseline and serial role artifacts alongside frozen READ text. Native rules
must remain searchable by body-only terms; resumed approved resolutions keep their snapshot
binding. `tests/knowledge/test_prompt_projection.py` checks restart and rejects wrong evidence
bindings/content, removed READ sections and over-budget required evidence.

The native production error guard must propagate `KnowledgeGapRaised` to the Requirement
coordinator, which journals WAITING_HUMAN without terminating the delivery Task. No verdict is
produced by a consultation. Search operation replay repairs the exact by-ID evidence entry
before returning, including an interruption between exclusive publications.

Good: missing facts stop before commands, resolution approval creates a new context and the
same Task resumes at its last delivery checkpoint. Bad: translating a gap into an invariant
failure, or changing the frozen knowledge selection to resolve it. Tests must assert both
the persisted enriched Context and fresh-process recovery.

### Repository inspection fallback

`KnowledgeAssessment.gap_owner` is `HUMAN` or `REPOSITORY`. The assessment prompt may select
`REPOSITORY` only when the missing fact can be established from the bound repository at the
exact `source_revision`; product decisions, external facts, stale or conflicting evidence stay
`HUMAN`. `KnowledgeConsultationService(..., allow_repository_inspection=True)` is the explicit
composition seam that permits this continuation. Without that flag, every `GAP` remains blocking.

The non-blocking receipt remains immutable with `assessment.status=GAP` and is passed to the
final role call. `KnowledgeAwareStructuredClient` adds a bounded instruction to inspect the
repository read-only and report contradictions. It never converts a human-owned gap into a
successful consultation. Upstream joint Product/Designer/Planner composition and native
Delivery context composition set the flag only alongside a repository-backed client.

| Case | Outcome |
| --- | --- |
| Good: `gap_owner=REPOSITORY`, exact source revision and read-only client | persist GAP receipt, continue final role call |
| Base: `gap_owner=REPOSITORY` without the composition flag | persist blocking Gap and wait for approval |
| Bad: `gap_owner=HUMAN`, conflict, stale fact, or invented citation | persist blocking Gap; no final role call |

The regression test must assert that a Designer receives the final call and its instruction to
read the bound repository, while the same assessment through a non-authorized service still
raises `KnowledgeGapRaised`.

Human-facing Knowledge Gap descriptions are Chinese application facts. The assessment prompt
requires Simplified Chinese for `gap_question`; before publication, a non-Chinese model question
is replaced by the bounded Chinese fallback instead of being translated or trusted. Platform-owned
`required_decision`, impact and routing reason strings are Chinese as well. Existing immutable gaps
are not rewritten, and the Console keeps compatibility for the former English fixed decision text.

`KnowledgeDeliveryGate.begin_task` freezes a one-time `DeliveryWorkflowAdmission` before new
role work. For an existing non-NEW Task it records exact already-sealed legacy Artifact IDs and
digests. Only those artifacts may resume with the original native gates and unchanged Context;
new artifacts require consultation. This handles an upgrade after Artifact publication but before
its StateEvent without fabricating knowledge evidence or retrying a completed Coder. NEW Tasks
have an empty exemption list. Admission replay never adds later artifacts.

First gap recovery preserves exact source revision. After that exact recovery is durable,
`KnowledgeResume.previous_resume_sha256` links later candidates' reuse of Requirement facts to
the first recovery, while retaining the new revision/run/context. A changed candidate with no
initial exact recovery still fails closed. See `docs/operations/planning-and-knowledge.md` for human
resolution API, existing data handling and rollback.

## Persistent queue wait boundary

```python
QueueKnowledgeWaitPort(queue: PersistentWorkQueue, *, claim: QueueClaim,
                       owner_token: str, binding: KnowledgeRunBinding,
                       records: KnowledgeRecordStore,
                       clock: Callable[[], datetime])
QueueKnowledgeWaitPort.wait(binding, routing) -> None
```

A trusted role worker may construct this adapter only from its actual Dispatcher `QueueClaim`
and in-memory owner token. It must explicitly pre-bind the exact consultation `KnowledgeRunBinding`
from its verified Context. The constructor cross-checks Task ID, role and the one repository against
claim facts. Every call requires equality of the complete pre-bound record, including Team, Project,
requirement, consultation run ID, source revision, Context ID and snapshot digest. T046 `QueueClaim`
does not contain Team/Project or a consultation run ID; the trusted worker composition supplies those
coordinates. Do not infer the consultation run from a WorkItem ID, namespace or delivery run ID.

Before releasing capacity, the adapter reads the persisted gap and route, checks their digests,
requires a BLOCKING gap with the same binding, and checks the route/wait-status mapping. It reads
the current WorkItem and rejects changed attempt/checkpoint/dispatch/repository identity or an
already waiting/closed item. Then it calls only `PersistentWorkQueue.wait` with exact work item,
lease ID, owner token, aware clock, waiting status, and digest-only gap/route reason. The native
MySQL transaction rechecks the active claim, token and current lease expiry and atomically marks
WAITING_HUMAN/WAITING_DEPENDENCY plus RELEASED. The adapter never writes Task status or verdicts.
Owner tokens are never placed in knowledge records or queue reasons. A repeated wait is rejected,
not accepted merely because another owner already put the WorkItem into a waiting state.

Good: a real Coder/QA/Reviewer claim reports a persisted blocking gap, waits and releases capacity.
Base: a route has durable facts but no queue authority; it cannot create a claim or mutate scheduling.
Bad: fake claim construction from a consultation ID, accepting changed-run replay, expanding a
single-repository claim to a joint repository set, or treating an expired owner as a successful wait.
`tests/knowledge/test_queue.py` covers exact binding, route integrity, waits, stale ownership and
replay; `test_queue_mysql.py` applies the same bridge to the existing guarded real-MySQL fixture.

Production `ase request`/Console uses a real per-role Worker claim before Delivery Context creation.
`WorkerKnowledgeWait` binds that claim to the consultation and releases capacity through
`QueueKnowledgeWaitPort`. A route persisted before the wait can be replayed by its next active owner;
an already committed wait resumes only after its stored Resolution is validated. Requirement
WAITING_HUMAN remains separate from Task checkpoint and queue scheduling status. No historical
approvals, Task events or knowledge records are rewritten; see `docs/operations/worker-operations.md`.

## Upstream stage workflow gates

T048 stage skills are deterministic receipt gates over the Project Requirement journal. `start`,
`architecture-check`, `planning-gate`, `plan`, `recovery` and `break-loop` may be reported as
`PASSED` only from a persisted `StageWorkflowProof` containing the exact current
`JointCheckpoint` and, where applicable, the validated TechnicalDesign, compiled ExecutionPlan,
blocking Gap/approved Resolution, or recorded failure/child checkpoint facts. A consultation or
knowledge manifest by itself never satisfies an upstream stage gate.

`StageWorkflowGate` stores the verified snapshot, checkpoint, proof, and ordinary
`WorkflowSkillEvidence` before the stage action proceeds. Proof identity binds Team, Project,
Requirement, repositories, role, source revision, Context and a deterministic stage run ID; the
record is content-addressed and replayable. `start` requires every selected unit to have a
PREPARED, integrity-valid preparation, exact repository root and committed base revision.
`architecture-check` calls the authoritative design validator. `planning-gate` recomputes the
Manager `PlanningDecision`; `plan` calls the authoritative plan validator and mechanical compiler,
including exact work graph/test coverage. SIMPLE plans remain zero-model deterministic output.
`recovery` requires an exact blocking gap/resolution lineage or concrete blocked delivery facts;
`break-loop` requires persisted rejected-plan feedback, failed integration evidence, or an
integrity-checked native child with BLOCKED/FAILED Task status plus explicit exhausted-budget or
repeated delivery-attempt facts. The proof retains original failure classification and checkpoint;
it does not claim a business fix or change the failed verdict. Knowledge recovery also reads back
the exact approved resolution from its owning record store before receipt publication. A gate cannot
create a Task, Assignment, Lease, verdict or approval.

The bounded Design-budget recovery is the one historical-checkpoint exception: callers may pass
`StageWorkflowGate.require("recovery", historical_checkpoint, ..., historical=True)` only after
proving that the immutable checkpoint digest is an ancestor in the current `JointJournal` hash chain.
The proof still records the historical `WAITING_HUMAN` checkpoint and exact Gap/Resolution lineage;
`historical=True` is rejected for every other skill and does not authorize edits to that checkpoint.

The joint service invokes these receipts at intake preparation, before committing design, before
planning/plan execution, and at recovery or failure-routing boundaries. Its existing request
stage path itself does not produce delivery claims; the native Delivery Supervisor does. Missing or invalid
proof stops the stage before child delivery; no production model or Artifact verdict is modified.
See `tests/knowledge/test_stages.py` for receipt replay, validator, SIMPLE, failure and binding
regressions. Existing Requirements need no migration: stage proof sidecars are written on subsequent
runs, while historical journal checkpoints remain immutable.

## Planning knowledge handoff and explicit design recheck

- Joint knowledge `source_revision` remains the historical aggregate scope fingerprint,
  NOT a Git revision. `repository_inspection` supplies each unit's repository ID, validated
  read root and actual Git revision. New consultations use a versioned identity. Candidate
  inspection must use the candidate revision, not the original baseline.
- Approved upstream resolutions are authoritative inputs across Product/Designer/Planner.
  Repository questions are delegated to read-only inspection; absence from the knowledge
  index is not absence from the repository. Designer owns implementation decisions under
  the approved scope; Planner decomposes and checks feasibility, not product rediscovery.
- New designs explicitly return `blocking_issues=[]` when ready. Nonempty issues or an
  omitted readiness declaration consume bounded Designer correction attempts and cannot
  reach Planning. Legacy persisted designs remain hash-compatible and readable.
- `RECHECK_DESIGN(delivery_id, expected_checkpoint_sha256)` is an explicit human request
  to investigate an unresolved Design/Planning gap before dispatch, NOT a resolution or
  approval of a proposed behavior change. The journal atomically appends a DESIGNING
  successor with typed recheck lineage, retained exact Product approval and unchanged
  budgets. Stale checkpoint, resolved gap, wrong scope/stage, children and exhausted
  Designer budgets reject before writes/model calls.
- Only gaps named by validated recheck lineage cease blocking that requirement's upstream
  investigation. Original questions remain required model input and visible history.
  New gaps still block. No generic gap deletion, synthetic answer or budget reset is allowed.
- Read-side `knowledge_wait_stage` comes from the durable checkpoint. WAITING_HUMAN is
  a pause, never an implicit return to Product; an unknown origin highlights no stage.
- Regression points: exact baseline/candidate context, cross-role approved facts, new human
  gap after recheck, restart/stale replay, no recheck model call, budget preservation,
  blocker correction, legacy receipt hashes and paused-stage rendering.

### Executable boundaries

- `multi_directory/service.py`: `JointDeliveryService.recheck_design(RecheckDesign)`
  returns `JointDeliveryResult` after one append. It does not call `_advance`.
- `web_console/models.py`: `RecheckDesignIntent` carries `action=RECHECK_DESIGN`,
  `project_id`, `delivery_id`, `expected_checkpoint_sha256` through the existing operation API.
  Manager binds `operator_id=web-console` and a checkpoint-bound `request_reference`.
- `JointCheckpoint.knowledge_rechecks[]` embeds `DesignKnowledgeRecheck` with original
  `gap`, `source_checkpoint_sha256`, `product_spec_sha256`, operator/reference/time.
  `JointJournal._validate_successor` verifies one appended recheck and the exact predecessor;
  it permits clearing the old design/decision only at that handoff. Later accepted design
  bytes are a new journal revision; old design bytes are never rewritten.
- `JointTechnicalDesign.blocking_issues` is required in new model requests. Absent fields
  on historical records serialize as absent, including nested stage-proof digests. This
  uses Pydantic `exclude_if` (minimum 2.12). `design_feedback` stores rejected full drafts
  for the next bounded correction, not as an accepted design.
- `knowledge/recheck.py` compares Team/Project/Requirement/repositories/snapshot/source
  bindings; `KnowledgeConsultationService` also checks the original gap in the record store.
  Stage gates consume the recheck-bearing verified journal. Generic `unresolved()` and
  Delivery-role behavior remain unchanged. A cached sufficient consultation cannot mask
  another unresolved human gap.

| Case | Result / assertion |
| --- | --- |
| Good: unresolved Planning gap, approved Product, no child, budget available | One DESIGNING successor; approval/attempts unchanged; no model call |
| Base: ordinary approved human answer | Existing resolution/resume path; no recheck needed |
| Bad: stale digest | `DeliveryCheckpointStale`, no append |
| Bad: resolved/foreign/Product/post-dispatch gap or exhausted budget | Reject; no model call, no append |
| Bad: readiness absent or blockers present | Bounded Design correction; no Planning/dispatch |
| Bad: a new human gap after recheck | WAITING_HUMAN; original recheck cannot bypass it |
| Unknown wait origin | No active Product highlight; do not infer a stage |

Tests: `tests/knowledge/test_joint_recheck.py`, `tests/manager/test_joint_designer_feedback.py`,
`tests/team_view/knowledge-gap.test.cjs`, `tests/web_console/test_manager.py` and schema parity.
Existing data requires no SQL migration: restart, refresh the affected Requirement, request
“重新核对设计”, then “继续交付”. If Designer budget is exhausted, raise its configured limit
and restart first; never reset attempts or approve a suggestion merely to unblock execution.
Rollback before any recheck uses a code/schema revert. After a recheck has been appended,
older binaries cannot read the new fields; keep compatible readers or roll forward. Do not
delete journal entries to make a downgrade work.
