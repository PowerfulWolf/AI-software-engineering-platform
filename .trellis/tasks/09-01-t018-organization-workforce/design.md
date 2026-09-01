# T018 Design

## Domain correction

现有 `AgentDefinition` 同时携带 role、model、permissions 和 identity，更接近一次角色执行的解析
配置，而不是长期团队成员。T018 保留它以兼容现有串行 Runtime，并新增组织级契约：

```text
AgentProfile + WorkItem
        │ scheduler match（T019）
        ▼
RoleAssignment + TaskLease
        │ ModelPolicy select（T019）
        ▼
AgentRunAllocation
        │ resolve current AgentDefinition
        ▼
TaskOrchestrator → isolated AgentRun
```

## Two orthogonal lifecycles

TaskStatus 只描述交付证据链：`NEW → PLANNING → IMPLEMENTING → QA → REVIEW → DONE`，以及
终局 `BLOCKED/FAILED`。WorkItemStatus 描述是否可调度：`READY/LEASED/RUNNING/WAITING_HUMAN/
WAITING_DEPENDENCY/RETRY_SCHEDULED/CLOSED`。

临时等待时 Task 保持最近 checkpoint，WorkItem 进入 `WAITING_*`，Lease 到期或显式释放；等待
条件满足后 WorkItem 回到 `READY`。只有没有安全继续路径或预算终局耗尽时 Task 才进入
`BLOCKED`。

## Deep module seams

- `PortfolioScheduler`（T019）只接受 WorkItem/AgentProfile/Project access/performance facts，返回
  Assignment 或明确不分配原因；不推进 Task 状态。
- `ModelRouter`（T019）只接受 `RunDemand`、AgentProfile 和 ModelPolicy，返回
  ModelSelection；不调用模型。
- `TaskOrchestrator` 保留当前每 Task 串行交付接口；它消费已解析的 AgentDefinition，不拥有
  全局队列或 Agent 身份。

## Validation matrix

| Case | Expected result |
|---|---|
| 一个 AgentProfile 可担任 coder/reviewer | 合法，但同一 Task 的冲突检查由 Scheduler 拒绝自审 |
| AgentProfile 直接包含具体 model | 未知字段，Schema/Pydantic 拒绝 |
| ModelPolicy 缺任一 risk floor | 拒绝，不能猜测高风险最低模型 |
| WorkItem 进入 WAITING_HUMAN 无原因 | 拒绝 |
| TaskLease 过期时间不晚于获得时间 | 拒绝 |
| 项目 sidecar 包含旧 agents layout | v0.2 manifest/schema 拒绝，不自动改写 |
| 两个独立 Task 使用同一 AgentProfile | 允许，受 max_parallel_assignments/Lease 限制 |
| RunDemand 缺少风险、规模或失败信号 | 由 Schema/Pydantic 拒绝或使用显式零值，ModelRouter 不读取 Agent 自报置信度 |
| 同一 AgentRun 共享另一个 Task Context/worktree | policy/identity violation，后续 composition 必须拒绝 |

## Good / Base / Bad

- Good：一个 AgentProfile 同时持有两个不同 Task 的有效 Lease，每个 AgentRunAllocation 都有独立
  assignment、Context、worktree policy 和 ModelSelection。
- Base：没有满足风险最低 BrainTier 的模型时 Scheduler 不分配并产生等待/升级事实。
- Bad：在项目 sidecar 复制 AgentProfile，或让一个长驻模型会话同时携带多个 Task 的可变上下文。

## Files

- Domain/Schema：`domain/workforce.py`、`domain/enums.py`、`schemas/workforce.schema.json`；
- Project binding：`project_workspace.py`、`project-workspace.schema.json`；
- Tests：`tests/workforce/`、`tests/project_workspace/`、contract tests；
- Knowledge：`CONTEXT.md`、ADR、README、docs、AGENTS、`.trellis/spec/core/`。
