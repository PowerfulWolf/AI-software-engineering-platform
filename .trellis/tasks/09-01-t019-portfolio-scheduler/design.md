# T019 Design

## Boundaries

```text
WorkItem + AgentProfile + active TaskLease
        │ pure scheduling decision
        ▼
AssignmentDecision + RoleAssignment + TaskLease

RunDemand + AgentProfile + ModelPolicy
        │ pure model route decision
        ▼
ModelSelection → AgentRunAllocation (T022)
```

Scheduler 不写 `TaskStatus`，不读取模型文本，不创建共享会话；ModelRouter 不调用 provider，
所有选择必须能由输入事实重放。等待/容量不足返回结构化 no-assignment，不伪造 `BLOCKED`。

## Files owned by this task

- `src/ai_software_engineer/scheduling/**`；
- `tests/scheduling/**`；
- 可选 `schemas/scheduling.schema.json`（若 decision wire contract 需要）；
- 本 task 的 `.trellis/tasks/**` 记录。

共享 README、milestones、architecture、spec 等由 root 在两条并行线汇合后统一更新，避免文档冲突。

## Determinism

使用显式 `now`、stable tuple sorting 和 typed reasons；不读取全局时钟、不产生随机 tie-breaker、
不按 provider 响应做二次决策。Lease 计数只统计 `lease_is_active(lease, at=now)` 的有效 Lease。
