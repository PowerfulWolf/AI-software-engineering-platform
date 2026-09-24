# Active knowledge contract (T048)

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

## Verification

Shared baseline/index contract tests, immutable-store tamper/replay tests, role
permission tests, knowledge effectiveness fixtures and delivery integration tests.
No Task migration or destructive data conversion is needed for existing requirements.

## Evaluation and completion evidence

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
initial exact recovery still fails closed. See `docs/planning-knowledge-operations.md` for human
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
approvals, Task events or knowledge records are rewritten; see `docs/t046-worker-operations.md`.

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
