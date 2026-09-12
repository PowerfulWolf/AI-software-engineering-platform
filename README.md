# ai-software-engineer v0.1

一个基于 Trellis 思想与 Multi-Agent 协作的、可审计的通用 AI 软件工程团队平台。

团队不绑定某家公司、业务领域或技术栈。你提供项目目录和需求，团队学习对应项目的规范后开展工作；
同一支 Agent 团队可以服务不同项目，项目之间的知识、上下文和交付记录保持隔离。

它的目标不是演示多个 Agent 互相对话，而是逐步建立一个有制度、有岗位边界、有组织记忆、
能够持续交付和自我改进的数字研发团队。

> 先为一个需求选择一个或多个代码目录，平台准备好项目规范后再与你聊需求。你确认产品文档后，团队按仓库执行 `Coder → QA → Reviewer`，最后联合验证，交付候选提交和证据，或明确的阻塞原因。

## 设计原则

1. **Knowledge belongs to the organization, not the agent**：规则、设计决策、失败经验和验收标准沉淀在 `.trellis/` 与任务 artifact 中；Agent 是可替换的执行者。
2. **No agent may be the sole judge of its own work**：Coder 不能批准自己的代码；同一 Task 历史
   的 Coder、QA、Reviewer 必须是不同 Agent，并使用独立 Run、Context、worktree 和受限权限。
3. **Agents communicate through verifiable artifacts, not shared assumptions**：跨角色传递只允许使用经过 Schema 校验、带来源 revision、证据和哈希的 artifact。
4. **Task 内串行，组织层有界调度**：每个 Task 仍按 `Coder → QA → Reviewer` 串行；组织可以在
   容量约束下分配多个相互隔离 Task，不引入单 Task 复杂 DAG、共享会话或外部分布式队列。
   T046 提供 MySQL PersistentWorkQueue、确定性 Dispatcher tick 和 owner-fenced Lease 生命周期；
   一次队列项只代表一个可执行角色 Run，不提前占用尚未开始的 QA/Reviewer。

## MVP 边界

输入：

- 一个或多个已有本地代码目录，可以属于同一仓库、不同仓库或不同业务项目（当前交付使用 Git）；
- 一条自然语言需求；Product Agent 将其整理为可评审 Product Spec，并由用户确认；
- 组织通用知识/AgentProfile/ModelPolicy，以及项目自身规范（由 sidecar 只读索引）。

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

平台由通用知识库、可切换的工作知识库和组织长期拥有的 Agent 团队组成。
当前实现用 Company sidecar 收纳服务对象的共享知识、项目知识子模块和需求记录，
它是知识与工作记录的隔离边界，不是把团队绑定到某家公司的产品限制。
Agent 通过受控 Skills 调用确定性能力。用户先选择项目目录，Project Manager Agent
完成项目准备；准备成功后，用户再与 Product Agent 讨论需求。后续由专业 Agent 按制度完成产品
定义、技术设计、执行规划、开发、测试和审查，最后把可合并候选或明确阻塞证据交给人类。

下图是当前控制平面边界。浏览器只提交 typed intent；Web Console 先把操作写入 Company sidecar，
再由后台 Project Manager 执行，因此刷新或关闭网页不会重复或取消已接纳的工作。Planner 对流转
和派发策略负责；Dispatcher 负责不依赖模型额度的有界轮询、领取事务和过期恢复，持有 Lease 的
Worker 负责启动、心跳与结果提交。正常状态按已批准规则推进，只有计划漂移、连续失败、资源冲突
或人工门禁才重新启动 Planner Agent。

