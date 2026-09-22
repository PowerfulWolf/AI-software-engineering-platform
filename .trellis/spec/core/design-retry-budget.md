# Design retry budget contract

## Scope and signatures

`ProductionConfig.execution_retry_policy.designer` is now canonical; the read compatibility property
`ProductionConfig.design_retry_policy: DesignRetryPolicy` defaults to `max_design_attempts=3` and
`max_transient_failures=5`; both accept strict integers in 1..100. Settings saves this secret-free
policy and requires Host/Reader reconstruction through the existing restart flow.
`JointDeliveryService(..., design_retry_policy: DesignRetryPolicy | None = None)` and
`ProductionTeamReader` use the same policy. `RequestView.design_budget` exposes counts, limits and
exhaustion from durable facts.

## Accounting and errors

`JointCheckpoint.attempts.design` reserves a Design artifact attempt before invocation. The new
`attempts.design_transient` key counts exhausted typed provider invocations, including failures in
Designer knowledge consultation. A fallback that succeeds in the same invocation does not consume
this count. Provider diagnostics continue to preserve each route attempt separately.

Only `StructuredModelError` with `transient=True` and code TIMEOUT, RATE_LIMITED, QUOTA_EXHAUSTED or
PROVIDER_UNAVAILABLE can refund the reservation and increment the transient count in one successor
checkpoint. Reuse the structured fallback classifier. Preserve previous design feedback and rethrow
the original error. KnowledgeGapRaised retains its existing refund without a transient failure.
Unknown interruption, crash, invalid output and other errors retain the reservation. No free
automatic retry loop is introduced. Check both budgets before reserving/calling the provider.
`StructuredModelError.retryable` is the shared classifier. Defaults, count-to-budget projection and
exhaustion order are defined in `multi_directory/budget.py`, not duplicated in Host or Reader.
Transient exhaustion takes precedence when both allowances are exhausted.

Existing approved-knowledge RecoverDesign requires the exact current checkpoint, absent design/plan,
exhausted Design allowance and unused transient allowance. It appends an audited successor resetting
only Design attempts. No old checkpoint is changed or rehashed. Increasing a configured allowance
permits another normal continuation; spent counts never decrease due to configuration.

## Projection and UI

The Settings API remains `GET/PUT /api/v1/admin/settings`, with
`config.execution_retry_policy.designer.{max_attempts,max_transient_failures}`. The legacy
`design_retry_policy` field remains accepted on input, but is not emitted. Save is followed by the
existing apply/restart operation. `GET /api/v1/team` returns each joint request's `design_budget`:
`design_attempts`, `max_design_attempts`, `transient_failures`, `max_transient_failures`, and optional
`exhausted` (`design`/`transient`; absent when available). Neither settings nor the read endpoint edits
Requirement counts. `schemas/production-config.schema.json` and `team-snapshot.schema.json` agree.

Active operations suppress all retry/recovery controls. Eligible recovery outranks ordinary failed
Design retry in status, guidance and action rendering. Exhaustion without recovery displays counts
and instructs the operator to raise the appropriate limit in Settings and restart. It must not show
a generic Continue action that is certain to fail or assert an unproven knowledge miscount.

## Validation matrix

| Input/fact | Outcome |
| --- | --- |
| 504 in knowledge assessment; Design count 0 | Design 0, transient 1; original error preserved |
| Transient false, invalid output or unknown exception | Design attempt remains spent |
| Two invalid designs, transient failure, valid design | Exactly three Design attempts spent |
| Either allowance exhausted, including reopened service | No model call or new reservation |
| Policy raised/lowered | Existing counts preserved; new allowance enforced |
| Missing legacy policy/transient count | Defaults and zero transient failures; hashes unchanged |
| Approved knowledge recovery plus exhausted transient count | Recovery rejected; increase policy |
| Exhaustion + failed Continue operation + recovery eligible | One RECOVER_DESIGN button |
| Bool/string/zero/over-100 limit | Validation failure before settings/Host mutation |

Good: temporary HTTP failure is separately accounted and an operator raises its finite allowance.
Base: valid first Design follows existing stage validation. Bad: reset history, classify exception
text as transient, or retry after a hard contract error without accounting.

## Required checks and existing data

Fake-provider service tests cover classification, restart, mixed failures, pre-call reservations and
configured limits. Config/Schema tests cover defaults and invalid limits; read projection and DOM
tests verify the submitted exact-checkpoint action, disabled running controls and saved settings.
No MySQL migration or journal rewriting is needed. See docs/operator-feedback-loop.md for recovery
of the reported existing codex Requirement and rollback instructions.

Specific regression locations: `tests/manager/test_design_retry_budget.py`,
`tests/team_view/test_design_budget.py`, `tests/team_view/knowledge-gap.test.cjs`,
`tests/config/test_production.py`, `tests/web_console/test_administration.py`, and
`tests/contracts/test_json_schema_contracts.py`. The existing unknown-interruption and approved
knowledge recovery tests in `test_joint_designer_feedback.py` remain applicable.

## Wrong vs correct

Wrong: `if latest_operation.status == FAILED: show_retry()` before consulting the Requirement's
recovery eligibility. A failed retry then hides the only useful action forever.

Correct: check active operation, recovery eligibility and budget exhaustion before ordinary retry;
test the actual submitted intent, not only a translated button label.

Wrong: refund every `Exception` or reset `attempts.design` on restart. That loses uncertain-call
accounting and can silently allow unlimited retries.

Correct: reserve before the call, refund only typed retryable failures in an append-only successor,
increment the separate transient counter, and leave other errors/crashes conservatively spent.

## Bug analysis: shared allowance and hidden recovery

### 1. Root cause category

B/D/E: stage reservations assumed all failed model calls were design attempts. A temporary 504,
including knowledge assessment before generation, spent the correction allowance. Separately, UI
precedence treated a failed Continue operation as stronger than durable recovery eligibility.

### 2. Why earlier coverage was insufficient

Knowledge-wait refunds covered `KnowledgeGapRaised`, not typed provider failures. The recovery
action existed, but its projection tests did not exercise a later failed retry. A higher shared
limit or a renamed retry button would leave these distinct failure modes intact.

### 3. Prevention mechanisms

| Priority | Mechanism | Action | Status |
| --- | --- | --- | --- |
| P0 | Typed accounting | Shared fallback classifier, separate durable counter, pre-call reservation | DONE |
| P0 | Cross-layer contract | One policy for Settings, Host and Reader; matched wire schemas | DONE |
| P0 | Regression tests | Restart/mixed-failure tests and browser assertion of exact recovery intent | DONE |

### 4. Systematic expansion

The all-role extension is specified in `execution-retry-policy.md`: Product/Planner gain independent
work/transient budgets, Delivery freezes its own role policy. Integration remains a deterministic
command/approval allowance, not a model retry. Action precedence tests must combine checkpoint facts
with failed/running operations and exact approvals, rather than checking translated labels alone.

### 5. Knowledge capture

This executable spec, the multi-directory contract and operator recovery instructions are updated.
The repository has no `src/templates/markdown/spec/` mirror or separate guides layer to synchronize.
