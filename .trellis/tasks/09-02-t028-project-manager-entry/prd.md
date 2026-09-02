# T028 PRD：Project Request、Project Manager 与产品设计阶段

## Goal

让使用者先选择一个本地项目目录，由 Project Manager 完成 Project Preparation；只有项目注册、
外置 workspace、ProjectProfile 和项目级规范准备成功后，才进入 Product Agent 需求讨论。平台把
讨论沉淀为 Product Spec，再由 Solution Designer Agent 形成 Technical Design，Planner Agent
形成整体 Execution Plan，之后才创建并启动 Coder → QA → Reviewer 的交付 Task。

## What I already know

- AgentProfile 属于组织；项目 sidecar 只保存 ProjectProfile、Assignment 和运行事实。
- 项目尚未投入真实使用，可以把当前 sidecar 结构作为唯一架构基线，不设计旧 `agents/` layout
  的迁移或兼容流程。
- 单个 Task 内仍必须串行执行 `Coder → QA → Reviewer`，Project Manager 不能绕过 QA/Review。
- 现有 `ProjectWorkspaceRegistry`、`ProjectProfile`、`SpecCompiler`、`RuntimeWorkspaceBinder`、
  `PortfolioScheduler`、`ModelRouter` 和 `RuntimeSession` 已提供底层能力，但缺少统一 application
  service 与面向用户的 CLI 入口。
- 当前 `Task` 在创建时就要求完整验收标准，因此原始用户想法不能直接等同于 Task；需要先有
  独立的 Project Request 生命周期，Product Spec 冻结后再派生 Delivery Task。
- “Producter Agent” 统一命名为 Product Agent；“Designer Agent” 在本项目中明确指 Solution
  Designer Agent（技术方案设计），不是 UI/UX 视觉设计。
- Project Manager 是组织级团队领导 Agent；项目准备、阶段推进、提交调度与交付等权限通过它的
  policy-bound Skills 暴露，Skill 内部调用 deterministic application services 与 stores。
- Planner Agent 负责执行计划，可通过 Scheduler/ModelRouter preview Skills 检查可行性；具体分配
  只能由 Project Manager 的 commit-dispatch Skill 复核并持久化。

## Assumptions (temporary)

- v0.1 先实现单项目、单 Project Request、单 Delivery Task；一个需求拆成多个并行 Task 属于后续。
- 统一入口必须由 typed request/result contract 驱动，支持 dry-run/plan 与 execute 两个阶段。
- 项目规范冲突、缺少组织成员/模型策略或不安全路径时 fail closed，并输出明确的人工处理信息。

## Confirmed Decisions

- Product Spec 达到 `READY_FOR_REVIEW` 后必须经过一次明确的用户确认；只有引用该精确版本与摘要的
  `ProductSpecApproval(APPROVED)` 才能解锁 Technical Design。用户要求修改时，Product Agent 产出
  新版本，旧版本与决定继续保留，不能原地改写。
- Project Manager Agent 是团队领导；它的 Skills 是 deterministic application services 的受控
  facade。用户只需要理解团队领导，不需要理解一个并列的 Project Manager Service 角色。
- Planner 是 Agent，负责提出 Execution Plan，并可使用只读 Scheduler/ModelRouter preview Skills；
  Project Manager 使用 commit-dispatch Skill 重新校验后，才创建 concrete Agent、Lease、provider
  和 model 事实。任何 Agent 都不能绕过 Skill 自我分配。
- Prepare 只产生组织规则 + 项目规则的 baseline。Product Spec 派生 Delivery Task 后必须加入
  Task constraints 再编译一次；两次编译都遇到冲突即路由人工，不能按优先级静默覆盖。

## T028 Delivery Slice

T028 冻结并实现上游阶段的 typed contracts、完整性摘要、用户审批门禁和 Delivery Task 派生守卫，
为后续 service/Agent/CLI 组合提供稳定 seam。执行层拆为后续连续任务：

- T029：Project Preparation 与 Project Manager Agent Skills；
- T030：Product Agent 对话、Product Spec 版本与确认循环；
- T031：Solution Designer、Planner、Scheduler/ModelRouter 组合；
- T032：单一项目入口、resume 与完整 intake-to-delivery E2E；
- T033：按实际交付需求决定是否增加 read-only Reporter Agent。

这种拆分不改变最终产品流程；它避免在 contract 尚未验证前，把五个阶段塞进一个不可恢复的
巨型入口。

## Requirements (evolving)

- 新建 Project Manager Agent 的 typed Skills，编排现有 application services 而不是复制领域逻辑；
  Agent 只持有获准的 Skill，不能直接拿状态、权限或资源分配 store 写端口。