```mermaid
flowchart TB
    U["用户<br/>浏览器中创建、讨论、批准、继续"] --> WEB["Local Web Console<br/>typed intent · durable operation"]
    WEB --> OPS[("Company sidecar<br/>QUEUED → RUNNING → terminal")]
    OPS --> PM["Project Manager Agent<br/>团队领导"]

    PM --> ONBOARD["Project Preparation<br/>注册外置 workspace<br/>发现 ProjectProfile<br/>编译项目级规范"]
    ONBOARD --> READY["Project Prepared<br/>项目上下文与安全边界就绪"]
    READY --> PRODUCT["Product Agent<br/>与用户澄清需求、维护需求对话"]
    U -. "准备完成后讨论需求" .-> PRODUCT
    PRODUCT --> PRODUCT_SPEC["Product Spec<br/>目标、范围、需求、验收标准"]
    PRODUCT_SPEC --> PRODUCT_REVIEW["Human Product Review<br/>可信人工通道验证 exact spec ID + digest"]
    PRODUCT_REVIEW --> DESIGNER["Solution Designer Agent<br/>技术方案与实施规划"]
    DESIGNER --> TECH_DESIGN["Technical Design<br/>架构、步骤、测试策略、风险"]
    TECH_DESIGN --> PLANNER["Planner Agent<br/>整体执行计划、能力与风险需求"]
    PLANNER --> EXEC_PLAN["Execution Plan<br/>阶段、检查点、角色与 BrainTier 需求"]
    EXEC_PLAN --> PLAN_SKILLS["Planner Skills<br/>Queue inspection · dispatch planning<br/>result routing · reprioritize"]
    PLAN_SKILLS --> QUEUE[("MySQL PersistentWorkQueue<br/>一个 WorkItem = 一个角色 Run")]
    QUEUE --> DISPATCHER["Dispatcher Service<br/>有界 tick · 原子领取 · 过期回收"]
    DISPATCHER --> ENGINES["Deterministic Skills<br/>PortfolioScheduler · ModelRouter"]
    ENGINES --> LEASE["RoleAssignment + TaskLease + ModelSelection<br/>owner token 只保存 digest"]
    LEASE --> RUNNER["Agent Runner<br/>独立 Context + role worktree"]

    RUNNER --> CODER["Coder<br/>实现、测试、checkpoint 或 candidate"]
    RUNNER --> QA["QA<br/>独立验证"]
    RUNNER --> REVIEWER["Reviewer<br/>独立审查"]
    CODER --> ORCH["Result Handler / Task Orchestrator<br/>校验 Artifact · 推进 Task"]
    QA --> ORCH
    REVIEWER --> ORCH
    ORCH -- "原子关闭当前项并发布下一项" --> QUEUE
    ORCH -- "需要人工或依赖" --> WAIT["WAITING_HUMAN / WAITING_DEPENDENCY<br/>立即释放 Lease"]
    WAIT -- "可信恢复信号" --> QUEUE
    ORCH -- "无安全继续路径" --> STOP["Task BLOCKED / FAILED<br/>保留现场与证据"]

    ORCH -- "各仓 APPROVE" --> JOINT["联合验收<br/>完整候选集合 · 实际集成测试"]
    JOINT -- "PASS" --> DELIVERY["Delivery<br/>各仓 candidate SHA + artifacts + 联合验收证据"]
    JOINT -- "FAIL" --> STOP
    DELIVERY -. "后续扩展" .-> REPORTER["Reporter（暂不开发）<br/>后续按需组织交付视图"]

    COMMON_KNOWLEDGE["Organization Knowledge<br/>通用规范 · Skills · 历史经验"] --> KNOWLEDGE["Knowledge Plane"]
    SIDECAR_KNOWLEDGE["Company Sidecar<br/>公司知识 · 项目子模块 · 需求记录"] --> KNOWLEDGE
    KNOWLEDGE --> PM
    KNOWLEDGE --> PRODUCT
    KNOWLEDGE --> DESIGNER
    KNOWLEDGE --> PLANNER
    KNOWLEDGE --> ORCH
    KNOWLEDGE --> RUNNER
    ORCH --> FACTS["Durable Facts<br/>StateEvent · Context · Artifact · Evidence"]
    FACTS --> VIEW["Read-only Projection<br/>从真实记录生成团队与交付视图"]
    VIEW --> WEB
    REPORTER --> HUMAN["Human Boundary<br/>合并、冲突决策、最终业务判断"]
    DELIVERY --> HUMAN
    STOP --> HUMAN
    VIEW --> HUMAN
```

模型路由引擎具备风险与能力约束，但当前生产 Host 使用配置中首个启用模型作为主模型，
默认策略对各风险等级采用同一档位；额度或临时故障时才按规则尝试备用路由。
这不是已经实现按任务难度自动选择不同成本/能力模型的完整策略。

### 各层只负责什么

