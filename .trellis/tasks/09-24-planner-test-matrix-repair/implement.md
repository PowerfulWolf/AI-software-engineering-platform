# Verification plan

- First reproduce with fake Planner: combined label then valid split succeeds in one resume;
  repeated invalid plans stop at configured budget, retained feedback survives restart;
  transient/unknown failures preserve accounting and no invalid plan is dispatched.
- Assert actual Planner input/output schema and exact expected test types. Cover legacy absent
  fields, multi-criterion missing levels, and unchanged strict native validation.
- Console typed-error and Node DOM regressions for current/legacy/invalid-output/provider cases.
- Run only affected pytest files and Node files, Ruff, strict targeted Mypy, schema parity and
  diff check. Read-only validate the current real Requirement and replay its rejected plan in
  memory; do not publish a fixed artifact or run its model.

## Implemented

- Shared exact validator now emits typed, unit-scoped missing-test issues. Joint input adds the
  typed matrix, and a fresh output schema restricts test levels without changing legacy plans.
- Joint COMPLEX planning automatically corrects only typed matrix rejection under configured
  work limits, with full rejected output and feedback lineage retained. Other failures stop.
- Knowledge waits refund only the unfinished producer's reservation; gates after a rejection
  cannot refund earlier work, even in the same advance.
- Console/UI distinguishes matrix, schema, generic platform, provider and unknown failures.
- Updated both affected JSON schemas and executable Trellis/contracts documentation.

## Validation results (incremental only)

172 Python tests across these explicitly selected files passed:

```sh
.venv/bin/pytest -q \
  tests/manager/test_joint_planner_test_matrix.py \
  tests/manager/test_joint_planner_feedback.py \
  tests/manager/test_stage_retry_budget.py \
  tests/manager/test_joint_designer_feedback.py \
  tests/manager/test_design_retry_budget.py \
  tests/manager/test_joint_contracts.py \
  tests/planning/test_complex_planning.py \
  tests/planning/test_joint_gate.py \
  tests/planning/test_trusted_projection.py \
  tests/planning/test_service.py \
  tests/knowledge/test_stages.py \
  tests/knowledge/test_joint_recheck.py \
  tests/knowledge/test_schema_parity.py \
  tests/web_console/test_manager.py --tb=short
```

Also passed:

```sh
.venv/bin/pytest -q tests/e2e/test_joint_delivery.py::test_joint_cli_to_candidates --tb=short
node --test tests/team_view/knowledge-gap.test.cjs tests/team_view/ui.test.cjs
git diff --check
```

- 2 end-to-end fixtures passed, using guarded `ASE_TEST_MYSQL_DSN` and fake models. The initial
  sandbox socket denial was resolved by approved test-only execution; no production DB used.
- 27 Node tests passed (DOM behavior; no visual layout change).
- Ruff lint/format and strict Mypy passed for all 9 changed Python source/test files.
- The original test-level semantic-rejection test expected manual attempts; it now asserts
  3 automatic work attempts and explicit budget increase before continuation. Other semantic
  rejections still assert a single attempt. New regressions were observed failing before the fix.
- Cross-layer check: shared native/joint validator, feedback serialization, checkpoint/stage-proof
  schemas, service accounting, Console error mapping, and list/detail UI guidance match.

## 存量数据处置

No production writes or migration. Read-only verified all 45 checkpoints and 11 stage-proof
envelopes/nested hashes for `delivery_multi_bd73c5ce9fa226eaa8e427b5c7c1dd96dce1e006`.
Checkpoint 45 remains PLANNING; Product approval and Design are retained, children are empty,
and Planner work is 1/5. Its exact old plan raises the new typed error; changing only the combined
test into two entries in memory passes plan validation and compilation. Nothing was published.

Operator recovery: restart the updated service, refresh the original Requirement, then click
**重试 Planner**. No new Product answer, Design rerun or new Requirement is required. Four work
attempts remain under the observed configuration; each correction consumes one. We did not restart
the service or invoke a real model on the user's behalf.

## Risks / rollback

Real-model output is not guaranteed to succeed; repeated coverage errors still stop at the configured
limit, and unrelated errors retain their existing fail-closed behavior. Live UI verification uses
the user's restart/refresh; offline DOM tests cover changed guidance and action precedence.

Before new feedback is published, revert this change and both schemas together. Once extended
feedback exists, keep a compatible reader or roll forward; do not delete immutable history to
make an older reader accept it. Production approval/budget resets are never part of rollback.
