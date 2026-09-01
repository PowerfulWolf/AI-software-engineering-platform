# Core Architecture Contract

## 1. Scope / Trigger

本规范适用于 ai-software-engineer v0.1 的所有运行时代码、CLI 和测试。凡是新增模块、跨层
payload、状态持久化或 Agent 执行入口，都必须先检查本规范。架构由 Control Plane、Organization
Workforce Plane、Knowledge Plane、Agent Execution Plane、Evidence Plane、Repository Plane 和
Human Boundary 组成；边界定义见 `docs/architecture.md`。

## 2. Signatures

```python
run_task(task_id: str) -> DeliveryResult
SerialOrchestrator.run_task(task_id: TaskId) -> DeliveryResult
RetryingOrchestrator.run_task(task_id: TaskId) -> DeliveryResult | BlockedResult
RunContextBuilder.build(task: Task, agent: AgentDefinition, *, attempt: int,
                        candidate_revision: str | None = None,
                        input_artifacts: tuple[Artifact, ...] = ()) -> ContextBundle
transition(task_id: str, to_status: TaskStatus, *, reason: str,
           artifact_ids: list[str] = ()) -> StateEvent
validate_transition(task: Task, to_status: TaskStatus) -> None
build_event(task: Task, to_status: TaskStatus, *, event_id: EventId,
            reason: str, source_revision: str,
            artifact_ids: tuple[ArtifactId, ...] = (),
            attempt: int = 1,
            occurred_at: datetime) -> StateEvent
apply_event(task: Task, event: StateEvent) -> Task
ContextBuilder.build(task: Task, role: AgentRole, *, attempt: int,
                     candidate_revision: str | None = None) -> ContextBundle
ContextStore.put(context: ContextBundle) -> ContextBundle
ContextStore.get(context_id: ContextId) -> ContextBundle
ArtifactStore.put(artifact: Artifact) -> ArtifactRef
ArtifactStore.get(artifact_id: ArtifactId) -> Artifact
TaskRepository.create(task: Task) -> None
TaskRepository.get(task_id: TaskId) -> Task
TaskRepository.append_event(event: StateEvent) -> None
TaskRepository.record_attempt(task_id: TaskId, attempt: int) -> None
TaskRepository.list_events(task_id: TaskId) -> tuple[StateEvent, ...]
TaskRepository.current_revision(task_id: TaskId) -> int
GitWorkspace.create(spec: WorktreeSpec) -> WorktreeRef
GitWorkspace.inspect(worktree: WorktreeRef) -> WorktreeSnapshot
GitWorkspace.remove(worktree: WorktreeRef) -> None
RoleWorktreeSession.open(spec: WorktreeSpec, agent: AgentDefinition,
                         *, denied_paths: tuple[str, ...] = ()) -> RoleWorktreeBinding
RoleWorktreeSession.inspect(binding: RoleWorktreeBinding) -> WorktreeSnapshot
RoleWorktreeSession.close(binding: RoleWorktreeBinding) -> None
WorkspacePolicy.authorize_read(path: str | PurePosixPath) -> PurePosixPath
WorkspacePolicy.authorize_write(path: str | PurePosixPath) -> PurePosixPath
WorkspacePolicy.authorize_command(arguments: tuple[str, ...]) -> tuple[str, ...]
EvaluatingAgentAdapter.run(request: AgentRequest) -> AgentResult
EvaluationTraceBuilder.build(case_id: EvaluationCaseId) -> EvaluationTrace
EvaluationEngine.evaluate(traces: tuple[EvaluationTrace, ...]) -> EvaluationReport
HandoffBuilder.build(task_id: TaskId) -> HandoffBundle
FileHandoffStore.put(bundle: HandoffBundle) -> HandoffRef
ProjectWorkspaceRegistry.register(project_root: str | Path, *,
                                   project_id: ProjectId | str | None = None) -> ProjectWorkspace
project_id_for_root(project_root: str | Path) -> ProjectId
```

这些接口必须是幂等或显式拒绝重复操作；实现不得通过全局可变状态绕过 Task/attempt 关联。

