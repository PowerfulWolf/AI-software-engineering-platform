# ai-software-engineer v0.1

一个基于 Trellis 思想与 Multi-Agent 协作的、可审计的 AI 软件工程平台。

它的目标不是演示多个 Agent 互相对话，而是逐步建立一个有制度、有岗位边界、有组织记忆、
能够持续交付和自我改进的数字研发团队。

> 目标：给定一个已有 Git 项目和一条可验收需求，平台以可追溯、可复核的方式串行运行 `Coder → QA → Reviewer`，最终产出一个可合并变更或明确的阻塞原因。

## 设计原则

1. **Knowledge belongs to the organization, not the agent**：规则、设计决策、失败经验和验收标准沉淀在 `.trellis/` 与任务 artifact 中；Agent 是可替换的执行者。
2. **No agent may be the sole judge of its own work**：Coder 不能批准自己的代码；同一 Task 历史
   的 Coder、QA、Reviewer 必须是不同 Agent，并使用独立 Run、Context、worktree 和受限权限。
3. **Agents communicate through verifiable artifacts, not shared assumptions**：跨角色传递只允许使用经过 Schema 校验、带来源 revision、证据和哈希的 artifact。
4. **Task 内串行，组织层有界调度**：每个 Task 仍按 `Coder → QA → Reviewer` 串行；组织可以在
   容量允许时调度多个相互隔离 Task，不引入单 Task 复杂 DAG、共享会话或分布式队列。

## 当前进度（2026-09-01）

T001–T022 已完成。自动化质量基线为 **344 个测试**、Ruff 检查与格式检查通过、strict Mypy
检查 **112 个源码文件**、Python package build 通过。

| 阶段 | 状态 | 已交付结果 |
|---|---|---|
| M0 设计与 Bootstrap | 已完成 | 总体架构、契约、状态机、Trellis/Codex 指令、Python CLI 骨架 |
| M1 Domain + Persistence | 已完成 | 强类型领域模型、SQLite 事件事实、纯状态机、不可变 ArtifactStore |
| M2 Git + Context | 已完成 | role worktree 隔离、命令/路径策略、确定性 Context Builder/Router |
| M3 串行 Agent Loop | 已完成 | Fake/真实 AgentAdapter、`Coder → QA → Reviewer`、有界重试与恢复 |
| M4 Evaluation + Handoff | 已完成 | Evaluation events、指标/ADR 重算、DONE/BLOCKED handoff、CLI/runtime |
| 执行安全边界 | 已完成 | fail-closed 命令执行端口、role worktree 执行生命周期 |
| M5 组织 Workforce 与任意项目接入 | 已完成 | sidecar、Workforce、Scheduler/ModelRouter、ProjectProfile、SpecCompiler、Runtime workspace binding |
| M6 可执行交付 | 进行中 | evidence capture、Agent tool protocol、跨语言真实项目 E2E |
| M7 Agent 可视化 | 待开始 | 只读投影/API、Task board、timeline、Agent detail、Human inbox |

完整阶段事实、任务清单和提交证据见
[`docs/archive/2026-09-01-t019-t022-organization-runtime.md`](docs/archive/2026-09-01-t019-t022-organization-runtime.md)；
后续路线见 [`docs/milestones.md`](docs/milestones.md)。

## MVP 边界

输入：

- 一个已有本地项目目录（Git 是 v0.1 的首个 Repository adapter，未来可接入其他 VCS）；
- 一条包含验收标准的 Task；
- 可选的项目规范、架构文档和测试命令。

输出：

- `plan`、`implementation-report`、`qa-report`、`review-report` 四类 artifact；
- 一个可审计的状态事件流；
- 通过 Review 的候选分支/补丁，或 `BLOCKED` 及其证据；
- 可从事件重算的 Evaluation/ADR 报告，以及供人类直接复核的 JSON + Markdown handoff。

明确不做：单 Task 并行 Agent/DAG、共享多 Task 会话、分布式 Scheduler、向量库/RAG 平台、
自动合并保护分支、生产发布、数据库迁移编排和跨仓库事务。

## 总体架构