| 层 | 核心职责 | 明确不能做 |
|---|---|---|
| Project Manager Agent | 团队领导；通过 prepare、advance、commit-dispatch、recover、deliver Skills 接单和推进整支团队 | 不能绕过 Skill 直接写状态、分配资源或批准代码 |
| Web Console command module | 接受浏览器 typed intent，先持久化 Operation，再异步委托 Project Manager；把 exact checkpoint/plan digest 隐藏在 UI 控件中 | 不能直接改 Task、Artifact、Git 或判定交付成功 |
| Product Agent | 与用户澄清需求，产出可评审、可追溯的版本化 Product Spec | 不能自己批准产品范围，不能持有人工决策验证权限，不能设计实现细节 |
| Solution Designer Agent | 把已确认 Product Spec 转换为 Technical Design 和实施/测试规划 | 不能改写产品需求，不能直接提交业务实现 |
| Planner Agent | 制定执行计划并拥有流转/派发策略；通过 QueueInspection、DispatchPlanning、ResultRouting、Reprioritize 等 typed Skills 决定下一步 | 不能亲自持有轮询、数据库锁、心跳或 Lease owner authority |
| Agent Skills | Agent 按角色调用的 typed、policy-bound 能力接口；把请求委托给确定性 service 并返回可验证结果 | 不是 Prompt 指令，不授予 ambient store/shell 权限 |
| PersistentWorkQueue | 在 MySQL 保存 Run 级 WorkItem、Assignment、Lease 和生命周期事件 | 不解释 Artifact，不修改 Task verdict，不保存模型会话 |
| Dispatcher Service | 持续执行 Planner 批准的规则；每次 tick 回收过期 Lease，并原子领取至多一个 Run | 不是 Agent，不依赖模型在线，不替 Worker 续约，不自行改变产品/技术计划 |
| Scheduler / ModelRouter engines | 为每个 Run 重新计算成员容量、独立性和模型选择 | 不能生成产品/设计内容，不能修改 Task verdict |
| Task Orchestrator | 按状态机串行推进一个 Task，校验 artifact 和 retry 条件 | 不能跳过 QA/Review，不能编写业务代码 |
| Agent Runner / Coder / QA / Reviewer | Runner 持有本次 Lease owner token 并负责 start/heartbeat/result；成员在独立 Context、worktree 和权限下完成岗位工作 | 不能共享隐式记忆，不能批准自己的工作，不能使用别人的 Lease 提交 |
| Knowledge + Evidence | 保存规范、上下文、artifact、命令、测试和模型使用证据 | 不能依赖某个 Agent 的临时会话 |
| Projection + Dashboard | 从 durable facts 重算团队和交付状态，向 Web Console 提供只读查询 | 只读，不能迁移状态或修改 verdict |
| Reporter（暂不开发） | 后续从已验证 artifact/Handoff 生成面向用户的交付表达 | 不能创造事实、改变 verdict 或隐藏失败 |
| Human Boundary | 处理规范冲突、业务歧义、保护分支合并与生产决策 | 人工动作必须留痕，不能静默改写历史 |

Project Manager、Product、Solution Designer、Planner、Coder、QA、Reviewer 都是组织 workspace
中持久化的长期成员；需求只产生 Assignment、Lease、独立 Context 和运行记录，不临时复制一套
AgentProfile。Scheduler、ModelRouter 和 Task Orchestrator 是这些成员调用的确定性能力，不作为
会聊天、会自我判断的新成员。

### 一个需求的实际流转

队列只发布“现在可以执行”的角色，不会在 Coder 开发时提前占用 QA 和 Reviewer：

```mermaid
flowchart LR
    PLAN["ExecutionPlan 已批准"] --> C1["Coder WorkItem<br/>READY"]
    C1 --> C_RUN["LEASED → RUNNING"]
    C_RUN -- "coder-progress" --> C_NEXT["关闭当前项<br/>发布后续 Coder WorkItem"]
    C_NEXT --> C1
    C_RUN -- "CandidateCommit" --> Q["QA WorkItem<br/>READY"]
    Q -- "FAIL + evidence" --> C_FIX["Coder Fix WorkItem<br/>READY"]
    C_FIX --> C_RUN
    Q -- "PASS" --> R["Reviewer WorkItem<br/>READY"]
    R -- "REJECT + findings" --> C_FIX
    R -- "APPROVE" --> DONE["Task DONE<br/>candidate SHA + evidence"]
```

如果 Task 已因额度、进程或基础设施故障终止但已经存在 candidate，Delivery 级恢复不会重开旧
Task：`resume → 独立候选验证 → PASS 则接纳；FAIL/REJECT 则创建关联修复 Task → 新 Candidate`。
因此“模型调用不能重复”和“需求必须继续完成”并不冲突：前者约束单个 Run，后者通过新的、可审计的
Run/Task 接续。

