# 增量验证与边界

新增实际final-input回归先因缺少typed exception/receipt变红，再完成真实preflight gate后转绿。
- receipt正向/负向/legacy约束：6 passed。
- final payload/native wrapper/schema/Responses/before-start + verifier preparation既有回归：31 passed。
- 6个相关文件 strict mypy通过，Ruff与diff检查通过。

记录内容只包含真实claim、Task/context digest、预算和estimate；无prompt/body/key。保留现有native verification receipt。
store故障、身份漂移或已有invocation拒绝wait发布。无退款/重试计数写入，无provider调用。

存量数据处置：此writer不改旧K1；旧terminal容量故障必须通过另一路显式legacy_terminal_context
观察与受控successor恢复，不补造旧request/final count。发布前同时集成classification与恢复consumer；
仅writer单独上线不能解决旧任务。回滚受控停服后恢复代码，保留已发布receipt及失败历史。

## 集成增量核验（2026-10-12）

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/agents/test_context_prompt_rendering.py \
  tests/agents/test_model_input_preflight.py \
  tests/context/test_baseline_projection.py \
  tests/manager/test_context_capacity_receipt.py \
  tests/orchestration/test_context_capacity_wait.py \
  tests/contracts/test_context_capacity_baseline_schema.py \
  tests/web_console/test_manager.py -k 'context or capacity or recovery'
node --test --test-name-pattern='blocked|阻塞|continu' tests/team_view/delivery-status.test.cjs
```

分别为 103 passed / 57 deselected 和 5 passed；覆盖完整原文 fallback、receipt、实际
最终输入、baseline 投影、三角色等待和恢复审批。Node 用例验证正在运行的 Continue
Operation 不能盖住持久化阻塞，残留 claim 不能把未运行节点显示成执行中。
这是自动化投影/DOM 验证；当前 CUA 浏览器不可用，尚无真实浏览器视觉验收结论。

旧 K1 的专用 reader 已进行生产只读 discover 核验：原 Task
`task_recovery_5536cf4e59ca28db0213bd719d50860d`，无本轮失败 Run；最新保存 Context
255325 tokens，完整旧补丁 604438 bytes。原 terminal event 的旧 source 仍保留，通过
已批准 baseline、完整 Context 与真实 claim 证明实际输入 source。空 worktree 的平台
清理记录、原 branch 和 source 均匹配。仅读取、未重建工作区、发布 receipt、批准或调用模型。

Coder 及 QA/Reviewer 的公开恢复路径已分别在隔离 MySQL 用一轮/两轮容量等待检验；
这些 fixture 的 DONE 不是生产 K1 的交付结果。发布和生产恢复尚待最终独立审查及维护部署。

终态 follow-up 集成为 `ec55d53`。保留原 strict `provider_started` 校验并合并 legacy 字段
拒绝用例，8 个 receipt/recovery/SQL 增量模块重新验证 82 passed；独立 reviewer 另复跑
workspace/Plan 34 passed，固定提交完整 diff/spec 无未解决 blocker。

## 存量需求部署与恢复步骤

1. 核验所有 Operation 完整 active 集为空，由受控 service stop 完成持久化记录与进程收尾。
2. 主维护 checkout 集成、推送修复。目标 checkout 是
   `/Users/zhangjunshuai/workspace/code/ai-workspace/AI-software-engineering-platform`，另行核验
   clean 后 fetch/ff-only 到新 main；不能把维护 checkout 当成目标仓库。
3. 用显式 `ASE_CONFIG=/Users/zhangjunshuai/workspace/code/.ase/config/self-iteration-ai.json`
   启动已修复服务，核验服务身份和公开读取能力。
4. 读取同一父 Requirement 的最新 checkpoint，经公开 `POST /api/v1/operations` 提交
   `ContinueDeliveryIntent`，准备受控方案。只在本次 proposal 有界还原有可信清理证明的原
   clean checkout；准备成功不代表模型开始或需求完成。
5. 从可信 store 读取完整方案、旧 patch、原授权链和目标基线，核对审批页面的实际事实后
   提交 exact `approved_plan_sha256`。新内部 Task 不得改变父 Requirement 身份或重置旧 Task。
6. 跟踪真实新 claim/Context/invocation，交付必须经过 Coder、独立 QA、Review 与 handoff。
   若再次阻塞，使用对应角色的 typed wait/精确方案；不手改 SQL、verdict 或旧审批。

以上为受控操作计划；实际维护、恢复和交付结果将另行记录，当前尚未执行这些生产 mutation。

最终集成 `e7d650c` 后，context renderer/receipt、fresh repair Schema regeneration、capacity
baseline Schema、domain resolution 和 verifier capacity reader 的组合增量 **89 passed**。
严格 mypy 检查全部 30 个变更 source 文件通过；Ruff check 全部 62 个变更 Python 文件通过。
format 检查发现 5 个既有本轮修改文件仅换行/引号格式不一致，已按仓库 Ruff 统一，未改变行为。
公开 Coder 一轮/两轮与 QA/Review 各一轮/两轮在真实隔离 MySQL 串行验证 **6 passed**；
固定 QA commit 的独立 narrow review **33 passed**，无范围内未解决 blocker。不跑全量。
