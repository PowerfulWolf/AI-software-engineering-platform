# Bounded Manager coordination

## Scope / signatures

Manager is a model-backed proposal role, not a deterministic-only placeholder. Both existing
verification coordination and cross-stage failure diagnosis use the configured Manager route.
Cross-stage integration covers the standard Console/`ase request` joint Requirement service;
legacy native `ase project` upstream journals keep their existing protocol. Candidate-verification
Manager calls use the same executor in both entry paths. No delivery queue role is added.

`ProductionConfig.execution_retry_policy.manager: ManagerRetryPolicy` owns `max_attempts=2`
(output/correction calls), `max_transient_failures=5` and `max_coordination_rounds=3`.
`execution_retry_policy.execution_time: ExecutionTimePolicies` contains Manager/Product/Designer/
Planner `ExecutionTimePolicy(initial_seconds=600, max_seconds=2400, max_capacity_timeouts=3)`.
Seconds are strict integers in 1..86400; failure bounds in 1..100. Ceiling must be >= initial.
The next window is `min(initial_seconds * 2**capacity_timeouts, max_seconds)`; reject before a
call when capacity_timeouts reaches its configured limit. These are elapsed execution windows,
not evidence of productive thinking, model context size or TaskLease lifetime.

## Contracts

Three independent counts: completed/invalid proposal work, typed service failures, and local
execution-window failures. No fallback for local expiry; unknown interruption does not refund.
Manager failures never recursively call Manager. Same-input advice reuse does not call a model.
Different checkpoint/correction text cannot reset the stable requirement/stage coordination budget.
An episode is exactly `(team_id, project_id, requirement_id, stage)`; candidate verification uses
`stage=VERIFICATION:<repository_id>`. Policy is snapshotted per call; current settings may raise
future allowance after restart but never erase historical counts. Exact cached success can be read
even after its budget is spent; a new invocation cannot. Work is charged per original input hash,
while transient/capacity counts and distinct-input rounds span the entire episode.

Manager receives verified evidence and an explicit bounded action set. Model output selects an
advertised action only; trusted services recheck current identity/approval/budgets before dispatch.
Automatic retry is permitted only for an already-authorized unfinished producer and typed transient
or local-window failure. Policy/permission/auth/unknown failures cannot grant automatic execution.
Coder/QA/Reviewer stay in the existing dispatch/recovery/independent-verdict path. Manager cannot
approve ProductSpec, alter criteria, restart terminal Tasks, reinterpret a negative verdict as an
outage, or claim arbitrary commands/capabilities. New repair or verification proposals need approval.

## Validation matrix

| Case | Result |
| --- | --- |
| Provider 504 | transient fact; unchanged next window |
| Local process watchdog | capacity fact; next window doubles within ceiling |
| Invalid proposal | work debit; bounded correction, no raw invalid input echo |
| Exhaustion / uncertain interrupted run | no model or automatic executor invocation |
| Reopen same evidence | replay immutable advice and counts |
| Unadvertised action / stale evidence / missing approval | reject dispatch |
| QA FAIL or Review REJECT | preserve verdict and normal Coder routing |

## Cases / tests

Good: Planner times out locally; evidence-bound Manager advice selects permitted same-stage retry
and the next invocation uses a longer configured window with unchanged Product approval.
Base: unchanged verification input reuses advice. Bad: reset a budget when the checkpoint digest
changes or repeatedly retry a valid FAIL. Policy, ledger/reopen, fake adapter, boundary/refusal,
schema, Console and UI incremental tests must assert these cases; no production model test calls.

## Wrong vs correct

Wrong: `except Exception: manager.run_again()` or giving Manager store/shell/approval tools.
Correct: seal typed failure, enforce independent budgets, validate one bounded proposal, then
revalidate the current deterministic action guard. Preserve original delivery phase in projections.

Cross-stage blockage input keeps ProductSpec identity separate from recovery authority. The
`product_spec_sha256` field is informational; `approval_sha256` is omitted unless an exact recovery
authorization is actually present. Manager must not infer a recovery approval from a ProductSpec
digest. Child findings include the child unit, stage, failure code, failure summary, Task identity,
Task status and next action, so a blocked parent can explain the current fact and route the exact
remedy. This input is still proposal context: Manager cannot approve, reset, or fabricate recovery.

#### Blockage input contract

`StageBlockage` carries `product_spec_sha256: str | None`, `approval_sha256: str | None`, and
`child_findings: tuple[str, ...]`. `approval_sha256` is omitted when no exact recovery
authorization exists. Each child finding includes `unit`, `stage`, `failure_code`,
`failure_summary`, `task_id`, `task_status`, and `next_action`; these are read-only facts for the
Manager prompt. The deterministic service validates the advertised action again before publishing
advice.

| Case | Required behavior |
|---|---|
| ProductSpec exists but no recovery authorization | send `product_spec_sha256`, omit `approval_sha256` |
| Child is blocked | include its current failure code/summary and Task facts |
| Manager proposes approval/reset from a digest | reject as unadvertised or unauthorized |

Good: Manager receives the exact child reason and proposes the authorized recovery route.
Bad: use the ProductSpec digest as the recovery approval identifier or send only a generic child
finding. `tests/manager/test_stage_coordination.py::test_blockage_does_not_present_product_approval_as_recovery_authority`
guards the digest separation.

## Executable APIs and persistence