每个方框都是独立 `work_item_id`。同一 Task 可以产生多个 Coder/QA/Reviewer Run；每次 Run 都重新
经过 Scheduler 和 ModelRouter。续跑可设置 `preferred_agent_id` 保持上下文连续，但只有原成员仍具备
能力和容量时才优先；实际代码现场属于 Task branch/worktree，不属于 Agent 的临时会话。

### Lease 生命周期

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
│   ├── config/                       # ProductionConfig 与模型路由契约
│   ├── domain/                       # Task、Agent、Artifact、Workforce 强类型模型
│   ├── product/ design/ planning/    # Product、Designer、Planner 阶段及不可变记录
│   ├── project_manager/              # prepare、阶段门禁、dispatch、Team Host
│   ├── scheduling/ work_queue/       # Scheduler、ModelRouter、持久队列和 Lease
│   ├── orchestration/ agents/        # 串行状态机、角色请求与模型适配器
│   ├── context/ artifacts/ evidence/ # Context、Artifact、Evidence 的存储与校验
│   ├── git/ role_workspace.py        # 分支/worktree、角色权限与受控命令执行
│   ├── multi_directory/              # 多目录/多仓需求拆分和联合验收
│   ├── recovery/                     # Delivery 统一续跑、失败 Coder 接手、候选复核与修复接续
│   ├── store/                        # MySQL 生产事实；SQLite 底层兼容实现
│   ├── projection/ team_view/        # 只读投影与兼容组件
│   ├── web_console/                  # 浏览器命令、持久 Operation、Project Manager 适配和 HTTP Host
│   ├── evaluation/                   # 事件重放、ADR 和 Handoff
│   ├── tools/                        # role/run 绑定的 typed Skill 协议
│   ├── company_workspace.py          # Company sidecar、公司发现与知识选择
│   ├── knowledge_documents.py        # MD/TXT/PDF/DOCX 导入、规范化与不可变知识记录
│   ├── project_workspace.py          # 项目源码和外置 sidecar 的绑定
│   └── runtime_workspace.py          # Organization/Project/Runtime 组合
├── schemas/                          # 所有公开/持久化契约的 JSON Schema
│   ├── task.schema.json
│   ├── artifact.schema.json
│   ├── work-queue.schema.json
│   ├── delivery-recovery.schema.json
│   ├── candidate-verification.schema.json
│   ├── console-operation.schema.json
│   ├── knowledge-document.schema.json
│   └── recovery-execution.schema.json
├── tests/                            # 与 src 分层对应；含真实 Git/MySQL 和离线模型契约测试
├── docs/
│   ├── production-setup.md           # 完整部署与运维手册
│   ├── architecture.md               # 架构和边界
│   ├── cli.md                        # CLI 与恢复命令
│   ├── archive/                      # 阶段成果和提交证据
│   └── decisions/                    # 已接受架构决策
└── .trellis/
    ├── spec/                         # 组织在本项目沉淀的可执行开发规范
    ├── tasks/                        # PRD、Design、Implement 等任务事实
    └── workspace/                    # 开发会话记录；不是生产 sidecar
