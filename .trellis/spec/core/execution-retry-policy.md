# Execution and retry policy

## Bounded upstream execution-time growth (2026-09-29)

### 1. Scope / Trigger

Manager, Product, Designer and Planner complete artifacts cannot checkpoint their model reasoning. The
joint producer defaults to a 600-second local execution window. A Codex CLI process that is
still incomplete when the local watchdog fires raises
`StructuredModelError(code=TIMEOUT, timeout_kind="local_execution_limit", transient=False)`.
This is evidence of a saturated local execution window, **not** proof that the model was
thinking or that the provider was healthy. The fallback client must not switch routes for this
classification. An explicit provider failure found in the CLI timeout stderr is classified by
its provider code instead. A Responses socket timeout has no reliable server-progress evidence
and remains typed transient; HTTP 504 and other provider errors retain their current routing.

### 2. Signatures

```python
StructuredModelError(code, safe_message, *, transient,
                     timeout_kind: Literal["local_execution_limit"] | None = None)
stage_timeout_seconds(attempts: Mapping[str, int], stage: str,
                      policy: ExecutionTimePolicy | None = None) -> int
JointDeliveryService._stage_output(checkpoint, model, instructions) -> DomainModel
```

### 3. Contracts

`stage_timeout_seconds(attempts, stage)` uses a bounded geometric series for `product`, `design`
and `plan`: by default 600 → 1200 → 2400 seconds; `execution_retry_policy.execution_time`
configures each role's initial/ceiling/capacity-failure limit. `JointDeliveryService._stage_output` refunds only the
unfinished reserved work attempt and appends `<stage>_capacity_timeout` to the sealed successor
checkpoint. The counter is independent of `<stage>_transient`, survives restart and is not
retroactively inferred for old journals. At the configured failure limit (default: third failure), the next
invocation is rejected before model launch with `execution time budget exhausted`. No stage,
approval, feedback, product/design/plan artifact or historical checkpoint is rewritten. A
successful invocation consumes its normal work attempt; prior capacity facts remain audit
history. Unknown process interruption does not refund. The knowledge intent/assessment
subcalls for these three roles receive the same expanded window; Delivery roles retain their
120-second consultation cap. Manager's real model calls have independent durable work, transient
and capacity records; ownership and coordination boundaries are in `manager-coordination.md`.

`StageBudget` projects `capacity_timeouts`, configured `max_capacity_timeouts`, `max_timeout_seconds`, next window and
`exhausted=capacity`. The Console maps only local-window timeouts to
`MODEL_EXECUTION_LIMIT`; it leaves `MODEL_TIMEOUT` for transport/provider timeouts. The UI
must not advise raising the *transient* failure limit when capacity is exhausted or offer a
known-futile retry. There is no automatic terminal-state rewrite. Operators inspect the
diagnostics and task size, then adjust the configured ceiling/count or plan smaller work if needed;
do not edit a production checkpoint or reuse an approval. Already-authorized unfinished joint
producers may automatically retry after validated Manager advice and another stage-budget check.
An approved historical Design knowledge wait can recover a *work* allowance, not a separately
exhausted execution-time allowance; both reader and action guard must suppress that futile
recovery while capacity is exhausted.

### 4. Validation & Error Matrix

| Evidence | Counter / route | Next call |
| --- | --- | --- |
| CLI local watchdog, no explicit provider error | `*_capacity_timeout += 1`, no fallback or transient debit | 1200 or 2400 seconds |
| CLI stderr explicitly reports 504 before watchdog | `*_transient += 1`, fallback permitted | same time window |
| Responses socket timeout | `*_transient += 1`, fallback permitted | same time window |
| Valid artifact after expansion | one work attempt, historical capacity fact retained | next stage |
| Configured final local watchdog (default: third) | `*_capacity_timeout >= max_capacity_timeouts` | reject before next call |

### 5. Good / Base / Bad Cases

- Good: a 600-second local timeout is sealed, restart invokes the same approved role at 1200
  seconds, and the eventual artifact passes its ordinary validation.
- Base: a first-call valid artifact consumes one work attempt with no capacity fact.
- Bad: treat an ambiguous socket timeout as proof of thinking, switch to a backup after the
  *local* watchdog, erase a capacity fact, or extend a terminal Task by editing its journal.

### 6. Tests Required

`tests/agents/test_structured_models.py` asserts local vs explicit provider evidence and route
count; `tests/manager/test_stage_retry_budget.py` asserts all three stage counters, windows,
restart, success and exhaustion; `tests/knowledge/test_consultation.py` asserts upstream subcalls
receive the expanded window; `tests/team_view/test_design_budget.py` and UI/Console tests assert
the projection, action suppression and distinct `MODEL_EXECUTION_LIMIT` code.

### 7. Wrong vs Correct

Wrong: `except TimeoutExpired: raise StructuredModelError(TIMEOUT, transient=True)` followed by
fallback, because a local execution limit is not a typed provider outage.
Correct: mark the local timeout origin, refund only the current producer reservation into a
sealed capacity checkpoint, and calculate the next bounded window from that fact.

