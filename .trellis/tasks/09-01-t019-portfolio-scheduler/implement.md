# T019 实现记录

## Changes

- 新增纯计算 `PortfolioScheduler`，按 readiness、priority、risk、age、capability 与容量稳定匹配
  组织 Agent；
- 新增 typed `AssignmentDecision` 与结构化拒绝原因，生成可重放的 `RoleAssignment` 和
  `TaskLease`，等待任务释放容量；
- 跨 attempt 强制 Coder/QA/Reviewer 独立，拒绝 Agent 自审；
- 新增纯计算 `ModelRouter`，按 policy default、risk floor、复杂度、失败历史、关键路径和
  context capacity 选择模型；未知 context capacity 对非空上下文 fail closed；
- Scheduler 不迁移 Task、不持久化队列；ModelRouter 不调用 provider，保持 v0.1 边界。

## Verification

- 调度定向测试：13 passed；
- 合并 T020 后全量测试：324 passed；
- Ruff lint、format、strict Mypy、offline build 与 `git diff --check` 通过。
