# Verification

Only incremental tests were run. Production ASE was not restarted or approved, K1 was not executed,
and its existing Task, Run, journals, approvals and worktree were not mutated.

## Public recovery and retained history

```bash
.venv/bin/pytest -q --tb=short tests/manager/test_legacy_rescue_delivery.py --maxfail=1
```

Final run: **5 passed in 82.99s**. Uses isolated MySQL, real Git and fake native role execution,
never real provider calls. Original UNKNOWN stays unknown. Original Task, branch, draft, index and
permissions remain unchanged until the new claimed Coder; independent QA/Reviewer verify one
candidate. Covers unsealed outcome, real sealed final refusal, local/reboot authorization mismatch,
active survey refusal, binding-before-consumption crash, later boot, active re-proposal refusal,
completed consumption replay without scanner, one budget consumption and complete history traversal.

## Affected baseline/read regressions

```bash
.venv/bin/pytest -q --tb=short \
  tests/manager/test_execution_baseline.py tests/manager/test_execution_baseline_reservation.py \
  tests/manager/test_legacy_snapshot.py tests/manager/test_execution_baseline_invocations.py \
  tests/manager/test_execution_baseline_context.py tests/manager/test_execution_baseline_native_rules.py \
  tests/work_queue/test_baseline_history.py tests/team_view/test_engineering_history.py --maxfail=1
```

Final run: **68 passed in 163.92s**.

## Focused observation, HTTP and Schema checks

- Scanner/old containment worker regression: **61 passed in 3.29s**.
- Final OS identity failure + HTTP acceptance regression: `pytest -q
  tests/manager/test_legacy_containment.py tests/web_console/test_legacy_rescue_acceptance.py`,
  **50 passed in 3.67s**. Twelve OS failure combinations preserve scene/history and return typed WAITING.
- `pytest -q tests/contracts/test_local_legacy_rescue_schema.py`: **5 passed**. Covers all three
  containing static schemas and one canonical preparation gate.
- Console HTTP/Manager/Transport regression by UI owner: **94 passed** before the final additional
  identity failure cases; those later cases are covered by the 50-test run above.
- Real Chrome legacy-rescue/engineering-wait/capability fixture: **11 passed**.
- Lightweight CJS engineering-wait/capability regression: **37 passed**.
- Negative regressions were demonstrated red before fixing input-value exposure, stale contract
  submission and prerequisite exceptions; final targeted runs are green.

## Real macOS observation and quality

Fixed read-only real macOS survey on a temporary empty directory finished in **0.702s**. Survey
integrity passes, no PROCESS_SCAN_INCOMPLETE. The only blocker is a real `codex resume` execution;
desktop app-server/mcp-server are not misclassified. No discovered process was signaled or stopped.
The survey cannot replace engineering attestation of the original call and all derived tools.

Changed Python production/test files: Ruff and format pass, strict mypy **17 files pass** (UI-owner
test files additionally checked by that owner). Schema generator passes Ruff/format and is
byte-idempotent. `git diff --check` passes. No full suite was run.

Independent read-only review of all changed boundaries found no remaining blocking issue after
re-proposal, quiescence, OS read failure, desktop process and duplicate Schema gate repairs.
Reviewer additionally ran two old-wire/boot compatibility tests successfully.

## 存量数据处置

No schema migration or history rewrite. Original K1 remains paused. Load this version through the
controlled service restart, then let the user click “准备保留进度的恢复方案” on the original requirement.
Only if the complete local cessation statement is true may the engineering user approve that exact
plan. Local active execution/incomplete survey remains a wait. The reboot option is retained.

Before new method facts exist, controlled stop/revert/start is possible. After they exist, retain a
compatible reader and forward-fix; never delete immutable authority, queue facts or retained work to
roll back. No automatic merge/deployment or production approval was performed.
