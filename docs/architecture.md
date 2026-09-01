# 总体架构

## 1. 目标与约束

v0.1 解决一个窄而完整的问题：在已有 Git 项目中，把一条需求交给受约束的 Coder、独立 QA 和独立 Reviewer，形成可审计的闭环。平台优先保证可追溯性、权限边界和失败可恢复性，而不是追求 Agent 数量或调度复杂度。

### 运行假设

- 一个 Task 只绑定一个 repository 和一个 base ref；
- 一个 TaskOrchestrator 实例一次只推进一个 Task，Task 内角色保持串行；
- 组织级 PortfolioScheduler 可以为多个隔离 Task 产生有界分配决策；持久化队列循环尚未接入 CLI Runtime；
- Agent 不直接互相调用，所有交互经过 Orchestrator 和 artifact store；
- 人类是需求来源和最终升级出口；v0.1 不自动向保护分支 push/merge。

## 2. 逻辑组件

### Control Plane

Control Plane 分为两个 seam。`PortfolioScheduler` 管理组织 WorkQueue、Agent 容量、Assignment、
Lease 和 ModelSelection，但不迁移 Task 交付状态；`TaskOrchestrator` 是唯一可以迁移一个 Task
状态的模块，负责检查前置条件、启动 Agent、验证 artifact、决定重试或终局升级。T010 的
`RetryingOrchestrator` 是当前 TaskOrchestrator 实现；T019 已交付纯 Scheduler/ModelRouter seam，
由后续 application service 负责持久化其 Assignment、Lease 和 ModelSelection 决策。

### Knowledge Plane

由 `.trellis/spec/`（组织级规则）、项目文档、任务 PRD/Design、历史 artifact 摘要和失败经验组成。`context/` 中的 Context Router/Builder 只读取声明过的来源并生成带哈希、脱敏、预算约束的 manifest；不把整仓库或整段历史盲目塞给模型。policy section 由机器权限生成并固定排在外部文本之前，仓库内容永远是数据而非新的系统指令。

### Project Binding 与外置 AI Workspace

`ProjectWorkspaceRegistry` 将操作者给出的本地 `project_root` 绑定到目标目录之外的
`ai_workspace_root`。目标项目仍是实际代码、测试、构建和默认命令 cwd；sidecar 保存
`ProjectProfile`、Assignment/规范、Task/StateEvent、Context、Artifact、Evidence、Evaluation、
Handoff、run metadata 和日志。T018 的 v0.2 layout 用 `assignments/` 替换 `agents/`，因为 Agent
身份属于组织而不是项目。manifest 与固定 layout 是后续 Runtime/Context/Visualization
共享的路径契约，注册过程不会复制源码或在目标项目写入平台文件。T020 的 `ProjectProfile`
确定性发现语言、构建系统、VCS 和原生规则来源；T022 的 `RuntimeWorkspaceBinding` 将这些事实与
组织 workspace、固定 RuntimePaths 绑定并在重开时校验完整性。

目标项目已有的 `AGENTS.md`、CONTRIBUTING、README、CI、`.editorconfig`、`.trellis/spec/` 等
project-native rules 只读发现并以 URI/hash 引用。平台 hard safety policy 不可被覆盖；工程规则
或任务约束冲突会生成 `SPEC_CONFLICT`，WorkItem 进入 `WAITING_HUMAN` 并释放 Lease，由人工选择
更新项目规范、平台规范或任务约束；只有决定终止本次交付时 Task 才进入 `BLOCKED`。T021 以
`SpecConflict`、`WaitingHumanRoute` 和 immutable `SpecResolution` 固化这条边界；决定还应进入
`HumanActionEvent`，Agent 和 UI 都不能静默选边。Markdown 正文保持 URI/hash 引用，只有显式
结构化规则参与自动冲突检测。

后续可选的 role worktree 是临时代码 checkout，与 sidecar 元数据分离；逻辑项目绑定仍指向给定
`project_root`。Agent 工作可视化只从 sidecar durable facts 和目标项目只读 Git inspection 生成
read projection，不成为第二个状态写入者，详见 [`docs/visualization.md`](visualization.md)。

### Organization Workforce Plane

组织 workspace 保存 `AgentProfile`、`ModelPolicy`、WorkQueue 和跨项目绩效；项目 sidecar 只保存
Assignment、project access/policy override 和运行事实。一个 AgentProfile 可以声明多个可担任
Role 和 `max_parallel_assignments`，但每个 RoleAssignment 都必须有独立 TaskLease、Context、
worktree、Artifact lineage 和 AgentRunAllocation。

