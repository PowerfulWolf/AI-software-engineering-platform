# ai-software-engineer v0.1

一个基于 Trellis 思想与 Multi-Agent 协作的、可审计的通用 AI 软件工程团队平台。

团队不绑定某个业务领域或技术栈。你先接入一个 Project，再为 Requirement 选择该 Project
涉及的一个或多个代码目录；同一支长期 Agent 团队服务所有 Project，而每个 Project 的知识、规范、
Repository 目录和 Requirement 交付事实保持隔离。

它的目标不是演示多个 Agent 互相对话，而是逐步建立一个有制度、有岗位边界、有组织记忆、
能够持续交付和自我改进的数字研发团队。

> Manager 先准备 Project 和所选 Repository，再让 Product 与你澄清 Requirement。你确认产品文档后，
> 团队按 Repository 串行执行 `Coder → QA → Reviewer`，最后交付可合并候选分支与验证证据，或明确的阻塞原因。

## 设计原则

1. **Knowledge belongs to the organization, not the agent**：规则、设计决策、失败经验和验收标准沉淀在 `.trellis/` 与任务 artifact 中；Agent 是可替换的执行者。
2. **No agent may be the sole judge of its own work**：Coder 不能批准自己的代码；同一 Task 历史
   的 Coder、QA、Reviewer 必须是不同 Agent，并使用独立 Run、Context、worktree 和受限权限。
3. **Agents communicate through verifiable artifacts, not shared assumptions**：跨角色传递只允许使用经过 Schema 校验、带来源 revision、证据和哈希的 artifact。
4. **Task 内串行，组织层有界调度**：每个 Task 仍按 `Coder → QA → Reviewer` 串行；组织可以在
   容量约束下分配多个相互隔离 Task，不引入单 Task 复杂 DAG、共享会话或外部分布式队列。
   T046 提供 MySQL PersistentWorkQueue、确定性 Dispatcher tick 和 owner-fenced Lease 生命周期；
   一次队列项只代表一个可执行角色 Run。当前 `ase request` 兼容入口仍使用串行 RuntimeSession，
   尚未切换为逐角色队列 Worker。

## MVP 边界

输入：

- 一个已选择的 Project，以及该 Requirement 涉及的一个或多个本地代码目录（当前交付使用 Git）；
- 一条自然语言需求；Product Agent 将其整理为可评审 Product Spec，并由用户确认；
- Team 通用知识、Project 背景知识、必须遵守的 Team/Project Spec、Repository 原生规范，以及
  AgentProfile 与 ModelPolicy。知识用于理解，Spec 用于约束和验收，两者不再混放。

日常 Web Console 入口的交付结果：

- DONE 时的 `plan`、`implementation-report`、`qa-report`、`review-report` 四类终态 artifact；复杂实现
  还会保留一个或多个 `coder-progress` checkpoint；
- ProductSpec/Approval、TechnicalDesign、ExecutionPlan 等上游团队交接 artifact；
- 一个可审计的状态事件流；
- 各仓通过 QA/Review 的候选提交与联合验收记录，或阻塞状态及其证据；
- Web Console 展示需求 checkpoint、后台操作、成员当前阶段、模型调用与报告；CLI 仅作为部署、
  诊断和 break-glass 入口保留。

底层另外提供 Evaluation/ADR 重算与 JSON + Markdown Handoff 能力；不能据此认为日常
request 命令已经自动生成完整评估与交付汇总报告。Reporter 仍暂不开发。

通用性指不绑定具体业务与目标项目语言，并非已支持所有运行环境：当前代码交付要求本地 Git
仓库、可用的构建/测试依赖及受控命令，生产存储使用 MySQL。

明确不做：单 Task 并行 Agent/DAG、共享多 Task 会话、分布式 Scheduler、向量库/RAG 平台、
自动合并保护分支、生产发布、数据库迁移编排和跨仓库事务。

## 总体架构

平台只有一支长期存在的 Team，但可接入多个 Project。`<platform_root>/team` 保存团队成员、通用知识、
团队 Spec、Skills 和模型策略；`<platform_root>/projects/<project_id>` 保存该 Project 的背景知识、Spec、
Repository sidecar 和 Requirement 事实。Team 与 Projects 是同一数据根下的并列边界，不互相包含。

Agent 通过受控 Skills 调用确定性能力。Manager 领导全队并控制规划分流和实际派发；Product 定义需求，
Designer 形成技术方案，Planner 处理复杂计划，Coder、QA、Reviewer 对每个 Repository 串行交付。一个 Requirement
可以涉及 1–N 个 Repository，但始终只属于一个 Project，并且只读取该 Project 与 Team 的知识。

下图是当前控制平面边界。浏览器只提交 typed intent；Web Console 先把操作写入 Team sidecar，
再由后台 Manager 执行，因此刷新或关闭网页不会重复或取消已接纳的工作。当前生产 request 路径由
Manager 编排上游阶段，并通过 RuntimeSession 串行推进仓库 Task。T046 队列与 Dispatcher 已具备
独立的领取、心跳、等待和过期恢复契约；把该入口迁移成逐角色 Worker 仍是后续集成工作。

