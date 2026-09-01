# v0.1 开发里程碑与第一批可执行任务

> 实施状态：T001–T018 已完成，T019 开始实现组织级 Scheduler/ModelRouter；
> 目标项目与外置 AI workspace 已有稳定绑定。M0–M4 的
> v0.1 核心库退出条件已通过自动化测试验证。T014 提供配置驱动的串行运行入口，T015 提供
> fail-closed 命令执行端口，T016 将其绑定到 role worktree 生命周期。
>
> 已完成阶段、逐任务验证基线和提交证据见
> [`docs/archive/2026-09-01-v0.1-foundation-t001-t017.md`](archive/2026-09-01-v0.1-foundation-t001-t017.md)。

## 里程碑

### M0 — Bootstrap（设计基线）

退出条件：README、AGENTS、`.trellis/spec/`、四类 artifact Schema、状态机和第一批任务清单已入库；所有契约可由 JSON Schema 解析。

### M1 — Domain + Persistence

实现 Task/Agent/Artifact 数据模型、SQLite repository、事件日志和 Schema 校验。

退出条件：状态迁移单元测试覆盖合法/非法路径；artifact 可原子写入并按 ID 读取。

### M2 — Git + Context

实现 Git worktree manager、路径/命令 policy、Context Builder/Router 和 manifest。

退出条件：可从 fixture repo 创建/销毁三类 worktree；越权写入和路径穿越被拒绝；相同输入 manifest 稳定。

### M3 — 串行 Agent Loop

实现 fake AgentAdapter、Orchestrator happy path 和 QA/Review retry path，再接入一个真实模型 adapter。

退出条件：一个 fixture Task 走通 `NEW → ... → DONE`；QA FAIL 和 Review REJECT 都能回到 Coder；进程中断可恢复。

### M4 — Evaluation + Human Handoff

实现 metrics emitter、ADR 计算、交付包和 `BLOCKED` 摘要；补充 5–10 个真实/合成 evaluation cases。

退出条件：指标可从事件流重算；人工可在不读内部日志的情况下理解并处理 BLOCKED/DONE。

### M5 — 组织 Workforce、任意项目接入与规范治理

Agent 由组织长期拥有，通过 Assignment/Lease 服务多个 Project；模型按 Run 的风险和复杂度
动态分配。平台从“绑定一个 Git fixture”推进到“给定任意本地项目即可安全接入”：项目状态
进入外置 sidecar，AgentProfile/ModelPolicy/WorkQueue 留在组织 workspace。项目规范冲突进入
`WAITING_HUMAN` 并释放 Lease，禁止 Agent 静默选择。

### M6 — 可执行交付

将受控命令、Git inspection、模型 tool protocol 和 evidence capture 接入真实 Coder/QA/Reviewer
运行，完成一个目标项目的可复核交付；单 Task 内仍保持串行，不自动 merge 保护分支。组织层
可在 T019 后有界并发多个相互隔离 Task。

### M7 — Agent 工作可视化

先建立只读事件投影与本地 read API，再实现 Task board、Run timeline、Agent detail 和 Human
inbox。可视化只消费 durable StateEvent、AgentRunEvent、Context、Artifact、Evidence 和
Handoff，不成为第二个状态写入者。详细设计见 [`docs/visualization.md`](visualization.md)。

## 第一批可执行任务