模型不是 Agent 身份。`RunDemand` 汇总 Task risk/complexity、Role、Context capacity、历史表现、
预算和客观 escalation signals；`ModelRouter` 根据这些信号、Role floor 和 policy route，为每次
AgentRun 返回一个带 policy version 与 reasons 的 `ModelSelection`。当前 `AgentDefinition` 保留为
解析后的单角色运行配置：

```text
AgentProfile + WorkItem + Project policy
        → PortfolioScheduler → RoleAssignment + TaskLease
        → ModelRouter → ModelSelection
        → AgentRunAllocation → resolved AgentDefinition
        → TaskOrchestrator
```

同一 Task 历史中的 Coder、QA、Reviewer 必须是不同 Agent；高风险 Task 可以额外要求不同模型
或 provider。跨 Task 并发只复用 Agent 身份和组织绩效，不复用可变会话或工作区。T019 的
`PortfolioScheduler.match/schedule` 与 `ModelRouter.route` 都是无 I/O 决策函数；T022 的
`RuntimeWorkforceResolver` 再将已持久化事实解析为 `AgentRunAllocation + AgentDefinition`。

### Agent Execution Plane

通过 `AgentAdapter.run(AgentRequest) -> AgentResult` 启动 planning-mode Orchestrator、Coder、QA、Reviewer。每个运行使用独立 `run_id`、Context manifest、角色权限、超时和 worktree。`AgentResult` 只能携带与 request 身份对齐的 typed Artifact，或不含 Artifact 的 typed failure；模型供应商可以更换，但角色契约不能由模型自行修改。T008 的 `FakeAgentAdapter` 通过脚本注入成功、QA FAIL、Review REJECT 和 timeout；T009 的 `SerialOrchestrator` 使用同一 seam 完成离线交付闭环。

### Command Execution Boundary

T015 的 `SubprocessCommandExecutor` 是角色执行命令的唯一预留端口：它绑定具体 worktree
root，先复用 `WorkspacePolicy` 检查完整 tokenized argv，再以 `shell=False`、明确 cwd、
最小环境和固定 timeout 启动进程组。非零 return code 只是可观察结果，不等于 verdict；
stdout/stderr 受字节上限并带截断标志，timeout/启动失败是稳定 typed error。这样 QA 能在
未来生成可复核 test evidence，同时不让 shell 字符串、宿主机 secrets 或 cwd 越界穿过执行边界。

T016 的 `RoleWorktreeSession` 是该端口与 Repository Plane 的最小组合层：它只接受同角色
`AgentDefinition` 与 `WorktreeSpec`，调用 `GitWorkspace.create` 后把返回的 manager-owned
root 绑定给 `SubprocessCommandExecutor`。QA/Reviewer 继续在 candidate SHA 的 detached
worktree 中运行，Coder 保留 attempt branch；`close` 委托 Git 的 dirty 检查，不能 force-delete
未持久化现场。该层不迁移 Task、不写 Artifact，也不把模型文本解释成命令。

### Evidence Plane

Artifact Store 保存 JSON artifact 正文、Schema 版本、producer、source revision、父子关系、证据路径与 SHA-256。T023 的 `FileEvidenceStore` 在 sidecar `evidence/` 与 `runs/` 下保存脱敏、限长、带 SHA-256 的 command/diff/test/Agent usage records 及 run manifest；超时、拒绝和启动失败也会留下可重放事实。T024 的 typed tool registry 将每个 role/run 的文件和命令操作绑定到 `WorkspacePolicy`，工具结果必须由应用层转成 evidence，不能直接写 artifact、verdict 或状态。

### Repository Plane

Git worktree 管理候选代码。Orchestrator 在主 checkout 上只做读取和 ref 操作；Coder 使用可写 worktree；QA 可在专用 worktree 写测试但不能改生产代码；Reviewer 只读。

v0.1 的 `GitWorktreeManager` 将所有 role worktree 放在 main checkout 外，Coder 使用独立 attempt branch，QA/Reviewer detached 到同一 candidate SHA。`WorkspacePolicy` 绑定具体 worktree root，先做 path/command 授权；Git adapter 再用 argv、固定 cwd/env/timeout 执行。dirty worktree 保留用于 evidence/recovery，不 force cleanup。

### Human Boundary

需求澄清、越权批准、冲突解决和最终合并都属于人类边界。临时等待人类或依赖时 WorkItem
进入 `WAITING_HUMAN/WAITING_DEPENDENCY` 并释放 Lease，Task 保留最近 checkpoint；只有没有
安全继续路径或预算终局耗尽时才进入 `BLOCKED`。T012 的 Evaluation 层把 case 启动、Agent
run、人工动作和回归窗口记录为不可变事件；`EvaluationEngine` 只从这些事件、StateEvent 与
封存 Artifact 重算指标。`HandoffBuilder` 为 `DONE/BLOCKED` 构造自包含 JSON + Markdown。