```mermaid
flowchart TB
    U["用户<br/>浏览器中创建、讨论、批准、继续"] --> WEB["Local Web Console<br/>typed intent · durable operation"]
    WEB --> OPS[("Team sidecar<br/>QUEUED → RUNNING → terminal")]
    OPS --> PM["Manager Agent<br/>团队领导"]

    PM --> ONBOARD["Project Preparation<br/>选择 Project · 注册 Repository sidecar<br/>发现 RepositoryProfile · 编译规范"]
    ONBOARD --> READY["Requirement Ready<br/>Project 与 Repository 边界就绪"]
    READY --> PRODUCT["Product Agent<br/>与用户澄清需求、维护需求对话"]
    U -. "准备完成后讨论需求" .-> PRODUCT
    PRODUCT --> PRODUCT_SPEC["Product Spec<br/>目标、范围、需求、验收标准"]
    PRODUCT_SPEC --> PRODUCT_REVIEW["Human Product Review<br/>可信人工通道验证 exact spec ID + digest"]
    PRODUCT_REVIEW --> DESIGNER["Designer Agent<br/>技术方案与实施规划"]
    DESIGNER --> TECH_DESIGN["Technical Design<br/>架构、步骤、测试策略、风险"]
    TECH_DESIGN --> GATE{"Manager PlanningGate<br/>确定性复杂度判断"}
    GATE -- "SIMPLE" --> FAST["Fast Plan<br/>零 Planner 模型调用"]
    GATE -- "COMPLEX" --> PLANNER["Planner Agent<br/>有界工作包、依赖、风险、测试矩阵"]
    FAST --> EXEC_PLAN["Execution Plan<br/>校验范围、修订链和验收覆盖"]
    PLANNER --> EXEC_PLAN
    EXEC_PLAN --> DISPATCH["Manager dispatch<br/>重新校验容量、独立性和模型策略"]
    DISPATCH --> ORCH["RuntimeSession / Task Orchestrator<br/>一次推进一个仓库 Task"]
    ORCH --> CODER["Coder<br/>独立 Context/worktree · checkpoint 或 candidate"]
    CODER -- "complete" --> QA["QA<br/>同一 candidate 独立验证"]
    QA -- "PASS" --> REVIEWER["Reviewer<br/>同一 candidate 独立审查"]
    QA -- "FAIL + evidence" --> CODER
    REVIEWER -- "REJECT + findings" --> CODER
    ORCH -- "阻塞知识缺口" --> WAIT["Requirement WAITING_HUMAN<br/>Task 保留交付 checkpoint"]
    WAIT -- "exact Resolution 批准<br/>新 Context/run" --> ORCH
    ORCH -- "无安全继续路径" --> STOP["Task BLOCKED / FAILED<br/>保留现场与证据"]

    REVIEWER -- "各仓 APPROVE" --> JOINT["联合验收<br/>完整候选集合 · 实际集成测试"]
    JOINT -- "PASS" --> DELIVERY["Delivery<br/>各仓 candidate SHA + artifacts + 联合验收证据"]
    JOINT -- "FAIL" --> STOP
    DELIVERY -. "后续扩展" .-> REPORTER["Reporter（暂不开发）<br/>后续按需组织交付视图"]

    COMMON_KNOWLEDGE["Team / Project 知识上传"] --> INDEX["异步增量 Indexer<br/>READY 后显式选择"]
    INDEX --> KNOWLEDGE["Knowledge Plane<br/>冻结快照 · typed search/read · 可追溯证据"]
    STRICT_SPECS["Engineering Specs<br/>适用的 Team/Project 规范 · Repository 原生规则"] --> KNOWLEDGE
    LEARNING["Learning Loop<br/>失败证据 / 已批准解答 · 独立发布审批"] --> KNOWLEDGE
    KNOWLEDGE --> PM
    KNOWLEDGE --> PRODUCT
    KNOWLEDGE --> DESIGNER
    KNOWLEDGE --> PLANNER
    KNOWLEDGE --> ORCH
    ORCH --> FACTS["Durable Facts<br/>StateEvent · Context · Artifact · Evidence"]
    FACTS --> VIEW["Read-only Projection<br/>从真实记录生成团队与交付视图"]
    VIEW --> WEB
    REPORTER --> HUMAN["Human Boundary<br/>合并、冲突决策、最终业务判断"]
    DELIVERY --> HUMAN
    STOP --> HUMAN
    VIEW --> HUMAN

    subgraph QUEUE_INFRA["T046 已有基础设施：request 入口尚未接入逐角色 Worker"]
        QUEUE[("MySQL PersistentWorkQueue")] --> DISPATCHER["Dispatcher 有界 tick"]
        DISPATCHER --> CLAIM["原子 Assignment / Lease / ModelSelection"]
        CLAIM --> WORKER["Worker seam<br/>owner-fenced 启动、心跳、结果"]
        WORKER --> QUEUE
    end
```

模型路由由“可用模型目录 + 每个 Agent 的有序策略”组成。Manager、Product、Designer、Planner、
Coder、QA、Reviewer 可以分别配置主模型和备用顺序；额度、限流或临时故障只会在该 Agent 自己的
策略内回退。全局启用的模型只是可选模型池；每个 Agent 只会使用自己显式选中的 0–N 个备用模型，
并按人工调整后的优先级尝试。同一模型可以用不同 Reasoning 配置成多条独立路由，例如 Product 选择 `medium`、Coder
选择 `high`；Agent 的选择会同时绑定 provider、model 和 reasoning。旧配置未指定角色策略时，七个成员继续共享全局启用顺序。当前仍未实现根据任务难度
自动调整成本/能力档位的完整动态策略。

### 各层只负责什么

| 层 | 核心职责 | 明确不能做 |
|---|---|---|
| Manager Agent | 团队领导；通过 prepare、advance、commit-dispatch、recover、deliver Skills 接单和推进整支团队 | 不能绕过 Skill 直接写状态、分配资源或批准代码 |
| Web Console command module | 接受浏览器 typed intent，先持久化 Operation，再异步委托 Manager；把 exact checkpoint/plan digest 隐藏在 UI 控件中 | 不能直接改 Task、Artifact、Git 或判定交付成功 |
| Product Agent | 与用户澄清需求，产出可评审、可追溯的版本化 Product Spec | 不能自己批准产品范围，不能持有人工决策验证权限，不能设计实现细节 |
| Designer Agent | 把已确认 Product Spec 转换为 Technical Design 和实施/测试规划 | 不能改写产品需求，不能直接提交业务实现 |
| PlanningGate / Planner Agent | Manager 确定性分流；SIMPLE 零模型生成，COMPLEX 产出有界工作包、依赖、风险与测试矩阵；preview 只读 | Planner 不能改变分流决定、分配具体成员或持有数据库锁、心跳、Lease owner authority |
| Agent Skills | Agent 按角色调用的 typed、policy-bound 能力接口；把请求委托给确定性 service 并返回可验证结果 | 不是 Prompt 指令，不授予 ambient store/shell 权限 |
| PersistentWorkQueue | 在 MySQL 保存 Run 级 WorkItem、Assignment、Lease 和生命周期事件 | 不解释 Artifact，不修改 Task verdict，不保存模型会话 |
| Dispatcher Service | 每次有界 tick 回收过期 Lease，并原子领取至多一个 Run；重复 tick 由外部监督驱动 | 不是 Agent，不依赖模型在线，不替 Worker 续约，不自行改变产品/技术计划 |
| Scheduler / ModelRouter engines | 为每个 Run 重新计算成员容量、独立性和模型选择 | 不能生成产品/设计内容，不能修改 Task verdict |
| Task Orchestrator | 按状态机串行推进一个 Task，校验 artifact 和 retry 条件 | 不能跳过 QA/Review，不能编写业务代码 |
| Agent Runner / Coder / QA / Reviewer | 成员在独立 Context、worktree 和权限下完成岗位工作；接入队列的 Worker 才持有 exact Lease owner token | 不能共享隐式记忆，不能批准自己的工作，不能使用别人的 Lease 提交 |
| Knowledge + Evidence | 维护冻结知识快照、受控检索、Context、缺口/解答与命令、测试、模型使用证据；Indexer 异步发布 verified 缓存 | 不能扩大已批准的知识范围，不能把描述性知识变成可执行规范或自动批准 Learning |
| Projection + Dashboard | 从 durable facts 重算团队和交付状态，向 Web Console 提供只读查询 | 只读，不能迁移状态或修改 verdict |
| Reporter（暂不开发） | 后续从已验证 artifact/Handoff 生成面向用户的交付表达 | 不能创造事实、改变 verdict 或隐藏失败 |
| Human Boundary | 处理规范冲突、业务歧义、保护分支合并与生产决策 | 人工动作必须留痕，不能静默改写历史 |

Manager、Product、Designer、Planner、Coder、QA、Reviewer 都是 Team workspace
中持久化的长期成员；Requirement 只产生 Assignment、Lease、独立 Context 和运行记录，不临时复制一套
AgentProfile。Scheduler、ModelRouter 和 Task Orchestrator 是这些成员调用的确定性能力，不作为
会聊天、会自我判断的新成员。

### 一个需求的实际流转

当前 `ase request` 入口在每个 Task 内按以下状态推进；复杂计划也不允许跳过独立 QA/Review：

