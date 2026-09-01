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
- 通过 Review 的候选分支/补丁，或 `BLOCKED` 及其证据；
- 可从事件重算的 Evaluation/ADR 报告，以及供人类直接复核的 JSON + Markdown handoff。

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
│   ├── cli.py                        # ase 命令入口与 composition root
│   ├── domain/                       # Task、Agent、Artifact 强类型契约
│   ├── store/                        # SQLite Task 快照与 StateEvent 日志
│   ├── artifacts/                    # 原子 JSON ArtifactStore 与 SHA-256
│   ├── git/                          # role worktree 隔离与 path/command policy
│   ├── context/                      # 确定、脱敏、预算受限的 Context Builder/Router
│   ├── agents/                       # AgentAdapter、Fake 与 OpenAI-compatible adapter
│   ├── orchestration/                # 串行 runner、Context composition 与状态机
│   ├── runtime.py                    # RuntimeConfig、角色路由与 task run composition
│   ├── execution.py                  # worktree 内受控 argv/subprocess 执行端口
│   ├── evaluation/                   # Evaluation events、metrics/ADR、handoff
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
│   ├── cli.md                        # CLI 使用说明
│   ├── runtime.md                    # Runtime 配置与 task run
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
│   ├── state-event.schema.json
│   ├── evaluation-event.schema.json
│   ├── handoff-bundle.schema.json
│   └── runtime-config.schema.json
├── .trellis/
│   ├── README.md
│   └── spec/core/
│       ├── architecture.md
│       ├── contracts.md
│       └── python-runtime.md
├── tests/
│   ├── domain/                       # 单对象不变量和权限边界
│   ├── context/                      # 路由、预算、脱敏和注入边界
│   ├── agents/                       # Fake/real AgentAdapter 共用契约
│   ├── orchestration/                # 串行交付闭环与状态 checkpoint
│   ├── evaluation/                   # 事件重放、ADR 与 DONE/BLOCKED handoff
│   ├── runtime/                      # RuntimeSession 与 fake adapter composition
│   ├── execution/                    # 命令 allowlist、环境和 timeout 测试
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
- CLI 使用：[`docs/cli.md`](docs/cli.md)
- Runtime 配置与 task run：[`docs/runtime.md`](docs/runtime.md)
- 里程碑：[`docs/milestones.md`](docs/milestones.md)
- 语言架构决策：[`docs/decisions/0001-python-control-plane.md`](docs/decisions/0001-python-control-plane.md)
- Codex bootstrap：[`AGENTS.md`](AGENTS.md)

## 当前状态

M0–M4 与 T001–T015 的 v0.1 核心库已经完成。当前可运行 `ase`，并可用 Pydantic 与 canonical JSON Schema 校验 Task、Agent Definition、StateEvent、ContextBundle、AgentRequest/AgentResult、四类 Artifact、EvaluationEvent、HandoffBundle 与 RuntimeConfig。Task/事件可从 SQLite 恢复，Artifact/Context/Evaluation/Handoff 文件存储都采用不可变、原子、fail-closed 的边界。Repository Plane、Context Plane、Fake/真实 AgentAdapter、串行 Orchestrator、有界 retry/recovery、RuntimeSession 和受策略约束的 worktree 命令执行端口已形成可离线验证的闭环。

T012 通过 `EvaluatingAgentAdapter` 自动记录 Agent run 事实，`EvaluationTraceBuilder + EvaluationEngine` 从状态事件、评估事件和封存 Artifact 重算 metrics/ADR；`HandoffBuilder + FileHandoffStore` 为 `DONE/BLOCKED` 输出自包含 JSON 与 Markdown。T013 将这些能力接入离线 CLI：`ase task create/show/events`、`ase evaluation report` 和 `ase handoff build`；T014 增加受配置驱动的 `ase task run`，从环境读取 API key，复用同一 stores 和 retry runner；T015 增加 `SubprocessCommandExecutor`，在固定 worktree cwd 中以 tokenized argv、命令 allowlist、最小环境、输出上限和进程组 timeout 执行后续 Coder/QA/Reviewer 命令。缺少回归观察窗口时 ADR 明确为 `PENDING`，不会把未知当成功。完整装配示例见 [`docs/evaluation.md`](docs/evaluation.md) 与 [`docs/runtime.md`](docs/runtime.md)。真实 provider 凭据、模型选择和网络策略仍由部署环境注入；v0.1 不自动 merge、部署或引入并行 DAG。
