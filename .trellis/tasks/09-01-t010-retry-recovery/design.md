# T010 Design

## 组件

| 组件 | 责任 |
|---|---|
| `RetryingOrchestrator` | 恢复 checkpoint、分类失败、执行有界串行 retry、产生 BLOCKED/FAILED event |
| `RetryClassification` | 固定失败类别，避免按 Agent 自由文本路由 |
| `BlockedResult` | 为人类返回分类、理由、attempt、Artifact 和完整事件索引 |
| `TaskRepository.record_attempt` | 原子单调更新 Task.attempts，不伪造 self-transition |
| `ArtifactStore.list_for_task` | 重新校验并枚举本 Task 的可信 Artifact，支持重启恢复 |

## 路由

1. `TIMEOUT`、`PROVIDER_ERROR`、`INVALID_OUTPUT` 在 `max_attempts` 内重试当前 role；
2. QA `FAIL` 持久化后进入 `QA → IMPLEMENTING`，下一个 Coder 输入 plan + qa-report；
3. Review `REJECT` 持久化后进入 `REVIEW → IMPLEMENTING`，下一个 Coder 输入 plan + QA + Review；
4. finding 修复的 implementation-report `supersedes` 旧 implementation，并将 finding IDs 作为
   direct parents；
5. 预算耗尽、策略/需求问题返回 `BlockedResult` 并追加 `BLOCKED` event；内部契约破坏追加
   `FAILED` event 并抛出 typed exception。

## Recovery

启动时读取事件最大 attempt，并与 Task.attempts 取最大值；枚举 ArtifactStore 中同 Task 的
Artifact，按 `created_at`/ID 选择最新 kind。已确认的 plan/QA/review 不重复消费；如果进程
在 Agent 调用前后中断，使用同一 checkpoint 和 attempt 重新构建 Context，失败结果不产生
verdict。