```mermaid
flowchart LR
    PLAN["已验证的 ExecutionPlan"] --> NEW["NEW → PLANNING"]
    NEW --> C_RUN["IMPLEMENTING<br/>Coder"]
    C_RUN -- "coder-progress" --> C_NEXT["CONTINUE_REQUIRED → QUEUED"]
    C_NEXT -- "有界续跑" --> C_RUN
    C_RUN -- "complete + CandidateCommit" --> Q["QA"]
    Q -- "FAIL + evidence" --> C_RUN
    Q -- "PASS" --> R["REVIEW"]
    R -- "REJECT + findings" --> C_RUN
    R -- "APPROVE" --> DONE["DONE<br/>candidate SHA + evidence"]
```

如果 Task 已因额度、进程或基础设施故障终止但已经存在 candidate，Delivery 级恢复不会重开旧
Task：`resume → 独立候选验证 → PASS 则接纳；FAIL/REJECT 则创建关联修复 Task → 新 Candidate`。
因此“模型调用不能重复”和“需求必须继续完成”并不冲突：前者约束单个 Run，后者通过新的、可审计的
Run/Task 接续。

同一 Task 可以产生多个 Coder/QA/Reviewer Run；代码现场属于 Task branch/worktree，
不属于 Agent 的临时会话。阻塞知识缺口使 Requirement 等待人工解答，Task 保持最近 checkpoint；
批准 exact Resolution 后建立新 Context/run，旧 Gap、调用、批准和证据继续保留。

### 持久队列的 Lease 生命周期

以下是 T046 已实现并独立验证的队列契约，不表示上面的 request 流程已完成 Worker 迁移。
队列只发布当前可执行角色，不提前占用 QA/Reviewer；Task 交付状态与 WorkItem 调度状态相互独立。

```mermaid
stateDiagram-v2
    [*] --> READY
    READY --> LEASED: Dispatcher 原子领取
    LEASED --> RUNNING: Worker 启动
    RUNNING --> RUNNING: heartbeat 续约
    RUNNING --> CLOSED: Artifact 校验通过
    RUNNING --> RETRY_SCHEDULED: 暂时失败或需要稍后继续
    RUNNING --> WAITING_HUMAN: 需要人工决定
    RUNNING --> WAITING_DEPENDENCY: 等待外部依赖
    LEASED --> RETRY_SCHEDULED: 启动失败或 Lease 过期
    RUNNING --> RETRY_SCHEDULED: heartbeat 过期
    RETRY_SCHEDULED --> LEASED: 到达 available_at 后被重新领取
    WAITING_HUMAN --> READY: 人工动作已留痕
    WAITING_DEPENDENCY --> READY: 依赖恢复已验证
    CLOSED --> [*]
```

领取在 MySQL 全局容量 fence 和行锁内完成；只有持有 exact `lease_id + owner_token` 的 Worker 能
启动、续约、完成、等待或重试。数据库只保存 owner token 的 SHA-256。等待会立即释放容量；过期
Lease 被标记为 EXPIRED，原 WorkItem 增加 `dispatch_sequence` 后进入可审计的延迟重排。关闭当前
WorkItem 与发布下一角色 WorkItem 在同一事务中完成，重复的相同 completion 可安全重放。

## 项目结构

```text
AI-software-engineering-platform/
├── README.md                         # 项目边界、架构与主使用入口
├── AGENTS.md                         # Codex/Trellis 项目级开发约束
├── CONTEXT.md                        # 领域术语与组织统一语言
├── pyproject.toml                    # Python 包、CLI、依赖和质量门禁
├── config/                           # 不含密钥的 Team Host 配置示例
├── src/ai_software_engineer/
│   ├── cli.py                        # `ase` 顶层命令
│   ├── config/                       # ProductionConfig、默认值、模型路由与受控 runtime.env
│   ├── domain/                       # Task、Agent、Artifact、Workforce 强类型模型
│   ├── product/ design/ planning/    # Product、Designer、Planner 阶段及不可变记录
│   ├── manager/                      # prepare、阶段门禁、dispatch、Team Host
│   ├── scheduling/ work_queue/       # Scheduler、ModelRouter、持久队列和 Lease
│   ├── orchestration/ agents/        # 串行状态机、角色请求与模型适配器
│   ├── context/ artifacts/ evidence/ # Context、Artifact、Evidence 的存储与校验
│   ├── git/ role_workspace.py        # 分支/worktree、角色权限与受控命令执行
│   ├── multi_directory/              # 多目录/多仓需求拆分和联合验收
│   ├── recovery/                     # Delivery 统一续跑、失败 Coder 接手、候选复核与修复接续
│   ├── store/                        # MySQL 生产事实；SQLite 底层兼容实现
│   ├── projection/ team_view/        # 只读投影与兼容组件
│   ├── knowledge/                    # 冻结快照、typed 检索、缺口恢复与增量索引
│   ├── web_console/                  # 浏览器命令、持久 Operation、Manager 适配和 HTTP Host
│   ├── evaluation/                   # 事件重放、ADR 和 Handoff
│   ├── tools/                        # role/run 绑定的 typed Skill 协议
│   ├── team_workspace.py             # 唯一 Team workspace、通用知识与 Project registry
│   ├── project_workspace.py          # Project、知识、Requirement 和 Repository catalog
│   ├── repository_workspace.py       # 代码目录与外置 Repository sidecar 的绑定
│   ├── repository_profile.py         # 语言、构建系统、VCS 和原生规范发现
│   ├── knowledge_documents.py        # MD/TXT/PDF/DOCX 导入、规范化与不可变知识记录
│   ├── knowledge_selection.py        # Team/Project 知识选择、完整性与即时解析
│   ├── spec_documents.py             # Team/Project 强制 Spec 的不可变版本和显式启用集合
│   ├── learning.py                   # QA/Review 失败归纳、人工决策与知识/Spec/Skill 建议发布
│   └── runtime_workspace.py          # Team/Project/Repository Runtime 组合与校验
├── scripts/
│   └── ase-console-service.sh        # Web Console 后台启动、停止、重启、状态和日志
├── schemas/                          # 所有公开/持久化契约的 JSON Schema
│   ├── task.schema.json
│   ├── artifact.schema.json
│   ├── work-queue.schema.json
│   ├── delivery-recovery.schema.json
│   ├── candidate-verification.schema.json
│   ├── console-operation.schema.json
│   ├── knowledge-document.schema.json
│   ├── project-knowledge-document.schema.json
│   ├── knowledge-selection.schema.json
│   ├── spec-document.schema.json
│   ├── spec-activation.schema.json
│   ├── learning-proposal.schema.json
│   ├── learning-authorization.schema.json
│   ├── learning-decision.schema.json
│   ├── planning-gate.schema.json
│   ├── knowledge-*.schema.json
│   └── recovery-execution.schema.json
├── tests/                            # 与 src 分层对应；含真实 Git/MySQL 和离线模型契约测试
├── docs/
│   ├── production-setup.md           # 完整部署与运维手册
│   ├── architecture.md               # 架构和边界
│   ├── cli.md                        # CLI 与恢复命令
│   ├── archive/                      # 阶段成果和提交证据
│   └── decisions/                    # 已接受架构决策
└── .trellis/
    ├── spec/                         # 团队在本项目沉淀的可执行开发规范
    ├── tasks/                        # PRD、Design、Implement 等任务事实
    └── workspace/                    # 开发会话记录；不是生产 sidecar
```