```text
Human / Product Owner → WorkQueue
              │
              ▼
PortfolioScheduler + ModelRouter
  AgentProfile · capacity · priority · risk · Lease
              │ RoleAssignment + ModelSelection
              ▼
TaskOrchestrator（每个 Task 内串行）
              │
     ┌────────┼─────────┐
     ▼        ▼         ▼
   Coder      QA     Reviewer
     │ isolated Context/worktree/Artifact
     ▼
Trellis Knowledge + Project sidecar + Git/Evidence
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
│   ├── domain/                       # Task、Agent、Workforce、Artifact 强类型契约
│   ├── store/                        # SQLite Task 快照与 StateEvent 日志
│   ├── artifacts/                    # 原子 JSON ArtifactStore 与 SHA-256
│   ├── git/                          # role worktree 隔离与 path/command policy
│   ├── context/                      # 确定、脱敏、预算受限的 Context Builder/Router
│   ├── agents/                       # AgentAdapter、Fake 与 OpenAI-compatible adapter
│   ├── orchestration/                # 串行 runner、Context composition 与状态机
│   ├── scheduling/                   # 纯 PortfolioScheduler 与 run-scoped ModelRouter
│   ├── runtime.py                    # RuntimeConfig、角色路由与 task run composition
│   ├── runtime_workspace.py          # 组织/项目 workspace 绑定与 workforce 解析
│   ├── project_profile.py            # 技术栈、VCS 与项目原生规则只读发现
│   ├── spec_compiler.py              # 三层规范编译、冲突与人工 resolution
│   ├── execution.py                  # worktree 内受控 argv/subprocess 执行端口
│   ├── role_workspace.py             # Git worktree + executor 生命周期组合
│   ├── project_workspace.py           # 目标项目与外置 AI sidecar workspace 绑定
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
│   ├── archive/                      # 已完成阶段的事实、验证与提交记录
│   └── decisions/                    # 已接受的架构决策
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
│   ├── runtime-config.schema.json
│   ├── project-workspace.schema.json
│   ├── workforce.schema.json
│   ├── project-profile.schema.json
│   ├── spec-conflict.schema.json
│   ├── spec-resolution.schema.json
│   └── runtime-workspace-binding.schema.json
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
│   ├── scheduling/                   # capacity、priority、independence 与模型路由
│   ├── project_profile/              # 跨语言发现、完整性与路径边界
│   ├── spec_compiler/                # 冲突、resolution 与不可变记录
│   ├── runtime_workspace/            # workspace/binding/allocation 组合契约
│   ├── execution/                    # 命令 allowlist、环境和 timeout 测试
│   ├── role_workspace/               # role worktree 与 executor 组合测试
│   └── contracts/                    # Python model ↔ JSON Schema 一致性
└── artifacts/runs/                   # 运行产物（默认 gitignored）
```

目标项目代码目录之外，平台会为每个项目建立外置 sidecar workspace。其固定布局如下；这些
目录不应出现在目标项目中：

```text
<ai-workspace-root>/<project-id>/
├── workspace.json
├── profile/ assignments/ knowledge/ policy/ state/
├── artifacts/ contexts/ evidence/ evaluations/
├── handoffs/ runs/ locks/ logs/ spec-conflicts/
```

目标项目仍是代码、测试和构建命令的默认 cwd；sidecar 只保存项目元数据、Assignment 和可审计
事实。AgentProfile 不属于项目，组织级数据采用独立 workspace：

```text
<organization-workspace>/
├── organization.json
├── agents/ model-policies/ work-items/
└── leases/ metrics/
```

项目原生规范会被索引和引用，不会被平台静默覆盖；规范冲突进入人工处理队列。

T018 将 sidecar layout 升级为 v0.2；旧 `agents/` layout 不会被静默改写。T022 提供 Python
composition seam，将组织 workspace、项目 sidecar、ProjectProfile 与 Runtime 绑定；CLI 自动
发现与绑定仍是后续入口工作：

