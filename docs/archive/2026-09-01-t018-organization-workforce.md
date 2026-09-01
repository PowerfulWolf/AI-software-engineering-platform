# T018 阶段归档：Organization-owned Agent Workforce

- 归档日期：2026-09-01
- Feature commit：`400ac04`（`feat: establish organization-owned agent workforce`）
- 完成任务：T018
- 里程碑状态：M5 组织 Workforce foundation 完成；T019 Scheduler/ModelRouter 待实现
- 质量基线：303 tests、Ruff check、Ruff format、strict Mypy（96 个源码文件）、offline package build、`git diff --check` 全部通过

## 阶段目标

纠正“每个 Project 拥有一套 Agent”的模型：Agent 是组织拥有的长期成员；Project 只保存工作、
规范、访问授权和运行事实；一个成员可以通过有界 Lease 服务多个相互隔离的 Task。模型不再是
成员身份的一部分，而是在每次 AgentRun 按风险和客观需求动态选择。

## 完成交付

- `AgentProfile`：组织级成员身份、能力、可担任角色和最大并行 Assignment，不包含项目路径、
  concrete model 或可变会话；
- `WorkItem`、`RoleAssignment`、`TaskLease`：调度状态与 Task delivery 状态正交，Lease 有明确
  时间窗口，`WAITING_HUMAN/WAITING_DEPENDENCY/RETRY_SCHEDULED` 释放容量；
- `RunDemand`、`ModelPolicy`、`ModelSelection`、`AgentRunAllocation`：模型选择按 risk、上下文/变更
  规模、受影响层、失败历史和 critical path 等信号记录 policy version 与 reasons，并将 Agent、
  Model、Context、Prompt、Spec、Tool policy 归因到唯一 Run；
- 同一 Task 历史中的 Coder、QA、Reviewer 不能复用同一 Agent，即使跨 retry attempt 也 fail closed；
- `ProjectWorkspace` v0.2 将 sidecar `agents/` 替换为 `assignments/`，旧布局不静默迁移；
- `ProjectId`、`RunId`、`ContextId` 统一到 `domain/identity.py`，消除跨层正则漂移；
- 同步 README、CONTEXT、AGENTS、ADR 0002、总体架构、状态机、失败路由、里程碑、可视化方案和
  `.trellis/spec/core/` 执行规范。

## 关键不变量

1. Knowledge 属于组织，不属于某个 Agent 会话；Project sidecar 不复制 AgentProfile。
2. 同一 Task 内交付保持 `Coder → QA → Reviewer` 串行；组织层未来才能并发多个隔离 Task。
3. AgentRun 不共享 Context、worktree、Artifact lineage 或可变模型会话。
4. `BLOCKED` 只表示终局没有安全继续路径；暂时等待使用 WorkItem waiting 状态并保留 Task checkpoint。
5. Provider/model route、risk floor、RunDemand 和 selection reasons 都是可校验事实，不能由 Agent
   自报置信度或自由文本覆盖。

## 验证与边界

测试覆盖正向/反向 Pydantic ↔ JSON Schema、risk floor 完整性、waiting/retry 条件、Lease 时间窗口、
naive clock、跨 attempt 自审冲突、Run attribution、sidecar v0.2 和 legacy layout 拒绝。

本阶段没有实现 PortfolioScheduler 的 capacity 聚合、priority aging、Lease expiry/release 或
ModelRouter route 算法；这些进入 T019。ProjectProfile/native-rule discovery、规范冲突编译、
Runtime 自动绑定、tool/evidence protocol、跨语言 E2E 和可视化 read model 仍是后续任务。v0.1
仍不引入复杂 DAG、消息队列、向量库、共享会话、自动 merge 或生产部署。

## 下一阶段入口

T019 需要消费本阶段的 `WorkItem`、`AgentProfile`、`TaskLease` 和 `RunDemand`，实现单进程、有界、
可重放的跨 Task PortfolioScheduler 与 deterministic ModelRouter；不能把单 Task 改成并行 DAG，
也不能让 scheduler 直接写 TaskStatus 或 verdict。