仓库中的 `src/` 是平台控制平面代码；运行平台后产生的数据不会写回这里，也不会写入目标项目。
`schemas/` 必须与 Python DomainModel 同步，`tests/` 覆盖对应边界，`.trellis/spec/` 记录以后所有
开发 Agent 都必须遵守的工程知识。

## Workspace 分工

平台运行涉及五类位置。最重要的约束是：`<platform_root>` 与所有目标代码目录必须分离，不能互相
包含；Team、Projects 和 worktrees 都位于 `<platform_root>`，目标 Git 仓库只保留项目自己的文件。

| 位置 | 典型路径 | 职责与规范 |
|---|---|---|
| 平台源码仓库 | `/path/to/AI-software-engineering-platform` | `ase` 的实现、Schema、测试和 Trellis 规范；只在开发平台本身时修改 |
| 目标代码目录 | `/path/to/backend`、`/path/to/frontend` | Project 下的 Repository 或模块源码、测试、构建配置和原生规范；必须是绝对路径、Git HEAD 已提交、开始时工作树干净；平台不创建 `.ase` |
| 平台数据根 | `<platform_root>`；macOS/Linux 缺省为 `~/.ase` | 唯一 Team、全部 Project sidecar 和隔离 worktree 的共同外置根；必须持久化、备份并限制访问权限 |
| MySQL | `ASE_MYSQL_DSN` 指向的 MySQL 8.0 | Task、StateEvent、dispatch、WorkItem、Assignment、Lease 等并发权威事实；不能与文件 sidecar 二选一，二者都要保存 |
| 配置与运行变量 | `ASE_CONFIG` + sibling `runtime.env` | JSON 保存普通设置；可信本机 MVP 将设置页提交的 DSN/API key 以 `0600` 写入 `runtime.env`，启动脚本自动加载；接口、页面、日志、仓库和 sidecar 不回显或保存正文 |

一个实际 `<platform_root>` 的职责如下：

```text
<platform_root>/
├── team/                              # 唯一、长期存在的 AI 团队
│   ├── team.json                      # Team 身份和数据根绑定
│   ├── agents/                        # 七个长期 AgentProfile 与能力/容量
│   ├── knowledge/                     # 跨 Project 通用知识，只用于理解上下文
│   │   ├── documents/<id>/            # 原文件、规范化正文和不可变 manifest
│   │   └── selection.json             # 当前显式启用集合；修改无需重启
│   ├── specs/                         # 团队级强制开发规范
│   │   ├── documents/<spec_id>/       # 同一 spec_key 的不可变版本
│   │   └── activation.json            # 每个 key 至多启用一个版本
│   ├── skills/
│   │   └── learning-proposals/        # 人工批准的 Skill 设计建议；不会自动变成可执行 Skill
│   ├── model-policies/                # 模型路由和风险策略
│   └── work-items/ leases/ metrics/   # 团队级工作、租约和指标事实
├── projects/                          # 与 team/ 并列；一个目录一个 Project
│   └── <project_id>/
│       ├── project.json               # Project 身份及所属 Team lineage
│       ├── knowledge/                 # 仅属于该 Project 的业务背景知识
│       │   ├── documents/<id>/        # Project-bound 文档记录
│       │   └── selection.json         # 该 Project 的启用集合
│       ├── specs/                     # 项目级强制规范与持续学习事实
│       │   ├── documents/<spec_id>/   # Project Spec 不可变版本
│       │   ├── activation.json        # 当前启用版本集合
│       │   └── learning/<proposal_id>/ # QA/Review 建议、发布前授权及完成决策
│       ├── repositories/              # 该 Project 可使用的代码目录 catalog
│       │   └── <repository_id>/
│       │       ├── workspace.json      # 源码绝对路径与 Project/sidecar 绑定
│       │       ├── profile/ policy/    # RepositoryProfile、编译规范、Runtime binding
│       │       ├── state/ contexts/    # checkpoint、dispatch、恢复计划、角色上下文
│       │       ├── artifacts/ evidence/ # 结构化交接物和验证证据
│       │       └── runs/ locks/ logs/  # 模型运行、互斥和诊断记录
│       └── requirements/
│           ├── _console_operations/   # 浏览器操作状态链
│           ├── retirement.json        # 已删除/被编辑替换需求的完整性绑定可见性索引
│           └── <delivery_multi_id>/   # 一项 Requirement 的讨论、计划、子交付和联合验收
└── worktrees/                         # Coder、QA、Reviewer 的隔离 Git checkout
    └── <repository_id>/...
```

目录规则：

- `team/` 只有一个，拥有 Agent、通用知识、Skills 和团队规则；Project/Requirement 不复制成员。
- `projects/<project_id>` 是项目知识与交付隔离边界；一个 Team 可长期服务多个 Project。
- `knowledge/` 是描述性背景，不是强制规则；`specs/` 才是编译进 Requirement baseline 的强制规范。
  Team Spec 作用于所有 Project，Project Spec 只作用于所属 Project，还可按角色、阶段、Repository
  和路径声明适用范围。同一字段规则冲突时停止交付并交由人工处理。
- `repositories/<repository_id>` 只绑定源码位置，不复制源码；RepositoryProfile 或规范漂移会使旧批准失效。
- `requirements/<delivery_multi_id>` 保存一项 Requirement 的联合事实链；它可选择该 Project 下 1–N 个
  Repository，每个 Repository 仍拥有独立 Task、candidate 和验证报告。
- `worktrees/` 是平台管理的执行现场，不是备份目录。不得手工清空正在运行或待恢复的 worktree；
  干净现场由平台回收，失败/脏现场保留供诊断。
- Candidate 分支和提交属于目标 Git 仓库；通过 QA/Reviewer 后交付可合并分支，平台不自动 merge、push 或 deploy。
- MySQL 与整个 `<platform_root>` 共同构成可恢复状态，备份、迁移或清理时必须成套处理。

## 推荐的 v0.1 运行形态

v0.1 推荐先以一台可信的 macOS/Linux 主机运行，不必先部署 Kubernetes 或分布式服务：

- 一个常驻的 Python 3.12 `ase-console` 进程同时提供本地 Web Console、Project/知识/设置管理、只读
  团队投影和后台 Manager 操作执行；完成初始启动后，日常接入 Project、创建 Requirement、讨论、批准、恢复和
  领取交付都在网页完成；
- 一个独立 MySQL 8.0 实例保存事务和并发权威；本地可使用仓库提供的 Docker Compose，
  正式环境使用独立用户、强密码和持久卷；
- 一个位于所有源码仓库之外的持久 `<platform_root>` 保存唯一 Team、全部 Project/Repository sidecar、
  Requirement、Artifact、Evidence 和 worktree；macOS/Linux 缺省为 `~/.ase`；
- 目标仓库仍按自身语言和工具构建，平台只要求 Git、干净主 checkout、允许的本地构建/测试命令；
- Codex CLI 路由推荐以当前账号可用的 `gpt-5.6-terra` 为主；需要时可把 DeepSeek、Qwen 的
  Responses-compatible endpoint 加入可选模型池，再为具体 Agent 显式选择是否作为备用及其优先级；
