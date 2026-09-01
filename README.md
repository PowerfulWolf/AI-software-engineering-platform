# ai-software-engineer v0.1

一个基于 Trellis 思想与 Multi-Agent 协作的软件工程平台 MVP。

> 目标：给定一个已有 Git 项目和一条可验收需求，平台以可追溯、可复核的方式串行运行 `Coder → QA → Reviewer`，最终产出一个可合并变更或明确的阻塞原因。

## 设计原则

1. **Knowledge belongs to the organization, not the agent**：规则、设计决策、失败经验和验收标准沉淀在 `.trellis/` 与任务 artifact 中；Agent 是可替换的执行者。
2. **No agent may be the sole judge of its own work**：Coder 不能批准自己的代码；QA 与 Reviewer 必须由独立会话、独立上下文和受限权限执行。
3. **Agents communicate through verifiable artifacts, not shared assumptions**：跨角色传递只允许使用经过 Schema 校验、带来源 revision、证据和哈希的 artifact。
4. **先闭环，再扩展**：v0.1 只实现单任务、单仓库、串行状态机；不引入复杂 DAG、向量数据库、自动生产部署或多租户。

## MVP 边界

输入：

- 一个已有 Git repository；
- 一条包含验收标准的 Task；
- 可选的项目规范、架构文档和测试命令。

输出：

- `plan`、`implementation-report`、`qa-report`、`review-report` 四类 artifact；
- 一个可审计的状态事件流；
- 通过 Review 的候选分支/补丁，或 `BLOCKED` 及其证据。

明确不做：并行 Agent/DAG、向量库/RAG 平台、自动合并到保护分支、生产发布、数据库迁移编排、跨仓库变更、长驻自治 Agent。

## 总体架构

```text
Human / Product Owner
          │ Task + acceptance criteria
          ▼
┌──────────────────────────────────────┐
│ Control Plane: Orchestrator          │
│ 状态机 · 路由 · 重试 · budget · 审计 │
└──────────────┬───────────────────────┘
               │ deterministic context bundles
┌──────────────▼───────────────────────┐
│ Knowledge Plane: Trellis              │
│ org rules · project specs · decisions │
│ task history · artifact index         │
└──────────────┬───────────────────────┘
               │ role-scoped input/output artifacts
     ┌─────────┼──────────┬────────────┐
     ▼         ▼          ▼            │
   Coder      QA       Reviewer         │
 (write)   (tests)    (read-only)       │
     └─────────┴──────────┴────────────┘
               ▼
       Git worktrees + CI evidence
```

## 项目结构

```text
ai-software-engineer/
├── README.md
├── AGENTS.md                         # Codex 项目级 bootstrap 指令
├── CONTEXT.md                        # 领域统一语言
├── pyproject.toml                    # Python 包、依赖与质量工具配置
├── src/ai_software_engineer/         # 控制平面 Python 包
│   ├── cli.py                        # ase 命令入口
│   ├── domain/                       # Task、Agent、Artifact 强类型契约
│   ├── store/                        # SQLite Task 快照与 StateEvent 日志
│   ├── artifacts/                    # 原子 JSON ArtifactStore 与 SHA-256
│   ├── git/                          # role worktree 隔离与 path/command policy
│   ├── context/                      # 确定、脱敏、预算受限的 Context Builder/Router
│   ├── orchestration/                 # 串行状态机 guard/reducer
│   └── prompts/                      # 后续：版本化 role prompt 模板
├── docs/
│   ├── architecture.md               # 分层、边界和部署形态
│   ├── tech-stack.md                 # 技术选型与取舍
│   ├── state-machine.md              # 状态、事件与迁移守卫
│   ├── contracts.md                  # 角色与 artifact 契约
│   ├── prompt-protocol.md            # 可直接模板化的 role prompts
│   ├── context-routing.md            # Context Builder/Router
│   ├── git-worktree.md               # 隔离、分支与合并策略
│   ├── orchestration.md              # 核心流程与伪代码
│   ├── failure-routing.md            # 失败分类、重试与升级
│   ├── evaluation.md                 # 指标与 Autonomous Delivery Rate
│   ├── milestones.md                 # 里程碑与第一批任务
│   └── decisions/
│       └── 0001-python-control-plane.md # 已接受的语言架构决策
├── schemas/
│   ├── task.schema.json
│   ├── agent.schema.json
│   ├── artifact.schema.json
│   ├── plan.schema.json
│   ├── implementation-report.schema.json
│   ├── qa-report.schema.json
│   ├── review-report.schema.json
│   ├── context.schema.json
│   └── state-event.schema.json
├── .trellis/
│   ├── README.md
│   └── spec/core/
│       ├── architecture.md
│       ├── contracts.md
│       └── python-runtime.md
├── tests/
│   ├── domain/                       # 单对象不变量和权限边界
│   ├── context/                      # 路由、预算、脱敏和注入边界
│   └── contracts/                    # Python model ↔ JSON Schema 一致性
└── artifacts/runs/                   # 运行产物（默认 gitignored）
```