```

仓库中的 `src/` 是平台控制平面代码；运行平台后产生的数据不会写回这里，也不会写入目标项目。
`schemas/` 必须与 Python DomainModel 同步，`tests/` 覆盖对应边界，`.trellis/spec/` 记录以后所有
开发 Agent 都必须遵守的工程知识。

## Workspace 分工

平台运行涉及五类位置。它们必须保持分离，特别是 `<platform_root>` 不能位于任一目标 Git
仓库内，也不能与目标仓库互相包含。

| 位置 | 典型路径 | 职责与规范 |
|---|---|---|
| 平台源码仓库 | `/path/to/AI-software-engineering-platform` | `ase` 的实现、Schema、测试和 Trellis 规范；只在开发平台本身时修改 |
| 目标项目目录 | `/path/to/backend`、`/path/to/frontend` | 原项目源码、测试、构建配置和原生开发规范；必须是绝对路径、Git HEAD 已提交、开始时工作树干净；平台不在其中创建 `.ase` |
| 平台数据根 | `<platform_root>`；macOS/Linux 缺省为 `~/.ase` | 所有组织/公司 sidecar 和临时 worktree 的共同外置根；可显式配置绝对路径或安全的 `~/...` 路径，必须持久化、备份并限制访问权限 |
| MySQL | `ASE_MYSQL_DSN` 指向的 MySQL 8.0 | Task、StateEvent、dispatch、WorkItem、Assignment、Lease 等并发权威事实；不能与文件 sidecar 二选一，二者都要保存 |
| 配置与密钥 | `ASE_CONFIG` + 环境变量 | JSON 只保存路径、模型名和密钥变量名；DSN/API key 正文只放环境或 secret manager，不写入仓库/sidecar |

一个实际 `<platform_root>` 的职责如下：

```text
<platform_root>/
├── organization/                    # 团队本身：跨公司、跨项目长期存在
│   ├── organization.json
│   ├── agents/                       # AgentProfile：成员身份、能力、并发容量
│   ├── model-policies/               # ModelPolicy：允许模型和路由策略
│   ├── work-items/ leases/ metrics/  # 组织级文件契约/扩展位置
├── companies/<company_id>/           # 一家公司/知识域一个 sidecar
│   ├── company.json
│   ├── knowledge/                    # 公司公共知识；不会递归自动加载
│   │   └── documents/<document_id>/  # 原文件、规范化 content.md 与不可变 manifest
│   ├── requests/_console_operations/ # 浏览器操作的不可变状态链；不是 Task/Delivery 真相替代物
│   ├── projects/<project_id>/        # 每个已识别 Git 项目的 sidecar 子模块
│   │   ├── workspace.json            # 项目源码绝对路径与 sidecar 身份绑定
│   │   ├── profile/                  # ProjectProfile：语言、构建、VCS 发现事实
│   │   ├── knowledge/ policy/        # 项目知识、编译规范、Runtime binding
│   │   ├── state/                    # 阶段 checkpoint、dispatch、恢复/复核计划
│   │   ├── contexts/ artifacts/      # 各角色明确输入和结构化输出
│   │   ├── evidence/ evaluations/    # 命令、测试、diff、模型使用和评估证据
│   │   └── runs/ locks/ logs/        # 模型路由记录、互斥和诊断日志
│   └── requests/<delivery_multi_id>/ # 多目录需求的产品/设计/计划/子交付/联合验收
└── worktrees/<project_id>/           # Coder、QA、Reviewer 的隔离 Git checkout
```

目录规则：

- `organization/agents` 中的成员由组织拥有，需求只创建 Assignment/Lease，不为每个项目复制 Agent。
- `companies/<company_id>` 是知识隔离边界；换公司时切换 sidecar，公司内所有项目作为子模块收纳。
- `projects/<project_id>` 不复制源码；ProjectProfile 和规范引用发生漂移时旧批准失效，冲突交给人工处理。
- `requests/` 保存跨仓需求的一份联合事实链；每个子项目仍拥有自己的 Task、candidate 和验证报告。
- `worktrees/` 是平台管理的执行现场，不是备份目录。不得手工清空正在运行或待恢复的 worktree；
  干净现场由平台回收，失败/脏现场保留供诊断。
- Candidate 分支和提交属于目标 Git 仓库；平台不自动 merge、push 或 deploy。
- MySQL 与整个 `<platform_root>` 共同构成可恢复状态，备份、迁移或清理时必须成套处理。

## 推荐的 v0.1 运行形态

v0.1 推荐先以一台可信的 macOS/Linux 主机运行，不必先部署 Kubernetes 或分布式服务：

- 一个常驻的 Python 3.12 `ase-console` 进程同时提供本地 Web Console、公司/知识/设置管理、只读
  团队投影和后台 Project Manager 操作执行；完成初始启动后，日常配置、创建、讨论、批准、恢复和
  领取交付都在网页完成；
- 一个独立 MySQL 8.0 实例保存事务和并发权威；本地可使用仓库提供的 Docker Compose，
  正式环境使用独立用户、强密码和持久卷；
- 一个位于所有源码仓库之外的持久 `<platform_root>` 保存 organization、Company sidecar、
  Artifact、Evidence 和 worktree；macOS/Linux 缺省为 `~/.ase`，也可显式配置安全的绝对路径或 `~/...`；
- 目标仓库仍按自身语言和工具构建，平台只要求 Git、干净主 checkout、允许的本地构建/测试命令；
- Codex CLI 路由推荐以当前账号可用的 `gpt-5.6-terra` 为主，路由顺序由配置决定；需要时显式配置
  DeepSeek、Qwen 的 Responses-compatible endpoint 作为备用，不能把禁用或占位路由当成自动降级；
- Coder、QA、Reviewer 使用同一 candidate commit 的独立 worktree，QA/Reviewer 不提交业务代码；
- SQLite 仅用于底层兼容命令和离线测试，不作为 `ase request` 生产入口的数据库。

浏览器提交的操作先以 append-only 事实保存为 `QUEUED`，后台执行时变为 `RUNNING`，最后变为
`SUCCEEDED`、`FAILED` 或 `INTERRUPTED`。Host 重启不会静默重放不确定的模型调用；用户在同一页面
按最新 durable delivery 事实“继续交付”。当前已具备后台进程形态，但自动随系统登录启动仍需要
macOS Keychain / Linux Secret Service 适配，不能把 MySQL DSN 明文写入 launchd/systemd 配置。

具体选择和理由见 [`docs/tech-stack.md`](docs/tech-stack.md)。

## 最新使用方法

日常主流程只有四步：**选择公司和知识 → 创建需求项目 → 与 Product Agent 讨论并批准 → 观察执行并领取候选分支**。
浏览器会携带 exact checkpoint 和恢复计划身份，不需要复制 JSON、delivery ID 或 SHA。

### 1. 首次启动服务

完成下方“一次性配置”后，在平台源码仓库启动本地 Web Console：

```bash
uv run ase-console
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。服务只监听 loopback，并校验 Host 和
Origin；它不是可直接暴露到局域网或公网的多用户系统。交付期间保持服务运行即可，关闭或刷新网页
不会取消已接纳的后台工作。

