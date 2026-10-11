# 实现与验证记录

本任务只改变新 Context 的阅读输入。`preserve_draft` 使用带完整 typed binding 与精确补丁
URI/SHA/字节数的 v2 投影；`coder_reapply` 继续包含完整旧补丁，历史 v1 内容与摘要保持。
所有 v2 消费者必须持有可信的完整 store verifier，重新验证最新 binding、plan、authority、
native epoch、start/stop 依据及旧补丁正文。候选完整 diff 和独立 QA/Review 契约保持。

## 增量验证

使用主仓 Python 3.12 虚拟环境，在本隔离 worktree 内设 `PYTHONPATH=src`，不跑全量测试。

- Red：新增真实 builder 大补丁测试在原实现抛出 `ContextBudgetExceeded`，确认旧正文重复
  输入在 32k fixture Context 预算内不可编译。
- `pytest tests/context/test_baseline_projection.py -x -q`：18 passed，158.35s。
- `pytest tests/manager/test_execution_baseline_context.py tests/recovery/test_terminal_baseline_context.py -x -q`：
  22 passed，102.43s。覆盖三角色身份、缺失 verifier、候选源码与 terminal v1/v2。
- `pytest tests/recovery/test_terminal_baseline_context.py tests/agents/test_candidate_review_source.py tests/manager/test_production_delivery.py tests/manager/test_native_verification.py -x -q`：
  56 passed，27.06s。随后 terminal 新增 v1/v2 参数由上项覆盖。
- `pytest tests/manager/test_production_execution_baseline.py -k 'public_stopped_provider or coder_reapply' -x -q`：
  3 passed，10 deselected，127.97s。公开 Host/MySQL fake model 与真实受控测试子进程走到独立
  QA/Review；包含同源、更新源与完整补丁 reapply。
- `pytest tests/manager/test_production_execution_baseline.py -k 'preserve_draft-False-False-False-False-False' -x -q`：
  1 passed，12 deselected，37.10s。普通非空 preserve 草稿公开交付回归。
- `pytest 'tests/manager/test_legacy_rescue_delivery.py::test_public_host_rescues_original_unknown_coder_without_rewriting_history[False-False-True-False]' -x -q`：
  1 passed，45.54s。真实本地停止核验、封存旧未知草稿后保留暂停，再由原需求独立验收。
- Ruff check、Ruff format --check：13 个变更 Python 文件通过。
- Strict mypy：8 个变更 source 与新 projection 测试共 9 文件通过。
- 五个独立 Python 进程直接导入 Context、terminal reader、native facts、delivery factory、
  production backend 均 exit 0；`git diff --check` 通过。

所有 MySQL 测试与 sibling agent 串行协调，结束后已释放测试窗口。
独立 reviewer `/root/stopped_unknown_public_path` 核查完整生产 diff、v1/v2 读取、完整 store
校验、candidate/native/terminal consumer 与 factory wrapper，未发现阻断问题；未重复全量测试。

## K1 只读核验与实际限制

原 run `run_ededa8839bcb445ab687a563c194948a` 的 Context 与完整 baseline store 已只读核验。
原 execution.baseline 为 595,135 字符，其中完整补丁 566,420 字符 / 604,438 字节，
补丁 SHA 为 `c085ce5563e49e446c861eb4771cc3634af2f8ad0ebb27181175d9cbf80211f5`。
原 base native prompt 估算 277,470 tokens 超过本地 256k；仅无损改 frame 仍超预算。
内存中应用本投影后 baseline 为 3,801 字符，Context 估算 106,654 tokens，base native
prompt 估算 120,454 tokens。模拟没有保存新 Context，也没有调用模型或继续 K1。

原 native stderr 被截断，真实首因仍不能据此定为输入超限。此任务不把 UNKNOWN 改成
认证错误，不生成停止证明，不退款，不修改旧失败、审批、Context、binding 或完整补丁。
最终序列化输入的预算与 start/outcome 边界由独立任务负责。

## 存量数据处置与回滚

无需改库或重写历史。原 K1 仍需通过父任务提供的精确 typed 受控授权和继续入口，使用
新 Run/Context 验证当前完整基线及保留工作区，再由独立 QA/Review 验收；本 fixture 成功
不等于 K1 已交付。本任务未部署、未重启、未审批、未发起生产执行。

在没有持久化 v2 前可撤回本提交；已有 v2 后须保留 reader 与完整证据 verifier，仅禁用
新 v2 生成，不删除 Context、不回写旧摘要、不删除保留草稿。
