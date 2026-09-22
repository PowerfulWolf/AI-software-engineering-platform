# Implementation and verification

## Outcome

- Basic settings has three visibly separated modules and compact heading/body/field spacing.
- Canonical execution policy covers Product/Designer/Planner/Coder/QA/Reviewer; work allowances and
  typed transient failures are distinct. Manager remains deterministic; verdicts cannot be retried
  to seek approval. Values are strict integers in 1..100, save/apply requires restart.
- Product/Planner join Design's append-only counters. New Tasks freeze policy at dispatch, persist
  transient facts and reserve successor identities atomically. Old Task wire/hashes are unchanged.
- Shared execution identity ceiling propagates through Task, Context, Artifact producers, events,
  Evidence, evaluation, worktree and scheduling contracts; unrelated recovery continuation limit stays 10.
- Exact approval/Design recovery outranks retry UI; raising Planner limits restores its retry action.
- Corrected the extra pre-reservation knowledge-gate refund bug: a wait cannot subtract old work.

## Final incremental checks

No full pytest or Node suite was run. All model executions use fake adapters. Only the dedicated
test MySQL database was mutated; production config, journal, Operations and databases were untouched.

```sh
.venv/bin/ruff check src tests
git diff --name-only -- '*.py' | xargs .venv/bin/ruff format --check
.venv/bin/ruff format --check src/ai_software_engineer/domain/retry_policy.py tests/config/test_execution_retry_policy.py tests/manager/test_stage_retry_budget.py tests/orchestration/test_execution_retry_budget.py tests/store/test_mysql_retry_policy.py
.venv/bin/mypy src tests
git diff --check
```

Ruff passed, changed/new Python formatting passed, Mypy passed (439 files), diff check passed.
An exploratory repository-wide format check identified a pre-existing difference in
`tests/knowledge/test_delivery_context.py:129`; that unrelated file was not changed.

```sh
.venv/bin/python -m pytest -q --tb=short tests/config/test_production.py tests/config/test_execution_retry_policy.py tests/contracts/test_json_schema_contracts.py tests/agents/test_structured_models.py tests/agents/test_fallback.py tests/agents/test_fake.py tests/context/test_builder.py tests/context/test_store.py tests/domain/test_event.py tests/domain/test_task_agent.py tests/orchestration/test_execution_retry_budget.py tests/orchestration/test_retry.py tests/orchestration/test_steps.py tests/store/test_repository.py tests/store/test_mysql_retry_policy.py
```

270 passed. Covers policy bounds/migration/conflicts, schemas, fallback, identity propagation,
all-role transient behavior, crash/reopen, permit separation and rollback on loss of fence.

```sh
.venv/bin/python -m pytest -q --tb=short tests/manager/test_stage_retry_budget.py tests/manager/test_design_retry_budget.py tests/manager/test_joint_designer_feedback.py tests/manager/test_joint_planner_feedback.py tests/manager/test_joint_contracts.py tests/manager/test_dispatch.py tests/manager/test_dispatch_authority.py tests/manager/test_team_host.py tests/manager/test_production_delivery.py tests/web_console/test_administration.py tests/team_view/test_design_budget.py tests/recovery/test_task_record.py tests/recovery/test_execution_records.py tests/recovery/test_delivery_continuation.py
```

142 passed. Includes Product/Planner restart and extension, Design recovery, projections and settings.
The new pre-reservation gate test first failed with `plan=1` instead of `2`, then passed after the fix.

```sh
.venv/bin/python -m pytest -q --tb=short tests/manager/test_production_backend.py tests/store/test_mysql_repository.py tests/work_queue/test_worker_mysql.py::test_frozen_policy_retry_has_distinct_real_claims tests/work_queue/test_worker_mysql.py::test_task_mutation_fence_rejects_wrong_owner_or_expired_lease
```

30 passed in the dedicated guarded test database. Initial sandbox network denial was resolved by
the approved test-only command; no production connection. Real SQL confirms new claim per retry,
freeze at dispatch, transaction persistence and owner/expiry fences.

```sh
node --test tests/team_view/ui.test.cjs tests/team_view/knowledge-gap.test.cjs
NODE_PATH=/Users/zhangjunshuai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules node --test tests/team_view/browser/settings-layout.test.cjs tests/team_view/browser/design-budget.test.cjs
```

22 DOM tests and 4 real-browser tests passed. Widths: 1440/768/390. Initial failed browser check
required closing the operation notification before navigating; the test now follows actual UI.
The existing joint-integration approval regression caught retry UI masking its exact approval;
the implementation now keeps approval precedence and that regression passes.

## Cross-layer/Trellis review

Used start/before-dev, incremental improve-ut, check/check-cross-layer, update-spec/break-loop and
finish-work. Single-agent implementation and self-check, no fabricated QA/Review verdict. Confirmed
Settings → typed Config → Host/service → frozen Task/transaction → Reader/API → UI propagation.
No template mirror exists. Native compatibility `ase project` upstream keeps its prior journal
protocol; normal Console/`ase request` and new production Delivery Tasks use the new policy.

## Existing data and rollback

No migration or direct production repair is required. The previously inspected codex Requirement
retains its approved ProductSpec and history: restart the updated service, open it and use
“恢复设计”, or raise the corresponding Designer limit and apply configuration before retrying.
Existing Task limits are frozen; terminal Tasks use the normal exact recovery-plan approval path.
Full operator steps and downgrade constraints are in `docs/operator-feedback-loop.md`.

Before new-policy Tasks exist, stop operations and revert this commit, converting canonical Designer
settings back to the old field. Once new-policy Task facts exist, retain a compatible reader and fix
forward; never delete retry facts, reset terminal state or rewrite immutable hashes to downgrade.