### 2. 在网页接入公司和知识

首次进入当前环境，或者需要服务新的知识域时：

1. 打开“设置”，在“接入新公司”中填写稳定的 `company_id`（例如 `company_acme`）和显示名称。
   Company 是知识、项目和交付记录的隔离边界；同一支组织 Agent 团队继续为所有公司服务。
2. 在“活动公司”中选择新公司，检查平台数据目录、MySQL 变量名、模型路由、Codex、真实模型开关和
   Console 端口，然后保存。页面显示“需要重启”时重启 `ase-console`；运行中的 Host 不会被热切换。
   切换到全新平台数据目录时只初始化当前公司，不自动搬迁旧目录中的知识、项目或需求事实。
3. 打开“公司知识库”，上传 Markdown、TXT、PDF 或 DOCX。平台保留原文件和来源信息，并生成稳定的
   `content.md`；不调用模型改写正文，也不会自动加载未选择的文档。
4. 回到“设置”，勾选用于新需求的知识文档并保存。重启后，新建需求会把这些内容绑定到准备摘要；
   已批准的旧需求不会被静默套用新知识。

单文件原始大小上限为 10 MB，规范化正文上限为 256 KB。加密 PDF、无可提取文本、损坏文档、危险
文件名和超限内容都会安全拒绝。原始文档位于
`companies/<company_id>/knowledge/documents/<document_id>/`，不写入平台源码或目标项目。

### 3. 日常需求交付全部在网页完成

1. 进入“需求与交付”，点击“新建需求项目”。填写需求名称，并每行填写一个绝对代码目录；一个
   需求可以覆盖同一仓库的多个模块，也可以跨多个仓库。
2. Project Manager 先注册项目、建立外置 sidecar、发现 ProjectProfile 并编译项目规范。操作卡片
   显示“已接单/执行中/成功/失败”；完成后点击“打开需求工作区”。
3. 在需求详情中和 Product Agent 讨论。ProductSpec 准备好后先阅读“阶段产物”，确认范围和验收
   标准，再点击“批准 ProductSpec 并开始交付”。
4. Designer、Planner 和每个仓库的 `Coder → QA → Reviewer` 串行工作。团队成员页只把当前岗位
   标成执行中，其他岗位显示已完成或等待；需求页同时展示涉及的所有目录和后台操作。

网页每 5 秒读取 durable facts。提交后可以刷新、关闭页面或稍后回来；同一浏览器动作使用幂等键，
同一 Delivery 同时只接纳一个活动操作。

### 4. 中断、失败和人工门禁

需求详情中的“继续交付”统一处理 Product、Designer、Planner、Coder、QA、Reviewer 和联合验收阶段：

- 普通中断从最近 checkpoint 继续，已完成阶段和仓库不会重跑。
- Candidate 已存在但 QA/Reviewer 未完成时，页面展示 exact 候选验证计划；阅读 Agent、模型和
  candidate 后点击“批准并继续”，不会重跑 Coder。
