# Planning Gate and bounded complex planning

## Scope / signatures

`PlanningGate.classify(PlanningFacts, upgrade=None) -> PlanningDecision` is pure, versioned
Manager policy. `PlanningFacts.from_design(ProductSpec, TechnicalDesign)` binds exact artifact
digests. `PlannerStageService.produce` persists the decision before invoking an adapter and uses
the deterministic fast generator for SIMPLE decisions. Planner has no gate routing authority.

## Contracts

- More than one repository/component, explicit work-package dependencies, migration, interface
  compatibility, backfill, security, performance, concurrency, normal/high/critical technical
  risk or multiple integration groups select COMPLEX. Absent legacy structured facts are
  treated conservatively where the design already supplies evidence.
- Human upgrade carries operator, rationale, exact input digest and timestamp; downgrade is
  not represented. Gate decisions, human upgrades and rejected plans remain immutable.
- A complex plan includes 1..16 work packages, each with exact component/design-step/acceptance
  references, risk, checkpoints and test matrix. Packages declare dependency IDs and order.
  Maximum parallelism is 1..4 and parallel packages have disjoint repository/component scopes.
- Every Task still executes Coder → QA → Reviewer. No concrete Agent/provider/model/Assignment/
  Lease may appear in plan output. Preview is read-only; Manager dispatch recalculates current
  capacity/model/dependency facts under the existing authority fence.
- Revisions include the previous ID/digest and structured feedback; stores require contiguous
  versions and exact immutable predecessor. Optional extension fields are omitted when absent,
  preserving old content hashes.
- The joint gate is authoritative for a committed Requirement plan. Only the trusted Host
  composition that supplies `DerivedStageInputs` sets `trusted_plan_projection=True` on the
  native backend; the native stage validates and journals that mechanical projection without
  rerunning classification or replacing its work graph, phases, risk or checkpoints.
- `validate_execution_plan_revision(plan, latest)` runs before a successful Planner receipt
  or READY revision and on new store publication. Initial plans require version 1 without
  feedback; revisions require the exact latest ID/digest, feedback and next contiguous version.
  Invalid lineage yields an `INVALID_OUTPUT` failure receipt and no READY/checkpoint. Existing
  legacy records are still readable and exact replay remains idempotent; reads do not retrofit
  the new publication rules onto their immutable content.
- `validate_plan_test_matrix(graph, required_levels)` is shared by native and joint validation.
  For each acceptance ID, every Design `test_levels` entry must occur in that criterion's plan
  tests; merely mentioning the criterion or substituting a weaker level is insufficient.
- Every semantically rejected typed joint plan, including graph components/steps/dependencies
  and test-level failures, remains in `JointPlanFeedback.previous_plan`. Its next attempt reads
  that immutable rejection and compiled revisions bind its exact digest.

## Validation matrix and tests

Good: one component/no complexity produces a deterministic three-phase plan with zero calls.
Base: high-risk sequential packages produce full acceptance/test coverage.
Bad: cycles, unknown acceptance IDs, weakened/missing test coverage, overlapping parallel scopes,
allocation fields, changed replay or unsupported gate versions fail closed.
Native receipt tests additionally cover initial feedback, absent feedback/predecessor, wrong
digest, stale predecessor and version gaps. Joint restart tests cover semantic rejection and
subsequent revision. The backend projection test verifies the regular SIMPLE route makes zero
adapter calls while trusted projection preserves the committed graph and phase demands.

Focused commands: `pytest tests/planning tests/manager/test_production_agents.py tests/manager/test_dispatch.py`;
schema parity, Ruff and strict Mypy are required. Gate and run stores must survive a fresh-process
read; existing dispatch tests remain the capacity-drift and atomicity boundary.

## Existing data / rollback

No database migration or rewriting of approvals, Task/Operation queues or historical plan bytes
is needed. Legacy plans omit new fields and preserve hashes. Resume a paused Requirement through
the existing Manager resume command; a rejected PLANNING checkpoint retains feedback for the
next bounded attempt. Existing terminal Tasks and exhausted budgets still use their explicit
human recovery flow. Roll back code/schema changes together and retain sidecar evidence; never
delete a rejection or change an approval to force dispatch.
