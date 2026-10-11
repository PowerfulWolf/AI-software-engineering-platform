# 恢复等待与存量 cursor 验证

## 实现范围

- `recovery/entry.py`：内部 `NativeRecoveryPending`；仅接纳 typed queue pending；
  原 approved plan/authorization/sealed Task/seed/invocation/dispatch 的只读存量接回入口。
- `recovery/pending_wait.py`：一致只读 SQL 快照；Task 事件连续 revision/身份/阶段链/最终状态与
  candidate 事件校验，精确唯一 WAITING、Task intent/source/checkpoint、allocation/boundary、
  无 active claim 和当前已释放领取校验；不调用会初始化 DDL 的后端 snapshot。
- `recovery/resume.py`：存量 admitted IMPLEMENTING/QA/REVIEW 先接回精确等待，只有没有
  typed wait 的 IMPLEMENTING 才考虑首轮中断路径；
  返回受控中文 reason/next action 和限长脱敏 detail。
- `manager/delivery.py`：`adopt_recovery_pending` 和共用的 snapshot 写入 seam；
  只追加当前原需求的 cursor，不再次运行后端，不改 Task/预算/批准/verdict。
- 两个专用测试文件和 `delivery-recovery.md` 的可执行契约。

## 先红回归

1. `test_pending_execution.py` 的 raw/structured pending 在原真实 `resume_execution → execute`
   路径分别直接抛出 `DeliveryQueuePending` / `DeliveryWaiting`；未知 RuntimeError 原样传播。
2. `test_pending_wait.py::test_admitted_fourth_attempt_wait_reattaches_before_first_attempt_interruption_gate`
   在存量修复前仍返回旧 BLOCKED Task cursor，确认只处理新执行 pending 不足以修复存量需求。

## 最终增量结果

```sh
.venv/bin/pytest -q tests/recovery/test_pending_wait.py \
  tests/recovery/test_pending_execution.py tests/recovery/test_knowledge_wait.py \
  tests/e2e/test_delivery_checkpoint.py tests/e2e/test_unified_project_entry.py --tb=short
```

初次结果：**94 passed in 5.46s**，含 23 个 fresh pending、31 个 stored pending 回归。
专用测试使用真实 temp recovery store/authorization/record hash 与 typed SQL fixtures；
验证真实 SQL reader 只发 SELECT/只读事务，未执行模型、claim、DDL、SQL 写入或重复后端执行。
这不是一次真实生产恢复验收，也未运行全量测试。

Ruff check/format 6 个相关 Python 文件、mypy 4 个源文件和 `git diff --check` 均通过。

独立评审补齐两项 P2：QA/Review 存量 wait 的公共入口覆盖；真实 stored accessor 不可调用会
初始化 schema 的 backend snapshot。补齐后 `test_pending_wait.py` **41 passed in 5.15s**，
增加 QA/Review × 原基线/执行基线零执行回归、事件 gap/identity/stage 反例和显式 invocation
plan/seed digest 反例；实际 controller → reader 路径断言后端 snapshot 不调用。
最终上述相同 focused 增量命令：**104 passed in 6.23s**。六个 Python 文件 Ruff check/format、
四个源文件 mypy 和 `git diff --check` 在最终改动后再次通过；此批均为 temp/typed fixture 测试，
未与并行实际 MySQL 验证争用数据库。

## 扩展集的既存失败隔离

一度扩展到旧 `test_interruption_native.py`、`test_execution.py`、`test_resume.py` 集成集；
出现 10 个失败后中止（39 passed / 10 failed，100.68s），未为了本补丁改写这些旧用例。

随后将完整冻结 commit `d8d5667d4aacf6d9bd0f04abf2bdd4056d50a540` archive 到
`/tmp/ase-pending-head-d8d5667-o91a6w8c`，使用主仓 `.venv/bin/python`，但 cwd、
PYTHONPATH 和 tests 全部指向隔离树，重跑以下两个 focus 用例，**2 failed in 27.92s**：

- `test_interruption_native.py::test_exact_interruption_resume_keeps_seed_and_old_invocation[False]`：
  在 `propose_delivery → read_terminal_workspace_snapshot` 缺少 `state/continuations/<task>`。
- `test_resume.py::test_joint_verification_approval_stays_current_and_completes_delivery[False-False]`：
  返回 `JointDeliveryResult`，旧断言期待 `JointDeliveryResumeResult`。

日志：`/tmp/ase-full-head-baseline-20261011.log`。以上两个失败明确在完整原 HEAD 已存在，
不由本轮 agents/runner/pending 改动引入；未据此声称其余 8 个失败全部完成基线归因。

## 存量数据处置和回滚

本次未部署、重启或写生产数据。加载修复后，在原需求点击继续，通过公开入口读取并核验
已批准恢复 Task 的当前等待，追加原需求 cursor 接回同一 Task。原终态 Task、旧失败
Operation、恢复执行、报告和现场全部保留；接回不是批准重跑或接纳旧错误报告。
后续通过该当前 typed wait 的 Handle/精确授权入口处理。缺记录、漂移或 active claim 时保持拒绝。
回滚不得删除新旧审计事实、重置 Task 或重放已消费 invocation；保留已追加 cursor 的兼容读取。

## Root production read-only validation

The final stored wait reader was invoked in a real production READ ONLY transaction and
validated task_recovery_8ca06fa0aec236ab940597ad1482bfc8, revision8, attempt4, current
work_3b2b392b685bca6f86c29cec6788e5e259bb3defcb5fc9e2c9e1dcafbf507584 and PLATFORM_BUG.
No schema initialization, model call, queue reservation or data mutation was performed.
Root independent focused tests and review are recorded in the rejected-output task verification.