Source: `manager/model_execution.py`, `manager/model_store.py`, `manager/stage_coordination.py`,
`multi_directory/{service,store}.py`, `recovery/verification_entry.py`.

```python
ManagerModelExecutor.run(client, *, instructions, payload, model, validate=None)
    # -> (validated draft, actual provider, actual model); last_run_id identifies its receipt
MySqlManagerClaimAuthority.claim(scope: ManagerRunScope, *, seconds: int)
    # -> context manager yielding ManagerInvocationGuard
ManagerInvocationGuard.check() -> None
ManagerInvocationGuard.write_scope()  # owner-fenced atomic transaction
ManagerRecordStore.put(namespace, key, record)  # immutable exact replay only
ProductionStageCoordinator.diagnose(checkpoint, error) -> ManagerCoordinationAdvice
allowed_coordination_actions(policy, checkpoint, error) -> tuple[CoordinationAction, ...]
```

The additive table is created idempotently when the production Manager store is first constructed:

```sql
CREATE TABLE IF NOT EXISTS manager_coordination_records (
  team_id VARCHAR(128) NOT NULL,
  namespace VARCHAR(64) NOT NULL,
  record_key CHAR(64) NOT NULL,
  payload_json JSON NOT NULL,
  sha256 CHAR(64) NOT NULL,
  PRIMARY KEY (team_id, namespace, record_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
```

Unexpected columns fail closed. `record_key=digest(key)`; reads recompute canonical payload SHA
and validate the model. Namespaces are `manager-context`, `manager-start`, `manager-final`.
Final records match all immutable STARTED fields, including scope, sequence, run/context identity,
owner hash, expiry, chosen time window and effective policy. Successful results and typed errors are
mutually exclusive. Unknown crashes retain STARTED, charge work and never invent a result.
Input is redacted and limited to 4 MB; stored records are bounded to 8 MB. Raw invalid output is
not echoed/stored. Each correction's actual prompt/input/schema gets its own context manifest;
budget identity remains the original input so correction cannot reset it.

Production claims use a dedicated live MySQL connection and nonblocking Team-scoped `GET_LOCK`.
The lock name is hashed; owner SHA binds connection identity plus a random nonce. A deadline bounds
the claim by configured maximum time × 16 (route limit) + 60 seconds. This is a conservative single
Manager lane, not a fake business Task/WorkItem. STARTED and final publish in separate transactions;
each transaction checks ownership before and after writes, rolling back on failure. A dropped
connection releases the lock, never reconnects as the same owner, and cannot publish late output.
CLI polls the guard and terminates the process group on loss; Responses may remain in its bounded
HTTP call, but cannot commit after losing ownership. The model never receives the store or guard.

Advice source-facts hashing excludes only presentation fields, journal sequence/parent/digest and
previous advice. Store append requires unchanged substantive facts and the exact predecessor hash.
The service rechecks both source hash and advertised action before publishing or applying advice.
Substantive changes clear stale advice. No Manager success can replace Product approval or verdicts.
`ContextBudgetExceeded` advertises WAIT only; child terminal blockage may additionally propose
existing recovery. Non-retry advice does not change the actual Requirement stage.

## Incremental tests / assertions

- `tests/config/test_execution_time_policy.py`: strict bounds, geometric ceiling, invalid order.
- `tests/manager/test_manager_model_execution.py`: independent counters, new run per retry,
  exact correction contexts, reopen/reuse, interrupted work debit and stable episode exhaustion.
- `tests/manager/test_manager_claim_mysql.py`: isolated DB, second-owner denial, no-owner denial,
  before/after-write owner-loss rollback, immutable commit and restart reuse.
- `tests/manager/test_stage_coordination.py`: Design 600→1200 with unchanged Product approval,
  bounded action set, context-failure WAIT, no delivery retry, stale/unavailable advice rejected
  before any journal append.
- `tests/contracts/test_manager_coordination_schema.py`: real receipts/contexts and config wire.
- `tests/recovery/test_manager_coordination.py`: existing verification capability/approval gates.
- `tests/team_view/browser/{settings-layout,design-budget}.test.cjs`: aligned settings, independent
  Manager/time values submitted, bounds, original stage, stale-service save refusal.

Run only explicit affected files with `.venv/bin/pytest -q --tb=short ...`; MySQL requires the
isolated `ASE_TEST_MYSQL_DSN` safety guard, never production DSN. No new environment secret keys.
Regenerate wire contracts with `.venv/bin/python scripts/sync-manager-schemas.py`.

## Existing records, rollout and rollback

Development does not modify production facts or execute paused requirements. Existing configs read
with defaults; old journals omit `coordination` and retain their original bytes/hashes. No historical
timeout is reclassified. The additive table does not update Task, approval or queue rows.

After user authorization: restart/reconstruct Host and refresh the UI (Settings contract version 2),
read the exact paused checkpoint, then use its normal Continue/Recovery entry. A terminal Task needs
a new exact recovery approval where the existing flow requires it; never replay a consumed approval
or edit SQL to clear state/budgets. Scope/source drift must follow the existing recovery gate.

For rollback, stop new executions and preserve the new table, checkpoints and receipts. Before any
new facts/config are published, reverting code is sufficient. After publication an old strict reader
may reject the new fields: prefer a forward compatibility fix, or restore a verified consistent
pre-rollout backup while retaining newer history separately for audit. Never strip advice fields,
delete audit rows or silently recompute historical hashes just to make old code accept them.