- 第一阶段输入只有绝对项目目录；Project Manager 必须先完成 Project Preparation，再开放需求讨论。
- Project Preparation 自动注册/reopen sidecar、发现 ProjectProfile、校验组织绑定，并编译不依赖
  Task 的项目级规范；Task-specific constraints 只能在 Product Spec 派生 Task 后二次编译。
- Product Agent 在 prepared project context 中接收用户的原始需求，负责澄清并形成结构化需求与
  验收标准。
- 建立独立于 Delivery Task 的 Project Request 状态和不可变需求对话/决策记录。
- 自动创建/重开项目 sidecar，发现 ProjectProfile，并绑定 organization/project runtime。
- Product Agent 输出 schema-valid Product Spec；Solution Designer Agent 只消费已冻结的 Product
  Spec 与 ProjectProfile/项目规范，输出 Technical Design（包含实施计划、测试策略与风险）。
- Planner Agent 只消费已验证 Product Spec、Technical Design、ProjectProfile 和组织能力事实，
  输出 Execution Plan（阶段顺序、检查点、所需角色/能力、风险和 BrainTier 建议）。
- Planner 可用 PortfolioScheduler/ModelRouter preview Skills 产生可行性证据；Project Manager 的
  commit-dispatch Skill 用同一确定性引擎复核并选择具体 Agent、Lease、provider/model。两个 Agent
  都不能直接修改 Assignment。
- Product Spec 与 Technical Design 冻结后，Project Manager 才生成 Schema-valid Delivery Task，
  并将二者作为 Coder、QA、Reviewer 的 required Context/artifact lineage。
- Coder 按 Technical Design 实现；QA 同时验证 Product Spec 验收标准和 Technical Design 测试策略；
  Reviewer 同时审查需求符合性、技术方案符合性和代码质量。
- Product/Designer/Coder/QA/Reviewer 通过持久化 artifact 交流，禁止共享隐式对话记忆。
- Reporter 若启用，只能读取已验证的阶段 artifact 与 Handoff，按用户需要生成展示结果；它不能
  修改事实、verdict 或掩盖失败。v0.1 优先复用 deterministic Handoff/Projection，再决定是否需要
  生成式 Reporter Agent。
- 规范冲突必须路由人工；任何 Agent 不得自行选择冲突规则。
- README 改为描述当前产品、真实入口、已完成能力和剩余边界；历史任务细节保留在 Archive。
- sidecar 仅采用当前组织级 Agent 架构，不保留旧 layout 迁移产品承诺。

## Acceptance Criteria (evolving)

### T028 contract foundation

- [ ] ProjectPreparation、ProjectRequest、ProductSpec、ProductSpecApproval、TechnicalDesign 和
      ExecutionPlan 都有 frozen Pydantic model、canonical wire payload、SHA-256 integrity 与
      Draft 2020-12 Schema。
- [ ] Product Spec 只能由引用 exact spec ID + digest 的用户 APPROVED record 解锁设计；
      `REQUEST_CHANGES`、过期 digest 或跨 Request approval 必须 fail closed。
- [ ] Technical Design 完整覆盖 Product Spec requirement IDs 与 acceptance IDs；Execution Plan
      保持 v0.1 串行 Coder → QA → Reviewer，且不能包含 concrete Agent/provider/model/Lease。
- [ ] 只有 identity、integrity、approval、coverage 全部一致的阶段链才能派生现有 NEW Delivery Task；
      Task 验收标准精确来自 Product Spec，不由 Planner 或 Coder 改写。
- [ ] stage contract 的正反例、schema drift、非法时间/ID/未知字段和跨项目引用均有测试。

### End-to-end target (T029–T032)

- [ ] 给定合法 fixture 项目与原始需求，Project Manager 可确定性地产生 workspace、profile、
      Project Request 和 Product Agent 上下文，而不是提前伪造 Delivery Task。
- [ ] Project Preparation 未完成或发生项目级规范冲突时 Product Agent 不启动；目标项目保持干净。
- [ ] Product Agent 产出带 requirement/acceptance IDs 的 Product Spec；Designer 产出可追溯到这些
      IDs 的 Technical Design。
- [ ] Planner 产出 Execution Plan；具体 Agent/模型分配只能来自 Scheduler/ModelRouter typed decision。
- [ ] 只有冻结的 Product Spec 和 Technical Design 才能派生 NEW Delivery Task。
- [ ] execute 模式通过现有 Runtime/Orchestrator 启动串行 Coder、QA、Reviewer，不跳过角色边界。
- [ ] 重复提交同一稳定 intake 不重复创建项目身份或 Task；冲突输入 fail closed。
- [ ] 目标项目目录不出现平台数据库、日志、artifact 或 AI 配置。
- [ ] 非法路径、规范冲突、缺失组织配置和运行失败均有 typed error/result 与测试。
- [ ] CLI 帮助和 README 只要求用户理解项目目录、需求与必要的组织配置。

