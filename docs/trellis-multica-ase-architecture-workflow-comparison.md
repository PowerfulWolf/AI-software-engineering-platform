# Trellis、Multica 与 ASE：架构、设计思想与工作流对比报告

> 核查日期：2026-09-20  
> 报告性质：基于当前代码和第一方资料的架构分析，不是性能评测或生产可用性认证。  
> ASE 指本地项目 `AI-software-engineering-platform`，软件名称为 `ai-software-engineer`。  
> 核心结论：Trellis 的重心是仓库内的工程方法与上下文；Multica 的重心是人类与 Agent 的团队工作台及运行协调；ASE 的重心是把组织知识、岗位权限、可核验验收和可恢复执行组合成软件交付流程。

## 目录

1. [研究范围与证据口径](#一研究范围与证据口径)
2. [结论速览](#二结论速览)
3. [设计思想对比](#三设计思想对比)
4. [三者的架构介绍](#四三者的架构介绍)
5. [从需求到交付的流程对比](#五从需求到交付的流程对比)
6. [逐项架构与能力对比](#六逐项架构与能力对比)
7. [典型场景对比](#七典型场景对比)
8. [ASE 当前实现与边界](#八ase-当前实现与边界)
9. [ASE 的优势、代价与未证实主张](#九ase-的优势代价与未证实主张)
10. [三者如何取舍与互补](#十三者如何取舍与互补)
11. [后续建设与验证建议](#十一后续建设与验证建议)
12. [容易产生的误解](#十二容易产生的误解)
13. [资料来源](#十三资料来源)

## 一、研究范围与证据口径

### 1.1 核查版本

| 对象 | 本次基线 | 说明 |
|---|---|---|
| Trellis | `mindfold-ai/Trellis`，commit `e77ae89f648a78d5859fa2e8ac314655898421a5`；CLI package 版本 `0.6.17` | 官方另有 beta 文档。本报告优先采用稳定文档，并用该源码快照确认 Channel 已存在。[T1]、[T3]、[T7] |
| Multica | `multica-ai/multica`，commit `8c4f4328f6e3baff08394b309034463b5db9d7af` | 源码基线日期为 2026-09-19；不据此推定所有用户安装版本都有主分支全部能力。[M1] |
| ASE | 本地 `main`，commit `9c21431`；包含 `f3472a7` 的 T046 Worker 接入 | 已纳入 T047 Planner、T048 主动知识闭环、T049 增量知识索引。代码合入不等于线上部署和真实交付已充分验证。[A1]、[A9] |

### 1.2 证据分级

- **源码确认**：检查了相关实现，可确认机制存在；不自动证明生产稳定性。
- **官方文档**：第一方明确描述的功能；没有在本次报告中逐项部署运行。
- **分析判断**：根据已确认机制推导的适用性、收益或代价，不作为实测结果。
- **未证实**：本次资料不足。不能把“未证实”写成“该产品没有”。

本报告未在待对比系统中运行真实需求或启动付费模型调用，未执行全量测试、未更改生产数据库，也不评价三者的许可证是否满足某个商业使用场景。

ASE 文档存在少量历史口径：例如旧规划知识说明仍称没有知识缺口审批表单，旧架构文字也可能把规划能力描述得比当前生产装配更广。发生冲突时，以当前代码、当前 README 和专项运维边界为主，不将历史计划直接计为现成功能。[A1]、[A9]、[A11]

## 二、结论速览

| 问题 | Trellis | Multica | ASE |
|---|---|---|---|
| 核心解决什么 | 让 AI 开发持续遵守项目规范，并获得合适的任务上下文 | 把人类、Agent、任务和执行环境组织到统一工作台 | 把一条软件需求推进到有证据的候选交付，并保留失败恢复路径 |
| 主要组织中心 | Repository、Task、Spec、开发日志 | Workspace、Project、Issue、Agent、Squad、Run | Team、Project、Requirement、Repository Task、AgentRun、Artifact |
| 工作流重心 | 规划、实现、检查、收尾和知识沉淀 | 分配、协作、并发运行、日志、重试、人类评审 | 产品批准、设计、规划、编码、独立 QA、独立 Review、联合验收 |
| 记忆和知识 | 仓库规范、任务文档、journal，以及历史检索 | 共享 Skills、参考材料、Issue/Project 上下文和执行历史 | 分层知识、冻结快照、受控检索、引用证据、知识缺口与审批 |
| 运行协调 | 已有本地 Channel 多 Agent runtime | 已有 server/daemon 协调、并发额度、排队和故障恢复 | 已接入 MySQL 逐角色队列；尚未交付独立 Worker fleet |
| 完成判定重心 | 工作流约定、检查步骤和宿主工具执行 | Run 状态与 Issue 状态分离，通常经人类 review 或 PR 集成完成 | 状态迁移校验产物、候选版本、验收覆盖和独立岗位证据 |
| 分析上的适用重点 | 希望在现有 coding agent 中建立工程习惯 | 希望集中协调多个 Agent 与多个任务 | 希望组织知识、审批和软件验收进入同一套可追溯交付系统 |

依据：[T1]–[T6]、[M1]–[M7]、[A1]–[A11]。

一句话概括：**Trellis 更关注“怎么做开发”，Multica 更关注“谁在什么环境做哪些工作”，ASE 更关注“依据什么做、做到什么程度才可交付、失败后怎么安全继续”。** 这是重心差异，不是互斥的功能分类。

## 三、设计思想对比

### 3.1 Trellis：把工程知识和流程留在仓库里

Trellis 的关键思想是：不要依赖模型在长对话中记住全部项目约定，而要把规范、任务背景和开发历史显式维护起来，在需要时注入或读取。

- `.trellis/spec/` 保存工程规范和项目约定。
- Task 保存需求、设计、实施上下文和进度资料。
- 开发者 journal 保存已经完成的工作与经验。
- Skills、工作流模板和平台适配负责把上述资料带入执行。
- Channel 补充本地多 Agent 协作能力，使任务可以委派给多个 Worker，并保存协作事件。

因此，Trellis 不只是 Prompt 模板集合，也不只是“一个 Agent 的记忆文件夹”。但工作流指令、平台 hooks 和本地协作 runtime，不应直接等同于一个统一的软件交付状态机。[T1]、[T2]、[T3]、[T4]、[T5]

### 3.2 Multica：把 Agent 纳入团队工作管理

Multica 的关键思想是：人类和 Agent 可以围绕共同的 Issue 工作，平台负责组织分配、执行环境、状态、历史和协作。

- Issue 表达一个持续目标，Run 表达一次执行。
- 一个 Issue 可以经历多个 Run，不因一次进程退出就丢失整个任务历史。
- Squad leader 可以协调成员、委派工作，并根据成员结果继续推进。
- Daemon 在本机或云机调用已配置的 coding CLI。
- Skills 可被多个 Agent 共享，任务也可以由人工、事件或计划触发。

Multica 因而不只是看板；其运行和恢复能力是产品的一部分。另一方面，Issue 状态允许灵活修改，不能仅凭“review gates”的宣传用语推断它强制执行 ASE 式的候选提交验收契约。[M1]、[M2]、[M3]、[M4]、[M5]、[M6]、[M7]

### 3.3 ASE：把工程制度变成可执行约束

ASE 当前明确贯彻三条原则：

1. **知识属于组织，而不是某个 Agent。** Agent 可以替换，规则、决定和工作事实仍由平台保存。
2. **执行者不能是自己工作的唯一裁判。** Coder、QA、Reviewer 在同一 Task 历史中必须是不同 Agent。
3. **通过可验证产物交接，而不是依赖共享假设。** 输入输出必须绑定任务、版本、上下文、来源和证据。

这使 ASE 更接近一个针对软件交付的控制系统，而不只是多 Agent 聊天系统。它把一部分工程规则转换为状态机、Schema、权限和证据检查。[A1]、[A2]、[A5]、[A8]

但应区分三个层次：

- **制度存在**：有明确的角色、产物和审批契约。
- **执行可靠**：真实运行能正确恢复，状态与现场一致。
- **交付有效**：产物真正满足业务需要，且成本和人工介入可接受。

当前实现为第一层提供了较多机制，对后两层不能只凭架构图作出保证。

## 四、三者的架构介绍

### 4.1 Trellis：仓库知识层、平台适配层与协作 runtime

以下是概念架构，不表示每个平台都采用完全相同的调用路径：

```text
开发者 / 主 Agent
        │
        ▼
Trellis 工作流与 Skills
        │
        ├── 读取 Repository Spec
        ├── 读取 Task 的 PRD / Design / Context
        └── 读取或记录开发 Journal
        │
        ▼
平台适配：Hook 注入 / Pull Prelude / Skill 读取
        │
        ▼
Coding Agent 执行 → 检查与验证 → 收尾与知识沉淀
        │
        └── 可使用 Channel 委派 Worker
                ├── 显式上下文与定向消息
                ├── 并行等待、interrupt、resume
                └── 持久事件和运行日志
```

| 组件 | 职责 | 不能据此推定的能力 |
|---|---|---|
| Spec | 保存规范、约定、经验 | 所有 Markdown 规则都已转成机器可判定规则 |
| Task 文档和上下文清单 | PRD、设计/实施文档及 JSONL 上下文文件清单 | 自动具备团队级资源调度和数据库事务 |
| Journal / Memory | 保存开发历史并支持检索 | 所有下游产物天然绑定相同代码 revision |
| 平台适配与 hooks | 在适当阶段提供上下文和流程约束 | 不同 coding host 的权限和自动化能力完全一致 |
| Check 等工作流 | 依据规范和需求检查 diff，运行验证 | 必然存在独立服务器对每个 verdict 进行强制校验 |
| Channel | 本地多 Worker 生命周期、消息、事件和恢复 | 自动等价于跨机器 Worker 集群、业务交付 DAG 或 OS 沙箱 |

Channel 在本次正式源码基线中已存在，文档列出的 Worker 包括 Claude/Codex。Trellis 对多个 coding 平台的适配范围，不能直接当作 Channel 能启动的 Worker 类型数量。[T3]、[T4]、[T7]

这里还有一处存储边界：工程规范与任务资料在 Repository 内；Channel 的持久事件位于本地用户级目录，并按作用域管理；`trellis mem` 检索已有本地会话，不应与 ASE 的文档增量索引混为一谈。[T2]、[T3]、[T5]

### 4.2 Multica：协作控制端、执行 Daemon 与外部 coding runtime

```text
用户 / 团队成员
        │
        ▼
Multica Web 工作台与 Server
        ├── Workspace / Project / Issue / 评论
        ├── Agent / Squad / Skills / 执行配置
        ├── Run 创建、队列、状态与历史
        └── 人工、事件或计划触发
        │
        ▼
Daemon：本机或云机
        ├── 领取和执行工作
        ├── 并发约束、目录等待、心跳
        ├── Runtime 进程管理和恢复
        └── 结果、日志与状态回传
        │
        ▼
选定 Runtime 对应的 Coding CLI
        │
        ▼
代码目录、工具、测试及 PR 等工作结果
        │
        └── 回到 Issue 讨论 / Review / 下一次 Run
```

这是官方产品边界的概括，没有将本次未核实的消息投递、事务或隔离细节画成强保证。[M1]、[M2]、[M4]

| 组件 | 职责 | 边界 |
|---|---|---|
| Server / 工作台 | 保存协作上下文、配置、Issue 和 Run 事实 | 不能因模型在本地执行就推定 Server 不保存上下文或配置 |
| Issue | 持续目标、讨论、协作状态 | 不是一次模型调用，也不等于一个代码提交 |
| Run | 一次执行及其日志、结果、失败记录 | `completed` 不自动等于需求验收成功 |
| Agent / Squad | Agent 配置、角色组织、leader 委派和协作 | 名称本身不证明不同成员具有机器强制的岗位权限 |
| Daemon | 驱动执行环境，管理并发、心跳和进程 | 同目录等待锁不能直接当作每个任务自动有独立 worktree |
| Runtime | 某台机器与某个 coding tool/custom profile 组成的可选执行环境 | 具体 CLI 调用由 daemon 执行；模型、工具与 sandbox 能力受该环境配置影响 |
| Skills | 共享指令、脚本、模板和参考资料 | 不能仅由 Skills 存在推定组织知识具有冻结快照或引用验证 |

Multica 官方说明 Server 也保存 Issue、评论、配置、上下文和运行记录；自定义环境变量及 MCP 配置也涉及服务端保存。选型时需要按部署配置评估数据边界，不能把“本地执行”简化为“所有数据只在本机”。[M2]

### 4.3 ASE：知识、调度、执行、证据与人工边界

```text
用户 / Local Web Console
        │ typed intent
        ▼
持久化 Operation → 后台 Manager 编排
        │
        ├── Project / Repository 准备
        ├── Product 讨论 → 人工批准 ProductSpec
        ├── Designer → TechnicalDesign
        └── PlanningGate → Fast Plan 或 Planner → ExecutionPlan
        │
        ▼
交付执行边界
        ├── MySQL WorkQueue + Dispatcher
        ├── Assignment / Lease / ModelSelection
        ├── 单 Supervisor 逐角色领取与续约
        └── Runtime / TaskOrchestrator 校验并推进
                    │
                    ▼
        Coder → QA → Reviewer → 候选交付
          ▲       │       │
          └──── FAIL / REJECT

贯穿上游与交付的公共能力：
  Knowledge：冻结知识、受控检索、缺口与解答
  Context：按角色和运行生成有预算、有来源的上下文
  Policy / Worktree：岗位权限、独立代码现场
  Artifact / Evidence：不可变产物和命令、测试、调用证据
  Human Boundary：产品、范围、冲突和知识解答等批准
  Read Projection：从持久事实生成页面展示
```

注意：T046 的逐角色队列当前接入 **Coder、QA、Reviewer** 原生交付；Product、Designer、Planner 模型会话和独立候选复核没有全部迁移到同一 Worker 队列。[A1]、[A9]、[A10]、[A14]

#### 4.3.1 各层职责

| 层 | 主要组件 | 负责什么 | 不负责什么 |
|---|---|---|---|
| 入口与交互 | Console、Operation、Team Host | 接受命令、保存操作、提供交互 | 不由页面直接宣布 verdict 或改写交付事实 |
| 产品与计划 | Product、Designer、Planner、PlanningGate | 澄清目标、方案、复杂度分流、工作包和验收矩阵 | 不把规划图自动当作并行执行 DAG |
| 调度 | WorkQueue、Scheduler、ModelRouter、Dispatcher | 计算成员与模型、容量约束、原子领取 | 不编写业务代码，不批准 QA/Review |
| 执行 | Supervisor、Worker、Runtime、AgentAdapter | 有界运行、续约、调用模型与受控工具 | 不让失去租约的旧 Worker 继续成功提交 |
| 交付控制 | TaskOrchestrator、artifact 校验 | 合法迁移、验收覆盖、候选版本与产物链检查 | 不凭自由文本“已完成”跳过验收 |
| 知识 | Indexer、Knowledge Skills、Gap/Resolution | 索引、检索、引用、版本与人工解答 | 不自动将任意文档升级为可执行规范 |
| 证据 | Context、Artifact、Evidence、StateEvent | 保存来源、版本、运行和验证事实 | 哈希校验不能证明业务结论一定正确 |
| 代码隔离 | Git worktree、WorkspacePolicy | 分离代码现场、限制路径与命令 | 不等价于容器或虚拟机隔离 |
| 展示与评估 | Projection、Evaluation、Handoff | 展示事实、按规则重算结果、形成交接资料 | 底层模块存在不代表日常入口已自动生成完整交付报告 |

依据：[A2]、[A8]、[A9]、[A10]、[A13]、[A14]。

#### 4.3.2 Team 与 Project 的关系

ASE 的逻辑是“一支长期 Team 服务多个 Project”，不是“每建一个 Project 就复制七个 Agent”。目录上 Team 和 Projects 并列：

```text
platform_root/
├── team/
│   └── 成员、团队知识/规范、模型策略、Skills、团队运行事实
└── projects/
    └── <project-id>/
        └── 项目知识/规范、Repository catalog、Requirement 与 sidecar

目标代码 Repository：位于上述平台元数据目录之外
角色 Worktree：临时代码现场，与平台 sidecar 元数据分别管理
```

生产 Task/调度事实使用 MySQL；Artifact、Evidence 和部分 journal 等在外置 workspace 保存。低层仍有 SQLite 兼容/测试适配器，但这不表示生产业务库已从 MySQL 改回 SQLite。[A2]

#### 4.3.3 Agent、角色、模型和服务不是同一个概念

| 名称 | 当前职责 | 关键边界 |
|---|---|---|
| Manager | 接单、准备、推进、调度、恢复协调与交付控制 | 当前生产主要调用确定性 Skills，不直接发起 Manager 模型调用 |
| Product | 多轮讨论、生成 ProductSpec | 不能批准自己的产品范围 |
| Designer | 技术方案、组件、风险和测试策略 | 必须覆盖已批准产品要求 |
| Planner | 复杂需求的工作包、依赖、执行顺序与验收测试矩阵 | 简单需求由确定性 Fast Plan 处理；计划不等于实际资源领取 |
| Coder | 允许范围内的代码与测试实现 | 不能生成自己的 QA/Review 批准；候选提交通过平台受控能力创建 |
| QA | 对候选代码执行验证，形成 QA 报告 | 不能改生产代码；测试写入受范围限制 |
| Reviewer | 对同一候选执行独立审查 | 只读审查，不修复代码或自行 merge |
| Scheduler / Dispatcher / Orchestrator | 确定性调度、领取和状态控制 | 是应用服务，不是额外的“会思考的 Agent” |

Agent 身份可以长期存在，模型是某次运行使用的能力。不同角色可以配置不同模型和推理程度；即便两个成员使用相同模型，也不能因此合并为同一个岗位身份。身份独立不意味着推理错误一定独立。[A1]、[A2]、[A11]

## 五、从需求到交付的流程对比

### 5.1 Trellis 的典型流程

```text
读取项目规范与任务背景
  → 澄清需求 / 建立 PRD
  → 形成方案和实施上下文
  → 主 Agent 实施，或委派 Worker
  → 根据规范、需求和 diff 检查
  → 运行适用的验证命令
  → 最终验证与规范更新
  → 确认并提交
  → finish-work 归档任务、记录经验
```

工作流会因宿主 coding agent、安装的技能和项目配置而变化。Check 模板明确要求需求/规范检查及 lint/typecheck 等验证，但不能据此认定所有平台都会自动跑相同测试，或每次检查都会生成服务端强校验的统一证据链。[T2]、[T4]、[T6]

### 5.2 Multica 的典型流程

```text
创建 Issue / 补充目标和项目上下文
  → 分配 Agent 或 Squad
  → 创建 Run，按容量和环境条件排队
  → Daemon 启动对应 Runtime
  → Agent 执行、回传日志与结果
  → 必要时重试、追加讨论、委派或再开 Run
  → 进入 Review / 人类确认 / PR 集成
  → 更新 Issue 的完成状态
```

必须区分两类完成：

- **Run completed**：这次执行结束，不代表业务目标已验收。
- **Issue done**：协作任务的完成状态，通常来自人类确认或集成流程；官方文档明确状态没有固定流转，成员和 Agent 可直接修改。

因此，Multica 能组织 QA/评审成员，不等于它默认强制要求 ASE 的 `同一 candidate SHA + 独立岗位 + 完整验收覆盖` 契约。[M3]、[M4]、[M6]

### 5.3 ASE 的实际流程

#### 上游：从讨论到可执行计划

1. 选择 Project 和需求涉及的一个或多个 Repository，保存需求代码基线。
2. Product 与用户多轮讨论，可使用已配置知识和经校验的截图输入。
3. 生成 ProductSpec，由用户批准精确版本和摘要。
4. Designer 形成 TechnicalDesign。
5. Manager 的确定性 PlanningGate 根据结构化事实判断 SIMPLE 或 COMPLEX。
6. SIMPLE 生成最小计划，不调用 Planner 模型；COMPLEX 调用 Planner 形成有界工作包、依赖、风险和验收矩阵。
7. 校验 ExecutionPlan，进入仓库 Task 派发与执行。

PlanningGate 会检查多仓、多模块、迁移、兼容性、数据回填、安全、性能、并发、工作包依赖和风险等因素。规则计算是确定性的，但输入事实是否全面仍依赖上游需求和设计质量；“确定性”不意味着分类永远正确。[A1]、[A3]

#### 下游：候选实现、独立验证和返工

```text
NEW → PLANNING → IMPLEMENTING（Coder）
                     │
                     ├── 本轮未完成 → 保存 checkpoint → 有界续跑
                     │
                     └── 实现完成 → 校验范围并生成 candidate
                                             │
                                             ▼
                                           QA
                           FAIL ─────────────┤
                            │                └── PASS → REVIEW
                            │                              │
                            └──── 返回 Coder ← REJECT ─────┤
                                                           └── APPROVE → DONE
```

计划绑定输入基线；实现报告、QA 报告、Review 报告必须绑定同一候选提交。Coder 被打回后产生新候选，不能把旧版本的通过结论直接当成新版本的通过结论。[A8]

一个 Requirement 可涉及多个 Repository；当前按仓库串行推进子交付。多仓最终还要对完整候选集合做联合验收，不能把“其中一个仓库 DONE”当成整个 Requirement DONE。最终交付候选与证据，不自动合并保护分支或部署生产。[A1]、[A2]

### 5.4 相同阶段下的对比

| 阶段 | Trellis | Multica | ASE |
|---|---|---|---|
| 需求输入 | Task / PRD 与交互式澄清 | Issue 描述、评论、Project 上下文 | Requirement 与 Product 多轮讨论 |
| 需求批准 | 依工作流和人工确认执行 | 依团队 Issue/Review 流程 | ProductSpec 精确版本与摘要的批准 |
| 规划 | 主会话或专门规划流程 | Agent / Squad leader 分解和委派 | 确定性复杂度分流，复杂计划交 Planner |
| 开始执行 | 主 Agent 或 Channel Worker | 创建 Run，Daemon 驱动 Runtime | 派发后由逐角色队列真实领取 |
| 岗位交接 | 文档、显式上下文与 Channel 消息 | Issue/Run 上下文、成员结果、委派 | Schema 合格且带版本、父子关系和证据的 Artifact |
| 质量检查 | Check 工作流和项目测试 | 人类 Review 或团队配置的测试/评审 Agent | 独立 QA PASS、Review APPROVE 和同候选校验 |
| 返工 | 保留任务资料，继续修订和检查 | 讨论、后续 Run 或 Squad 再委派 | 原 findings/evidence 回到 Coder，形成新候选 |
| 收尾 | 确认、提交、归档和 Journal | 更新 Issue，结合 Review/PR 流程 | 候选与证据交付；合并和生产决策保留人工边界 |

依据：[T2]、[T3]、[T6]、[M3]、[M4]、[M6]、[A1]、[A2]、[A8]。

## 六、逐项架构与能力对比

### 6.1 知识、规范和上下文

| 项目 | Trellis | Multica | ASE |
|---|---|---|---|
| 知识载体 | Repo Spec、Task 文档、Journal、历史检索 | Skills、脚本、模板、参考资料及协作上下文 | Team 通用知识、Project 背景知识、开发规范、Repository 原生规则 |
| 加载方式 | Hook / Pull Prelude / Skill 驱动读取 | 分配的 Skills 与 Issue/Project 上下文；repo Skills 可由底层工具读取 | 冻结选择后按角色、运行与预算受控检索和读取 |
| 版本约束 | Git 与任务资料提供版本基础 | 协作历史与 Skills 更新机制；本次未证实统一冻结快照契约 | Requirement 保存精确知识快照，历史需求不会被新文档静默覆盖 |
| 引用验证 | 本次未证实全局统一强校验 | 本次未证实与 ASE 相同的引用约束 | 检索命中、读取内容、作用域、Run、摘要均校验并留证据 |
| 缺失知识 | 可以通过交互、研究和补充资料解决 | 可以通过评论、协作和后续执行补充 | 显式 KnowledgeGap、批准的 Resolution、新 Context/Run 恢复 |
| 增量处理 | 文件、索引和记忆能力因功能配置而异 | 本次未证实与 ASE 等价的文档索引生命周期 | 后台确定性解析与分段、缓存复用、原子发布、失败重试和退休隔离 |
| 经验回写 | Journal、Spec 更新等工程流程 | 共享 Skills 等复用机制 | Learning proposal 与发布审批分离，不能由 Agent 自动激活规则 |

ASE 的上传文档索引已经实现，但它不是一个自动理解全部业务的知识专家，也不是通用向量 RAG 平台。文档规范化、分段和检索，不等于自动生成经过验证的强制规范。[T2]、[T5]、[M5]、[A4]、[A6]、[A7]

### 6.2 调度、并发和代码隔离

| 项目 | Trellis | Multica | ASE |
|---|---|---|---|
| 并发入口 | Channel 多 Worker | 多 Run 与 daemon/Agent 并发额度 | 组织调度基础与 T046 逐角色队列 |
| 已确认容量机制 | Channel 源码默认每 project/scope 6 个 live Worker，可配置 | 官方默认每 daemon 20 个 Run、每 Agent 6 个，可配置 | MySQL 容量 fence，Assignment/Lease/ModelSelection 受事务约束 |
| 生命周期 | Spawn、消息、等待、interrupt、kill、resume | 排队、运行、心跳、重试、重启恢复 | 领取、启动、心跳、完成、等待、重排、租约过期 |
| 同目录安全 | 取决于选用的任务、worktree 与宿主执行方式 | 文档有同本地目录等待锁 | 同一 Task 使用保留的独立 Coder 工作树；QA/Reviewer 有独立候选工作树 |
| 生产并发边界 | 本地协作 runtime 不等于集中团队服务 | 已提供 daemon 运行协调机制 | 单 Task 角色严格串行；当前接入仍是单 Supervisor，未交付独立 fleet/多 Task 并发部署 |
| 多仓交付 | 可以组织多个仓库的工程任务；本次未证实统一候选集契约 | 可以组织跨项目/任务协作；本次未证实统一候选集契约 | Requirement 投影到各仓 Task，完整候选集合联合验收 |

上述默认并发数字不是性能排名；它们没有相同的硬件、任务、模型和验收基准。规划文档里的依赖关系也不自动意味着运行时会并行执行。[T3]、[T8]、[M2]、[A2]、[A9]、[A10]

### 6.3 模型、工具和岗位权限

| 项目 | Trellis | Multica | ASE |
|---|---|---|---|
| 模型来源 | 依宿主 coding agent 和配置 | 依已接入 Runtime/CLI 与配置 | Codex CLI 和 Responses-compatible 等适配路径 |
| 角色模型选择 | 依平台及 Worker 配置 | Agent/runtime 配置 | 每个 Agent 显式主模型与有序备用路由 |
| 推理程度 | 依宿主支持 | 依 runtime 支持 | 路由身份包括 provider、model、reasoning |
| 备用机制 | 不概括为所有平台统一策略 | 有故障重试；不将重试等同于自动换模型 | 只在指定临时故障类型下尝试该 Agent 已批准的备用路由 |
| Skills 的本质 | 工程指令及可选脚本、上下文组织 | 可共享的指令、脚本、模板和参考材料 | 文档知识与 typed/policy-bound 能力需区分；部分工作流被实现为确定性门禁 |
| 权限约束 | 平台 sandbox、工具权限、hooks 与流程共同决定 | Workspace 角色、Agent Access、Runtime 共享范围控制调用权限；执行工具权限受 runtime/部署配置影响 | 角色路径/命令 policy、工作树与产物校验；Codex 路径还依赖其 sandbox |

ASE 不会因为“一个模型已加入目录”就默认把它用作所有 Agent 的备用。认证错误、业务歧义、无效产物和权限违规也不能靠盲目切模型掩盖。按难度自动升降模型成本档位的完整策略尚未实现。[A11]

岗位约束也不意味着模型本身只“懂”一个岗位。实际限制来自输入上下文、工具、可写路径、返回契约和状态权限，而不是把模型改造成了七种不同基础模型。[A2]

### 6.4 质量、证据、状态与可观测性

| 项目 | Trellis | Multica | ASE |
|---|---|---|---|
| 质量组织 | 规范、任务要求、Check 与验证流程 | Review、团队成员和可配置 QA/评审协作 | 固定的独立 QA/Reviewer 及状态迁移契约 |
| 交接记录 | 任务资料、消息、日志和检查结果 | Issue、Run、评论、结果及日志 | 不可变 Artifact、Context、Evidence、StateEvent |
| 代码版本一致性 | 可通过流程和 Git 管理；未证实全局统一强制 | 未证实与 ASE 相同的全局强制机制 | 实现、QA、Review 必须对应同一 candidate SHA |
| 完成判断 | 由配置的工作流和宿主行为落实 | Issue 状态灵活；Run 完成不等于目标完成 | DONE 需要合法状态链及相关证据校验 |
| 展示事实 | 任务、会话及 Channel 事件 | Issue 与 Run 管理视图 | Projection 从持久化事实重算，区分交付、调度与运行状态 |
| 效果评估 | 本次未建立统一对照指标 | 有日志/成本等产品能力；未建立同口径对照 | 已有 Evaluation/ADR 重算基础，但不能据此宣称更高真实成功率 |

ASE 的验收覆盖校验能发现“某个验收项没有对应结果”，不能证明验收项本身完整，也不能证明测试没有漏测。SHA-256 用于一致性和完整性检查，不是业务正确性证明，也不应被描述为抵御拥有底层写权限者的数字签名体系。[A5]、[A8]、[A13]

### 6.5 失败恢复与人工边界

| 项目 | Trellis | Multica | ASE |
|---|---|---|---|
| 会话恢复 | Task/Journal 和 Channel/provider session 续接 | Run 历史、daemon 重启回收、安全 session 续接 | 基于 checkpoint、Artifact、工作树和新 Run 接续，不依赖同一聊天会话 |
| 临时故障 | 依 Channel/宿主及任务处理 | 有 transient fault 重试和特定恢复策略 | 有界重试、指定模型回退、租约过期重排等分别处理 |
| 验收失败 | 继续修改和检查 | 评论、后续 Run 或重新委派 | QA FAIL/Review REJECT 携原始 findings/evidence 返回 Coder |
| 范围或规则冲突 | 通过项目规范和人工协作处理 | 通过配置、讨论和人工协作处理 | 显式冲突/范围批准；不能靠改状态绕过授权 |
| 终态后恢复 | 依任务和 session 管理方式 | 可以继续同 Issue 的后续 Run | 保留旧 Task 历史，通过恢复计划、候选复核或关联修复 Task 继续 |
| 通用环境自愈 | 不推定为内建通用保证 | 不把重试/Squad 协作当作任意环境自愈保证 | 有受控自愈抽象，但生产通用自愈未接入 |

依据：[T3]、[M4]、[M6]、[A1]、[A9]、[A12]。

### 6.6 存储、部署与集成边界

| 项目 | Trellis | Multica | ASE |
|---|---|---|---|
| 主要部署形态 | CLI 初始化到仓库，依赖可用的 coding host；Channel 在本地运行 | Cloud 或自托管工作台，连接本机/云机 daemon | 可信本机 Console、Team Host、本地 Git 与 MySQL |
| 主要持久事实 | Repo Spec/Task/Journal；另有 Channel 事件与既有 provider 会话 | Server 保存协作与运行记录，daemon 管理执行现场 | MySQL Task/调度事实 + 外置 workspace 的 Artifact/Evidence/Journal 等 |
| 数据库依赖 | 不将本地文件工作流误称为中心数据库服务 | 官方部署说明包含 PostgreSQL | 生产 MySQL；SQLite 保留为低层兼容/测试适配 |
| 环境扩展 | 平台适配、Skills、hooks、Channel | Runtime/CLI、daemon、Skills、Squad 和集成 | Typed adapter/port、受控 Skills、角色模型策略和执行 policy |
| 隔离含义 | 由项目、协作方式及宿主工具共同决定 | Workspace 权限、runtime 与部署配置共同决定 | Team/Project 逻辑作用域和角色工作树，不宣称强多租户 OS 隔离 |
| 合并与发布 | 按主会话、人类确认和项目流程处理 | 可结合 PR 集成、review 和协作状态 | 交付候选及证据，不自动合并保护分支或发布生产 |

上述是部署职责与数据位置的比较，不是安全等级排名。ASE 备份与回滚还必须考虑 MySQL 和文件产物的一致性，不能只回退其中一侧后继续写入；Multica 本地执行也不能被简化为服务端完全不保存上下文。[T1]、[T2]、[T3]、[M1]、[M2]、[A2]、[A9]

## 七、典型场景对比

以下用于解释机制差异，不是三套系统的实测结果。

### 7.1 执行中发现项目知识不足

- **Trellis**：Agent 可以阅读 Spec、任务资料、历史或请求补充，再把新结论纳入任务上下文。
- **Multica**：可在 Issue 中讨论、补充资料或委派其他成员，再继续本次或后续 Run。
- **ASE**：可登记绑定本次运行的 KnowledgeGap，暂停在安全检查点；经精确 Resolution 批准后，构建新 Context/Run 继续。解答若要成为长期知识，还要走独立发布流程。

ASE 的差异在于知识缺口、批准和继续执行有显式数据契约，而不仅是聊天里的一个问题。[A6]

### 7.2 QA 发现问题，需要 Coder 多次返工

- 三者都可以组织返工，不能把“能打回”当作 ASE 独有能力。
- ASE 会把原始 findings、命令和证据交回 Coder；候选代码更新后，QA/Review 必须匹配新候选。
- 恢复时若只有 Reviewer 失败，已有 QA 结论能否复用取决于候选和证据链校验，不能无条件复用，也不必一律从产品讨论重新开始。

ASE 的特点是把返工与证据有效性连起来；代价是恢复路径更多，对状态一致性要求更高。[A1]、[A8]

### 7.3 两个需求同时工作，第一个合入主分支

- Trellis Channel 可以并行组织 Worker，但仍要明确每个任务的代码现场和合并方式。
- Multica 可以运行多个任务，同时有目录争用处理；不能据此假定任意两个 Run 都自动持有隔离分支。
- ASE 为需求保存代码基线和独立工作现场，源 checkout 更新并不应自动废弃第二个需求。最后合并仍需处理集成变化和冲突。

但 ASE 当前的工作树隔离与调度基础，不能直接当作独立 Worker fleet 已部署完成的证明。尤其不能因为计划里有多个工作包，就说一个 Task 内已经支持并行 Coder。[A1]、[A2]、[A9]

### 7.4 服务重启或 Worker 丢失租约

- Trellis 可依靠持久任务资料、Channel 事件和可恢复 session 接续。
- Multica 有 daemon 重启回收、运行历史和安全 session 恢复。
- ASE 保留工作树和 checkpoint；旧 owner 丢失租约后不能继续成功提交。需要等待旧执行退出及租约安全回收，再从合法记录继续。

ASE 当前可能仍需用户点击“继续交付”，第一次继续也可能只完成过期回收。它不是已经实现了所有重启场景下完全无人介入的永久 Worker 服务。[A9]

### 7.5 模型执行结束，但页面还显示 QA 或 Review

需要先区分不同状态：

| 状态层 | 回答的问题 | 不代表什么 |
|---|---|---|
| Requirement / Task | 需求整体或仓库交付走到哪一步 | 不代表模型此刻仍在线 |
| WorkItem / Lease | 工作是否可领取、运行、等待或已释放资源 | `CLOSED` 不代表需求已经 DONE |
| Operation | 用户这次提交或继续动作是否完成 | 不代表最终业务目标已完成 |
| AgentRun / 模型调用 | 某次模型调用是否在运行、成功或失败 | 调用返回成功不代表验收通过 |
| Heartbeat | 执行器是否有近期存活证据 | 没有心跳不能猜测为在线或空闲 |

三者都有不同层次的任务与执行概念。ASE 应通过只读 Projection 将这些事实解释清楚，而不是把“最后运行过哪个 Agent”当成当前交付阶段。这是当前架构要求，不是本次对在线页面正确性的验证。[A1]、[A2]、[A9]

## 八、ASE 当前实现与边界

| 能力 | 本次核查结论 | 不能扩大的表述 |
|---|---|---|
| Product 多轮讨论与人工批准 | 已接入生产入口 | 不代表 Product 能自行批准需求 |
| T047 复杂度分流和 Planner | 已实现简单 Fast Plan、复杂工作包/依赖/风险/验收矩阵 | 不代表复杂计划已经按 DAG 并行执行 |
| T048 主动知识闭环 | 已有受控检索、证据、知识缺口、批准恢复和工作流门禁 | 不代表所有知识都被正确理解，或所有原生 Trellis Skills 都会自动运行 |
| T049 增量知识索引 | 已有异步处理、缓存、发布、重试与退休隔离 | 不代表已实现可自主维护知识质量的 Curator Agent |
| T046 生产 Worker 接入 | Coder/QA/Reviewer 真领取、续约、结果接纳和下一角色发布 | 不代表上游会话和独立候选复核已全迁移，也不代表独立 fleet 已交付 |
| 每 Agent 模型与备用顺序 | 已实现显式选择和有序回退，支持不同 reasoning 路由 | 不代表任意失败都会换模型，或已按任务难度动态优化成本 |
| 独立 QA/Review | 已有不同身份、运行、上下文、工作树和同候选校验 | 不代表不同成员必然使用不同基础模型或不会共同漏判 |
| 多仓需求 | 已有联合产品/计划、仓库子交付和候选集验收 | 不代表跨仓事务、自动 merge 或生产部署 |
| 恢复 | 已有检查点、候选验证、范围批准和关联修复路径 | 不代表所有阻塞都可自动解除，或已保证模型调用严格 exactly-once |
| Manager 通用自修复 | 存在 `ManagerLeaderRecovery` 抽象与测试；本次未发现生产调用装配 | 不能说已能自主扩展 Skills/MCP、修复任意环境并提交 |
| Evaluation / Handoff | 底层能力存在 | 日常入口并未因此自动具备完整 Reporter 产品能力 |

依据：[A1]、[A3]–[A14]。

特别说明：上游存在“Provider 已返回、Stage Artifact 尚未落盘时进程崩溃”的重复调用/计费窗口。可靠恢复并不自动等于端到端每次外部模型调用只发生一次。[A11]

## 九、ASE 的优势、代价与未证实主张

### 9.1 已有实现支撑的差异化特点

**第一，知识和交付证据绑定。**

系统可以追溯某次需求依据哪份知识、哪个版本、哪些引用作出判断；知识缺口和人工解答能进入恢复链。相比单纯扩大 Prompt，这为长期项目和多项目团队提供了更明确的管理边界。[A4]、[A6]、[A7]

**第二，完成标准由程序检查。**

不是只看任务卡片是否变绿，而是检查实现、QA、Review 的候选版本、产物关系、验收覆盖和身份独立性。这是可具体验证的机制特点，而不是“Agent 更聪明”的主张。[A5]、[A8]

**第三，工作进度独立于某个模型会话。**

计划、代码现场、候选、失败结论、批准和证据由平台保存。换模型或进入新 Run 后仍可从已验证事实接续。模型仍需读取和理解上下文，但不必把长聊天记录当成唯一记忆。[A1]、[A2]、[A9]

**第四，多项目与多仓需求有明确组织边界。**

长期 Team 与项目知识分开，Repository 和 Requirement 的身份进入契约；多仓交付不仅是开多个聊天窗口，还要检查完整候选集合。它适合需要重复服务同一组织多个项目的场景。[A1]、[A2]

这些是 ASE 已实现的特点，不代表 Trellis 或 Multica 绝对无法通过扩展、Skills、Squad 或其他集成形成类似流程。

### 9.2 同时付出的代价

- **工程复杂度更高**：交付状态、队列状态、Operation、Artifact、审批、工作树都要保持一致。
- **运维负担更高**：本地 Git、依赖环境、MySQL、文件产物和进程生命周期需要协调备份与恢复。
- **简单任务的流程更重**：跳过 Planner 模型能减少部分开销，但产品、设计和验收链仍有成本。
- **严格校验可能增加等待**：缺少证据、范围不匹配或历史数据不一致都可能阻止推进；必须提供可理解的原因和安全恢复入口。
- **开发效率不等于 Agent 数量**：更多岗位可能增加调用费用、时延和交接错误，需要实际测量。

这些代价是架构分析，不是已经完成的三方性能比较。

### 9.3 目前不能宣称的优势

1. 不能说 ASE 的真实需求成功率一定高于 Trellis 或 Multica。
2. 不能说独立 QA/Reviewer 已消除幻觉、漏测或同模型共性错误。
3. 不能说 ASE 已比 Multica 更成熟地支持大规模并发和团队协作。
4. 不能说 ASE 已实现完整自主研发、自主环境修复和自动上线。
5. 不能说知识索引已证明能降低 Token 消耗或提升业务正确率。
6. 不能说 worktree、应用 policy 或内容哈希等价于强多租户隔离和完整安全认证。

现有优势应称为“机制和定位上的优势候选”。它们需要通过真实交付效果，转化为产品优势。

## 十、三者如何取舍与互补

### 10.1 按主要问题选择

| 当前主要问题 | 优先考虑 | 原因 |
|---|---|---|
| Agent 经常忘记仓库规范，任务上下文和经验散落 | Trellis | 直接围绕 Repo Spec、Task 和工作流改善开发过程 |
| 多个 Agent、项目和执行机器难以统一协调 | Multica | 工作台、Run、Squad 和 daemon 调度是其产品重心 |
| 需要追溯依据、岗位责任、验收版本和失败恢复 | ASE | 已把这些要求纳入软件交付数据与状态契约 |
| 希望开箱即用获得所有能力 | 不应仅凭本报告选定 | 三者部署、集成、权限和实际成功率需要小规模试点验证 |

这是适用性建议，不是绝对排名。

### 10.2 Trellis 与 ASE 的关系

两者可以在不同层面共存：

1. **开发 ASE 本身**：使用 Trellis 的规范、任务、检查和经验沉淀方法。
2. **ASE 服务的目标仓库**：发现并读取该仓库原有 `.trellis/spec/` 等工程规则，保留来源。
3. **ASE 运行时**：把选定要求实现为应用层门禁，检查证据和状态。

第三层不是对本机 `SKILL.md` 的自动批量执行。ASE 的 `WorkflowSkillDefinition` 将相关能力定义为 `deterministic_gate`，读取知识证据和持久交付事实，不通过名字授予 shell、数据库或额外 Agent 启动权限。[A5]

### 10.3 Multica 与 ASE 的潜在关系

分析上可以把 Multica 视作协作/执行接入层，把 ASE 视作软件交付控制层，但当前不能当成已有集成。

若未来集成，至少需要明确：

- Issue 与 Requirement、Run 与 AgentRun/WorkItem 如何映射。
- 哪一方拥有最终交付状态，不能让两边同时自由修改 `DONE`。
- 谁管理并发额度、租约、取消和重试，避免双重调度。
- Multica Runtime 的结果如何转换成 ASE 可验证 Artifact/Evidence。
- Skills、项目上下文、凭证和审批在哪一侧保存及授权。

简单地把 ASE 流程放进一段 Multica Agent Prompt，不会自动获得两者完整的可靠性保证。相反，如果两个系统各自重试同一任务，可能出现重复执行和重复计费。

## 十一、后续建设与验证建议

本节是建议，不代表本次已创建开发任务或已经实现。

### 11.1 建议优先级

| 优先级 | 方向 | 应交付的可观察结果 |
|---|---|---|
| P0 | 真实需求端到端闭环与恢复 | 一条需求正常交付，并通过 QA 打回、进程中断、知识等待等恢复场景；无须手改数据库推进 |
| P0 | 状态一致性和阻塞原因收口 | 需求页、成员队列、后台 Operation 与执行事实一致；明确当前角色、主要原因和下一步 |
| P1 | 上游 durable attempt 记录 | 能区分未调用、调用中、返回未封存和已接受结果，缩小重复调用/计费窗口 |
| P1 | 受控 Manager 自修复接入 | 预批准环境能力、有限重试、修复证据；代码修复仍走 Coder/QA/Reviewer；高风险动作交人工 |
| P1 | 多需求 Worker 并发部署 | 多个需求真正重叠执行，验证容量、独立工作树、重启、取消和租约 fencing |
| P1 | 知识效果评测 | 相同任务启用/禁用知识对照，观察错误率、返工和成本，而不仅是检索接口通过 |
| P2 | 面向用户的交付汇总 | 汇总改动、验收证据、风险、合并建议和存量恢复操作，不创造新 verdict |

Manager 自修复的目标应是“在预批准边界内恢复交付”，不是允许它自行扩大权限、安装任意外部能力或修改状态机来消除阻塞。

### 11.2 公平比较需要怎样的试验

建议选择单仓小改动、复杂模块改动、跨仓接口改动、知识依赖强的需求和中断恢复任务，使用同一基线、相近模型/预算和独立验收。

至少记录以下指标：

| 指标 | 目的 |
|---|---|
| 真实验收通过率与交付后回归率 | 区分“流程结束”和“产物正确” |
| 首次 QA/Review 通过率、返工次数 | 观察规划、知识和岗位分离的实际收益 |
| 人工介入次数与分钟数 | 检验是否真正减少人工救场，而非把工作转移给用户 |
| Token/调用成本与总交付耗时 | 检验多岗位带来的质量收益能否覆盖成本 |
| 中断后恢复成功率与重复执行率 | 检验持久化和恢复机制，而不只是正常路径 |
| 知识检索命中、正确引用及实际纠错情况 | 区分“读了知识”和“知识帮助做对事情” |
| 并发吞吐、目录冲突与状态误报 | 检验调度和隔离是否形成真实用户收益 |

对比应分别说明“各产品默认推荐配置”和“尽量统一模型/工具后的配置”。不能把一方默认能力与另一方高度定制的实现混为同一条件。ASE 的 Evaluation/ADR 能提供部分记录基础，但尚不构成现成的三方基准测试。[A13]

## 十二、容易产生的误解

| 误解 | 更准确的表述 |
|---|---|
| Trellis 只是 Prompt | 它还包含规范、任务、上下文、平台适配和本地 Channel runtime |
| Multica 只是看板 | 它已有 daemon、队列、并发、恢复、Squad 和共享 Skills |
| 有七个 Agent 就比单 Agent 强 | 需看岗位契约、上下文质量、验证独立性和实际收益 |
| 队列项完成就是需求完成 | 执行结束、候选验收和需求交付是不同事实 |
| T046 接入后就有完整并发服务 | 当前是逐角色队列接入；独立 fleet 和并发部署仍需建设 |
| 复杂 Planner 就是并行执行器 | Planner 形成计划；实际领取和执行由调度及执行服务负责 |
| 知识库上传后会自动变成可信规范 | 文档索引、事实确认、规范启用和学习发布是不同步骤 |
| 同一模型运行三个角色没有任何隔离 | 身份、上下文、工作树和权限仍可隔离，但推理错误可能相关 |
| 不同 Agent 就一定有独立判断 | 不同身份不是认知多样性证明；需模型策略和独立测试支持 |
| Manager 类存在就代表自愈已上线 | 还要有生产调用链、执行器、审批、证据和回归验证 |
| 有证据链就一定没有 Bug | 证据能说明检查了什么，不能保证要求和测试覆盖全部风险 |
| 代码有了就是服务已验证 | 合入、部署、在线流程验证和长期质量是不同里程碑 |

最终建议：ASE 应持续聚焦“组织知识驱动、证据约束、可恢复的软件交付”。Trellis 的工程方法和 Multica 的协作/运行管理都值得借鉴；最重要的下一步是用真实需求证明 ASE 能减少返工和人工介入，而不是只扩大角色或模块数量。

## 十三、资料来源

### 13.1 Trellis 第一方资料

| 编号 | 资料 | 本报告使用范围 |
|---|---|---|
| T1 | [Trellis 固定版本 README][T1] | 定位和总体能力 |
| T2 | [How It Works][T2] | Spec、Task、Journal 和研发流程 |
| T3 | [Channel][T3] | Worker、消息、事件、等待和恢复 |
| T4 | [Multi-platform][T4] | 平台适配差异 |
| T5 | [Memory Recall][T5] | 历史会话检索 |
| T6 | [Check 模板源码][T6] | 检查要求与执行边界 |
| T7 | [CLI package.json][T7] | 正式源码基线版本 |
| T8 | [Channel guard 源码][T8] | 默认 Worker 预算与生命周期约束 |

### 13.2 Multica 第一方资料

| 编号 | 资料 | 本报告使用范围 |
|---|---|---|
| M1 | [Multica 固定版本 README][M1] | 定位、部署与产品组件 |
| M2 | [Daemon Runtimes][M2] | 执行边界、并发和服务端数据范围 |
| M3 | [Issues][M3] | Issue 状态、Review 和协作 |
| M4 | [Runs][M4] | Run 生命周期、重试、恢复和 completed 语义 |
| M5 | [Skills][M5] | 共享指令、脚本、模板和参考资料 |
| M6 | [Squads][M6] | Leader、委派与成员协作 |
| M7 | [Autopilots][M7] | 计划与事件触发 |

### 13.3 ASE 当前本地代码与说明

以下链接是本机绝对路径，内容基线为 `9c21431`；工作目录未来更新后，应按该 Git 版本回看。正文未将所有架构文档里的历史设计都视为当前生产装配。

| 编号 | 资料 | 本报告使用范围 |
|---|---|---|
| A1 | [README][A1] | 最新流程、组织边界、已实现能力与非目标 |
| A2 | [总体架构][A2] | 控制、知识、执行、证据、工作树和存储边界 |
| A3 | [PlanningGate 源码][A3] | SIMPLE/COMPLEX 的确定性判断 |
| A4 | [Knowledge Skills 源码][A4] | 作用域、冻结知识、检索与引用校验 |
| A5 | [Workflow Gates 源码][A5] | 确定性门禁及证据约束 |
| A6 | [Knowledge Gaps 源码][A6] | 缺口、解答、批准和恢复契约 |
| A7 | [Knowledge Index 源码][A7] | 后台索引、缓存、发布和退休处理 |
| A8 | [Orchestration Runner 源码][A8] | 同候选 QA/Review、验收覆盖与状态流转 |
| A9 | [T046 Worker 运维说明][A9] | 生产接入范围、继续交付和回滚边界 |
| A10 | [Queued Worker / Supervisor 源码][A10] | 真实领取、串行角色执行与恢复 |
| A11 | [生产配置与运行说明][A11] | 模型路由、Manager 当前行为和重复调用窗口 |
| A12 | [Manager Leader Recovery 源码][A12] | 受控自修复抽象；不代表生产接入 |
| A13 | [Evaluation 与 Handoff][A13] | 指标、观察窗口和交付证据基础 |
| A14 | [Production Backend 源码][A14] | 当前生产执行装配 |

补充材料：[外部产品第一方来源核查笔记][R1]。该笔记保存更细的来源口径；本报告已包含独立阅读所需的主要结论和引用。

[T1]: https://github.com/mindfold-ai/Trellis/blob/e77ae89f648a78d5859fa2e8ac314655898421a5/README.md
[T2]: https://docs.trytrellis.app/start/how-it-works
[T3]: https://docs.trytrellis.app/advanced/channel
[T4]: https://docs.trytrellis.app/advanced/multi-platform
[T5]: https://docs.trytrellis.app/skills-market/mem-recall
[T6]: https://github.com/mindfold-ai/Trellis/blob/e77ae89f648a78d5859fa2e8ac314655898421a5/packages/cli/src/templates/trellis/agents/check.md
[T7]: https://github.com/mindfold-ai/Trellis/blob/e77ae89f648a78d5859fa2e8ac314655898421a5/packages/cli/package.json
[T8]: https://github.com/mindfold-ai/Trellis/blob/e77ae89f648a78d5859fa2e8ac314655898421a5/packages/cli/src/commands/channel/guard.ts
[M1]: https://github.com/multica-ai/multica/blob/8c4f4328f6e3baff08394b309034463b5db9d7af/README.md
[M2]: https://multica.ai/docs/daemon-runtimes
[M3]: https://multica.ai/docs/issues
[M4]: https://multica.ai/docs/tasks
[M5]: https://multica.ai/docs/skills
[M6]: https://multica.ai/docs/squads
[M7]: https://multica.ai/docs/autopilots
[A1]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/README.md
[A2]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/docs/architecture.md
[A3]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/src/ai_software_engineer/planning/gate.py
[A4]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/src/ai_software_engineer/knowledge/skills.py
[A5]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/src/ai_software_engineer/knowledge/workflow.py
[A6]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/src/ai_software_engineer/knowledge/gaps.py
[A7]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/src/ai_software_engineer/knowledge/index.py
[A8]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/src/ai_software_engineer/orchestration/runner.py
[A9]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/docs/t046-worker-operations.md
[A10]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/src/ai_software_engineer/work_queue/worker.py
[A11]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/docs/production-setup.md
[A12]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/src/ai_software_engineer/manager/leader_recovery.py
[A13]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/docs/evaluation.md
[A14]: /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/src/ai_software_engineer/manager/production_backend.py
[R1]: /Users/zhangjunshuai/Documents/Codex/2026-08-31/referenced-chatgpt-conversation-this-is-an/research/multica-trellis-primary-sources-2026-09-20.md