- Coder、QA、Reviewer 使用同一 candidate commit 的独立 worktree，QA/Reviewer 不提交业务代码；
- Team 通用知识、Project 背景知识和 Spec 的创建/启停由 sidecar 即时提供给之后的新需求，无需重启；已准备
  Requirement 绑定精确版本，不会被静默重解释；运行配置改变仍需重启；
- SQLite 仅用于底层兼容命令和离线测试，不作为 `ase request` 生产入口的数据库。

推荐用仓库脚本管理后台进程，而不是长期占用一个终端：

```bash
./scripts/ase-console-service.sh start
./scripts/ase-console-service.sh status
./scripts/ase-console-service.sh logs
./scripts/ase-console-service.sh restart
./scripts/ase-console-service.sh stop
```

多个代码检出目录会共用默认的本机 Console 状态目录。启动器在 PID 记录中同时保存实际可执行文件；
从另一个已更新检出目录执行 `restart` 时，会先验证并停止原受管实例，再从当前目录启动，避免把正常
进程误报为 stale PID。真正无关或身份不匹配的进程仍不会收到信号。

浏览器提交的操作先以 append-only 事实保存为 `QUEUED`，后台执行时变为 `RUNNING`，最后变为
`SUCCEEDED`、`FAILED` 或 `INTERRUPTED`。Host 重启不会静默重放不确定的模型调用；用户在同一页面
按最新 durable delivery 事实“继续交付”。当前已具备后台进程形态，但自动随系统登录启动仍需要
macOS Keychain / Linux Secret Service 适配，不能把 MySQL DSN 明文写入 launchd/systemd 配置。

具体选择和理由见 [`docs/tech-stack.md`](docs/tech-stack.md)。

## 最新使用方法

日常主流程只有四步：**选择或创建 Project → 创建 Requirement 并选择代码目录 → 与 Product Agent
讨论并批准 → 观察执行并领取候选分支**。
浏览器会携带 exact checkpoint、恢复范围和恢复计划身份，不需要复制 JSON、delivery ID 或 SHA。

### 1. 首次启动服务

在平台源码仓库后台启动本地 Web Console：

