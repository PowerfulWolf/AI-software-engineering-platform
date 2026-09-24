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
- Test levels are exact design keys: `manual_ui` and `accessibility` require separate
  `PlanTestItem` entries, never the invented combined key `manual_ui_accessibility`.
  New joint Planner calls carry explicit per-unit `required_test_matrix` and constrain the
  output level enum to design-provided levels. The shared semantic guard remains authoritative.
- Missing design test coverage raises typed `PlanTestMatrixError`; joint feedback records
  its criterion/required/observed/missing levels. Only that typed rejection is automatically
  corrected under the existing configured Planner work budget, with each failed response
  consuming work and retaining an immutable predecessor. SIMPLE, unknown errors, policy or
  approval failures are not automatically retried; provider errors retain transient accounting.
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

## Scenario: exact test matrix and bounded joint correction

### Scope / trigger and signatures

Joint Planner output can be valid JSON while weakening Design coverage. In
`domain/project_delivery.py`, `validate_plan_test_matrix(graph, required_levels, *, unit_id=None)`
raises `PlanTestMatrixError(issues: tuple[PlanTestMatrixIssue, ...])`, a `ValueError` subtype.
Each issue contains `unit_id?`, `acceptance_criterion_id`, `required_levels`, `observed_levels`,
and `missing_levels`; levels and criterion order are deterministic. Native plans reuse the guard.
`multi_directory/planning.py::planner_test_requirements(design)` returns typed
`PlannerTestRequirement(unit_id, acceptance_criterion_id, test_levels)` entries.

### Contracts

`JointDeliveryService._produce` supplies `required_test_matrix[]` separately from existing
`required_coverage`. A fresh invocation schema sets `PlanTestItem.level.enum` to the union of
accepted Design levels; persisted/legacy schemas keep `level: string`. The enum prevents invented
names but does not prove per-criterion coverage, so the deterministic guard remains mandatory.
Never infer aliases or split arbitrary model strings into accepted tests.

`JointPlanFeedback.test_matrix_issues` is optional/nonempty when present and omitted when absent,
including nested checkpoint and stage-proof serialization. Structured matrix feedback uses
`reason_codes=["PLAN_TEST_MATRIX_MISSING_LEVELS"]`, retains the entire rejected `previous_plan`,
and lists exact corrections. A later accepted plan binds predecessor and feedback digests through
`compile_joint_plan`; rejection never becomes an accepted plan, dispatch or approval.

Only COMPLEX typed matrix rejection loops automatically, reserving a new Planner work attempt each
time. On final rejection preserve `PlanTestMatrixError`, not a generic exhaustion message. Other
validation/permission/lineage errors stop. Knowledge waits refund only the unfinished producer
inside `_stage_output`; waits in gates or after rejected responses do not refund spent work.

Console translates the terminal error to `PLANNER_TEST_MATRIX_REJECTED`. `stageFailureGuidance`
drives list/detail guidance from the latest Operation code, not diagnostic success or stale feedback.
Legacy `COMMAND_REJECTED` means platform validation, not a provider outage. Exhaustion and exact
approval precedence remain unchanged; a running operation hides duplicate retry actions.

### Validation / error matrix

| Input/failure | Result |
| --- | --- |
| Separate `manual_ui` + `accessibility` for exact criterion | Coverage passes |
| Combined `manual_ui_accessibility` | Both exact levels missing; feedback + bounded correction |
| Repeated matrix rejection at Planner limit | Typed failure, no dispatch; counters survive restart |
| SIMPLE generator coverage error | Stop after one generation; no zero-cost loop |
| Malformed JSON/schema or unrelated validation failure | No matrix correction; work remains spent |
| Typed transient provider failure after a rejection | Refund only current call; increment `plan_transient`; stop |
| Unknown interruption | No refund or automatic retry |
| Knowledge wait between corrections | Preserve already rejected work; refund only an unfinished producer |

### Good / Base / Bad and required tests

Good: combined then separate fake responses complete planning in one resume with work count 2.
Base: legacy feedback without the extension round-trips unchanged; an increased operator budget
allows a later call without altering the immutable journal prefix. Bad: silently accepting aliases,
retrying arbitrary `ValueError`, or refunding prior rejected work bypasses the contract.

Run the incremental files `tests/manager/test_joint_planner_test_matrix.py`,
`test_joint_planner_feedback.py`, `test_stage_retry_budget.py`,
`tests/planning/test_complex_planning.py`, `tests/web_console/test_manager.py`, and
`tests/team_view/knowledge-gap.test.cjs`. Assert exact input/schema/feedback lineage, budget boundary,
restart prefix, no premature delivery and error-specific UI. Check checkpoint/stage-proof schema
parity and read legacy journal/proof hashes without writing production data.

### Wrong vs correct / bug analysis

- B/E (cross-layer contract/implicit assumption): unrestricted level text was treated by the model
  as a descriptive label, while the validator required exact keys. Input matrix, per-call enum and
  semantic guard now agree; no weaker validation is introduced.
- The prior planning/knowledge fix addressed a different boundary. It could not prevent this
  artifact-level rejection. Restarting or repairing credentials cannot repair a test matrix.
- D (coverage gap): tests now exercise invalid→corrected output and provider/knowledge interruptions
  between corrections, rather than checking only isolated validators.
- Native validation shares the typed guard; automatic correction is deliberately joint-only because
  native receipt/commit recovery has a different protocol. No template mirror exists in this repo.

### Current Requirement recovery / rollback

For the diagnosed `delivery_multi_bd73c5ce9fa226eaa8e427b5c7c1dd96dce1e006`, no data repair is needed.
Checkpoint 45 remains PLANNING with Product approval, Design and rejected plan retained; observed
Planner work was 1/5. After restarting the updated service, refresh and click **重试 Planner**.
Do not recreate the Requirement, answer the obsolete knowledge question, reset budgets or rerun
Designer. The user owns this continuation; verification must not invoke production models.
If facts advance, re-read the current checkpoint rather than asserting the old count is current.

Before new feedback is published, revert code and schemas together. After extended feedback is
published, keep a compatible reader or roll forward: an old strict reader cannot ingest the new
field. Never remove immutable records to force a downgrade.