## 3. Contracts

- `run_task` 只能推进 `docs/state-machine.md` 中的合法迁移；
- T009 `SerialOrchestrator.run_task` 只接受 `NEW` Task，以固定单 attempt 顺序运行
  planning-mode Orchestrator、Coder、QA、Reviewer；retry、BLOCKED 路由和恢复属于 T010；
- T010 `RetryingOrchestrator` 只在上述串行路径上增加有界 retry/recovery；每次 Agent 调用前
  持久化 `attempt`，从 durable Artifact/event checkpoint 恢复，不引入复杂 DAG、队列或向量库；
- 每个 Agent 输入只包含 ArtifactStore 已持久化并读回的显式上游 Artifact；
  `FileRunContextBuilder` 将其编译为 required `artifact://<id>` source，禁止隐式 Agent 消息；
- Coder request/context revision 是输入基线，implementation-report revision 是输出 candidate，
  且必须等于 `content.commit_sha`；QA/Reviewer request 与 Artifact 必须绑定该 candidate；
- plan/implementation/QA 必须完整覆盖 Task acceptance criterion IDs；Artifact 直接 parent
  固定为 `() → plan → implementation → qa`，4 个 producer run ID 必须独立；
- `validate_transition` 是唯一状态图入口；`build_event`/`apply_event` 必须保持纯函数，不得读写 repository；
- `apply_event` 不得修改传入的 Task，且必须拒绝 Task ID、起始状态或时间戳不一致的事件；
- `ContextBundle` 必须包含 source URI、脱敏内容、SHA-256、token 计数、policy、精确 source revision 和 `context_id`；policy section 固定优先级 0，外部 source 不得占用该优先级；
- 真实 Agent 启动前 `FileRunContextBuilder` 必须把 manifest 写入 ContextStore；
  `FileContextStore` 读取时重算排除 built_at 的 canonical ID，篡改/冲突 fail closed；
- `AgentAdapter` 只接受 typed `AgentRequest` 并返回 `AgentResult`；成功必须携带身份对齐的 Artifact，失败/超时不得携带 verdict，Fake adapter 通过 scenario 验证该边界；
- `ArtifactStore.put` 只接受 Schema 校验通过且 `integrity.validated=true` 的 envelope；
- `ArtifactStore.get` 返回重新校验且 digest 匹配的 typed Artifact；缺失、篡改或损坏文件返回稳定错误；
- Artifact parent/supersedes 只能引用已存在的同 Task Artifact，写入采用临时文件、`fsync` 和原子 rename；
- `StateEvent` 必须包含 `event_id`、from/to status、actor、attempt、reason、source revision 和 artifact IDs；
- Task 快照与 StateEvent 必须由 `TaskRepository.append_event` 在同一 SQLite 事务中提交；相同事件正文重放幂等，不同正文复用 ID 拒绝；
- repository 每个连接开启 foreign keys，数据库使用 WAL；关闭后重新打开必须只依赖持久化 JSON 恢复 Task 与事件序列；
- `record_attempt` 只能单调增加 Task.attempts，不能超过 Task.max_attempts；它不虚构状态迁移，
  StateEvent 的 attempt 用于审计并与快照最大值交叉校验；
- 主 checkout 只读，业务代码只能在角色 worktree 产生。
- role worktree root 必须位于 main checkout 外；Coder branch 与 QA/Reviewer detached candidate 不复用旧 attempt；dirty worktree 不自动清理；
- repository hook/fsmonitor 禁用，repository-local external checkout filter 在没有更强 sandbox 的 v0.1 中 fail closed；
- 路径 policy 绑定 worktree root 并检查 lexical + symlink containment，command policy 只接受完整 token prefix 和无 shell syntax 的 argv。
- T016 `RoleWorktreeSession` 只组合同角色 `WorktreeSpec + AgentDefinition`，并把
  `GitWorkspace.create` 返回的 manager-owned path 绑定到 T015 command executor；它不能创建
  第二套 layout/ref、绕过 dirty cleanup、迁移 Task 或解释 verdict；