```bash
./scripts/ase-console-service.sh start
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。服务只监听 loopback，并校验 Host 和
Origin；它不是可直接暴露到局域网或公网的多用户系统。用 `status` 查看状态、`logs` 跟踪日志、
`restart` 重启、`stop` 停止。关闭或刷新网页不会取消已接纳的后台工作。

### 2. 在网页准备 Team、Project、知识和规范

首次进入当前环境时：

1. 打开“设置”。没有配置文件时页面展示内置默认值；按需修改平台数据目录、完整 MySQL DSN、
   模型路由/API Key、七个 Agent 各自的主模型、可选备用模型与优先级、Codex、真实模型开关和 Console 端口。
   先测试 MySQL 连接，再保存；页面显示
   “需要重启”时，在保存结果弹窗点击“应用配置”重启 Web Console；如果浏览器或托管进程不可用，再执行
   `./scripts/ase-console-service.sh restart`。保存与应用是两个可审计动作，密钥仍只写入受限的 `runtime.env`。
2. 打开“状态”，确认 MySQL、Codex、Team workspace 和启用的模型路由已经就绪。“Agent 模型路由”
   按团队固定顺序展示七名成员各自的主模型、备用顺序、Reasoning 和就绪情况；这是当前配置状态，
   不表示 Agent 正在调用模型。“可用模型目录”用于检查底层 Provider/凭证。Team 没有知识文档是
   正常状态，不会被标记成故障。
3. 打开“需求与交付”，在本页创建或选择 Project。Project 表示一组长期共享业务背景、知识和开发
   规范的项目，不等于单个 Git 仓库，也不等于一次 Requirement；同一 Project 可以登记多个代码目录。
4. 打开“知识库”，先选择独立的“团队知识库”或“项目知识库”，再选择内容类型。团队知识库只维护
   一份，不挂在任何 Project 下面；项目知识库会要求选择具体 Project：
   - 团队“通用知识”与项目“背景知识”：页面默认只展示已导入资产；点击对应导入按钮，在弹窗中一次
     选择多份跨 Project 共享知识或当前 Project 的业务背景、术语和架构说明。支持 Markdown、TXT、
     PDF、DOCX。
   - “开发规范”：页面默认只展示现有规范；点击“导入开发规范”，在弹窗中批量选择 Markdown/TXT，
     并配置适用角色、阶段、Repository、路径和可选验证方法。稳定 `spec_key` 由平台根据文件名生成并在
     后续更新中复用，不需要用户填写。创建只生成未启用的新版本，检查后必须显式启用。
   - “学习改进”只在项目知识库出现：扫描当前 Project 已持久化的 QA FAIL 与 Review REJECT，查看复发次数和证据；
     人工可拒绝，或批准沉淀为背景知识、Project Spec 或非执行性的 Skill 设计建议。
5. 背景知识和 Spec 启停会立即用于之后的新需求，不需要重启；已经准备或批准的需求不会被静默套用
   新版本。绑定事实变化时会安全停止并要求重新准备；Team、Project 或 Repository 规则冲突时由人工决策。

是否重启以“是否改变进程基础依赖”为准：

| 操作 | 是否重启 |
|---|---|
| 上传/启停 Team 通用知识或 Project 背景知识、创建/启停 Spec、处理学习改进、创建/切换 Project | 不需要 |
| 修改平台数据目录、MySQL DSN、模型路由/API Key、Agent 模型策略、Codex 路径、真实执行开关或端口 | 需要；页面会显示“需要重启” |

单文件原始大小上限为 10 MB，规范化正文上限为 256 KB。加密 PDF、无可提取文本、损坏文档、危险
文件名和超限内容都会安全拒绝。原始文档位于
`<platform_root>/team/knowledge/documents/<document_id>/` 或
`<platform_root>/projects/<project_id>/knowledge/documents/<document_id>/`，不写入平台源码或目标项目。
Spec 位于对应 scope 的 `specs/documents/<spec_id>/`，当前启用集合写入 `specs/activation.json`。

### 3. 日常需求交付主要在网页完成

创建、讨论、批准、执行观察和常规继续都在 Web Console 完成。遇到知识缺口时，当前版本没有单独的
Gap 审批表单：可信本机管理员使用需求详情中的“查看待确认的知识”表单（底层 API 也可作为运维入口），
批准 exact 解答后再点击“继续需求”。CLI `ase request resume` 仍保留为同一恢复动作的 break-glass/runbook
入口；所有人工解答、来源哈希和恢复都会进入标准审计记录。

1. 进入“需求与交付”，在同一页创建或选择 Project，再点击“新建需求”。填写 Requirement 名称，点击
   “选择代码目录”打开系统目录弹窗，一次选择一个或多个本地目录；选中的绝对路径会显示为可移除标签，
   无需手工输入。一个 Requirement 可以覆盖同一仓库的多个模块，也可以跨多个 Git 仓库。
2. Manager 将这些目录注册为该 Project 的 Repository，建立外置 sidecar、发现 RepositoryProfile
   并编译 Team + Project + Repository 规范。操作卡片
   显示“已接单/执行中/成功/失败”；完成后点击“打开需求工作区”。
   Product 对话开始前，可在需求详情中编辑名称/目录；ProductSpec 批准前都可以逻辑删除需求。
   编辑会生成新的不可变需求版本并保留旧记录，删除只从当前 Project 列表中移除，不擦除对话和
   审计历史；需求删除后，其派生仓库 Task 也会同时退出团队成员的当前任务队列。Product 对话开始后
   不允许改写已绑定的需求，需创建新 Requirement。每个 Requirement 会保留独立、只读的代码基线；
   即使主分支之后合入其他需求或工作目录更新，旧需求仍从自己的基线继续。只有该基线提交或 worktree
   损坏时才会安全停止并提示恢复；最终 Review 通过后的合并冲突在合入最新目标分支时处理。
3. 在需求详情中和 Product Agent 多轮讨论，可输入文字，也可直接在输入框粘贴最多 4 张 PNG、JPEG 或
   WebP 截图。Product Agent 的追问和你的每次回复都会保存在同一条时间线中；截图会绑定当前
   Requirement/checkpoint，只提供给 Product Agent。ProductSpec 准备好后先阅读“阶段产物”：内容仍需
   调整就继续讨论，确认范围和验收标准后再点击“批准 ProductSpec 并开始交付”。
4. Designer、Planner 和每个 Repository 的 `Coder → QA → Reviewer` 串行工作。Manager 先执行 PlanningGate：
   SIMPLE 计划不调用 Planner 模型，COMPLEX 才生成有界 Planner 工作包；实际派发仍由 Manager 按当前事实
   重新校验。团队成员页只把当前岗位
   标成执行中，其他岗位显示已完成或等待；Manager、Product、Designer、Planner 的 Requirement 阶段
   也会进入各自任务队列，不再等到 Coder Task 创建后才出现。每列使用紧凑的需求任务概览卡，点击
   整张卡可查看模型、完整目录和执行时间线。需求页同时展示涉及的所有目录和后台操作；交付流程区
   只显示七个节点状态，不重复显示 Manager 运行文案。

网页每 5 秒读取 durable facts。提交后可以刷新、关闭页面或稍后回来；同一浏览器动作使用幂等键，
同一 Delivery 同时只接纳一个活动操作。

### 4. 中断、失败和人工门禁

需求详情中的“继续交付”统一处理 Product、Designer、Planner、Coder、QA、Reviewer 和联合验收阶段：

- 普通中断从最近 checkpoint 继续，已完成阶段和仓库不会重跑。
- Candidate 已存在但 QA/Reviewer 未完成时，页面展示 exact 候选验证计划；阅读 Agent、模型和
  candidate 后点击“批准并继续”，不会重跑 Coder。
- Coder 无 Candidate 但保留了修改时，如果现场含原需求未授权的文件，页面先逐条展示具体路径并
  要求一次“补充文件范围”审批；这里只批准本次恢复读取这些精确路径，不批准目录或通配符。
  随后页面展示包含实际修改的 exact 恢复计划并要求第二次审批，之后才创建新的关联 Task 接续；
  路径或现场变化会使旧审批失效，未知半成品不会直接进入 QA。
- QA FAIL 或 Reviewer REJECT 会保留旧 Candidate 和证据，创建修复 Task，重新执行
  `Coder → QA → Reviewer`。
- QA 只有 `NOT_TESTED`/命令环境 `ERROR`、没有任何验收项或测试 `FAIL` 时，不再误派给 Coder；
  Candidate 会保留，继续交付只创建新的 QA/Reviewer 验证计划。
- 显式 deny、规范冲突、来源漂移或业务歧义仍会停止并要求人工处理；网页不会偷偷放宽制度。
- 如果 Host 在操作执行中退出，该 Web Operation 会标记为 `INTERRUPTED`。重新启动服务后打开需求，
  依据当前 Delivery 事实再次点击“继续交付”，不会盲目重放原模型调用。
- 失败或中断的操作提示可以关闭；浏览器会记住关闭状态，同一需求的同类动作后续成功时也会自动
  隐藏旧失败提示。关闭只影响界面，Operation 和失败证据仍保留用于审计。
- 阻塞原因统一收口在需求详情的“阻塞信息”，按当前阻塞、最近恢复结果和建议操作展示；页顶操作卡
  只提供“打开需求工作区”入口，任务队列和需求列表不重复铺陈同一段阻塞文本。
- 阻塞需求可显式关闭或删除。关闭会停止继续交付，进入“已关闭”清单并保留需求与全部交付历史；后续
  可点击“重新启动需求”将它恢复为待继续状态，再显式继续交付。删除会让需求及其派生 Task 同时退出
  当前 Project 和 Agent 队列；底层 checkpoint、Task sidecar 和证据仍只作为审计记录保留。

### 5. 领取交付结果

需求进入 `DONE` 后，“交付结果”列出每个改造目录对应的 Candidate commit、可定位时的 Candidate
branch，以及 QA/Reviewer/联合验收证据入口。人工确认后，仍按目标项目自己的 PR、保护分支、联调、
发布和回滚流程交付。v0.1 不自动 merge、push 或 deploy，也不会切换目标项目当前 checkout。

### 一次性配置

准备 Python 3.12+、uv、Git、MySQL 8.0 和已登录的 Codex CLI，然后执行 `uv sync`。配置文件不存在
或 MySQL 尚未配置时，Web Console 仍以 setup 模式启动，并在设置页展示稳定默认值；这时交付入口
返回“待配置”，不会启动 Agent。第一次保存会创建默认路径
`~/.config/ai-software-engineer/config.json` 及同目录 `runtime.env`。

设置页允许直接填写完整 MySQL DSN 和 Responses provider API Key；输入框留空表示保留原值，后端
只返回已配置状态，不返回正文。当前可信本机 MVP 将这些运行变量以权限 `0600` 明文保存在
`runtime.env`，启动脚本会自动加载；不要提交或共享该文件。未来可换成 Keychain/Secret Service，
不改变页面工作流。完整 MySQL、模型 fallback 和配置边界见
[生产配置指南](docs/production-setup.md)。

`verify-*`、`request resume` 和底层 Task Runtime 仍作为诊断/break-glass 能力保留，不是日常用户
流程。详细断点矩阵见 [CLI 手册](docs/cli.md) 与
[恢复规范](.trellis/spec/core/delivery-recovery.md)。

<details>
<summary>运维与诊断：兼容 CLI 流程</summary>

以下命令用于部署验证、逐条审计和 Web Console 不可用时的 break-glass 操作。日常使用无需保存
`delivery_id` 或 `checkpoint_sha256`。

### 1. 首次配置（只做一次）

准备 Python 3.12+、uv、Git、MySQL 8.0 和已登录的 Codex CLI：

```bash
uv sync
uv run ase --version
codex login status
```

复制并修改配置：

```bash
mkdir -p "$HOME/.config/ai-software-engineer"
cp config/production.example.json "$HOME/.config/ai-software-engineer/config.json"
```

配置时：

- 连接 MySQL：设置 `ASE_MYSQL_DSN`。
- 配置数据目录：macOS/Linux 可省略 `platform_root`，稳定使用当前用户的 `~/.ase`；如需自定义，必须使用所有代码目录之外的安全绝对路径。
- 启用模型：将 `live_model_execution` 设为 `true`，并把第一个启用路由改成当前可用模型。

配置文件至少确认以下字段；`platform_root` 未列出时使用上述默认值：

```json
{
  "team_id": "team_ai",
  "team_name": "AI Team",
  "live_model_execution": true
}
```

知识选择由 Web Console 写入 Team/Project sidecar；配置中的旧 `*_knowledge_paths` 字段仅供兼容入口，
新部署无需填写。

再为当前 shell 设置 MySQL DSN；配置放在其他位置时同时设置 `ASE_CONFIG`：

```bash
export ASE_MYSQL_DSN='mysql+pymysql://USER:PASSWORD@127.0.0.1:3307/DATABASE'
export ASE_CONFIG='/absolute/path/to/production-config.json' # 使用默认配置路径时可省略
```

把配置中的第一个已启用 `model_routes` 改成当前实际可用模型（推荐 Codex CLI 的
`gpt-5.6-terra`）。密钥和 DSN 正文只放环境变量。完整 MySQL、模型 fallback 和安全配置见
[生产配置指南](docs/production-setup.md)。

### 2. 日常使用：创建、讨论、确认

兼容 CLI 入口要求配置 `default_project_id` 与 `default_project_name`；日常网页流程不需要默认 Project。

**① 创建 Requirement。**一个 Requirement 可以传一个目录，也可以同时传多个不相邻仓库/模块：

```bash
uv run ase request create /absolute/path/to/project-a /absolute/path/to/project-b \
  --name "你的需求名称"