### Bug analysis / prevention

Category B/D/E: one error code conflated two boundaries, and tests covered provider failures but
not the fallback-plus-stage-budget chain. The prevention mechanism is a typed origin on the
error, a durable independent counter, cross-layer tests and the shared checklist in
`../guides/timeout-classification.md`. Similar native Task timeouts still have a distinct
checkpoint/attempt policy; do not copy this joint-upstream policy into Delivery roles without
their own evidence and contract tests.

## Scope and signatures

`ProductionConfig.execution_retry_policy: ExecutionRetryPolicy` replaces the Design-only setting.
Product defaults to 20 artifact/discussion attempts; Designer/Planner/Coder default to 3 work
attempts; all seven model roles default to 5 typed transient failures. Each count is a strict integer
in 1..100. QA/Reviewer have no configurable verdict retry: findings return to Coder or require a
new verification approval. Manager defaults to 2 artifact/correction calls per input and 3 distinct
coordination inputs per stable Requirement/stage episode. Its typed model failures are not verdicts.

Scope: Console/`ase request` joint upstream and newly dispatched production Tasks. Native legacy
`ase project` upstream records retain their original protocol; do not apply new counter meanings to
their hashed journals. Hand-created Tasks without a policy keep the compatibility runner. Integration
commands and candidate verification admissions are not model-call retry loops; retain exact approvals.
Source: `domain/retry_policy.py`, `config/production.py`, `multi_directory/service.py`,
`orchestration/retry.py`, `store/{repository,mysql_repository}.py`, `team_view/{reader,app.js,style.css}`.
Settings API: `GET/PUT /api/v1/admin/settings` with `config.execution_retry_policy` and the existing
write-only runtime variables; save/apply reconstructs Host and Reader. Existing Task tables are
unchanged; Manager adds the immutable audit table described in `manager-coordination.md`.

`Task.retry_policy: DeliveryRetryPolicy | None` freezes Coder work and per-role transient limits at
dispatch. `Task.retry_failures: tuple[DeliveryRetryFailure, ...] | None` is absent from legacy JSON.
`TaskRepository.record_retry_failure(task_id, failure) -> None` checks role/current attempt, appends
one typed fact and reserves the successor execution attempt atomically, with exact-replay/conflict
validation and MySQL owner fencing. No verdict or new status is written by this method.

`domain.task.task_matches_dispatch(current, dispatched, *, allow_legacy_retry_policy=False)` is
the shared immutable-intent comparison for dispatch replay, native recovery, candidate verification,
failed-continuation inspection and read projections. Only `status`, `attempts`, `updated_at` and
`retry_failures` are runtime fields. All other fields, including frozen `retry_policy`, constraints,
acceptance criteria and metadata, remain exact. Only the read-only Team View explicitly allows its
existing legacy missing-policy compatibility; recovery/execution must never opt into it.

A Coder timeout followed by a successful candidate legitimately leaves retry facts in the terminal
Task that were absent from its dispatch. Comparing those facts as immutable content strands
`CONTINUE_DELIVERY` at `candidate provenance is missing, unsafe or inconsistent`. Fix the reader,
not historical Task/dispatch/artifact data: retain the original candidate and append-only history,
then let normal resume propose an exact verification plan requiring normal approval.

Regression checks: `tests/recovery/test_verification_snapshot.py` covers retries plus candidate,
event, policy and intent drift; `tests/e2e/test_planned_delivery.py` reopens a real SQLite repository
after `record_retry_failure` and proves replay preserves its events and retry facts;
`tests/domain/test_task_dispatch_identity.py` keeps legacy compatibility out of execution.

## Accounting and compatibility

Upstream Product/Design/Plan reserve their stage attempt before calling a provider. Only typed
transient failures refund it in a successor checkpoint and increment `<stage>_transient` (Design
keeps `design_transient`). Original feedback and errors survive. Knowledge waits refund the stage
reservation without consuming transient allowance. Old checkpoints are not rewritten.
Only the unfinished producer's reservation can be refunded, inside `_stage_output`. A knowledge
wait in a pre-invocation gate or after a rejected response must never decrement spent work.
Comparing counters against the entry checkpoint is insufficient when one advance contains several
bounded corrections: earlier responses in that same advance have already consumed work.

Delivery execution identities remain monotonic; work attempt equals execution attempt less earlier
recorded transient failures. Identity ceiling is work allowance plus the three role allowances,
at most 400. Every attempt-bearing wire contract shares that ceiling. Worker loops remain bounded
and require separate real claims for each new Run. Exhausted failures retain evidence and block;
unknown/invalid output is not refunded. Settings cannot revive a terminal Task.

New Tasks freeze policy inside dispatch facts. Legacy Tasks keep their former max_attempts and
recovery semantics. Operator changes take effect after restart for upstream continuations/new
Tasks, not retroactively on a frozen Task. Legacy `design_retry_policy` input maps to Designer;
conflicting old/new policies are rejected rather than silently selecting one.

