# T047 implementation contract

Manager evaluates a versioned, deterministic PlanningGate over exact ProductSpec and
TechnicalDesign digests. Counts come from approved artifacts; Designer provides typed
migration/interface/backfill/security/performance/concurrency/dependency facts, never a
routing decision. A human upgrade is an immutable fact; no downgrade operation exists.
Simple plans are generated without invoking the Planner model. Gate decisions are saved
before model execution and bound into the Planner context and run receipt.

ExecutionPlan retains the serial Coder → QA → Reviewer demand contract. An optional bounded
work-package graph (maximum 16 packages, 4 concurrent isolated packages) describes modules,
steps, dependencies, acceptance IDs, risk, tests and checkpoints. Parallelism is between
isolated delivery Tasks, never roles in one Task. Legacy plans retain their original digest
because absent extensions are omitted. Exact ProductSpec criteria are referenced, never copied
or edited. Plans with missing/unknown coverage, cycles or overlapping parallel scopes fail.

Revisions reference the previous exact plan and structured feedback. Publication is append-only;
durable gate/run/plan/checkpoint records support fresh-process replay. Dispatch continues through
the existing current-fact Scheduler/ModelRouter and transaction fence; plans confer no allocation
authority. Tests cover deterministic routing, human upgrade, zero-model fast path, graph and
coverage errors, revision immutability, durable replay and existing dispatch capacity drift.

Allowed changes: planning, plan/design domain contracts and schemas, production upstream adapters,
their focused tests and this task's specification. Rollback: revert the code/schema change while
retaining all sidecar records; existing v0.1 documents remain readable without rewriting data.

The trusted Host factory disables native gate generation only for its already committed
`DerivedStageInputs` projection; the joint decision remains the source of routing authority.
Native and joint graph validation share the per-acceptance design test-level preservation
contract. Native revision publication is checked against the latest immutable predecessor before
success receipt/READY, while legacy read/replay remains compatible. Every typed joint semantic
rejection is recorded with exact previous-plan bytes and structured feedback before retry.