```

平台会注册项目、建立外置 sidecar、发现 RepositoryProfile 和项目规范。成功输出
`stage=READY_FOR_DISCUSSION`；这一步不调用模型。若规范冲突或源码 HEAD 发生变化，先处理冲突，
不要拿旧 checkpoint 强行继续。

**② 讨论需求。**将 `DELIVERY_ID` 和 `CHECKPOINT` 替换为上一步输出值：

```bash
uv run ase request discuss DELIVERY_ID \
  --checkpoint CHECKPOINT \
  --message "描述你要解决的问题、期望结果，以及已知的限制和验收要求"
```

Product Agent 如有问题就继续执行 `discuss`；每次必须使用最新 checkpoint。输出中的
`dialogue` 是澄清记录，`product_spec` 是待评审产品文档。

**③ 批准产品文档并启动交付。**只有看到 `WAITING_PRODUCT_APPROVAL` 且范围、验收标准正确时执行：

```bash
uv run ase request approve DELIVERY_ID --checkpoint CHECKPOINT
```

这一步开始消耗模型额度。平台继续生成 TechnicalDesign、ExecutionPlan，为每个仓库执行
`Coder → QA → Reviewer`，最后做多仓联合验收。正常路径无需手工创建 Task、Agent 或 worktree。

### 3. 查看进度和拿到结果

命令行查看当前 checkpoint：

```bash
uv run ase request status DELIVERY_ID
```

若平台进程意外退出且没有并发执行者，再继续 durable checkpoint：

```bash
uv run ase request resume DELIVERY_ID
```

另开一个使用同样 `ASE_CONFIG`/`ASE_MYSQL_DSN` 的终端可启动只读工作台：

```bash
uv run ase team serve --port 8765
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)，查看 Agent 当前任务、涉及目录、阶段、
模型调用、阻塞原因和 QA/Review 报告。页面只读；它显示 durable facts，不承诺后台进程在线。

- **需要你回答或确认**：按 `checkpoint.next_action` 操作。
- **中断或阻塞**：先看 `next_action` 和失败证据；`resume` 不会掩盖规范冲突或失败 verdict。
- **Coder 单次运行未完成**：平台保存 `coder-progress`，自动执行
  `CONTINUE_REQUIRED → QUEUED → IMPLEMENTING`；若最终无 candidate 但 worktree 有保留修改，
  `resume` 会生成精确恢复计划，批准后创建新 Task 接续，半成品不会直接进入 QA。
- **DONE**：`children` 给出各仓 candidate commit，`integration` 给出联合验收；人工复核后按原项目流程合并。

平台不会自动合并、推送或部署，也不会把候选代码自动切换到目标项目当前分支。
日常接单不需要 `ase task ...` 底层 Runtime，也不需要手工准备 sidecar、Agent 或 snapshot。

### 4. 中断或失败：日常只使用 `resume`

无论停在 Product、Designer、Planner、Coder、QA、Reviewer 还是多仓联合验收，先执行同一个命令：

```bash
uv run ase request resume DELIVERY_ID
```

平台读取 MySQL、sidecar、Git 和不可变 checkpoint，只执行下一项尚未完成且已获授权的工作：

- 普通进程中断：直接从最近 checkpoint 继续；已完成的阶段和仓库不会重跑。
- Dispatch 已创建 Task、但 Runtime 尚未接纳任何 Agent 时：若 Task 仍是
  `NEW / revision 0 / candidate=null`，直接重入 Delivery；这不是 Coder 失败，不需要恢复计划。
- Coder 尚无 candidate、失败 worktree 存在修改：自动定位失败 Run/Context；若存在遗漏授权的文件，
  先返回 `SCOPE_APPROVAL_REQUIRED` 和精确路径，使用 `--approve-scope` 批准本次恢复范围后才捕获内容；
  随后返回精确恢复计划，批准后创建新 Task 接续旧修改，再走 `Coder → QA → Reviewer`；新的恢复/修复 Coder 若再次中断，
  继续执行同一个 `resume`，平台会沿完整 Task/dispatch 历史创建下一次恢复，而不是卡死在第一轮。
- Coder 已产生 candidate、QA/Reviewer 因额度或进程故障中断：先返回一个精确验证计划，**不会重跑 Coder**。
- QA FAIL 或 Review REJECT：保留 Candidate V1 和原失败 Task，自动创建关联修复 Task，再走
  `Coder → QA → Reviewer` 得到 Candidate V2。
- 已完成 Task、checkpoint 尚未来得及写入：从 Task event 和 sealed artifacts 接管，零模型调用。
- 规范冲突、需求歧义、权限/来源漂移：返回明确人工 gate，不会偷偷放宽规则。

当输出为 `SCOPE_APPROVAL_REQUIRED` 时，先核对列出的每个遗漏文件路径，再批准该精确范围：

```bash
uv run ase request resume DELIVERY_ID \
  --approve-scope SCOPE_SHA256 \
  --approval-reference "human-approved-exact-file-scope"
```

这一步只允许平台安全捕获保留现场，不能启动 Agent。随后输出
`VERIFICATION_APPROVAL_REQUIRED` 或 `RECOVERY_APPROVAL_REQUIRED` 时，检查返回的 plan
文件，确认 Agent、模型、candidate/保留修改和目录范围后，用输出中的完整摘要批准并继续：

```bash
uv run ase request resume DELIVERY_ID \
  --approve-plan PLAN_SHA256 \
  --approval-reference "human-approved-delivery-plan"
```

如果某个已批准的模型调用结果不确定，平台不会重复调用同一 Run；下一次 `resume` 会生成新的验证
计划并再次要求确认。`verify-propose / verify-inspect / verify-approve / verify-run` 仍保留给诊断和
break-glass 操作，日常交付不需要手工串这四个命令。

