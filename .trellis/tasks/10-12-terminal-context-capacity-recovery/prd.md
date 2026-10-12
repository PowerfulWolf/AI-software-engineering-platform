# 原需求的终态上下文容量恢复

## 目标

旧版本把已经真实领取 Coder 工作、但还未启动模型的最终上下文超限误归为终态
`BUDGET_EXHAUSTED`。原需求有已批准的 `coder_reapply` 执行基线和完整开发补丁，当前
worktree 是干净的。增加可核验的恢复入口，使原 Requirement 通过新的精确人工恢复批准继续。

## 范围与允许路径

- `src/ai_software_engineer/recovery/**`；新增独立 no-start reader，普通失败 Run reader 保持严格。
- `schemas/delivery-recovery.schema.json` 和 `scripts/sync-capacity-recovery-schema.py`；保留手写 guards。
- `tests/recovery/test_context_capacity*.py`；增量回归普通恢复模型、批准、完整补丁与启动前分类。
- `.trellis/spec/core/terminal-context-capacity-recovery.md`、本任务资料和规范索引。
- 收据模型使用另外的 `context-capacity-receipt` 任务所定义的唯一 typed 模型。

## 验收标准

1. 原 terminal Task、StateEvent、旧 Run/route/stop/outcome 和批准内容不改写，不退款、不重建 Requirement。
2. 仅严格原终态原因、latest 完整验证基线、真实超限 Context、原 immutable CLAIMED、结束的 claim、
   全 CLOSED 队列、无本次模型/受控执行启动事实及空闲 Worker lock 一致时允许准备。
3. `origin=legacy_terminal_context` 只记录现在的回溯观察；不构造历史 AgentRequest/Run 或最终输入统计。
4. clean actual capture 和完整历史 retained patch 是不同事实；新方案使用唯一完整 required `recovery.patch`。
5. 公开 `scope_supplement → propose_delivery → exact approval → successor Task` 路径保持同一个原需求。
6. 任意 current facts、完整 patch、权限、基线或批准漂移拒绝；旧普通恢复仍必须有真实原 Run。
7. Python/Schema wire 相符；字段为空时保留普通存量 bytes/hash；只运行本次增量验证。

## 验证与回滚

验证命令及结果写入 `verification.md`。回滚使用提交的反向提交；受控停服后再部署旧版本，
保留所有不可变收据、计划、批准和旧执行现场。旧版本不能执行新 capacity 方案，不能删记录绕过。

## 存量数据处置

不直接改数据库。发布修复后，在原需求的继续入口准备方案，平台当前只读核验原事实并显式封存
回溯收据；用户批准 exact 新计划后沿同需求创建新的内部 Task、真实 claim 和新 Run。原 terminal
Task 与完整历史补丁均保持可追溯；缺事实时说明缺口并保留现场。
