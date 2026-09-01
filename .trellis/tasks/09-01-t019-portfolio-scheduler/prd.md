# T019 — PortfolioScheduler 与 ModelRouter

## Goal

让组织级 Agent 真正能在多个彼此隔离的 Task 之间被有界调度，并为每次 AgentRun 按
`RunDemand + AgentProfile + ModelPolicy` 做可重放的模型选择。Scheduler 只管理 WorkItem、
Assignment、Lease 和容量，不迁移 TaskStatus；ModelRouter 只返回带理由的 ModelSelection，
不调用 provider。

## Requirements

- 实现单进程、纯函数优先的 `PortfolioScheduler`；
- 按 readiness、priority/age、required capabilities、risk 和可用 capacity 选择 Agent；
- 聚合 active Lease，不得超过 `AgentProfile.max_parallel_assignments`；等待 WorkItem 不保留 active Lease；
- 使用 `validate_assignment_independence` 拒绝同一 Task 历史中的 Coder/QA/Reviewer 自审；
- 实现 deterministic `ModelRouter`，满足 RiskTier floor、Agent 能力、Context capacity 和显式 escalation 信号；
- 返回 typed `AssignmentDecision` / `ModelSelection`，拒绝原因必须结构化、可审计；
- 不引入消息队列、数据库、复杂 DAG、provider SDK 或共享可变会话。

## Acceptance Criteria

- [ ] 同一输入 WorkItem/Agent/Lease 得到稳定选择和稳定拒绝原因；
- [ ] capability 不匹配、Agent inactive、capacity 超限、lease 未过期和自审 assignment 被拒绝；
- [ ] priority、等待时间和 risk 的排序规则明确且有边界测试；
- [ ] ModelRouter 只选择 policy 中存在、满足 risk floor 且可容纳 Context 的 route；
- [ ] ModelSelection reasons 能解释 default、risk floor、complexity、capacity 或 escalation；
- [ ] 多 Task 可以共享 AgentProfile，但每个 Assignment/Lease/Run 保持独立；
- [ ] 测试、Ruff、strict Mypy、build 和 Schema 检查通过。

## Out of Scope

持久化 WorkQueue、分布式锁、跨进程调度、自动 TaskStatus 迁移、真实 provider 调用和 UI。

## Rollback

回滚 T019 提交即可恢复 T018 的 Workforce contracts；不改写已有 Task/Artifact/Context 事实。