| ID | 任务 | 交付物 | 验收标准 | 依赖 |
|---|---|---|---|---|
| T001 | 初始化 Python 包与 CLI 骨架 | `pyproject.toml`、`src/ai_software_engineer/cli.py` | `--help` 可运行，pytest 可发现 | M0 |
| T002 | 实现 Task/Agent/Artifact Pydantic 模型 | `src/ai_software_engineer/domain/*` | 通过对应 JSON Schema 的正反例 | T001 |
| T003 | 实现 SQLite repository 与事件日志 | `src/ai_software_engineer/store/*` | 事务写入、幂等 event、重启读取 | T002 |
| T004 | 实现状态机 reducer/guard | `src/ai_software_engineer/orchestration/state_machine.py` | 覆盖所有迁移和非法迁移 | T003 |
| T005 | 实现 ArtifactStore | `src/ai_software_engineer/artifacts/*` | 原子写入、sha256、父子关系、不可变 | T002/T003 |
| T006 | 实现 Git worktree manager | `src/ai_software_engineer/git/*` | fixture repo 中创建三角色 worktree，路径 allowlist 生效 | T001 |
| T007 | 实现 Context Builder/Router | `src/ai_software_engineer/context/*` | 生成稳定 manifest，脱敏并限制预算 | T002/T006 |
| T008 | 实现 FakeAgentAdapter | `src/ai_software_engineer/agents/fake.py` | 可注入成功、QA FAIL、Review REJECT、超时和 typed failures | T002/T007 |
| T009 | 实现 Orchestrator happy path | `src/ai_software_engineer/orchestration/runner.py` | fixture Task 走到 DONE 并生成四类 artifact | T004–T008 |
| T010 | 实现失败路由与恢复 | `src/ai_software_engineer/orchestration/retry.py` | attempt 上限、分类路由、重启恢复测试 | T009 |
| T011 | 接入真实 AgentAdapter | `src/ai_software_engineer/agents/openai_compatible.py` | fake/real 共用 request/response contract | T008/T009 |
| T012 | 实现 metrics、ADR 和交付包 | `src/ai_software_engineer/evaluation/*` | 从事件流重算 ADR，输出 handoff bundle | T009/T010 |
| T013 | 组装离线 CLI/runtime 入口 | `src/ai_software_engineer/cli.py` | 可创建/查看 Task、重算 evaluation、生成 handoff，错误 fail closed | T003/T012 |
| T014 | 组装配置驱动的 Task run | `src/ai_software_engineer/runtime.py`、`ase task run`、RuntimeConfig Schema | 真实 adapter 与 fake adapter 共用 composition seam；自动记录 CaseStarted/AgentRun；缺少密钥、非法配置和终态 Task fail closed | T010–T013 |
| T015 | 实现受控命令执行器 | `src/ai_software_engineer/execution.py`、命令契约测试 | argv allowlist、固定 worktree cwd、最小环境、超时进程组终止和输出截断均 fail closed | T006/T014 |
| T016 | 接入 role worktree 与受控执行生命周期 | `src/ai_software_engineer/role_workspace.py`、组合契约测试 | 同角色 AgentDefinition 才能绑定 manager-owned worktree；命令 cwd 固定；dirty cleanup 保留现场 | T006/T015 |
| T017 | 建立外置 Project Workspace 注册与初始化 | `src/ai_software_engineer/project_workspace.py`、workspace Schema、contract tests | 任意本地项目获得稳定 sidecar；不复制源码、不污染目标项目；幂等和边界 fail closed | T016 |
| T018 | 组织级 Agent workforce 与 run-scoped model 契约 | `workforce.py`、workforce Schema、ADR、sidecar v0.2 | Agent 不归 Project；Assignment/Lease/WorkItem/ModelPolicy/RunDemand 可校验；等待不等于 BLOCKED | T017 |
| T019 | PortfolioScheduler 与 ModelRouter | scheduler/model router ports + deterministic fake | capability/priority/age/risk/capacity 可重放分配；自审和超容量拒绝；等待释放 Lease | T018 |
| T020 | 发现 ProjectProfile 与项目原生规范 | `project_profile.py`、native-rule index、profile Schema | 识别语言/构建/VCS/规范来源并保存 URI/hash；未知或冲突事实不猜测 | T017/T018 |
| T021 | SpecCompiler 与人工冲突治理 | `spec_compiler.py`、`spec-conflict` artifact、resolution event | 三层规范可审计合并；工程冲突进入 `WAITING_HUMAN`，终止时才 BLOCKED | T020 |
| T022 | Runtime 绑定 organization/project workspace | Runtime/CLI composition tests | 代码 cwd/sidecar/组织 workforce 分离；AgentRunAllocation 连接 Assignment、Model 与运行事实 | T019/T021 |
| T023 | 命令、diff、测试与 Agent usage evidence capture | `evidence/`、`runs/` durable contracts | 每次运行产出可定位、脱敏、带 SHA 的证据；超时/拒绝也可回放 | T015/T022 |
| T024 | Coder/QA/Reviewer tool protocol | typed tool port + fake integration | Agent 只能通过 policy-bound argv/tool 调用，不能从自由文本执行 shell 或修改 verdict | T016/T019/T023 |
| T025 | 真实目标项目串行交付 | fixture matrix + e2e | Java/Go/TS/Python 项目完成 candidate→QA→Review；组织可调度下一个 READY Task | T020–T024 |
| T026 | 事件驱动 RunProjection 与只读 read API | projection models/API contract | 重算 Task/WorkItem/Agent/Model/Lease timeline；API 不迁移状态、不写 verdict | T012/T018/T022/T023 |
| T027 | 本地 Agent 工作可视化 dashboard | Task board、team capacity、timeline、agent detail、human inbox | 同时看到交付/调度状态、模型理由、成本、证据、等待和冲突 | T026 |

## 第一批任务的执行顺序

`T001 → ... → T017 → T018 → T019 → T020 → T021 → T022 → T023 → T024 → T025 → T026 → T027`。

每完成一个任务，都先运行 contract tests，再更新 `.trellis/spec/`。T019 只实现单进程、有界、
Lease 驱动的跨 Task 调度；禁止把单 Task 改成并行 DAG，也不引入消息队列或向量库。可视化必须
先消费 durable facts，不能反向驱动 Agent。
