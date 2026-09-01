# T018 — Organization-owned Agent workforce foundation

## Goal

纠正“每个项目拥有一套 Agent”的领域假设：Agent 是组织拥有的长期团队成员；项目拥有规范、
工作和执行记录；Task 通过 Assignment/Lease 临时使用 Agent 能力；模型由每个 Agent Run 的
ModelPolicy 选择。

## Requirements

- 定义 AgentProfile、WorkItem、RoleAssignment、TaskLease、ModelPolicy、ModelSelection 和
  AgentRunAllocation 的 Python/JSON Schema 契约；
- 保留 Task 内 `Coder → QA → Reviewer` 串行和独立裁决，但允许未来在组织层并发多个 Task；
- 把交付状态与调度等待状态分开，临时等待释放 Lease，`BLOCKED` 只表示终局阻塞；
- 项目 sidecar 不保存 Agent 本体，将 `agents/` 替换为 `assignments/`；
- 记录不可逆架构决策，更新统一语言、README、规范、架构、失败路由和路线图；
- 不在本任务实现消息队列、分布式 Scheduler、并行 DAG 或真实 provider model routing。

## Acceptance Criteria

- [ ] AgentProfile 可以声明多个可担任角色、能力、容量和默认 ModelPolicy，但不绑定项目或具体模型；
- [ ] RoleAssignment/TaskLease 把成员身份、Task、Role 和有界容量显式关联；
- [ ] AgentRunAllocation 记录可归因的 Agent、Model、Prompt、Spec、Tool policy 和 Context；
- [ ] WorkItem 的 `WAITING_*` 状态需要原因，且与 Task delivery status 正交；
- [ ] ModelPolicy 对所有风险级别定义最低 BrainTier，ModelSelection 带可审计理由；
- [ ] Project Workspace v0.2 layout 使用 `assignments/`，旧 `agents/` layout 不被静默接受；
- [ ] 文档明确同一 Task 的 Coder 与 QA/Reviewer 不能是同一 Agent；
- [ ] 所有测试、Ruff、Mypy、build 和 Schema 检查通过。

## Rollback

回滚本任务提交即可恢复 T017 的 v0.1 sidecar layout 和旧文档。已有 v0.1 sidecar 不被本任务
自动删除或改写；未来迁移必须由显式工具完成。