低层 [失败 Coder 接手流程](docs/cli.md#显式接手失败-coder-的保留修改) 和 `verify-*` 仍保留给
诊断与逐条审计；日常流程不需要切换命令。未知半成品不会被自动视为正确实现，`resume` 只负责
封存并展示精确恢复计划，仍需人工批准后才能交给新的 Coder Task。详细断点矩阵见
[CLI 手册](docs/cli.md) 与 [恢复规范](.trellis/spec/core/delivery-recovery.md)。

</details>

## 开发与验证

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build --offline
```

MySQL 集成测试需设置 `ASE_TEST_MYSQL_DSN`，并且必须指向名称为 `test_*`、`*_test` 或
`*_tests` 的专用测试数据库（例如 `ase_self_iteration_test`）。pytest 会在任何 MySQL fixture
执行前拒绝生产库名称，并在每个 `mysql` 用例前后统一清理 Task/事件、调度、验证预留和工作队列
事实；测试或 fixture 失败也会执行清理。表结构、锁行及无关表保留。每个并发 pytest 进程/worker
必须使用不同的测试数据库，不能共用这个会被清理的 schema。测试使用脚本化模型验证契约，
不代表真实模型已完成业务验收。

## 当前进度（2026-09-19）

| 阶段 | 阶段性成果 |
|---|---|
| M0–M2 平台基础 | 完成架构、强类型契约、状态机、Artifact、Context 和 Git 隔离 |
| M3–M4 串行交付 | 完成底层 `Coder → QA → Reviewer`、有界恢复、Evaluation/ADR 与 Handoff 组件；不等于生产入口已启用全部能力 |
| M5 团队与项目接入 | 完成 Team-owned Workforce、确定性调度算法、RepositoryProfile、SpecCompiler 和外置 sidecar |
| M6 可执行与可审计 | 完成受控命令、typed tools、Evidence、跨语言边界和只读 API |
| M7 团队可视化 | 本地只读团队工作台，跨 Project 读取 Requirement、成员分配、涉及目录、执行历史和报告；旧静态组件保留为底层工具 |
| M8 接单与推进 | 接通 Product、Designer、Planner、原子 dispatch 和可恢复 CLI 入口；产品批准与必要澄清仍由人工完成 |
| M9 Production Team Host | 完成命令级自动装配、MySQL 存储、配置驱动的模型路由与隔离交付；Coder 支持有界 checkpoint/续跑，真实模型验收需另行执行 |
| M10 知识与联合交付 | Team 通用知识、Project 专属知识按需加载；Requirement 先准备后讨论；多 Repository 独立交付、联合候选验收与中断恢复 |
| M11 持续团队与候选提交 | 七个 Team 级长期成员；显式 CandidateCommit Skill；CoderProgress Artifact；可重启的有界 Coder 续跑循环 |
| M12 持久工作队列 | MySQL Run 级 WorkItem、确定性 Dispatcher tick、原子 Assignment/Lease/ModelSelection、owner-fenced 心跳/完成/等待/重试/过期回收；`ase request` 兼容入口仍是串行 RuntimeSession，逐角色 Worker 集成尚未完成 |
| M13 候选复核恢复 | 对已有 Coder candidate 提供 `verify-propose / inspect / approve / run`；使用独立 QA/Reviewer allocation、Lease 和 worktree，保留原失败 Task 与联合需求历史，不自动 merge/push/deploy |
| M14 统一恢复与自动修复 | `request resume` 统一接管现有持久化阶段；候选复核可由同一入口批准和续跑；QA FAIL/Review REJECT 创建确定性修复 Task 并重新走 Coder→QA→Reviewer；看板显示验证与修复工作；终态 Task 可零调用补写 Delivery checkpoint |
| M15 Web 交付控制台 | 浏览器完成 Project 选择、Requirement 创建、Product 对话与批准、统一继续/精确恢复计划批准和候选领取；操作先写入 Team sidecar，再由后台 Manager 执行，页面刷新不丢单；CLI 降为运维和 break-glass 入口 |
| M16 平台管理面 | 浏览器创建/选择 Project，分别管理内容寻址的 Team 通用知识与 Project 知识，并维护平台目录、MySQL、模型路由、Codex、执行开关和端口；知识选择即时生效，运行配置变化明确要求重启 |
| M17 Team–Project 边界 | 将唯一 Team 与多个 Project 设为并列聚合；Project 管理知识、规范、Repository 和 Requirement；增加 Web Console 后台启动、停止、重启、状态和日志脚本 |
| M18 运行设置与状态 | Web Console 可零配置降级启动，展示内置默认值；设置页写入完整 MySQL DSN/Responses API Key，服务脚本加载受控 `runtime.env`；独立状态页显示 MySQL、Codex、Team、知识和模型路由就绪情况；知识管理不混入设置页 |
| M19 Spec Center 与持续学习 | 通用/背景知识与强制 Spec 分离；Team/Project Spec 支持不可变版本、显式启用、适用范围和验证方法，并进入 production baseline/context；QA/Review 失败可生成证据化 Learning proposal，经人工审批后沉淀为背景知识、Project Spec 或非执行性 Skill 设计建议 |
| M20 需求输入与 Agent 模型策略 | 新建 Requirement 使用 macOS/Linux 原生目录选择器；Product 对话支持有界、不可变、可追溯的截图附件；七个长期 Agent 可分别配置主模型与备用顺序，运行事实保留实际选择 |
| M21 知识导入与路由状态 | 知识库改为资产列表优先，通用知识、背景知识和开发规范通过作用域明确的弹窗批量导入；状态页分别展示七名 Agent 的精确模型策略与底层可用模型目录 |
| M22 需求维护 | Product 对话开始前可编辑 Requirement 名称与代码目录，ProductSpec 批准前可逻辑删除；编辑发布替代需求、删除只改变当前可见性，旧 checkpoint、对话与 Operation 继续保留审计；代码基线漂移时停止无效恢复并预填新 Requirement；失败提示可关闭但不擦除事实 |
| M23 规划分流（T047） | Manager PlanningGate 根据结构化 Product/Design 事实选择 SIMPLE/COMPLEX；SIMPLE 零 Planner 模型调用，COMPLEX 计划保留工作包、依赖、风险、检查点和验收测试矩阵 |
| M24 主动知识闭环（T048） | 冻结 Team/Project/Repository 适用知识与规范，提供带证据的 typed search/read、预算化 Context consultation、exact Gap/Resolution 恢复和独立 Learning 发布审批 |
| M25 增量索引（T049） | 上传异步进入 QUEUED/PROCESSING/READY/FAILED/RETIRED 生命周期；增量缓存、原子发布、替换/退休互斥、失败重试和 Web 状态页已覆盖 |

## 文档导航

- [分类索引](docs/README.md)：使用、运维、架构、协议、开发、决策与历史。
- [生产部署与配置](docs/production-setup.md)、[团队工作台](docs/visualization.md)。
- [总体架构](docs/architecture.md)、[角色与 Artifact 契约](docs/contracts.md)。
- [当前路线与待验收事项](docs/milestones.md)、[工程任务索引](.trellis/tasks/README.md)。
- [历史归档与交付证据](docs/archive/README.md)。
- [工程规范](.trellis/spec/index.md)、[领域术语](CONTEXT.md)、[Codex 开发指引](AGENTS.md)。