- Evaluation 不扩展状态机：`EvaluatingAgentAdapter` 装饰既有 adapter 并发出 replay-safe
  AgentRunEvent；TraceBuilder 只读 Task/StateEvent/Artifact/EvaluationEvent；Engine 是纯计算；
- ADR 的 DONE、四制品链、独立 run、evidence、人类动作、policy 与 regression 条件都必须从
  typed facts 重算；未关闭 regression window 是 `PENDING`，不是成功；
- Handoff 只允许 `DONE/BLOCKED`，其 deterministic JSON 与 Markdown 必须一致；它不执行复核
  argv、不 merge，也不修改 Task/Artifact/verdict。

### Project workspace and visualization boundary

- `ProjectWorkspaceRegistry` 只读 canonical `project_root`，并在外置 registry root 原子初始化
  固定 sidecar layout；目标项目永远是默认代码 cwd，sidecar 保存平台元数据，不复制源码。
- manifest、registry path、project path 必须通过 lexical + resolved containment 校验；sidecar
  与 project root 重叠、existing symlink、ID collision、manifest/layout 损坏都 fail closed。
- project-native rules 与平台工程约定冲突时不使用自动优先级；生成 `SPEC_CONFLICT` 并等待
  HumanAction/Resolution artifact。平台 hard safety policy 不能被项目规则放宽。
- Visualization read projections 只能从 durable StateEvent、AgentRunEvent、Context、Artifact、
  Evidence、Evaluation、Handoff 和只读 Git inspection 重算，不写 Task/verdict 或执行 Agent。

## 4. Validation & Error Matrix

| 输入问题 | 检测点 | 结果 |
|---|---|---|
| Task 不符合 Schema | Task repository 边界 | 拒绝创建，不启动 Agent |
| revision 不存在/不匹配 | Git manager + artifact validator | `BLOCKED`（外部 ref）或 `FAILED`（内部不变量） |
| context 超预算/含 secret | Context Builder | 先脱敏再计数/哈希；optional 裁剪，required 无法满足时 `BLOCKED` |
| context ID 冲突、持久化篡改或非法 JSON | ContextStore | `ContextConflict`/`ContextCorruption`，不启动真实 Agent |
| worktree root/role/ref/revision 不合法 | Git manager | typed Git workspace error；不复用或清理现场 |
| WorktreeSpec 与 AgentDefinition role 不一致 | RoleWorktreeSession | `RoleWorktreeAgentMismatch`；不创建 worktree |
| role binding dirty 时请求 close | RoleWorktreeSession → Git manager | `DirtyWorktree`；保留 changed paths 现场 |
| repository hook/filter 可能执行 | Git manager | hook 强制禁用；external filter 拒绝 create |
| path/command 越权 | WorkspacePolicy | stable policy violation；命令不启动并生成 evidence |
| artifact Schema/哈希失败 | ArtifactStore | 不入库，不触发状态迁移 |
| 非法状态迁移 | state machine guard | 事务回滚并记录 invariant error |
| Agent 超时 | execution adapter | 无 verdict；按 transient 规则重试 |
| Task 不是 `NEW` | `SerialOrchestrator` 入口 | `TaskNotRunnable`，不追加事件 |
| AgentDefinition 缜密性/角色映射错误 | runner 初始化 | `OrchestratorConfigurationError`，不启动 Agent |
| Agent FAILED/TIMED_OUT | 当前阶段 checkpoint | `AgentRunFailed`，不伪造 Artifact/verdict |
| QA FAIL / Review REJECT | verdict guard | Artifact 可持久化；停在 QA/REVIEW，T010 决定路由 |
| criteria、parent、candidate 或独立 run 不一致 | delivery guard | `DeliveryContractViolation`，不推进下一状态 |
| retry attempt 超过预算 | retry router | `BlockedResult` + `BLOCKED` event，保留最后 finding Artifact |
| Evaluation event exact replay / changed replay | EvaluationEventStore | 幂等返回 / `EvaluationEventConflict` |
| Evaluation event digest、JSON 或身份损坏 | EvaluationEventStore/TraceBuilder | corruption/contract error，不计算指标 |
| DONE 缺回归观察 | EvaluationEngine | `ADR=PENDING`，仍在分母 |
| 非终态或 DONE 断链请求 handoff | HandoffBuilder | `HandoffNotReady` / `HandoffContractError` |
| Handoff JSON/Markdown/identity 被篡改 | FileHandoffStore | `HandoffCorruption`，不返回半可信内容 |
| project root 缺失或不是目录 | ProjectWorkspaceRegistry | `ProjectRootNotFound`；不创建 registry/sidecar |
| registry/sidecar 与 project 重叠或 registry 是 symlink | ProjectWorkspaceRegistry | `WorkspacePlacementError`/`WorkspaceRootError`；目标项目保持不变 |
| Project ID 已绑定另一 project root | ProjectWorkspaceRegistry | `ProjectWorkspaceConflict`；不覆盖首次 manifest |
| workspace manifest/layout 缺失、digest/Schema 非法或路径不匹配 | ProjectWorkspaceRegistry | `ProjectWorkspaceCorruption`；不自动修复组织状态 |
| staging 初始化失败 | ProjectWorkspaceRegistry | `ProjectWorkspaceError`；清理本轮隐藏 staging，不发布半成品 |