## 3. 数据流

```text
WorkItem + AgentProfile + ModelPolicy
  → Assignment + Lease + RunDemand
  → run-scoped ModelSelection
  → Task(JSON)
  → validate + persist
  → planning context → plan artifact → seal/store/read-back
  → coder context(policy + task + role + persisted plan)
  → implementation-report + candidate commit → seal/store/read-back
  → QA context(candidate + persisted plan/implementation) → qa-report → seal/store/read-back
  → review context(candidate + persisted plan/implementation/QA) → review-report → seal/store/read-back
  → DONE | retry current role/Coder | BLOCKED | FAILED
  → EvaluationTrace → metrics/ADR
  → HandoffBundle(JSON + Markdown) → human review/merge or unblock decision
```

每个箭头都是一个契约边界：输入必须先通过 Schema 校验，输出必须包含 `task_id`、`source_revision` 和可定位 evidence。`FileRunContextBuilder` 只把 ArtifactStore 读回的显式上游 Artifact 编译为 `artifact://<id>` Context source；下游不读取上游 Agent 的未持久化记忆。

## 4. 持久化模型

| 数据 | v0.1 存储 | 说明 |
|---|---|---|
| Task 与状态 | SQLite | 事务性更新，唯一状态写入者是 Orchestrator；attempt 通过 `record_attempt` 单调 checkpoint |
| Artifact 索引 | 后续接入 SQLite | T005 先由文件名和 typed `ArtifactRef` 提供按 ID 读取；Orchestrator 阶段再持久化查询索引 |
| Artifact 正文 | 文件系统 JSON | `artifacts/art_<artifact-id>.json`，临时文件 + 原子 rename |
| 运行日志 | 文件系统文本 | 脱敏、截断、由 evidence 引用 |
| Evaluation events | 文件系统 canonical JSON | 一事件一文件，带内部 SHA-256，exact replay 幂等 |
| Handoff | 文件系统 JSON + Markdown | deterministic ID，等价重建保留首次观察时间 |
| Project workspace binding | 外置 sidecar `workspace.json` + 固定目录 | 目标项目外置、幂等、与项目路径绑定；不复制源码 |
| Agent/Model workforce | 组织 workspace 文件记录 | T022 原子保存 AgentProfile/ModelPolicy；work-items/leases/metrics 为后续持久化端口 |
| ProjectProfile / Spec governance | Project sidecar 文件记录 | profile 与 runtime binding 不可变；冲突/resolution 使用带 SHA 的 append-only 记录 |
| Trellis 规则 | Git 中的 Markdown | 组织知识，评审后变更 |

Task 快照和状态事件的 Python 入口分别是 `Task` 与 `StateEvent`；`SqliteTaskRepository` 使用 `tasks`、`state_events` 两张表。快照正文和事件正文均保留 JSON，便于重启后由 Pydantic 重新校验并按事件 revision 回放。

Artifact 的 Python 入口是 `Artifact` union；`FileArtifactStore` 以 Artifact ID 作为受校验的文件名。写入前必须由 `seal_artifact` 生成 canonical JSON SHA-256，Store 再验证 typed contract、`validated=true` 和父子 lineage；成功写入使用临时文件、`fsync` 和原子替换，重复正文幂等，变更正文拒绝覆盖。

## 5. 信任边界与安全默认值

1. 用户 Task、仓库内容和测试输出都视为**潜在不可信数据**；prompt 注入不能改变角色权限或状态机。
2. 权限以 Orchestrator 传给执行器的 policy 为准，Agent prompt 中的自然语言不能扩大权限。
3. 所有命令通过 allowlist 执行，禁止任意 shell 拼接；网络默认关闭，只有显式配置的包镜像/模型 endpoint 可访问。
4. artifact 写入采用临时文件 + 原子 rename；校验失败的 artifact 不进入正式索引。
5. Secret 不进入 context；日志和 artifact 写入前执行基本脱敏（API key、token、密码、私钥）。
6. 内部 Git 调用禁用 repository hooks/fsmonitor 和 external diff/textconv；发现 repository-local external checkout filter 时 v0.1 fail closed。完整 OS/container sandbox 仍是 command executor 阶段的安全门，Git policy 不冒充该能力。

## 6. v0.1 非目标

不做单 Task 内多角色并发或复杂 DAG，不引入消息队列、向量数据库、自动生产部署、跨仓库事务、
自动需求拆分、自动修改组织规范或自动 merge 保护分支。组织层只实现单进程、有界、Lease 驱动
的多 Task 调度；不会用共享长驻会话冒充并发，也不会在 v0.1 引入分布式 Scheduler。
