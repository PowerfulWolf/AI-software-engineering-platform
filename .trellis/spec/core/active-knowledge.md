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
  BLOCKING gaps prevent progress until an exact approved resolution is present.
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

The joint service invokes these receipts at intake preparation, before committing design, before
planning/plan execution, and at recovery or failure-routing boundaries. Its existing request
stage path itself does not produce delivery claims; the native Delivery Supervisor does. Missing or invalid
proof stops the stage before child delivery; no production model or Artifact verdict is modified.
See `tests/knowledge/test_stages.py` for receipt replay, validator, SIMPLE, failure and binding
regressions. Existing Requirements need no migration: stage proof sidecars are written on subsequent
runs, while historical journal checkpoints remain immutable.
