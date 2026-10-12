# 首次真实 Coder 与执行身份不是同一事实

## Observed current facts

只读`KnowledgeRecordStore`验证：K1恢复Task `task_recovery_45588301d1b35b02f44762650b6195e4`
attempt1没有DeliveryInvocationStart/outcome；attempt2真实start为
`run_e197336456dc4dd683e2245194ad6fcc`，2026-10-12T03:17:01.994116Z，timeout1800秒，source
`9cccb5b5a0eff3b1c3dff6fc0cc5c5210b9fa550`。Root另以真实PID birth和业务改动确认已在开发。
知识完成记录数不是进行中主调用数，不能据completed-only列表或父进程CPU认定模型未开始。

现有`FirstCoderRunWorkspaceAdmission`按`request.attempt>1`返回None；RecoverySeedService.authorize
也硬编码attempt1。实际执行身份会被知识准备失败推进，所以二者不能证明恢复种子已准入。

## Required behavior

在拥有真实claim和锁的可信应用边界，根据精确当前Task/dispatch/原seed与持久化实际准入历史，
区分知识-only失败、已开始但未知、已经准入并产生可信结果。首次真实main请求不论attempt数字
仍须核对当前批准/sealed Task/seed/context/权限并封存真实准入；不得扩大权限或退款。

任何start无outcome或原生执行未停止仍保留不确定性，不重放、不补造旧recovery invocation。
已接纳progress、候选返工或确定已消费原seed的后续运行使用原正常input gate；不重放旧seed。
不同provider/fresh adapter不得改变这些结论，不能用内存flag或最近一次attempt代替durable事实。

## Minimum red test

真实临时Git HEAD干净、请求attempt2、没有任何过去main执行，fake seed authority已漂移。
Coder必须在provider前调用可信seed检查并拒绝；目前wrapper直接跳过，Codex/Responses都进入
fake provider。额外dirty case保证不会仅依赖默认clean check误当已完成seed核验。

## Existing data treatment

当前K1 attempt2已真实运行，不停止、不修改现场或审批、不追补recovery invocation。
等待真实结果保存，之后按exact run/outcome/route/candidate链和原QA/Review验收路径处理。
如继续需要当前准入而历史种子receipt缺失，应采用明确typed、精确绑定现存事实的受控决定，
不得把新修复追溯应用成旧执行已经有receipt。此任务阶段未执行任何生产写操作。

## Final implementation and review

Removed attempt-number admission selection. The production Supervisor's existing real
`WorkerExecutionGuard` supplies the current claim; the selector reads only exact Task-indexed
queue items, immutable original claims/steps and exact main invocation keys. First actual main
admission revalidates the seed at the actual Context attempt and publishes its unchanged receipt
under the Worker write fence. Legacy accepted progress/candidate and the old separately approved
replacement are checked through exact outcome/publication/artifact identities. No old missing
receipt is backfilled; unknown prior starts still reject replay. Newer native continuation keeps
precedence over the seed gate.

Codex no longer catches arbitrary `Exception` around admission. Both providers map typed gate
rejections to Chinese `WORK_INTERRUPTED`, nontransient, before any model call. Lease loss, unknown
execution, queue/knowledge wait and unexpected bugs propagate unchanged. Recovery domain callers
retain the `RecoveryRejected` type. No wire schema, SQL, approval or production facts were changed.

Independent reviewer `/root/summary_result_scope_compat` reviewed source/contracts, original-claim
and accepted-dispatch binding, replacement scope and error propagation: scoped PASS. Reviewer
separately ran the new provider + seed/interruption files (50 PASS before the additional I/O row),
then all 40 provider tests including I/O (PASS), plus Ruff/strict mypy on 15 owned files (PASS).

## Incremental verification evidence

All commands use `PYTHONPATH=src` and the main repository `.venv/bin/` tools in the isolated
`ase-capacity-receipt` worktree. No full test suite or real provider was run.