- Coder 无 Candidate 但保留了修改时，页面展示 exact 恢复计划；批准后创建新的关联 Task 接续，
  未知半成品不会直接进入 QA。
- QA FAIL 或 Reviewer REJECT 会保留旧 Candidate 和证据，创建修复 Task，重新执行
  `Coder → QA → Reviewer`。
- 规范冲突、来源漂移、权限或业务歧义仍会停止并要求人工处理；网页不会偷偷放宽制度。
- 如果 Host 在操作执行中退出，该 Web Operation 会标记为 `INTERRUPTED`。重新启动服务后打开需求，
  依据当前 Delivery 事实再次点击“继续交付”，不会盲目重放原模型调用。

### 5. 领取交付结果

需求进入 `DONE` 后，“交付结果”列出每个改造目录对应的 Candidate commit、可定位时的 Candidate
branch，以及 QA/Reviewer/联合验收证据入口。人工确认后，仍按目标项目自己的 PR、保护分支、联调、
发布和回滚流程交付。v0.1 不自动 merge、push 或 deploy，也不会切换目标项目当前 checkout。

### 一次性配置

准备 Python 3.12+、uv、Git、MySQL 8.0 和已登录的 Codex CLI。复制
`config/production.example.json` 到用户配置目录，配置公司、模型路由和位于源码之外的
`platform_root`。这是管理页面能够启动之前唯一必须准备的 bootstrap；启动后可在“设置”中维护所有
现有无密钥配置。每次启动服务的环境必须提供：

```bash
export ASE_MYSQL_DSN='mysql+pymysql://USER:PASSWORD@127.0.0.1:3307/DATABASE'
export ASE_CONFIG='/absolute/path/to/production-config.json' # 默认位置可省略
```

设置页只显示这些密钥变量“已提供/未提供”，不会读取或回显正文。密钥和 DSN 正文只放环境变量或
secret manager，不写入配置、仓库或 sidecar。完整 MySQL、模型
fallback 和安全配置见 [生产配置指南](docs/production-setup.md)。真正的自动登录启动要等
macOS Keychain / Linux Secret Service 适配完成，当前不要把 DSN 明文写进 plist 或 systemd unit。

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
- 配置数据目录：macOS/Linux 可省略 `platform_root`，稳定使用当前用户的 `~/.ase`；如需自定义，可使用所有代码目录之外的绝对路径或安全的 `~/...`，显式值优先。
- 启用模型：将 `live_model_execution` 设为 `true`，并把第一个启用路由改成当前可用模型。

配置文件至少确认以下字段；`platform_root` 未列出时使用上述默认值：

```json
{
  "company_id": "company_ai",
  "company_name": "AI company",
  "live_model_execution": true
}
```

再为当前 shell 设置 MySQL DSN；配置放在其他位置时同时设置 `ASE_CONFIG`：

```bash
export ASE_MYSQL_DSN='mysql+pymysql://USER:PASSWORD@127.0.0.1:3307/DATABASE'
export ASE_CONFIG='/absolute/path/to/production-config.json' # 使用默认配置路径时可省略
```

把配置中的第一个已启用 `model_routes` 改成当前实际可用模型（推荐 Codex CLI 的
`gpt-5.6-terra`）。密钥和 DSN 正文只放环境变量。完整 MySQL、模型 fallback 和安全配置见
[生产配置指南](docs/production-setup.md)。

### 2. 日常使用：创建、讨论、确认

**① 创建需求项目。**一个需求可以传一个目录，也可以同时传多个不相邻仓库/模块：

```bash
uv run ase request create /absolute/path/to/project-a /absolute/path/to/project-b \
  --name "你的需求名称"
```

平台会注册项目、建立外置 sidecar、发现 ProjectProfile 和项目规范。成功输出
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
- Coder 尚无 candidate、失败 worktree 存在修改：自动定位失败 Run/Context 并返回精确恢复计划；
  批准后创建新 Task 接续旧修改，再走 `Coder → QA → Reviewer`；新的恢复/修复 Coder 若再次中断，
  继续执行同一个 `resume`，平台会沿完整 Task/dispatch 历史创建下一次恢复，而不是卡死在第一轮。
