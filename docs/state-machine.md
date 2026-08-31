# Task 状态机

## 1. 状态集合

| 状态 | 含义 | 可停留条件 |
|---|---|---|
| `NEW` | Task 已创建但尚未检查 | Schema 合法、仓库可访问 |
| `PLANNING` | 生成并校验 plan | 需求和验收标准足够明确 |
| `IMPLEMENTING` | Coder 在候选 worktree 中实现 | 有有效 plan，且未超出重试预算 |
| `QA` | QA 执行测试并产出 verdict | 有候选 revision 和 implementation-report |
| `REVIEW` | Reviewer 独立审查 | QA `PASS` 且候选 revision 未变化 |
| `DONE` | Review `APPROVE`，候选变更可交付 | 所有 required checks 有证据 |
| `BLOCKED` | 需要人类处理或外部条件 | 需求冲突、预算耗尽、环境不可用等 |
| `FAILED` | 平台自身不可恢复故障 | 数据损坏、内部 invariant 违反 |

## 2. 合法迁移

```text
NEW ──validate──> PLANNING
PLANNING ──plan.valid──> IMPLEMENTING
IMPLEMENTING ──candidate.ready──> QA
QA ──PASS──> REVIEW
QA ──FAIL (retryable)──> IMPLEMENTING
QA ──FAIL (non-retryable/budget exhausted)──> BLOCKED
REVIEW ──APPROVE──> DONE
REVIEW ──REJECT (retryable)──> IMPLEMENTING
REVIEW ──REJECT (non-retryable/budget exhausted)──> BLOCKED
任何非终态 ──platform invariant violation──> FAILED
```

`DONE`、`BLOCKED`、`FAILED` 是终态。重新执行必须显式创建新的 attempt 或人工将 Task 置回 `IMPLEMENTING`，不能由 Agent 自行跳转。

## 3. Python Guard / Reducer

`src/ai_software_engineer/orchestration/state_machine.py` 是状态迁移的唯一纯函数入口：

```python
validate_transition(task: Task, to_status: TaskStatus) -> None
build_event(task: Task, to_status: TaskStatus, *, event_id: EventId,
            reason: str, source_revision: str,
            artifact_ids: tuple[ArtifactId, ...] = (),
            occurred_at: datetime) -> StateEvent
apply_event(task: Task, event: StateEvent) -> Task
```

`validate_transition` 只接受上表中的边；自迁移和终态迁移分别拒绝为 `IllegalTransition`/`TerminalTask`。`build_event` 固定 `actor=orchestrator`，并调用同一 guard；`apply_event` 检查 Task ID、`from_status` 和时间戳，返回新的 immutable Task，不修改输入。Repository 只负责在事务中持久化已通过 guard 的事件，不重复定义状态图。

## 4. StateEvent 持久化契约

每次状态变化都由 `schemas/state-event.schema.json` 描述，并通过 `StateEvent` typed model 进入 repository。StateEvent 至少包含 `event_id`、`task_id`、`from_status`、`to_status`、`actor=orchestrator`、`reason`、`artifact_ids`、`source_revision` 和带时区的 `occurred_at`。

SQLite 中 Task 快照和 StateEvent 必须在同一个 `BEGIN IMMEDIATE` 事务内写入：事件正文以 JSON 保存，Task `revision` 从 0 开始，每个事件递增 1。相同 `event_id` 和完全相同正文的重放是幂等 no-op；相同 ID 的不同正文必须拒绝，不能覆盖审计记录。

## 5. 迁移守卫

- 每次迁移都带 `event_id`、`from_status`、`to_status`、`actor=orchestrator`、`reason`、`artifact_ids` 和时间戳。
- 迁移在 SQLite 事务中完成；状态版本（`revision`）采用乐观锁，重复提交必须幂等。
- `QA → REVIEW` 只接受最新候选 revision 的 `qa-report.status=PASS`。
- `REVIEW → DONE` 只接受 `review-report.verdict=APPROVE`、required evidence 完整且工作树干净。
- 任何 artifact 的 `task_id`、`source_revision` 或 Schema 版本不匹配，迁移拒绝并进入 `FAILED`（数据问题）或 `BLOCKED`（外部问题）。

## 6. 事件记录示例

```json
{
  "event_id": "evt_01J...",
  "task_id": "task_20260831_001",
  "from_status": "QA",
  "to_status": "REVIEW",
  "actor": "orchestrator",
  "reason": "qa_passed",
  "artifact_ids": ["art_qa_001"],
  "source_revision": "a1b2c3d",
  "occurred_at": "2026-08-31T12:00:00Z"
}
```

## 7. 回放与恢复

状态可由事件流重放得到，artifact 只作为事件引用的证据。进程重启后：

1. 读取最后一个已提交事件；
2. 检查对应 artifact 和 worktree 是否存在；
3. 若上次 Agent 运行没有 `completed` 记录，标记该 attempt 为 `interrupted`；
4. 从最近一个有效 checkpoint 继续，不重复消费已确认的 artifact。
