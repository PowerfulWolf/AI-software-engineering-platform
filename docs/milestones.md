# v0.1 开发里程碑与第一批可执行任务

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

## 第一批可执行任务

| ID | 任务 | 交付物 | 验收标准 | 依赖 |
|---|---|---|---|---|
| T001 | 初始化 Python 包与 CLI 骨架 | `pyproject.toml`、`runtime/cli.py` | `--help` 可运行，pytest 可发现 | M0 |
| T002 | 实现 Task/Agent/Artifact Pydantic 模型 | `runtime/domain/*` | 通过对应 JSON Schema 的正反例 | T001 |
| T003 | 实现 SQLite repository 与事件日志 | `runtime/store/*` | 事务写入、幂等 event、重启读取 | T002 |
| T004 | 实现状态机 reducer/guard | `runtime/orchestrator/state_machine.py` | 覆盖所有迁移和非法迁移 | T003 |
| T005 | 实现 ArtifactStore | `runtime/artifacts/*` | 原子写入、sha256、父子关系、不可变 | T002/T003 |
| T006 | 实现 Git worktree manager | `runtime/git/*` | fixture repo 中创建三角色 worktree，路径 allowlist 生效 | T001 |
| T007 | 实现 Context Builder/Router | `runtime/context/*` | 生成稳定 manifest，脱敏并限制预算 | T002/T006 |
| T008 | 实现 FakeAgentAdapter | `runtime/agents/fake.py` | 可注入成功、QA FAIL、Review REJECT、超时 | T002 |
| T009 | 实现 Orchestrator happy path | `runtime/orchestrator/runner.py` | fixture Task 走到 DONE 并生成四类 artifact | T004–T008 |
| T010 | 实现失败路由与恢复 | `runtime/orchestrator/retry.py` | attempt 上限、分类路由、重启恢复测试 | T009 |
| T011 | 接入真实 AgentAdapter | `runtime/agents/openai_compatible.py` | fake/real 共用 request/response contract | T008/T009 |
| T012 | 实现 metrics、ADR 和交付包 | `runtime/evaluation/*` | 从事件流重算 ADR，输出 handoff bundle | T009/T010 |

## 第一批任务的执行顺序

`T001 → T002 → T003 → T004/T005/T006 → T007 → T008 → T009 → T010 → T011 → T012`。

每完成一个任务，都先运行 contract tests，再更新 `.trellis/spec/`；不要在 T009 之前引入并行调度、队列或向量库。
