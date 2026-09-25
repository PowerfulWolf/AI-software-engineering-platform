# Continue-delivery provenance fix — 2026-09-25

## Outcome and live recovery

The fix was implemented and loaded into the Console from the isolated
`ai-workspace/ase-provenance-recovery` worktree at base `60a04a5`. After validation, the user
explicitly requested committing and merging these changes into the platform's main checkout.
The commit containing this handoff is the integration unit; Git history records its identity.

The original failing Requirement is
`delivery_multi_bd73c5ce9fa226eaa8e427b5c7c1dd96dce1e006` in `project_codex_ea3536b4974b`.
Its retained candidate is `fb76942771f79cecd9ae887961c8bb570c52046b`.
Public Console operation `operation_5018b2c5895c19265dc63623db326699` completed `SUCCEEDED`,
returning candidate-verification approval for plan
`3d1eb17020b41c5803a92c46988809113e0eecf5cdc9d3dd03a618f3e9e3166f` and parent checkpoint
`88e46f9e208026a98a690f3bdd75c1fa8587ec7da664c98d559751099bb7219e`.

The real browser was checked: the original Requirement displays “批准独立 QA 与 Reviewer 验证”
and an enabled “批准并继续” button with the retained candidate. No approval was submitted and
no verification model was started. `GET /api/v1/console` reports `delivery_ready=true`.

## Root causes and prevention

1. Change-propagation/test gap: recovery compared runtime `retry_failures` against the immutable
   dispatch. A valid Coder timeout followed by success therefore failed candidate provenance.
   `task_matches_dispatch` now centralizes immutable intent while retaining strict policy checks.
2. Cross-layer contract gap: parent synchronization discarded a child's human approval result.
   `JointDeliveryResumeResult` now carries both the synchronized parent and the exact native gate;
   it rejects a mismatched child. Console reuses the existing native approval formatting.
3. The browser matched approvals against the operation's old input checkpoint, hiding a valid
   gate after parent synchronization. It now matches the parent result checkpoint, preserving
   compatibility for older native-result operations and rejecting stale/consumed approvals.

The maintained contracts are `.trellis/spec/core/execution-retry-policy.md` and
`.trellis/spec/core/multi-directory-delivery.md`; this repository has no spec-template mirror.

## 存量数据处置

No database repair or history rewrite was required. Task, dispatch, retry history, artifacts,
candidate, existing decisions and past failed Operations remain intact. Normal Console continuation
appended new Operation/parent-checkpoint records and proposed an exact verification plan.
Refresh the existing page, inspect the plan and explicitly click “批准并继续”. A subsequent
QA environment failure is a separate verification result, not grounds to bypass QA/Review.

## Validation

The regression tests were observed failing at the intended seams before the respective fixes.

```sh
.venv/bin/pytest -q -p no:cacheprovider \
  tests/recovery/test_candidate_verification.py \
  tests/recovery/test_verification_admission.py \
  tests/recovery/test_verification_disposition.py \
  tests/recovery/test_verification_routing.py \
  tests/recovery/test_delivery_continuation.py \
  tests/orchestration/test_execution_retry_budget.py \
  tests/e2e/test_planned_delivery.py tests/manager/test_dispatch.py \
  tests/team_view/test_dispatch_identity.py tests/recovery/test_verification_snapshot.py \
  tests/domain/test_task_dispatch_identity.py tests/recovery/test_joint_resume.py \
  tests/manager/test_team_host.py tests/web_console/test_manager.py
node --test tests/team_view/ui.test.cjs
```

Results: 133 Python tests and 6 UI tests passed. Ruff and `git diff --check` passed. Strict mypy
passed the 9 modified production modules plus 6 directly related test modules (15 files).
The original real-data read-only provenance probe passed; the public API and live browser also
confirmed the original user-visible recovery path without bypassing approval.

### Remaining validation limits

The broader Git/MySQL run of `tests/recovery/test_resume.py` is not green:

- Three native recovery tests also fail on the unchanged main checkout: post-feedback recovery,
  failed-candidate remediation, and verification after checkpoint append. Their setup/status
  expectations fail before the intended assertions. They were not weakened or skipped.
- Both `joint_scope_recovery_targets_current_preparation_after_main_advances` cases now retain
  approvals and the parent cursor but subsequently fail in the separate Coder recovery path:
  the old preparation remains / parent stays BLOCKED after plan approval. This path is not the
  user's retained-candidate QA verification path and has not been declared fixed.
- Including that older integration test module in mypy also reveals 5 existing errors in its
  imported `tests/manager/test_production_backend.py`; production modules type-check cleanly.

No full-suite pass or completed business delivery is claimed.

## Runtime / rollback

The current Console process still uses the isolated worktree. Merging the same code into the
main checkout does not require a service restart; future starts may use either merged checkout.
The existing configuration is
`/Users/zhangjunshuai/workspace/code/.ase/config/self-iteration-ai.json`; credentials stay only in
its managed runtime environment file and are never copied into source or this handoff.

To roll back, first confirm there are no QUEUED/RUNNING Console operations. Use a separate clean
checkout of the pre-fix revision `60a04a5`, install its locked dependencies, and run its
`scripts/ase-console-service.sh restart` with the same `ASE_CONFIG`. This restores the old
implementation (and its provenance bug) without changing delivery data or resetting the main
checkout. Restarting from the merged main checkout keeps the fix and is not a rollback.