`RequestView.stage_budget` exposes active `role`, `attempts`, `max_attempts`, `transient_failures`,
`max_transient_failures` and optional `exhausted=work|transient`. `design_budget` stays available for
legacy readers. Exhaustion hides futile Product/Planner/Design continuations. Exact pending approvals
(including joint integration in a retained PLANNING checkpoint) and eligible Design recovery take
precedence over ordinary retry presentation. Raising a Planner limit exposes an exact-checkpoint
retry after a failed operation; it must not strand the request in an apparently running stage.

## Validation and required tests

| Case | Required result |
| --- | --- |
| Typed transient QA failure, then QA success | new execution identity; Coder work allowance unchanged |
| Failure persisted, process restarts | count and next execution identity survive; no free retry |
| Duplicate failure fact | no-op; altered fact at same role/attempt rejected |
| Transient false, unknown error, invalid output | no refund; fail closed or existing bounded correction |
| QA FAIL / Review REJECT | return original finding to Coder, consume work allowance |
| Legacy policy/checkpoint/Task | original hashes and frozen limits unchanged |
| Operator increases setting | no Task status/approval mutation |
| Bool/string/zero/over-100 | reject before publication |

Good: retryable provider outage has its own durable budget. Base: first valid execution traverses
unchanged QA/Review gates. Bad: retry a valid negative verdict until it approves, reset Task attempt,
or place ineffective role fields in Settings. Fake adapter, persistence reopen/fence, schema and
browser tests must assert these boundaries. Production records are not test fixtures.

## Required test locations and executable checks

- `tests/config/test_execution_retry_policy.py` and `tests/contracts/test_json_schema_contracts.py`:
  strict bounds, canonical output, old input, conflict rejection, Task and nested wire ceilings.
- `tests/manager/test_stage_retry_budget.py`: Product/Planner reservation, typed refund, restart,
  unchanged historical prefix, no provider call at exhaustion, increased configuration permits a call.
- `tests/orchestration/test_execution_retry_budget.py`: all Delivery roles, crash after failure
  commit, invalid knowledge output, absent Run ID before adapter invocation and fresh permit required.
- `tests/store/test_mysql_retry_policy.py`: loss of fence before/after UPDATE rolls back.
- `tests/work_queue/test_worker_mysql.py::test_frozen_policy_retry_has_distinct_real_claims`:
  real MySQL lease per role invocation; work=1 still succeeds after a Coder timeout.
- `tests/team_view/browser/{settings-layout,design-budget}.test.cjs`: CSS geometry at 1440/768/390,
  seven roles, independent time controls, exhaustion and Planner resumption; `ui.test.cjs` retains exact approvals.

For this user-authorized change run the explicit file list in the task's `implement.md`, never the
full suite. MySQL tests use only `ASE_TEST_MYSQL_DSN`, guarded by `tests/mysql_safety.py`.

## Wrong vs correct

Wrong: increase `Task.max_attempts` globally or silently discard failure facts on restart.
Correct: freeze a typed policy at dispatch, atomically record failure plus next execution identity,
then require a new role permit. Work counts and execution identity have different semantics.

Native pre-candidate recovery must use `Task.work_budget_exhausted` when admitting a successful
`coder-progress` at `RETRY_BUDGET_EXHAUSTED`. Comparing `attempts == max_attempts` is wrong for
frozen policies: default work exhaustion occurs at 3 while the execution identity ceiling is 18.
Still require exact terminal Coder role/run/context/attempt, progress checkpoint sequence and
terminal event provenance; this does not admit arbitrary successful runs. Legacy tasks without a
policy retain their original meaning through the shared Task property. A non-transient INVALID_OUTPUT
under a frozen policy stops after one call, with no refund or hidden retry, and remains inspectable
through the normal exact recovery proposal. `tests/recovery/test_native.py` exercises both production
Host/MySQL paths; changing tests to match these facts must not weaken the recovery/approval checks.

Wrong: `if failed_operation: show_retry()` ahead of recovery/approval facts.
Correct: retain exact approvals, then apply active-stage budget and failed-operation presentation.

## Bug analysis and prevention

1. B/C/E — Design-only policy and a shared delivery attempt assumed transport failures were work;
   a renamed settings title alone would not fix the accounting or persistence boundary.
2. Initial propagation needed more than field changes: Task/Context/Evidence/Queue schemas all
   carried a ceiling of 10; UI default paragraph margins compounded its 24px form gap.
3. Shared constrained types and transient-code classifier, immutable compatibility tests, SQL fence
   tests and real CSS geometry assertions now cover these failure modes.
4. Product/Planner projections must be checked alongside recovery approvals: a PLANNING stage can
   represent pending integration approval rather than a failed model invocation.
5. This spec and operator recovery instructions are the organizational record. No template mirror
   exists in this repository.

## UI layout

Basic settings contains platform/team, runtime, execution/retry, and execution-time sections. Each has a
visible top divider; module spacing is separate from the compact internal heading/description/grid
spacing. Reset paragraph margins inside sections; never stack form grid gaps with default margins.