## 5. Good / Base / Bad Cases

- **Good**：同一 Task/attempt 的 context manifest、完整四 Artifact lineage，以及
  implementation/QA/Review 共用的 candidate SHA 可从事件流重放；plan 可以绑定 base revision。
- **Base**：模型不可用时 fake adapter 仍能让状态机、权限和 artifact contract tests 通过。
- **Bad**：Orchestrator 直接读取 Agent 自由文本并把“looks good”写成 `DONE`；必须拒绝并要求结构化 artifact。
- **T009 Good**：真实临时 SQLite + FileArtifactStore + FakeAgentAdapter 产生 5 个事件、
  4 个 sealed Artifact，关闭重开后 Task 仍为 `DONE`。
- **T009 Bad**：使用 `NEW` Task 快照预构建 planning Context，或强制 Coder 输出 Artifact
  复用输入 base revision；前者破坏 manifest identity，后者使 Coder 无法产生新 commit。
- **T012 Good**：同一 SQLite/Artifact/Evaluation facts 重放产生同一 metrics/ADR；等价 handoff
  重建保留首次观察时间。
- **T012 Base**：DONE delivery 在 regression window 结束前保持 `PENDING`，人类仍可审阅 handoff。
- **T012 Bad**：只看 `Task.status == DONE` 就写 `adr=true`，或任务完成后手工补造“无人干预”历史。
- **T016 Good**：Coder binding 使用 attempt branch，QA/Reviewer binding detached 到同一 candidate；
  binding executor 的 cwd 等于 manager-issued root，clean 后才关闭。
- **T016 Bad**：把 QA AgentDefinition 配给 Coder spec、直接用 main checkout 构造 executor，
  或 force-remove dirty role worktree。
- **T017 Good**：同一 canonical project root 重复注册返回首次 `workspace.json`，目标项目内容
  不变，14 个平台目录全部位于外置 sidecar；T018 v0.2 layout 使用 `assignments/`，不复制 Agent。
- **T017 Base**：一个尚无语言/构建描述的空本地目录也能注册；ProjectProfile 发现属于 T018。
- **T017 Bad**：在目标项目创建 `.ase`、把源码复制到 sidecar、复用已绑定的 Project ID，或
  发现旧 layout 缺失时静默补目录。

## 6. Tests Required

- 状态机：每条合法迁移 + 每个非法跳转断言拒绝和事务不变；
- Artifact：正反 Schema、哈希篡改、重复 ID、revision mismatch；
- Context：来源排序稳定、预算裁剪、secret redaction、priority 0 保留、prompt injection 不改变 policy；
- ContextStore：canonical ID、等价重放、冲突、篡改、原子文件 round-trip；
- Git：worktree 隔离、path/command allowlist、未保存变更阻止清理；
- Recovery：中断后重放不重复 event，能回到最近 checkpoint。
- Serial runner：公开 seam fixture 断言 `DONE`、5 个事件、revision=5、四类 Artifact lineage、
  Context/run identity；Agent failure、QA FAIL、criterion 缺失、重复 run ID、非 NEW Task
  分别停在预期 durable checkpoint。
