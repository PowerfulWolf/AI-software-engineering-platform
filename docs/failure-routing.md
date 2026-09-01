# 失败、重试与路由规则

## 1. 失败分类

| 类别 | 示例 | 默认动作 |
|---|---|---|
| `TRANSIENT_INFRA` | 模型超时、临时网络错误、进程被中断 | 指数退避后重试同一角色，最多 2 次 |
| `INVALID_OUTPUT` | JSON 不符合 Schema、缺字段、哈希不匹配 | 不重试原输出；重启同角色一次，仍失败则 `BLOCKED` |
| `QA_FINDING` | 测试失败、验收标准未满足 | 将 findings 原样路由给 Coder，创建新 attempt |
| `REVIEW_FINDING` | BLOCKER/MAJOR 代码问题 | 将 finding + evidence 路由给 Coder，创建新 attempt |
| `POLICY_VIOLATION` | 越权写文件、篡改 verdict、执行禁用命令 | 立即终止 run，记录安全事件，`BLOCKED` |
| `REQUIREMENT_AMBIGUITY` | 验收标准互相冲突或缺少关键输入 | `BLOCKED`，请求人类澄清 |
| `BUDGET_EXHAUSTED` | attempt/token/time budget 用尽 | `BLOCKED`，交付全部 evidence |
| `PLATFORM_BUG` | 状态不变量破坏、数据库损坏 | `FAILED`，保留现场并报警 |

## 2. 重试规则

- attempt 上限默认 3（初次 + 2 次修复），Task 可降低但不能由 Agent 提高；
- 同一输入、同一模型、同一错误最多重试 2 次；超过即升级；
- QA/Review finding 必须在新 Coder context 中可见，并带原 artifact ID；
- 重试不得覆盖旧 artifact；新 artifact 通过 `supersedes` 和 `parent_artifact_ids` 关联；
- 若失败来自环境而非代码，重试 Coder 没有意义，应重试原角色或阻塞。

## 3. 路由矩阵

| 触发 | 下一角色/状态 | 必带上下文 |
|---|---|---|
| plan Schema 失败 | Planner/Coder（一次） | 校验错误路径 |
| Coder 崩溃 | Coder | 相同 context manifest、attempt+1 |
| QA 测试失败 | Coder → `IMPLEMENTING` | qa-report、失败命令、候选 diff |
| QA 环境故障 | QA | 环境日志、原候选 SHA |
| Review REJECT | Coder → `IMPLEMENTING` | review-report、QA report、候选 diff |
| Review 证据不足 | Reviewer | 缺失证据清单 |
| 权限越界 | `BLOCKED` | policy decision、命令/路径、日志 |
| 需求歧义 | `BLOCKED` | 问题、受影响验收标准 |

## 4. 升级内容

进入 `BLOCKED` 时必须生成一份可供人类处理的摘要：发生阶段、最后有效 revision、已尝试次数、阻塞分类、最小需要的决定、完整 evidence 路径和建议下一步。不要只返回“Agent failed”。

## 5. v0.1 实现边界（T010）

`RetryingOrchestrator` 在 T009 的串行 runner 上实现上述最小闭环：

- `TaskRepository.record_attempt` 在每次 Agent 调用前单调持久化 attempt，进程重启后从 Task
  快照和 StateEvent 的最大 attempt 恢复；
- ArtifactStore 通过 `list_for_task` 扫描并重新校验本 Task 的 Artifact，恢复最新 plan、
  implementation、qa-report 和 review-report；
- QA/Review finding 仅作为已持久化 Artifact 路由，修复 Coder 的新 Artifact 必须声明
  旧 implementation 的 `supersedes`，并把 finding Artifact 放进 parent lineage；
- `BlockedResult` 包含 classification、reason、attempt、Artifact IDs 和完整 event IDs，
  同时追加 `BLOCKED` StateEvent；内部契约破坏追加 `FAILED` 后保留异常现场。

该实现仍是单 Task、串行、进程内控制循环。队列、复杂 DAG、跨任务调度和模型供应商重试
退避属于后续版本；v0.1 的 retry 次数上限由 Task.max_attempts 统一约束。
