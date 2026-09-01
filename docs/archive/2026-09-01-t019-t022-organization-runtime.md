# T019–T022 Organization Scheduling and Runtime Binding

## 阶段事实

- 日期：2026-09-01
- 范围：T019、T020、T021、T022
- 实现提交：`8d76ce2`
- 基线提交：`ea7f22e`
- 里程碑状态：M5 已完成，M6 从 T023 evidence capture 开始
- 质量基线：344 tests、Ruff check、Ruff format、strict Mypy（112 个源码文件）、offline package
  build、`git diff --check` 全部通过

本阶段把 T018 的组织 Workforce 领域契约连接成可执行的本地 application seams：组织可以按
能力、优先级、风险和容量为工作分配长期 Agent；每次 Agent Run 独立选择模型；任意目标项目可
被只读发现并绑定到外置 sidecar；规范冲突不能由 Agent 静默裁决；Runtime allocation 在启动
Agent 前校验全部组织、项目、模型、Context 和 Lease 事实。

## T019 — PortfolioScheduler 与 ModelRouter

新增：

- `src/ai_software_engineer/scheduling/portfolio.py`
- `src/ai_software_engineer/scheduling/model_router.py`
- `src/ai_software_engineer/scheduling/models.py`
- `tests/scheduling/test_scheduler.py`

形成的能力：

1. `PortfolioScheduler.match/schedule` 对 immutable snapshots 产生 typed Assignment/Lease decision；
2. batch 内新 Lease 立即计入后续 capacity，避免同一轮超配；
3. READY、future retry、waiting、closed、Agent active/role/capability/capacity 与 no-self-review 均有
   稳定 rejection code；
4. WorkItem 以 ready、priority、risk、age、Task ID 确定排序，决策和 ID 可重放；
5. `ModelRouter.route` 应用 default tier、risk floor、complexity、历史失败和 context capacity，选择
   最小满足约束的 route；无可用 route 返回 typed refusal，不调用 provider。

边界：T019 是 pure decision seam，不是持久化 WorkQueue、分布式 Scheduler 或后台 worker。

## T020 — ProjectProfile

新增：

- `src/ai_software_engineer/project_profile.py`
- `schemas/project-profile.schema.json`
- `tests/project_profile/test_discovery.py`

形成的能力：

1. 从给定 project root 只读发现语言 markers、build systems、Git/VCS revision 和 project-native
   rule sources；
2. 原生规则记录 root-relative path、`project://` URI、content SHA 和 exact source revision；
3. profile identity 排除 `observed_at`，相同项目事实产生稳定 digest；
4. root 缺失、symlink escape、非 UTF-8 规则、Git metadata/revision 不一致均 fail closed；
5. 未知技术事实保持 unknown/empty，不执行项目命令，不猜测测试入口。

## T021 — SpecCompiler 与人工冲突治理

新增：

- `src/ai_software_engineer/spec_compiler.py`
- `schemas/spec-conflict.schema.json`
- `schemas/spec-resolution.schema.json`
- `tests/spec_compiler/test_compiler.py`

形成的能力：

1. `SpecRule` 显式表达 platform hard、organization、project 和 Task constraint；
2. `SpecCompiler.compile` 自动加入 Task constraints，并验证 project rule 必须由 ProjectProfile 的
   URI/hash 来源支持；
3. 相同 scope/key 的不兼容结构化值生成 immutable `SpecConflict`，返回
   `WAITING_HUMAN` route，不按层级或 priority 静默覆盖；
4. `SpecResolution` 必须包含 actor、rationale、evidence 和 exact conflict identity；hard safety
   不能被较弱规则放宽；
5. `FileSpecRecordStore` 用 canonical JSON、SHA、atomic rename 和 immutable put 保存冲突与决定；
6. 成功的 `CompiledSpec` 以唯一 required `compiled.spec` ContextSource 进入运行 Context。

边界：Markdown 规范正文保留 URI/hash 引用，不做模型驱动的语义解析；只有显式结构化规则参与
自动冲突判断。

## T022 — Organization/Project Runtime Binding

新增或修改：

- `src/ai_software_engineer/runtime_workspace.py`
- `src/ai_software_engineer/runtime.py`
- `schemas/runtime-workspace-binding.schema.json`
- `tests/runtime_workspace/test_binding.py`
- `tests/runtime_workspace/test_allocation.py`

形成的能力：

1. `OrganizationWorkspace` 原子建立固定 `agents/`、`model-policies/`、`work-items/`、`leases/`、
   `metrics/` layout；
2. `RuntimeWorkspaceBinding` 将 organization、project root、T017 sidecar、ProjectProfile 与固定
   RuntimePaths 连接，三类 root 不得重叠；
3. binding 和 profile 以 immutable 记录保存；重开时重新校验 organization/project manifest、
   current project facts 和所有 SHA；
4. `FileOrganizationWorkforceStore` 在 organization workspace 保存带 envelope SHA 的
   AgentProfile/ModelPolicy；Project 不复制 Agent 本体；
5. `RuntimeWorkforceResolver` 验证 WorkItem、Assignment、active Lease、Agent、ModelPolicy、
   ModelSelection、CompiledSpec 和 persisted Context，返回完整 `AgentRunAllocation +
   AgentDefinition`；
6. `RuntimeSession` 可接收 resolved definitions 和 bound project root，Task repository 漂移时拒绝
   运行；多模型角色集合使用稳定 identity 进入 evaluation case。

边界：Python composition seam 已完成，当前 CLI 仍要求显式 sidecar paths，不会自动创建
Assignment/Lease 或启动跨 Task WorkQueue loop。

## 不变量确认

1. Knowledge belongs to the organization, not the agent：ProjectProfile、CompiledSpec、冲突、
   resolution、workforce 和 binding 都是可持久化、可校验的组织事实；
2. No agent may be the sole judge of its own work：Scheduler 在 Assignment 边界拒绝同一 Task 历史
   的跨角色 Agent 复用；Task 内仍固定 Coder → QA → Reviewer；
3. Agents communicate through verifiable artifacts, not shared assumptions：CompiledSpec 以 exact
   URI/SHA 进入 persisted Context，Runtime allocation 不接受隐式会话；
4. target project 保持干净：源码目录、Project sidecar 和 organization workspace 互不重叠，平台
   metadata 不写进目标项目；
5. Scheduler 不迁移 TaskStatus，SpecCompiler 不自行解决冲突，Runtime resolver 不调用模型。

## 验证证据

在实现提交前运行：

```text
uv run pytest                         344 passed
uv run ruff check .                  passed
uv run ruff format --check .         232 files already formatted
uv run mypy src tests                112 source files, no issues
uv build --offline                   sdist + wheel built
git diff --check                     passed
```

测试覆盖正常、非法、边界、篡改、重放和跨对象 identity mismatch；不依赖 provider 网络、容器或
外部数据库。

## 剩余工作与下一入口

M6 仍需完成：

1. T023：封存 command、diff、test 和 Agent usage evidence；
2. T024：把 Coder/QA/Reviewer 接入 typed、policy-bound tool protocol；
3. T025：在 Python、Java、Go、TypeScript fixture/真实项目上完成端到端串行交付；
4. 持久化 WorkQueue/scheduler application service 与 CLI workspace 自动 binding；
5. T026–T027：durable projection/read API 与只读可视化工作台。

继续禁止单 Task 并行 DAG、共享可变 Agent session、向量库、分布式队列、自动 merge 保护分支和
自动生产部署。