- Evaluation：5-case suite 覆盖 eligible/pending/human/blocked/regression；event store 覆盖 replay、
  conflict、合法篡改；emitter 覆盖 success/invalid/replay；handoff 覆盖 DONE/BLOCKED/断链/篡改。
- Role worktree composition：真实 Git fixture 覆盖同角色 binding、Coder branch、QA detached
  candidate、固定 executor cwd、role mismatch、dirty/clean cleanup 和初始化失败回收。
- Project workspace：真实临时目录覆盖 stable ID、幂等 replay、目标目录无写入、固定 layout、
  ID collision、registry symlink、project overlap、manifest/layout corruption 和 staging cleanup；
  `ProjectWorkspaceManifest.to_wire()` 必须通过 canonical JSON Schema 正反 fixture，Schema-valid
  正文篡改也必须由 manifest SHA-256 检出。

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

### Project workspace wrong vs correct

```python
# Wrong: platform metadata pollutes the target project.
state_database = project_root / ".ase" / "state.sqlite3"

# Correct: code cwd and platform state have distinct, typed roots.
workspace = ProjectWorkspaceRegistry(registry_root).register(project_root)
code_cwd = workspace.project_root
state_database = workspace.directory("state") / "state.sqlite3"
```

## 8. Required invariants

1. TaskOrchestrator 是一个 Task 的唯一状态迁移者；PortfolioScheduler 不写 TaskStatus；
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

## 10. Organization Workforce Plane

### 10.1 Implemented T018 seams

```python
AgentProfile.model_validate(payload: object) -> AgentProfile
ModelPolicy.model_validate(payload: object) -> ModelPolicy
RunDemand.model_validate(payload: object) -> RunDemand
WorkItem.model_validate(payload: object) -> WorkItem
RoleAssignment.model_validate(payload: object) -> RoleAssignment
TaskLease.model_validate(payload: object) -> TaskLease
AgentRunAllocation.model_validate(payload: object) -> AgentRunAllocation
validate_assignment_independence(candidate: RoleAssignment,
                                 existing: tuple[RoleAssignment, ...]) -> None
lease_is_active(lease: TaskLease, *, at: datetime) -> bool
```

TaskStatus 继续表示单 Task 交付证据链；WorkItemStatus 表示组织调度可用性。临时
`WAITING_HUMAN/WAITING_DEPENDENCY/RETRY_SCHEDULED` 必须释放/到期 Lease，Task 保持最近
checkpoint。`BLOCKED` 只用于终局无安全继续路径。当前 T010 还没有 WorkItem composition，
兼容映射将在 T019 替换。

### 10.2 Target T019 seams

```python
PortfolioScheduler.assign(work_item: WorkItem,
                          agents: tuple[AgentProfile, ...],
                          active_leases: tuple[TaskLease, ...]) -> AssignmentDecision
ModelRouter.select(demand: RunDemand,
                   agent: AgentProfile,
                   policy: ModelPolicy) -> ModelSelection
```

Scheduler 只管理 WorkItem、capacity、Assignment 和 Lease，不迁移 TaskStatus；ModelRouter 只返回
带 reason 的 ModelSelection，不调用 provider。TaskOrchestrator 继续固定一个 Task 内角色顺序。

### 10.3 Required invariants

1. AgentProfile 属于 organization，不属于 Project；
2. 同一 Task 历史中的 Coder、QA、Reviewer agent_id 两两独立；
3. active Lease 不超过 AgentProfile.max_parallel_assignments；
4. 每个 AgentRunAllocation 绑定 Agent、Assignment、ModelSelection、Context、Prompt、Spec 和 tool policy；
5. 跨 Task 并发不能共享 Context、worktree、Artifact lineage 或可变模型会话；
6. 模型评价按 Agent × Model × Role × Task class × Risk 归因。