- `pytest tests/recovery/test_first_real_seed_admission.py tests/recovery/test_preparation_inspection_scope.py -q --tb=short`: 26 PASS, 10.83 s.
- `pytest tests/agents/test_first_real_coder_admission.py -q --tb=short`: 40 PASS, 4.34 s, covering both providers, selection/authorization phases, zero provider calls, fixed classification and exact control signals.
- Existing adapter/fallback increment before the final narrow error seam: 130 PASS, 33.66 s. After that seam, initial-admission/Codex/new-provider increment: 100 PASS and one obsolete fake RuntimeError rejection expectation. The fixture now raises typed WorkspaceAdmissionRejected; focused rerun of that case and then-current 36 new cases: 37 PASS, 4.84 s. No generic RuntimeError catch was restored.
- `ruff check` and `ruff format --check` on 15 owned Python files: PASS. `mypy --strict` on the same files: PASS (15 files).
- Selected real Git/isolated MySQL initial seven-node run: 2 PASS, 5 FAIL, 585.98 s. Two reapply failures used the old error expectation; it now expects the earlier exact-current-start refusal. Their focused final rerun is recorded below when complete.

## Known baseline integration fixture failures

The other three initial MySQL failures use `tests/recovery/test_native.InterruptedFactory`,
which has no real native owned-process capture/stop journal. They fail in
`recovery.propose[_delivery] -> read_terminal_workspace_snapshot -> _read_facts ->
FileContinuationStore._open_directory` because `state/continuations` is missing. They do not
reach seed selection. This is a verified existing fixture mismatch, not a passing test:

- Independent isolated `efb2fc1` baseline, `tests/recovery/test_execution.py::test_joint_child_recovery_retains_approved_parent_context`: 1 FAIL, 9.55 s, same missing-directory stack.
- Same baseline, `tests/recovery/test_interruption_native.py::test_exact_interruption_resume_keeps_seed_and_old_invocation[False]` and `[True]`: 2 FAIL, 5.39 s, same stack.
- Current `e3dd96f` plus this work, same exact three nodes: 3 FAIL, 12.41 s, same stack.

Do not create an empty directory or synthetic stop record to make these fixtures pass. A follow-up
fixture migration must use a real offline subprocess and the native capture/stop recorder, retaining
the complete original invocation audit and all no-replay rules. This task does not relax production
auditing to accommodate stale fixtures.

## Existing data and rollback

The earlier read-only K1 observation has since acquired a genuine matched failed main outcome and
real owned-session `local_execution_limit` stop. Its missing historical seed invocation stays missing.
Its native same-Task continuation was already selected; this fix does not approve/resume it or alter
its worktree/budget/history. Root handles the separate capacity gate and current public operations.
Revert the scoped code commit before another execution to roll back; retain any real receipt already
published by the fixed version. Reverting never authorizes replay.

Final adapter regression confirmation after typed fake correction and the I/O matrix addition:
`pytest tests/agents/test_first_real_coder_admission.py tests/agents/test_initial_admission_scope.py tests/agents/test_codex_cli.py -q --tb=short`: **105 PASS, 30.05 s**. This supersedes the intermediate 100-pass/one-obsolete-fixture result above; no remaining adapter failure.

Final isolated MySQL reapply confirmation:
`pytest 'tests/recovery/test_execution.py::test_recovery_complete_native_delivery_and_preserve_failed_history[True-False]' 'tests/recovery/test_execution.py::test_recovery_complete_native_delivery_and_preserve_failed_history[True-True]' -q --tb=short`: **2 PASS, 390.64 s**. Both use real offline native source execution/stop, real Git/MySQL claims, fresh exact recovery admission and independent QA/Review. The isolated DB was explicitly released after completion.

Final historical-claim boundary check: the selector also explicitly compares returned
`original_claim(start.lease_id).lease.id` with the exact start lease, since the SQL lookup key
alone is not a field-integrity guarantee. A schema-valid same-work claim with a foreign lease ID
returned under the old key was reproduced as a failing negative test before the one-line guard
(`test_original_claim_returned_under_foreign_lease_key_is_rejected`: DID NOT RAISE, 1.32 s).
The fix rejects this mismatch before seed consumption or legacy accepted-input use; no record is
backfilled. The corresponding independent delta review is required before the final commit.

Final lease-boundary delta: author 1 PASS/2.14 s, independent reviewer 1 PASS/1.07 s; both-file Ruff and strict mypy PASS. Independent delta review PASS. The full scoped source/spec review remains PASS.
