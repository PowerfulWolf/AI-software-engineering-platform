# Design

1. `PlanTestMatrixError` carries typed criterion/required/observed/missing test levels from
   shared validation. Persist optional `JointPlanFeedback.test_matrix_issues` using omitted
   absent fields to preserve legacy nested checkpoint/stage-proof hashes.
2. `planner_test_requirements` builds typed per-unit requirements from accepted design.
   `_produce` passes these as explicit input; a fresh per-call schema restricts level to the
   union of design levels. Exact per-criterion coverage still requires deterministic validation.
3. Joint Planning becomes a bounded loop only for `PlanTestMatrixError`. Append full rejected
   plan and typed feedback, then re-enter with a new reserved work attempt. Fail at allowance;
   valid plans alone reach dispatch. Typed transient failures retain the old refund semantics.
4. Manager exposes `PLANNER_TEST_MATRIX_REJECTED` at terminal rejection; UI separates this,
   generic legacy COMMAND_REJECTED, MODEL_INVALID_OUTPUT and provider failures. No new API
   mutation or UI retry authority is introduced.

Do not split arbitrary level strings, weaken required levels, automatically accept edited
artifacts, reset attempts or rerun Designer. Historical rejected feedback is input, not an
accepted plan; a successful correction binds its predecessor digest through existing compilation.
