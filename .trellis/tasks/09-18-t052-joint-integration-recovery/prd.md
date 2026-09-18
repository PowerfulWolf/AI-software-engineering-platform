# T052 联合验收失败恢复

## Goal

让已完成原生子交付的联合 Requirement 能把联合命令启动失败、超时和非零退出封存为 durable evidence，并在用户继续交付时生成一次有界的联合验收计划替代，最终可以进入 `DONE` 或稳定 `BLOCKED`。

## Requirements

- 联合命令无法启动、超时、零测试成功或非零退出都不能变成无证据的 `MANAGER_FAILURE`。
- 失败 evidence 必须脱敏、绑定原计划和候选集合，保留在不可变 journal 历史中。
- 只有明确的 `BLOCKED + integration evidence` 恢复路径可以清空当前计划并进入 Planner 重规划；普通 checkpoint 不得改变已批准计划。
- 重规划有界，跳过已经 `DONE` 的子交付，不重新执行 Coder、QA 或 Reviewer。
- Web Console 通过同一状态链显示联合验收失败/重规划，不把失败操作伪装成执行中。

## Acceptance Criteria

- [ ] 启动失败和超时生成失败 `CommandResult`，父需求进入 `BLOCKED`，Operation 不再是通用 Manager failure。
- [ ] 用户继续交付后可生成新的完整 `JointExecutionPlan`，验证通过后再次执行联合验收。
- [ ] 旧计划、失败 evidence、子交付候选和 Reviewer 事实保持可读且不可变。
- [ ] 成功联合验收仍以完整 candidate set 和 integration evidence 进入 `DONE`。
- [ ] 合法、非法、边界和恢复测试通过，规范与文档同步。

## Technical Notes

变更集中在联合 service/journal/production backend 和对应 contract tests。真实模型与生产 journal 不在离线测试中执行；交接时用户重启 Console 并点击一次“继续交付”。
