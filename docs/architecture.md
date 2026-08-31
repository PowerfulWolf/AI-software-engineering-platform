# 总体架构

## 1. 目标与约束

v0.1 解决一个窄而完整的问题：在已有 Git 项目中，把一条需求交给受约束的 Coder、独立 QA 和独立 Reviewer，形成可审计的闭环。平台优先保证可追溯性、权限边界和失败可恢复性，而不是追求 Agent 数量或调度复杂度。

### 运行假设

- 一个 Task 只绑定一个 repository 和一个 base ref；
- 一个 Orchestrator 实例一次只推进一个 Task（可在未来扩展并发）；
- Agent 不直接互相调用，所有交互经过 Orchestrator 和 artifact store；
- 人类是需求来源和最终升级出口；v0.1 不自动向保护分支 push/merge。

## 2. 六个逻辑组件

### Control Plane

由 Orchestrator、状态机、路由器、预算管理器和审计日志组成。它是唯一可以迁移 Task 状态的组件，负责检查前置条件、启动 Agent、验证 artifact、决定重试或升级。

### Knowledge Plane

由 `.trellis/spec/`（组织级规则）、项目文档、任务 PRD/Design、历史 artifact 摘要和失败经验组成。Context Builder 只读取声明过的来源并生成带哈希的 manifest；不把整仓库或整段历史盲目塞给模型。

### Agent Execution Plane

通过 `AgentAdapter` 启动 Coder、QA、Reviewer。每个运行使用独立会话标识、独立 prompt、角色权限和 worktree。模型供应商可以更换，但角色契约不能由模型自行修改。

### Evidence Plane

Artifact Store 保存 JSON artifact 正文、Schema 版本、producer、source revision、父子关系、证据路径与 SHA-256。Git diff、测试输出和静态检查结果都以 evidence 条目引用，必要时保存截断后的日志文件。

### Repository Plane

Git worktree 管理候选代码。Orchestrator 在主 checkout 上只做读取和 ref 操作；Coder 使用可写 worktree；QA 可在专用 worktree 写测试但不能改生产代码；Reviewer 只读。

### Human Boundary

需求澄清、越权批准、冲突解决和最终合并都属于人类边界。任何无法在既定预算或证据标准内解决的情况都进入 `BLOCKED`，而不是让 Agent 自行放宽规则。

## 3. 数据流

```text
Task(JSON)
  → validate + persist
  → plan artifact
  → coder context(manifest + plan)
  → implementation-report + candidate commit
  → QA context(manifest + diff + acceptance criteria)
  → qa-report
  → review context(manifest + code + qa-report)
  → review-report
  → DONE | retry Coder | BLOCKED
```

每个箭头都是一个契约边界：输入必须先通过 Schema 校验，输出必须包含 `task_id`、`source_revision` 和可定位 evidence。下游只信任 artifact，不读取上游 Agent 的未持久化记忆。

## 4. 持久化模型

| 数据 | v0.1 存储 | 说明 |
|---|---|---|
| Task 与状态 | SQLite | 事务性更新，唯一状态写入者是 Orchestrator |
| Artifact 索引 | 后续接入 SQLite | T005 先由文件名和 typed `ArtifactRef` 提供按 ID 读取；Orchestrator 阶段再持久化查询索引 |
| Artifact 正文 | 文件系统 JSON | `artifacts/art_<artifact-id>.json`，临时文件 + 原子 rename |
| 运行日志 | 文件系统文本 | 脱敏、截断、由 evidence 引用 |
| Trellis 规则 | Git 中的 Markdown | 组织知识，评审后变更 |

Task 快照和状态事件的 Python 入口分别是 `Task` 与 `StateEvent`；`SqliteTaskRepository` 使用 `tasks`、`state_events` 两张表。快照正文和事件正文均保留 JSON，便于重启后由 Pydantic 重新校验并按事件 revision 回放。

Artifact 的 Python 入口是 `Artifact` union；`FileArtifactStore` 以 Artifact ID 作为受校验的文件名。写入前必须由 `seal_artifact` 生成 canonical JSON SHA-256，Store 再验证 typed contract、`validated=true` 和父子 lineage；成功写入使用临时文件、`fsync` 和原子替换，重复正文幂等，变更正文拒绝覆盖。

## 5. 信任边界与安全默认值

1. 用户 Task、仓库内容和测试输出都视为**潜在不可信数据**；prompt 注入不能改变角色权限或状态机。
2. 权限以 Orchestrator 传给执行器的 policy 为准，Agent prompt 中的自然语言不能扩大权限。
3. 所有命令通过 allowlist 执行，禁止任意 shell 拼接；网络默认关闭，只有显式配置的包镜像/模型 endpoint 可访问。
4. artifact 写入采用临时文件 + 原子 rename；校验失败的 artifact 不进入正式索引。
5. Secret 不进入 context；日志和 artifact 写入前执行基本脱敏（API key、token、密码、私钥）。

## 6. v0.1 非目标

不做多 Agent 并发、复杂 DAG、向量数据库、自动生产部署、跨仓库事务、自动需求拆分、自动修改组织规范、自动 merge 保护分支。若未来需要这些能力，先补充新的状态、权限和评估契约。