## 推荐的 v0.1 运行形态

- 单机 CLI + Python 进程；
- SQLite 保存 Task、状态事件和 artifact 索引；文件系统保存 artifact 正文；
- Git CLI 管理 worktree；
- 模型通过一个 `AgentAdapter` 接口接入，默认支持 OpenAI-compatible endpoint；
- 每次 Agent 运行都有超时、token budget、最大重试次数和可复现的 context manifest。

具体选择和理由见 [`docs/tech-stack.md`](docs/tech-stack.md)。

## 开发环境

```bash
uv sync
uv run ase --help
uv run pytest
uv run ruff check .
uv run mypy src tests
```

项目使用 Python 3.12+。uv 会读取 `.python-version` 并建立隔离环境；`ase` 是平台 CLI 入口。

## 文档导航

- 架构与边界：[`docs/architecture.md`](docs/architecture.md)
- 状态机：[`docs/state-machine.md`](docs/state-machine.md)
- 契约与权限：[`docs/contracts.md`](docs/contracts.md)
- Prompt 协议：[`docs/prompt-protocol.md`](docs/prompt-protocol.md)
- Context：[`docs/context-routing.md`](docs/context-routing.md)
- Git 隔离：[`docs/git-worktree.md`](docs/git-worktree.md)
- Orchestrator：[`docs/orchestration.md`](docs/orchestration.md)
- 失败路由：[`docs/failure-routing.md`](docs/failure-routing.md)
- 评估：[`docs/evaluation.md`](docs/evaluation.md)
- 里程碑：[`docs/milestones.md`](docs/milestones.md)
- 语言架构决策：[`docs/decisions/0001-python-control-plane.md`](docs/decisions/0001-python-control-plane.md)
- Codex bootstrap：[`AGENTS.md`](AGENTS.md)

## 当前状态

M0 设计基线和 T001–T007 已完成。当前可运行 `ase`，并可用 Pydantic 校验 Task、Agent Definition、StateEvent、ContextBundle 以及四类 Artifact；正反例受 canonical JSON Schema contract tests 保护。Task 状态事件可在 SQLite 重启后恢复，状态图由纯函数 guard/reducer 管理，ArtifactStore 提供 SHA-256、lineage、原子写入和不可变重放保证。Repository Plane 可从指定 SHA 创建隔离的 Coder/QA/Reviewer worktree，检查 staged/unstaged/untracked 变更，并通过绑定 worktree root 的 policy 拒绝路径逃逸和未授权命令。Context Plane 会按角色路由显式来源，先脱敏再计数/哈希，并在超预算时确定性截断或 fail closed。

下一步是 T008：实现 FakeAgentAdapter，注入成功、QA FAIL、Review REJECT 和超时场景。后续实现仍严格按 `AGENTS.md` 与 `.trellis/spec/` 推进，任何跨语言契约变更先更新 Schema 和文档，再更新代码与测试。