```python
from datetime import UTC, datetime

from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry
from ai_software_engineer.project_profile import ProjectProfile
from ai_software_engineer.runtime_workspace import OrganizationWorkspace, RuntimeWorkspaceBinder

workspace = ProjectWorkspaceRegistry("/path/to/ase-workspaces").register("/path/to/target-project")
now = datetime.now(UTC)
organization = OrganizationWorkspace.initialize(
    "/path/to/ase-organization",
    organization_id="organization_primary",
    created_at=now,
)
profile = ProjectProfile.discover(workspace.project_root, project_id=workspace.project_id)
binding = RuntimeWorkspaceBinder().bind(organization, workspace, profile, bound_at=now)
print(workspace.project_root)  # 实际代码 cwd
print(workspace.root)  # 外置 AI workspace
print(binding.paths.database)  # sidecar/state/state.sqlite3
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

## 当前如何使用

当前版本首先是一套可运行、可测试、可扩展的控制平面基础，而不是已经能够对任意项目全自动
改码交付的最终产品。现阶段可以：

- 用 `ase task create/show/events` 创建和审计强类型 Task；
- 用 `ase task run` 按固定顺序运行配置驱动的 Coder、QA、Reviewer；
- 用 `ase evaluation report` 从 durable facts 重算指标和 ADR；
- 用 `ase handoff build` 为 `DONE/BLOCKED` Task 生成 JSON + Markdown 交付包；
- 在 Python application seam 中注册任意本地项目的外置 sidecar workspace；
- 只读发现语言、构建系统、VCS 和项目原生规范来源，并以 URI/hash 形成 ProjectProfile；
- 用 SpecCompiler 编译结构化组织/项目/Task 规则，冲突时生成 `WAITING_HUMAN` 路由和不可变 resolution；
- 用 AgentProfile、WorkItem、RoleAssignment、TaskLease、ModelPolicy、ModelSelection 和
  AgentRunAllocation 表达组织成员、容量和 run-scoped 大脑；
- 用 PortfolioScheduler/ModelRouter 做确定、可重放的 Assignment/Lease 与模型选择决策；
- 在 Python application seam 中绑定组织/项目 workspace，并解析 run-scoped AgentDefinition；
- 复用 Git worktree、Context、Artifact、retry、evaluation 和受控命令执行组件继续开发。

最小 CLI 流程：

```bash
uv sync
uv run ase task create --file task.json --database /path/to/ai-workspace/state/state.sqlite3
export OPENAI_API_KEY='...'
uv run ase task run <task-id> --config runtime.json
uv run ase handoff build <task-id> \
  --database /path/to/ai-workspace/state/state.sqlite3 \
  --artifacts /path/to/ai-workspace/artifacts \
  --output /path/to/ai-workspace/handoffs
```

当前 CLI 尚未自动发现并绑定 workspace。使用 CLI 时，外部目标项目的 state、artifact、context、
evaluation 和 handoff 路径仍必须显式指向 sidecar，避免污染目标项目；Python application 可用
T022 的 `RuntimeWorkspaceBinding.compose_runtime_config(...)` 完成同一装配。配置示例和字段说明见
[`docs/runtime.md`](docs/runtime.md) 与 [`docs/cli.md`](docs/cli.md)。

当前尚未完成的关键闭环是：持久化 WorkQueue 与调度 application service、CLI workspace 自动
装配、让模型通过受策略约束的 tool protocol 真正编辑/测试项目、封存命令/diff/测试证据、
跨语言项目 E2E，以及可视化工作台。平台也不会自动 merge 保护分支或部署生产环境。

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
- Project workspace 与 Agent 工作可视化：[`docs/visualization.md`](docs/visualization.md)
- 里程碑：[`docs/milestones.md`](docs/milestones.md)
- 阶段归档：[`docs/archive/README.md`](docs/archive/README.md)
- 语言架构决策：[`docs/decisions/0001-python-control-plane.md`](docs/decisions/0001-python-control-plane.md)
- Agent Workforce 决策：[`docs/decisions/0002-organization-owned-agent-workforce.md`](docs/decisions/0002-organization-owned-agent-workforce.md)
- Codex bootstrap：[`AGENTS.md`](AGENTS.md)
