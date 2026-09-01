# T018 实现记录

## Changes

- 新增 organization-owned `AgentProfile`，将 Agent 身份与项目、具体模型和可变会话解耦；
- 新增 `WorkItem`、`RoleAssignment`、`TaskLease`，把跨 Task 调度容量与单 Task 交付状态分离，
  临时等待不伪装成终局 `BLOCKED`；
- 新增 `ModelPolicy`、`RunDemand`、`ModelSelection` 和 `AgentRunAllocation`，支持按每次 Run
  的风险、复杂度/上下文规模、变更规模、历史失败和关键路径信号选择并归因模型；
- 统一 `ProjectId`、`RunId`、`ContextId` 到 `domain/identity.py`，避免跨层正则漂移；
- 将 project sidecar 从 `agents/` 升级到 v0.2 `assignments/`，旧布局 fail closed，不静默迁移；
- 固化同一 Task 历史中 Coder、QA、Reviewer 的 Agent 独立性，并同步 Schema、核心规范、README、
  ADR、架构、状态机、失败路由、里程碑和可视化数据源设计。

## Verification

- 全量 pytest：303 passed；
- Ruff lint 与 format check：通过；
- strict Mypy：96 source files 通过；
- `uv build --offline`：成功生成 sdist 与 wheel；
- `git diff --check`：通过。