- Coder 已产生 candidate、QA/Reviewer 因额度或进程故障中断：先返回一个精确验证计划，**不会重跑 Coder**。
- QA FAIL 或 Review REJECT：保留 Candidate V1 和原失败 Task，自动创建关联修复 Task，再走
  `Coder → QA → Reviewer` 得到 Candidate V2。
- 已完成 Task、checkpoint 尚未来得及写入：从 Task event 和 sealed artifacts 接管，零模型调用。
- 规范冲突、需求歧义、权限/来源漂移：返回明确人工 gate，不会偷偷放宽规则。

当输出为 `VERIFICATION_APPROVAL_REQUIRED` 或 `RECOVERY_APPROVAL_REQUIRED` 时，检查返回的 plan
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

MySQL 集成测试需设置 `ASE_TEST_MYSQL_DSN`，指向专用测试数据库。测试使用脚本化模型验证契约，
不代表真实模型已完成业务验收。

## 当前进度（2026-09-12）

| 阶段 | 阶段性成果 |
|---|---|
| M0–M2 平台基础 | 完成架构、强类型契约、状态机、Artifact、Context 和 Git 隔离 |
| M3–M4 串行交付 | 完成底层 `Coder → QA → Reviewer`、有界恢复、Evaluation/ADR 与 Handoff 组件；不等于生产入口已启用全部能力 |
| M5 组织与项目接入 | 完成组织拥有的 Workforce、确定性调度算法、ProjectProfile、SpecCompiler 和外置 sidecar |
| M6 可执行与可审计 | 完成受控命令、typed tools、Evidence、跨语言边界和只读 API |
| M7 团队可视化 | 本地只读团队工作台，自动读取当前公司多目录需求、成员分配、执行历史和报告；旧静态组件保留为底层工具 |
| M8 接单与推进 | 接通 Product、Designer、Planner、原子 dispatch 和可恢复 CLI 入口；产品批准与必要澄清仍由人工完成 |
| M9 Production Team Host | 完成命令级自动装配、MySQL 存储、配置驱动的模型路由与隔离交付；Coder 支持有界 checkpoint/续跑，真实模型验收需另行执行 |
| M10 公司知识与联合交付 | 公司统一 sidecar、按需知识加载；先准备后讨论的需求项目入口；多仓独立交付、联合候选验收与中断恢复 |
| M11 持续团队与候选提交 | 七个组织级长期成员；显式 CandidateCommit Skill；CoderProgress Artifact；可重启的有界 Coder 续跑循环 |
| M12 持久工作队列 | MySQL Run 级 WorkItem、Planner-owned Dispatcher tick、原子 Assignment/Lease/ModelSelection、owner-fenced 心跳/完成/等待/重试/过期回收；`ase request` 逐角色 Worker 接线仍待完成 |
| M13 候选复核恢复 | 对已有 Coder candidate 提供 `verify-propose / inspect / approve / run`；使用独立 QA/Reviewer allocation、Lease 和 worktree，保留原失败 Task 与联合需求历史，不自动 merge/push/deploy |
| M14 统一恢复与自动修复 | `request resume` 统一接管现有持久化阶段；候选复核可由同一入口批准和续跑；QA FAIL/Review REJECT 创建确定性修复 Task 并重新走 Coder→QA→Reviewer；看板显示验证与修复工作；终态 Task 可零调用补写 Delivery checkpoint |
| M15 Web 交付控制台 | 浏览器完成多目录项目创建、Product 对话与批准、统一继续/精确恢复计划批准和候选领取；操作先写入 Company sidecar，再由后台 Project Manager 执行，页面刷新不丢单；CLI 降为运维和 break-glass 入口 |
| M16 平台管理面 | 浏览器创建/选择公司，导入 Markdown/TXT/PDF/DOCX 为内容寻址的公司知识，并维护平台目录、活动公司、知识选择、MySQL 引用、模型路由、Codex、执行开关和端口；运行时绑定变化明确要求重启 |

## 文档导航

- 生产部署与最新使用：[`docs/production-setup.md`](docs/production-setup.md)
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
- 阶段成果与提交证据：[`docs/archive/README.md`](docs/archive/README.md)
- 语言架构决策：[`docs/decisions/0001-python-control-plane.md`](docs/decisions/0001-python-control-plane.md)
- Agent Workforce 决策：[`docs/decisions/0002-organization-owned-agent-workforce.md`](docs/decisions/0002-organization-owned-agent-workforce.md)
- Codex bootstrap：[`AGENTS.md`](AGENTS.md)
