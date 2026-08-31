# Core Architecture Contract

## 1. Scope / Trigger

本规范适用于 ai-software-engineer v0.1 的所有运行时代码、CLI 和测试。凡是新增组件、跨层 payload、状态持久化或 Agent 执行入口，都必须先检查本规范。架构由 Control Plane、Knowledge Plane、Agent Execution Plane、Evidence Plane、Repository Plane 和 Human Boundary 组成；边界定义见 `docs/architecture.md`。

## 2. Signatures

```python
run_task(task_id: str) -> DeliveryResult
transition(task_id: str, to_status: TaskStatus, *, reason: str,
           artifact_ids: list[str] = ()) -> StateEvent
validate_transition(task: Task, to_status: TaskStatus) -> None
build_event(task: Task, to_status: TaskStatus, *, event_id: EventId,
            reason: str, source_revision: str,
            artifact_ids: tuple[ArtifactId, ...] = (),
            occurred_at: datetime) -> StateEvent
apply_event(task: Task, event: StateEvent) -> Task
ContextBuilder.build(task: Task, role: AgentRole, *, attempt: int,
                     candidate_revision: str | None = None) -> ContextBundle
ArtifactStore.put(artifact: Artifact) -> ArtifactRef
ArtifactStore.get(artifact_id: ArtifactId) -> Artifact
TaskRepository.create(task: Task) -> None
TaskRepository.get(task_id: TaskId) -> Task
TaskRepository.append_event(event: StateEvent) -> None
TaskRepository.list_events(task_id: TaskId) -> tuple[StateEvent, ...]
TaskRepository.current_revision(task_id: TaskId) -> int
GitWorkspace.create(spec: WorktreeSpec) -> WorktreeRef
GitWorkspace.inspect(worktree: WorktreeRef) -> WorktreeSnapshot
GitWorkspace.remove(worktree: WorktreeRef) -> None
WorkspacePolicy.authorize_read(path: str | PurePosixPath) -> PurePosixPath
WorkspacePolicy.authorize_write(path: str | PurePosixPath) -> PurePosixPath
WorkspacePolicy.authorize_command(arguments: tuple[str, ...]) -> tuple[str, ...]
```

这些接口必须是幂等或显式拒绝重复操作；实现不得通过全局可变状态绕过 Task/attempt 关联。

## 3. Contracts

- `run_task` 只能推进 `docs/state-machine.md` 中的合法迁移；
- `validate_transition` 是唯一状态图入口；`build_event`/`apply_event` 必须保持纯函数，不得读写 repository；
- `apply_event` 不得修改传入的 Task，且必须拒绝 Task ID、起始状态或时间戳不一致的事件；
- `ContextBundle` 必须包含 source URI、脱敏内容、SHA-256、token 计数、policy、精确 source revision 和 `context_id`；policy section 固定优先级 0，外部 source 不得占用该优先级；
- `ArtifactStore.put` 只接受 Schema 校验通过且 `integrity.validated=true` 的 envelope；
- `ArtifactStore.get` 返回重新校验且 digest 匹配的 typed Artifact；缺失、篡改或损坏文件返回稳定错误；
- Artifact parent/supersedes 只能引用已存在的同 Task Artifact，写入采用临时文件、`fsync` 和原子 rename；
- `StateEvent` 必须包含 `event_id`、from/to status、actor、reason、source revision 和 artifact IDs；
- Task 快照与 StateEvent 必须由 `TaskRepository.append_event` 在同一 SQLite 事务中提交；相同事件正文重放幂等，不同正文复用 ID 拒绝；
- repository 每个连接开启 foreign keys，数据库使用 WAL；关闭后重新打开必须只依赖持久化 JSON 恢复 Task 与事件序列；
- 主 checkout 只读，业务代码只能在角色 worktree 产生。
- role worktree root 必须位于 main checkout 外；Coder branch 与 QA/Reviewer detached candidate 不复用旧 attempt；dirty worktree 不自动清理；
- repository hook/fsmonitor 禁用，repository-local external checkout filter 在没有更强 sandbox 的 v0.1 中 fail closed；
- 路径 policy 绑定 worktree root 并检查 lexical + symlink containment，command policy 只接受完整 token prefix 和无 shell syntax 的 argv。

## 4. Validation & Error Matrix

| 输入问题 | 检测点 | 结果 |
|---|---|---|
| Task 不符合 Schema | Task repository 边界 | 拒绝创建，不启动 Agent |
| revision 不存在/不匹配 | Git manager + artifact validator | `BLOCKED`（外部 ref）或 `FAILED`（内部不变量） |
| context 超预算/含 secret | Context Builder | 先脱敏再计数/哈希；optional 裁剪，required 无法满足时 `BLOCKED` |
| worktree root/role/ref/revision 不合法 | Git manager | typed Git workspace error；不复用或清理现场 |
| repository hook/filter 可能执行 | Git manager | hook 强制禁用；external filter 拒绝 create |
| path/command 越权 | WorkspacePolicy | stable policy violation；命令不启动并生成 evidence |
| artifact Schema/哈希失败 | ArtifactStore | 不入库，不触发状态迁移 |
| 非法状态迁移 | state machine guard | 事务回滚并记录 invariant error |
| Agent 超时 | execution adapter | 无 verdict；按 transient 规则重试 |

## 5. Good / Base / Bad Cases

- **Good**：同一 Task/attempt 的 context manifest、candidate SHA 和四类 artifact 可从事件流重放。
- **Base**：模型不可用时 fake adapter 仍能让状态机、权限和 artifact contract tests 通过。
- **Bad**：Orchestrator 直接读取 Agent 自由文本并把“looks good”写成 `DONE`；必须拒绝并要求结构化 artifact。

## 6. Tests Required

- 状态机：每条合法迁移 + 每个非法跳转断言拒绝和事务不变；
- Artifact：正反 Schema、哈希篡改、重复 ID、revision mismatch；
- Context：来源排序稳定、预算裁剪、secret redaction、priority 0 保留、prompt injection 不改变 policy；
- Git：worktree 隔离、path/command allowlist、未保存变更阻止清理；
- Recovery：中断后重放不重复 event，能回到最近 checkpoint。

## 7. Wrong vs Correct

### Wrong

```python
if agent_text.lower().startswith("looks good"):
    task.status = "DONE"
```

### Correct

```python
review = artifact_store.validate_and_get(review_artifact_id, schema="review-report")
assert review.source_revision == candidate_sha
assert review.content["verdict"] == "APPROVE"
transition(
    task.id,
    "DONE",
    reason="review_approved",
    artifact_ids=[plan_id, impl_id, qa_id, review_artifact_id],
)
```

## 8. Required invariants

1. Orchestrator 是唯一状态迁移者；
2. Agent 不能直接向另一个 Agent 发送未持久化消息；
3. 每个 run 都绑定一个 context manifest、policy、source revision 和预算；
4. 每个 artifact 都必须 Schema 校验、哈希和原子持久化；
5. 任何下游决策都能从事件流和 artifact 证据重放；
6. 主 checkout 不承载 Agent 的业务代码写入。

## 9. Validation points

- 状态机非法迁移测试；
- artifact revision/task/schema/integrity 一致性测试；
- context allowlist、脱敏和稳定性测试；
- Git path/command policy 与 worktree 隔离测试；
- 中断恢复和幂等回放测试。