## Definition of Done

- T028 contract/unit tests、Ruff、strict Mypy、offline build 全部通过；
- README、domain context 与 `.trellis/spec/` 同步；
- 不引入单 Task DAG、消息队列、向量库、自动 merge 或生产部署。

## Out of Scope

- 后台常驻进程、分布式队列和多租户；
- 自动修改或合并保护分支；
- 自动解决组织规范与项目规范冲突；
- 旧 sidecar layout 的迁移工具或兼容承诺。
- 一个 Project Request 自动拆分为多个 Delivery Task 或 Task DAG。

## Technical Notes

- 预计复用 `ProjectWorkspaceRegistry.register`、`ProjectProfile.discover`、
  `RuntimeWorkspaceBinder.bind`/`compose_runtime_config` 和现有 Task repository。
- 需要先定义 application-service signature、输入/输出 Schema、idempotency key、错误矩阵以及
  Good/Base/Bad 测试，再实现 CLI。

## Research Notes

### Existing seams

- `cli.py` 当前只有 task/evaluation/handoff 命令，所有 workspace 与 RuntimePaths 由使用者手工提供；
- `ProjectWorkspaceRegistry.register` 已提供稳定项目身份、外置 sidecar 和幂等重开；
- `ProjectProfile.discover`、`SpecCompiler.compile`、`RuntimeWorkspaceBinder.bind` 已覆盖项目发现、
  冲突路由和 Runtime 路径绑定；
- `RuntimeSession.run_task` 已能调用现有串行 Orchestrator，但持久 WorkQueue application loop 和
  real model tool-execution composition 尚未完成。
- 当前 `Task` 必须在创建时已有 acceptance criteria；因此 Product Agent 阶段不能被硬塞进现有
  Task 状态机，否则会导致“先有验收标准，再讨论需求”的循环依赖。

### Feasible approaches

**Approach A：打开项目，内部先 Prepare 再进入需求对话（已选择）**

- 用户调用 `ase project open --project ...`；
- Project Manager 内部先原子完成 Project Preparation，成功后才开放 Product Agent 对话；
- 对话、Product Spec、Technical Design、Execution Plan 和 Delivery 使用同一 Project Request；
- 用户入口简单，同时保证 Product Agent 一开始就理解项目事实和规范。

**Approach B：要求用户显式 Prepare 后再 Chat**

- `ase project prepare` 产生 workspace/profile，`ase project chat` 再进入需求；
- 优点是每一步显式；缺点是继续把内部编排责任推给使用者，不符合“项目经理接单”的产品预期。

**Approach C：后台队列/daemon**

- 用户提交后由常驻 scheduler 自动拉取；
- 适合未来多项目并发，但现在会提前引入进程生命周期、队列恢复和运维复杂度，不属于 T028。

## Expansion Sweep

- Future：同一个 ProjectManager service 可被 CLI、HTTP API 和 Dashboard 提交入口复用；未来再接
  持久 WorkQueue loop，不改变 intake contract。
- Related：plan-only、execute、resume 必须使用同一 intake identity，不能创建三套 Task。
- Failure：重复提交、项目事实漂移、规范冲突、组织配置缺失和 Agent failure 都必须返回可恢复的
  typed checkpoint，不允许留下半初始化 workspace 或伪造成功。

## Proposed end-to-end flow

```text
User selects project directory
          ↓
Project Manager Agent: prepare_project Skill
          ↓ prepared ProjectProfile + project-level spec
User ↔ Product Agent
          ↓ Product Spec（可评审、版本化）
   Solution Designer Agent
          ↓ Technical Design（实施计划、测试策略、风险）
      Planner Agent
          ↓ Execution Plan（阶段、能力、风险、BrainTier 需求）
Project Manager Agent: commit_dispatch Skill
          ↓ Scheduler/ModelRouter engines → Delivery Task + Assignment/ModelSelection
         Coder
          ↓ implementation-report + candidate
           QA
          ↓ qa-report
        Reviewer
          ↓ review-report
   Handoff / optional Reporter
          ↓ 用户需要的交付视图
```

Project Manager 是用户看到的团队领导 Agent，但其 authority 来自 policy-bound Skills 背后的
deterministic services；Agent 不能绕过 Skill 直接调用其他 Agent、修改状态或分配资源。Reporter
即使后续成为 Agent，也只是 read-only presenter；阶段事实仍以 Product Spec、Technical Design、
Execution Plan、Implementation、QA、Review 和 Handoff 为准。
