# Execution and retry policy

## Scope and signatures

`ProductionConfig.execution_retry_policy: ExecutionRetryPolicy` replaces the Design-only setting.
Product defaults to 20 artifact/discussion attempts; Designer/Planner/Coder default to 3 work
attempts; all six model roles default to 5 typed transient failures. Each input is a strict integer
in 1..100. QA/Reviewer have no configurable verdict retry: findings return to Coder or require a
new verification approval. Manager is deterministic and has no model budget.

Scope: Console/`ase request` joint upstream and newly dispatched production Tasks. Native legacy
`ase project` upstream records retain their original protocol; do not apply new counter meanings to
their hashed journals. Hand-created Tasks without a policy keep the compatibility runner. Integration
commands and candidate verification admissions are not model-call retry loops; retain exact approvals.
Source: `domain/retry_policy.py`, `config/production.py`, `multi_directory/service.py`,
`orchestration/retry.py`, `store/{repository,mysql_repository}.py`, `team_view/{reader,app.js,style.css}`.
Settings API: `GET/PUT /api/v1/admin/settings` with `config.execution_retry_policy` and the existing
write-only runtime variables; save/apply reconstructs Host and Reader. No SQL schema migration.

`Task.retry_policy: DeliveryRetryPolicy | None` freezes Coder work and per-role transient limits at
dispatch. `Task.retry_failures: tuple[DeliveryRetryFailure, ...] | None` is absent from legacy JSON.
`TaskRepository.record_retry_failure(task_id, failure) -> None` checks role/current attempt, appends
one typed fact and reserves the successor execution attempt atomically, with exact-replay/conflict
validation and MySQL owner fencing. No verdict or new status is written by this method.

## Accounting and compatibility

Upstream Product/Design/Plan reserve their stage attempt before calling a provider. Only typed
transient failures refund it in a successor checkpoint and increment `<stage>_transient` (Design
keeps `design_transient`). Original feedback and errors survive. Knowledge waits refund the stage
reservation without consuming transient allowance. Old checkpoints are not rewritten.
Only a reservation made within the current advance can be refunded: a pre-invocation planning gate
must never decrement historical `plan` attempts. Compare against the entry checkpoint counts.

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
  six roles/ten controls, exhaustion and Planner resumption; `ui.test.cjs` retains exact approvals.

For this user-authorized change run the explicit file list in the task's `implement.md`, never the
full suite. MySQL tests use only `ASE_TEST_MYSQL_DSN`, guarded by `tests/mysql_safety.py`.

## Wrong vs correct

Wrong: increase `Task.max_attempts` globally or silently discard failure facts on restart.
Correct: freeze a typed policy at dispatch, atomically record failure plus next execution identity,
then require a new role permit. Work counts and execution identity have different semantics.

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

Basic settings contains named platform/team, runtime, and execution/retry sections. Each has a
visible top divider; module spacing is separate from the compact internal heading/description/grid
spacing. Reset paragraph margins inside sections; never stack form grid gaps with default margins.
