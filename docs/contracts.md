# 角色、权限与 Artifact 契约

## 1. 角色总览

下表是已经进入 Task delivery runtime 的四个岗位，即 `AgentRole`。组织长期成员可声明的
`OrganizationRole` 还包含 `project_manager/product/designer/planner`；这些上游岗位不能被
伪装成 delivery `AgentRole` 以绕过各自的 stage/context/approval 契约。

| 角色 | 读取 | 写入 | 可执行 | 不能做 | 输出 |
|---|---|---|---|---|---|
| Orchestrator | Task、全部 artifact、策略和 Git 元数据 | 状态事件、artifact 索引、运行元数据 | 受 allowlist 的 Git/测试/Agent 启动 | 不写业务代码，不替代 Reviewer | 状态迁移、路由决定 |
| Coder | 任务上下文、规范、相关代码、QA/Review findings | 生产代码、单元测试、implementation-report | lint、unit test、受限构建 | 修改 verdict、修改 Trellis 规则、访问 secrets | commit + implementation-report |
| QA | PRD、验收标准、候选 diff、生产代码、测试规范 | QA 测试目录、qa-report | 测试、静态检查、只读构建 | 修改生产代码、批准代码、改写 Coder artifact | qa-report |
| Reviewer | PRD、plan、diff、implementation-report、qa-report、规范 | review-report（仅 artifact store） | 只读检查、测试复跑 | 修改仓库、修改 QA verdict、直接 merge | review-report |

权限必须由机器可验证的 policy 表达；自然语言 prompt 只是解释，不是授权来源。

## Project Manager、Agent Skills 与上游交接

Project Manager 是用户看到的组织级团队领导 Agent。项目准备、阶段推进、提交调度、失败路由和
交付通过 typed、policy-bound Skills 执行；Skill 背后是确定性 application service 与最小 ports，
而不是 Prompt 中的自由授权。Planner 可以调用只读 Scheduler/ModelRouter preview Skills 检查计划
可行性，但 preview 不写 Assignment/Lease/ModelSelection；只有 Project Manager 的
`commit_dispatch` Skill 重新校验当前 facts 后才能提交具体分配。

进入现有 TaskOrchestrator 前，上游交接链固定为：

```text
ProjectPreparation → ProjectRequest → ProductSpec + ProductSpecApproval
                   → TechnicalDesign → ExecutionPlan → NEW Task
```

Product Agent 不能批准自己的 Product Spec；用户 Approval 必须引用精确 spec ID 与 SHA-256。
TechnicalDesign 必须精确覆盖全部 requirement/acceptance IDs；ExecutionPlan v0.1 只能声明串行
Coder→QA→Reviewer 的 capability/risk/BrainTier demand，不能携带 concrete Agent、model、provider、
Assignment 或 Lease。正式 wire contracts 位于 `schemas/project-*.schema.json`、
`schemas/product-spec*.schema.json`、`schemas/technical-design.schema.json` 和
`schemas/execution-plan.schema.json`。

## Organization Workforce 契约

T018 的 [`schemas/workforce.schema.json`](../schemas/workforce.schema.json) 定义八类组织级事实：

- `AgentProfile`：长期成员身份、能力、eligible roles、最大并行 Assignment 和默认 ModelPolicy；
- `WorkItem`：Task 的优先级、风险、能力需求和 `WAITING_*` 调度状态；
- `RoleAssignment`：Agent 在一个 Task attempt 中临时担任的 Role；
- `TaskLease`：有明确获得/过期时间的 Agent 容量占用；
- `ModelPolicy`：eligible provider/model routes、默认 BrainTier 和完整 risk floors；
- `ModelSelection`：一次 Run 的 provider/model/tier/policy version 与选择理由；
- `RunDemand`：一次 Run 的风险、上下文规模、变更规模、受影响层数和历史失败等客观路由信号；
- `AgentRunAllocation`：把 Agent、Assignment、Model、Context、Prompt、Spec 和 tool policy 绑定到
  唯一 `run_id`。

`AgentProfile.eligible_roles` 使用 `OrganizationRole`，可表达 Project Manager、Product、
Designer、Planner 与四个 delivery 岗位的长期胜任资格。`RoleAssignment`、`RunDemand` 和
现有 TaskOrchestrator 仍使用只含 `orchestrator/coder/qa/reviewer` 的 `AgentRole`；只有进入
delivery runtime 时才能执行这一收窄映射。

`AgentProfile` 不包含具体 model 或 project path；Project 不能复制或拥有 AgentProfile。当前
`AgentDefinition` 是由上述事实和 project policy 解析出的单角色执行配置，用来兼容既有
TaskOrchestrator，不是团队成员本体。

同一 Task 历史中的 Coder、QA、Reviewer assignment 必须使用不同 `agent_id`。一个 Agent 可以
持有多个不同 Task 的 Lease，但 active Lease 总量不能超过 `max_parallel_assignments`，且各 Run
不得共享 Context、worktree、Artifact lineage 或可变模型会话。T019 的
`active_capacity_by_agent` 和 `PortfolioScheduler` 已实现 capacity aggregate、自审拒绝与 batch
内新 Lease 占用；决策持久化属于后续 WorkQueue application service。

ModelPolicy 必须覆盖 `low/normal/high/critical` 全部 RiskTier，且每个最低 BrainTier 都有 eligible
route。ModelRouter 选择最小满足质量/风险约束的 route，并记录 reasons；模型升级依据测试失败、
invalid Artifact、QA/Review 驳回、高风险路径或 Context capacity 等客观信号，不只使用 Agent
自报置信度。绩效按 `agent × model × role × task class × risk` 归因。

## Evaluation 与 Handoff 契约

T012 新增两类不改变 Task 状态的组织级事实：

- `EvaluationEvent`：`CaseStartedEvent` 固定 case/model/prompt/spec/base/tests；
  `AgentRunEvent` 记录 role/run/attempt/output validity/policy violation；
  `HumanActionEvent` 记录允许或取消自治资格的人工动作；`RegressionCheckEvent` 关闭观察窗口。
- `HandoffBundle`：只为 `DONE/BLOCKED` 构造，携带 Task 摘要、candidate、验收项、四制品链或
  阻塞证据、changed files、风险、复核 argv 和人类下一步。

`EvaluationEventStore.append/get/find/list_for_case` 与 `FileHandoffStore.put/get` 都是 immutable
边界。Evaluation event 文件使用 `event + sha256` 内部信封，合法字段被篡改也会被发现；
Handoff ID 排除 `generated_at`，等价重建保留首次观察，JSON 和确定性 Markdown 任一不一致都
fail closed。Wire contract 分别是 `schemas/evaluation-event.schema.json` 和
`schemas/handoff-bundle.schema.json`。

ADR 不由 `Task.status == DONE` 单独决定。`EvaluationEngine` 还要求最终 StateEvent 的四制品
链、独立 run、candidate revision、required criterion evidence、无越权人工动作/策略放宽，
以及交付后的 regression window PASS。观察窗口未完成返回 `PENDING` 并保守地留在 ADR 分母。

## Project Workspace 契约

`ProjectWorkspaceRegistry(registry_root).register(project_root, project_id=None)` 把一个 canonical
本地目标项目绑定到外置 sidecar，并返回 typed `ProjectWorkspace`。目标项目仍是实际代码、测试
和构建命令 cwd；sidecar 只承载平台状态。`workspace.json` 的 wire contract 是
`schemas/project-workspace.schema.json`，固定字段为：

- `schema_version=v0.1`、`layout_version=v0.1`；这是使用 `assignments/` 的唯一初始布局；
- `project_id`、absolute `project_root`、absolute `ai_workspace_root`；
- 14 个固定 layout 名称，其中 `assignments/` 保存项目相关分配事实，不保存 Agent 本体；
- UTC `created_at` 和排除自身字段计算的 canonical `manifest_sha256`。

初始化先在 registry root 下建立隐藏 staging、写入并 `fsync` manifest，再以目录 rename 发布。
同一绑定重放返回首次 manifest；Project ID collision、registry symlink、目标项目内 sidecar、缺失
project、manifest digest/Schema/path mismatch 或 layout 缺失均 fail closed。注册不复制源码，也不
在目标项目创建 `.ase`、数据库、Agent 日志、Artifact 或 Evidence。T022 的 Python
`RuntimeWorkspaceBinding` 已能把 Runtime paths 固定到 `ProjectWorkspace.directory(...)` 下；
当前 CLI 自动装配尚未接入，CLI 配置仍必须显式使用这些 sidecar paths。

AgentProfile、ModelPolicy、全局 WorkQueue 和团队绩效位于组织 workspace。T020 的 ProjectProfile
只读发现语言、构建、VCS 和原生规范来源并记录 URI/hash；T021 的 `SpecCompiler` 对显式结构化
规则产生 `SPEC_CONFLICT` 和 `WAITING_HUMAN` route，人工 resolution 以不可变 SHA 记录。
Markdown 正文不会被模型猜测式解析。只有决定终止本次交付时 Task 才进入 `BLOCKED`；hard
safety policy 不允许项目规范放宽。正式 wire contracts 是
`project-profile.schema.json`、`spec-conflict.schema.json`、`spec-resolution.schema.json` 与
`runtime-workspace-binding.schema.json`。

## 1.2 Agent Run 输入/输出契约

`AgentAdapter.run(request: AgentRequest) -> AgentResult` 是 Fake 与真实模型 adapter 的共同边界。Request 固定携带 `run_id`、`task_id`、`role`、`attempt`、`source_revision`、`context_manifest_id`、`input_artifact_ids`、`permissions`、`output_schema` 和 `timeout_seconds`；其中 Context manifest ID 必须来自已成功构建的 ContextBundle。

Result 的 `SUCCEEDED` 状态必须有一个 producer/task/kind/context manifest/run ID 全部对齐的 typed Artifact，不能同时有 failure。Orchestrator、QA、Reviewer 的 Artifact revision 必须与 request 的输入 revision 相同；Coder request revision 是输入基线，其 implementation-report 可以指向新 candidate，但 envelope `source_revision` 必须与 `content.commit_sha` 相同。`FAILED` 或 `TIMED_OUT` 必须只携带 `AgentFailure(code, message, transient)`，不产生 verdict；`TIMED_OUT` 只能使用 `TIMEOUT` code。Fake adapter 的 scenario 只用于离线测试，不得绕过这些检查。

角色与 `output_schema` 固定映射为：Orchestrator → `schemas/plan.schema.json`、Coder → `schemas/implementation-report.schema.json`、QA → `schemas/qa-report.schema.json`、Reviewer → `schemas/review-report.schema.json`。Request 使用其他角色的 Schema 时在 Pydantic boundary 拒绝，不启动 adapter。

### 1.2.1 OpenAI-compatible adapter

`OpenAICompatibleAgentAdapter` 是 v0.1 的真实 provider 实现，仍只暴露上述
`AgentAdapter` seam。它使用标准库 `urllib` 通过 `POST /chat/completions` 发送
`model`、policy-first `messages`、`temperature=0`、`stream=false` 和 JSON response
format；API key 只存在于 `Authorization` header，不进入 prompt、异常或返回的
`AgentFailure.message`。HTTP transport 与 PromptBuilder 都是 Protocol，可在无网络测试中
替换。默认 `RequestPromptBuilder` 只发送 request 元数据；接入生产 Context 时应注入
`ContextPromptBuilder(ContextResolver)`，由 resolver 显式读回已持久化 ContextBundle 和
上游 Artifact。

2xx 响应只接受一个完整 v0.1 Artifact JSON（也容忍单层 Markdown `json` fence），再由
`validate_artifact` 和 `AgentResult` 做 role/kind/task/run/context/revision 校验；Coder 的
candidate 仍必须满足 `source_revision == content.commit_sha`。未 sealing 的 provider Artifact
会由 Orchestrator 再次 `seal_artifact`，adapter 不写 ArtifactStore。HTTP 408/429/5xx、连接错误
映射为可重试 `PROVIDER_ERROR`；timeout 映射为 `TIMED_OUT/TIMEOUT`；非法 JSON、Schema 或
身份映射为不可重试 `INVALID_OUTPUT`，三者都不携带 Artifact/verdict。

adapter 按 `run_id` 缓存成功和失败结果：完全相同 request 重放返回同一个 immutable
result；相同 ID 搭配不同 request 字段抛 `AgentRequestConflict`，不会再次调用 provider。

## 1.1 ContextBundle 契约

`ContextBuilder.build(task, role, *, attempt, candidate_revision=None)` 只消费声明的 `ContextSource`，返回不可变、角色隔离的 `ContextBundle`。每个 source 必须是 inline `content` 或 root-relative `relative_path` 之一；`roles=()` 表示全角色，`priority=0` 仅供机器 policy。生成的 `policy`、`task`、`role`（以及可选 `candidate`）section 由 Builder 控制，外部 source 不能覆盖其 ID。

Bundle 的 `source_revision` 是实际读取/审查的 revision；每个 section 暴露脱敏后的 `content`、URI、SHA-256、token 数、priority 和 `truncated`。redaction 只暴露安全 URI、kind 和 count，不保留 secret 值。`budget.used_input_tokens` 必须等于 section token 总和且不超过 `max_input_tokens`；required source 放不下抛 `ContextBudgetExceeded`，optional source 确定性截断或省略。

`context_id` 是不含 `built_at` 的 canonical manifest SHA-256（`ctx_<64 hex>`），因此相同输入可重放。仓库内容、Task 文本和命令输出仍是数据，不得改变 policy、权限、role 路由或状态机。Context 失败使用 `ContextSourceError`、`ContextSourceNotFound`、`ContextSourceDenied` 或 `ContextBudgetExceeded`，不返回 partial bundle。

真实 Agent 调用前，`FileRunContextBuilder(..., context_store=store)` 把 manifest 写入
`ContextStore`。`FileContextStore` 使用临时文件、`fsync` 和原子 rename，读取时重新做
Pydantic 与 canonical ID 校验；`InMemoryContextStore` 只用于测试。`StoredContextResolver`
组合 ContextStore 和 ArtifactStore，让 `ContextPromptBuilder` 解析 request 中的 ID；input
Artifact 内容已在 `artifact://<id>` Context section 中计入预算，不在 prompt 中重复一份。

### AgentPermissions 的执行语义

`WorkspacePolicy(worktree.path, permissions, denied_paths=...)` 是路径和命令授权入口：

- `read_paths` 与 `write_paths` 分开匹配，写权限不从读权限推导；Task deny glob 永远优先；
- 路径既检查 lexical canonical form，也在绑定的 worktree root 下解析 symlink，越过 root 或指向 `.git` 时抛 `PathPolicyViolation`；
- `commands` 中每个字符串用 `shlex.split` 固化为 token prefix。运行时只接收 argv tuple，按完整 token 匹配并拒绝 shell syntax；
- 返回成功只代表 operation 在 application policy 中获准，不代表可以绕过后续 executor 的 cwd、env、timeout、network、resource 和 evidence 约束。

### T023 EvidenceRecord / RunEvidenceManifest

`RunEvidenceSession` 将每次命令、diff、测试和 Agent usage 封装为带 `RunEvidenceIdentity` 的
discriminated `EvidenceRecord`。落盘前统一执行 secret redaction、UTF-8 字节上限和 canonical
JSON SHA-256；`FileEvidenceStore` 采用 immutable put、原子写入和读取时完整性校验。timeout、
拒绝和启动失败也必须先持久化 typed evidence，再重新抛出原异常。一个 run 只能由
`RunEvidenceManifest` 封存，manifest 的 evidence IDs、identity 和时间窗口必须与磁盘事实一致。
相同 operation/evidence ID 的完全相同重放是幂等，不同正文或篡改内容拒绝。

### T024 Typed Agent Tool Protocol

Agent 只能提交 `ReadFileRequest`、`WriteFileRequest`、`RunCommandRequest`，每个请求都带
`run_id`、`role`、`operation_id`。`PolicyBoundToolRegistry` 绑定一个 role、worktree root 和
`WorkspacePolicy`，返回 typed success 或 `ToolRejectedResult`。路径是 repository-relative，命令
是 tokenized argv；协议没有自由文本 `shell`/`exec`、verdict、artifact 或 state mutation 字段。
Coder 的写权限由 policy 限定，QA 只能写 `tests/**`，Reviewer 始终只读；`.trellis`、
artifact/state/verdict/report 路径以及 shell interpreter 都必须 fail closed。工具成功不等于
QA PASS/Review APPROVE，所有结果必须由应用层显式交给 EvidenceStore 后才能进入交付链。

Git role workspace 由 `GitWorkspace.create/inspect/remove` 管理。Coder 使用 attempt branch；QA/Reviewer detached 到 candidate SHA；dirty workspace 不允许清理。完整错误与 Git 执行安全契约见 [`docs/git-worktree.md`](git-worktree.md)。

## 2. 共同输入信封

每次 Agent 运行都收到以下固定结构：

```json
{
  "run_id": "run_...",
  "task_id": "task_...",
  "role": "coder",
  "attempt": 1,
  "base_revision": "a1b2c3d",
  "context_manifest_id": "ctx_...",
  "input_artifact_ids": ["art_plan_..."],
  "permissions": {
    "read_paths": ["src/**", "tests/**", ".trellis/spec/**"],
    "write_paths": ["src/**", "tests/unit/**"],
    "commands": ["pytest", "ruff", "git diff", "git status"]
  },
  "output_contract": "schemas/implementation-report.schema.json"
}
```

## 3. Coder 契约

### 输入

- Task + acceptance criteria；
- 最新有效 `plan`；
- 相关代码快照及项目规范；
- 之前 attempt 的 `qa-report`/`review-report`（重试时）；
- 明确的 write path 和 command allowlist。

### 行为约束

- 先检查 plan 和失败 findings，再修改代码；
- 每个验收标准都要映射到实现位置和测试；
- 不通过删除/禁用测试来“修复”失败；
- 完成后运行允许的验证命令并提交候选 commit；
- 若发现需求冲突或需要越权，输出 `blocked_reason`，不要猜测。

### 输出

- 候选 commit SHA；
- `implementation-report`，至少包含 changed_files、acceptance_mapping、tests_run、known_risks、blocked_reason（可空）；
- 不得写入 `qa-report` 或 `review-report`。

## 4. QA 契约

### 输入

最新候选 commit、Task 验收标准、plan、implementation-report 和 QA 规范。QA 必须重新读取候选代码，不能只相信 Coder 的摘要。

### 行为约束

- 默认在 QA worktree 中运行；
- 可新增/修改测试文件，但生产路径写入被 policy 拒绝；
- 每条验收标准必须有 `PASS`、`FAIL` 或 `NOT_TESTED`，后者必须说明原因；
- 失败必须附可复现命令、关键输出、文件/行号或测试 ID。

### 输出

`qa-report.status` 为 `PASS` 或 `FAIL`。只有所有 required criteria 为 `PASS` 且 required checks 有 evidence 时才允许 `PASS`。

## 5. Reviewer 契约

### 输入

候选 diff、Task、plan、implementation-report、qa-report、项目规范和风险策略。Reviewer 上下文不包含 Coder 的隐式会话记忆。

### 行为约束

- 只读 worktree；
- 检查正确性、回归风险、安全、可维护性和契约一致性；
- 优先验证 QA/其他 Agent 的结论，不盲目接受或拒绝；
- 发现问题要给出严重级别、位置、理由和修复建议；
- 不直接修代码、不直接 merge。

### 输出

`review-report.verdict` 为 `APPROVE` 或 `REJECT`。`APPROVE` 要求 findings 为空或全部为 `INFO`，且 evidence 足够；`REJECT` 至少有一个 `BLOCKER`/`MAJOR` finding。

## 6. Artifact 通用规则

- 正文符合对应 JSON Schema；
- Python 入口先使用 `Task.model_validate`、`AgentDefinition.model_validate` 或 `validate_artifact` 转成 typed model；下游不解析裸 `dict`；
- `producer` 是角色 + resolved AgentDefinition 版本 + run_id；`AgentRunAllocation` 另行提供长期
  AgentProfile 与 run-scoped ModelSelection 归因；
- `source_revision` 指向实际读取/审查的 Git revision；
- 对 Coder，request/context 的 `source_revision` 是修改前输入基线，implementation-report 的 `source_revision` 是修改后 candidate；后者必须等于 `content.commit_sha`。QA/Reviewer request 与 Artifact 都绑定这个 candidate；
- `evidence` 是带 URI 和 SHA-256、可定位、可复核的引用，不接受“看起来没问题”这类无证据描述；Finding 至少引用一个 envelope Evidence ID；
- artifact 不可原地修改；修订通过新 artifact + `supersedes` 关系表达；
- Schema 校验、哈希计算和持久化由 Orchestrator/ArtifactStore 完成，Agent 不能自报通过。

`ArtifactStore.put(artifact: Artifact) -> ArtifactRef` 只接受 `schema_version=v0.1`、typed union 校验通过、`integrity.validated=true` 且 digest 匹配的 Artifact。Digest 对 canonical JSON 顶层 `integrity` 字段之外的内容计算 SHA-256；`seal_artifact` 生成带 `validated_at` 的不可变副本。Store 将正文写入 `artifacts/art_<artifact-id>.json`，采用临时文件 + `fsync` + 原子 rename。

`ArtifactStore.list_for_task(task_id)` 只返回重新解析、校验 digest 和 lineage 后属于该 Task
的 Artifact，并按稳定 ID 顺序枚举；它是恢复入口，不是 Agent 可写的共享状态。

`parent_artifact_ids` 必须指向已存在且属于同一 Task 的 Artifact；`supersedes` 还必须是同一 kind。相同 ID 的完全相同正文重放是幂等 no-op，不同正文抛出 `ArtifactAlreadyExists`，不覆盖旧证据；缺失/跨 Task/跨 kind 引用抛出 `ArtifactParentError`。

## 7. 四类 artifact 的最小字段

| kind | 必填业务字段 |
|---|---|
| `plan` | goal、assumptions、steps、acceptance_mapping、risks |
| `implementation-report` | commit_sha、changed_files、acceptance_mapping、tests_run、known_risks |
| `qa-report` | status、criteria_results、tests_run、findings、evidence |
| `review-report` | verdict、findings、checked_dimensions、evidence |

详细机器契约见 [`schemas/`](../schemas/)。

## 8. StateEvent 与持久化

状态迁移事件使用 `schemas/state-event.schema.json`，Python 入口为 `StateEvent`。`TaskRepository.append_event(event)` 以事件的 `from_status` 对比当前 Task 快照，成功后在同一事务中写入事件、更新 `status`/`updated_at` 并递增 revision；不负责判断状态机边是否合法，合法性由 T004 reducer/guard 决定。

`SqliteTaskRepository` 对重复事件执行精确幂等：正文相同直接成功且不新增 revision，正文不同抛出 `EventIdempotencyConflict`。未知 Task、stale `from_status`、重复 Task ID 和损坏 JSON 都转换为 typed repository error，不返回半结构化数据。

`TaskRepository.record_attempt(task_id, attempt)` 在同一 SQLite 文件中原子更新 Task 快照的
`attempts`，不增加状态 revision；重复或更小的 attempt 是幂等 no-op，超过 `max_attempts`
拒绝。它用于 Agent 调用前的崩溃恢复，避免把 self-transition 当成 attempt 日志。

状态图由 `orchestration.state_machine` 的 `validate_transition`/`build_event`/`apply_event` 唯一维护。Repository 不自行放宽或扩展迁移边；ArtifactStore/Orchestrator 后续再对 QA PASS、Review APPROVE 和 candidate revision 做跨 Artifact 守卫。

T009 的 `SerialOrchestrator.run_task` 只接受 `NEW` Task，并按固定单 attempt 路径提交 5 个事件。每个 Agent Artifact 先由 runner 检查 request echo、直接 parent lineage、criterion coverage 和 revision，再由 `seal_artifact`/ArtifactStore 原子持久化并读回。T010 的 `RetryingOrchestrator` 在此之上执行有界 retry：QA FAIL/Review REJECT 回流 Coder，瞬时 Agent failure 重试当前 role，预算或策略问题进入 BLOCKED；旧 Artifact 不覆盖并保留 `supersedes` lineage。

## 9. Python 领域入口

`src/ai_software_engineer/domain/` 是 Python 控制平面的唯一领域类型入口。`TaskStatus`、
`WorkItemStatus`、`OrganizationRole`、`AgentRole`、`BrainTier`、`RiskTier` 和 `ArtifactKind` 不能在 store、agent adapter
或 orchestrator 中重复定义。`to_wire()` 负责生成 JSON-compatible payload 并省略不存在的
optional 字段；cross-language 消费者仍以 `schemas/*.json` 为准。

Pydantic validator 只处理单个对象可判断的规则；Task required criterion 与 QA 结果是否一一对应、四类 Artifact 是否属于同一 candidate revision、各 verdict 是否来自独立 run 等跨对象规则，由后续 ArtifactStore/Orchestrator guard 执行。

## 10. Project Manager preparation Skill（T029）

T029 把项目注册、ProjectProfile 发现、organization binding 和项目级规范编译收口为
Project Manager Agent 的 typed Skill：

```python
class ProjectManagerSkill(Protocol):
    def prepare_project(self, request: PrepareProjectRequest) -> PrepareProjectResult: ...
    def require_product_context(self, result: PrepareProjectResult) -> ProjectPreparation: ...
    def advance_stage(self, request: StageAdvanceRequest) -> StageAdvanceAuthorization: ...
```

Agent-visible request/result/authorization 的 wire contract 是
`schemas/agent-skill-project-manager.schema.json`。`PrepareProjectRequest` 的唯一业务输入是
无控制字符的绝对 `project_root`。organization identity、sidecar registry、platform rules、
rule provider、clock 和 stores 都是 Skill runtime
按 policy 注入的依赖，不是 Agent 可以传入或替换的 ambient authority。

`prepare_project` 严格按以下顺序运行：

```text
register/reopen external sidecar
  → discover and integrity-check ProjectProfile
  → bind organization + project + exact profile
  → compile PLATFORM_HARD/PLATFORM_ENGINEERING/PROJECT baseline
  → append compilation record
  → PREPARED checkpoint or WAITING_HUMAN route
```

项目基线是 task-free 的：必须包含至少一条 `PLATFORM_HARD` 规则，拒绝 `TASK` 规则，
不会虚构 Task/acceptance criteria。结构化 PROJECT rule 必须绑定当前 ProjectProfile 中精确的
source URI + SHA-256；未有显式 adapter 解释的原生规范只作为 opaque source 引用。
重叠 scope 下同一 field 的不同 value 不按优先级静默覆盖，而是生成 project-scoped
`ProjectSpecConflict` 和 `WAITING_HUMAN`，且 `product_agent_start_allowed=false`。

成功的 `ProjectPreparation` 和 baseline compilation 都在外置 sidecar 内 append-once 保存，
通过同目录 temporary file + fsync + exclusive hard-link publish 保证并发首写不被覆盖。
完全相同的重放返回第一次记录及其时间戳；一旦 profile/binding/baseline 漂移、记录篡改、
identity collision、symlink/path escape 或同一项目改内容，必须返回 typed error，不覆盖、
不返回 partial result。成功或失败都不允许在目标项目目录写入 AI 运行事实。

`require_product_context` 不信任传入 result 的快照；它重新 prepare/reopen sidecar，对 current
profile/binding/baseline 重做完整性验证并与传入 checkpoint exact compare。
`advance_stage` 只接受与目标阶段完全一致的 artifact prefix，返回绑定所有输入 digest 的
`StageAdvanceAuthorization`。它不修改 Product/Design/Plan，不写 verdict，也不代替后续
Task state machine。T029 的能力由 T032 通过 `UnifiedProjectEntryService` 暴露为“项目目录 + 需求”的
统一 CLI/application 入口。

## 11. Product Agent 需求澄清与人工确认（T030）

T030 的 `ProductDiscoveryService` 只能在 exact `ProjectPreparation` 之上工作，不会创建或修改
Delivery Task。它接受四类 typed command：

```python
start(command: StartProductDiscoveryCommand) -> ProductDiscoveryResult
record_human_message(command: RecordHumanMessageCommand) -> ProductDiscoveryResult
run_product(command: RunProductAgentCommand) -> ProductDiscoveryResult
decide_as_human(command: HumanProductDecisionCommand) -> ProductDiscoveryResult
```

每个 command 都携带稳定 operation/run ID、timezone-aware `submitted_at` 和（除 start 外）
`expected_checkpoint_sha256`。过期 checkpoint、同一 operation ID 下改变 typed input、错误阶段或
lineage 不匹配都 fail closed。

### Product context 和 adapter

`ProductContextBuilder` 构建与 Delivery `Task`/`ContextBundle` 分离的 task-free
`ProductContextManifest`。它精确绑定 ProjectPreparation、当前 ProjectRequest、已提交对话前缀、
当前 ProductSpec 以及 next version/supersedes，并为每个来源记录 URI 与 SHA-256。
`built_at` 可留痕但不参与 context identity，因此相同事实可确定重建。

`ProductAgentAdapter.run(ProductAgentRequest) -> ProductAgentResult` 只允许返回两种成功结果：
澄清问题或 `READY_FOR_REVIEW` ProductSpec。timeout、provider failure 和 invalid output 使用
typed failure，不生成批准 verdict。Product Agent 权限明确排除代码修改、shell/command、
Delivery Task 状态、ProductSpecApproval 和 stage authorization。Fake adapter 与真实 adapter 共享该边界。

### 人工决策不可伪造

`HumanProductDecisionCommand` 只携带人工通道生成的 `approval_reference`、exact ProductSpec ID/digest
和 expected checkpoint，不直接信任调用方声称的决策、操作人、理由或时间。与 Product Agent
隔离的 `HumanProductDecisionVerifier` 必须将引用验证为 `VerifiedHumanProductDecision`；
验证结果与命令或当前 spec 有任何不一致都拒绝。

`REQUEST_CHANGES` 会写入 exact ProductSpecApproval、新 ProjectRequest revision 和人类理由对话，
再回到需求澄清。`APPROVED` 除写入同样的不可变批准事实外，还必须调用
Project Manager `advance_stage(StageAdvanceRequest)`；该 Skill 使用当前 facts 重新校验
`PRODUCT_SPEC_APPROVED → SOLUTION_DESIGN`，不接受调用方伪造时间或 authorization。

### 不可变事实、崩溃恢复与重放

Product sidecar store 保存六类 append-only 事实：

1. digest-linked `ProductDialogueRecord`；
2. supersedes-linked `ProjectRequestRevision`；
3. 版本化 `ProductSpec`；
4. 绑定 exact spec ID/digest 的 `ProductSpecApproval`；
5. 引用当前对话、request、spec 和 approval digest 的 `ProductDiscoveryCheckpoint`；
6. 绑定 command digest、result identity 与预期 checkpoint 的 `ProductOperationRecord`。

外部输出校验完成后的写入顺序是“operation receipt（完整 effect bundle）→ 效果事实 →
checkpoint”，checkpoint 是对外可见的提交点。如果进程在 receipt 之后、effects 或 checkpoint
发布之前崩溃，exact command replay 会从 receipt 中补齐事实并恢复 checkpoint。已完成的批准
重放从 receipt 恢复已验证决策和 stage authorization，不会
再次调用人工验证器或重复推进阶段。store 在文件发布时防止 symlink/path escape，
并对 schema、SHA-256、序号、supersedes 和跨事实 lineage 逐次复核。

Wire contracts 为 `schemas/product-agent-run.schema.json`、`product-context.schema.json`、
`product-dialogue.schema.json` 和 `product-discovery-checkpoint.schema.json`。其他 Product 记录在
Python typed boundary 上验证；后续若跨进程暴露，必须先补 wire schema，不能传递裸 `dict`。

## 12. Designer、Planner preview 与 commit-dispatch（T031）

T031 把 approved ProductSpec 到现有 Delivery Task 之间的空档实现为三个相互隔离的边界：
Designer 产出 TechnicalDesign；Planner 产出不含具体分配的 ExecutionPlan，并使用只读 preview
检查当前可行性；Project Manager 根据提交时的当前事实重算并一次提交三阶段分配。三个边界都不
复用 Delivery `ContextBundle`，也不会直接运行 Coder、QA 或 Reviewer。

### Designer：完整项目知识、最小权限和提交点

`RunDesignerCommand` 携带完整且可读的 `ProjectPreparation`、`ProjectProfile`、
`ProjectSpecBaseline`、当前 `ProjectRequestRevision`、approved ProductSpec/Approval、
`SOLUTION_DESIGN` authorization 和稳定 `submitted_at`。`DesignContextBuilder` 由这些事实生成
task-free `DesignContextManifest`；相同内容的 identity 不含 `built_at`，因此可确定重建。
只提供 URI/hash 而不提供 Profile/Baseline 正文不满足该契约。

```python
DesignerAgentAdapter.run(DesignerAgentRequest) -> DesignerAgentResult
DesignerService.run(RunDesignerCommand) -> DesignerServiceResult
```

Designer request 只能读取项目事实、项目规范、请求、ProductSpec 和 Approval，并输出
TechnicalDesign。权限显式拒绝代码写入、shell、修改 Product/Approval、推进项目阶段和创建
Delivery Task。成功结果必须绑定 exact run/project/request/context，且 TechnicalDesign 必须精确覆盖
全部 requirement IDs 与 acceptance criterion IDs；timeout、provider error 和 invalid output 是 typed
failure，不产生 design 或 request revision。

成功提交采用明确的 journal/commit 语义：

```text
DesignRunRecord receipt（包含完整预期效果）
  → CAS append supersedes-linked ProjectRequestRevision(status=PLANNING)
  → append TechnicalDesign
  → exact read-back design + revision
  → publish DesignCommitCheckpoint（对外完成点）
```

只有 `DesignCommitCheckpoint` 存在才表示 Planner handoff 完整。若进程在 receipt 后、revision 或
checkpoint 前中断，相同 command replay 从 receipt 补齐效果，不重复调用 Designer adapter 或
Project Manager stage advancer。相同 run ID 改变 command digest、Product store 当前 revision/spec/
approval 漂移、授权或 coverage 不一致、append-only identity 冲突和读回不一致均 fail closed。

### Planner：抽象 ExecutionPlan 与不可写 preview

`PlannerContextManifest` 精确绑定状态为 `PLANNING` 的 ProjectRequestRevision、ProductSpec、Approval、
TechnicalDesign、DesignCommitCheckpoint 和 planning authorization，不含 Delivery Task。
`PlannerAgentPermissions` 只允许读取 stage artifacts、生成
ExecutionPlan，以及调用只读 Scheduler/ModelRouter preview；明确拒绝项目写入、命令执行、修改
Product/Design、持久化 Assignment/Lease/ModelSelection 和推进阶段。

```python
PlannerAgentAdapter.run(PlannerAgentRequest) -> PlannerAgentResult
PlannerStageService.produce(ProduceExecutionPlanCommand) -> PlanningStageResult
PlanningPreviewService.preview(...) -> PlanningPreview
```

ExecutionPlan 固定三个串行 phase：`coder → qa → reviewer`。每个 phase 只描述 role、objective、
required capabilities、risk、minimum BrainTier、checkpoints 和 critical-path 标志；模型输出包含
具体 agent/model/provider/Assignment/Lease 等额外字段时由 strict model/schema 拒绝。
`PlannerStageService` 在 adapter 返回后重新检查 current handoff，随后先持久化包含唯一 plan 与 READY
revision effects 的 `PlannerRunRecord`。materialization 使用 expected-predecessor CAS 追加
`READY_FOR_DELIVERY` revision，再发布 exact plan 和 `PlannerCommitCheckpoint`。进程重启时，即使 fresh
adapter 会返回不同 plan，也只能从 durable receipt 补齐原结果，不会再次调用 adapter 或覆盖旧 revision。

`PlanningPreviewService` 不接受 store/repository write port。它消费由完整 stage chain 派生的
`NEW Task`、READY WorkItem、三个 `RunDemand`、AgentProfile、active Lease、existing Assignment 和
ModelPolicy；依次调用现有 `PortfolioScheduler.match` 与 `ModelRouter.route`。每一 phase 的临时
Assignment/Lease 会在内存中计入下一 phase capacity，但不会落盘。

成功的 `PlanningPreview` 包含三个 `PlanningPhasePreview`，其中的 Agent/Assignment/Lease/
ModelSelection 只是带时间窗的建议 evidence，不是授权。preview 还绑定 Task digest、WorkItem digest、
ExecutionPlan digest、排序规范化的 workforce snapshot digest、`previewed_at` 和 `valid_until`。
capacity 或 model route 不可行时抛带 exact decision evidence 的 `PlanningPreviewRejected`，不会伪造
可行性或写入组织/项目 store。

### Project Manager commit-dispatch：当前事实重算与单次原子写

```python
ProjectManagerDispatchService.commit_dispatch(
    CommitDispatchRequest,
) -> DispatchCommitRecord
DispatchCommitStore.commit(DispatchCommitRecord) -> DispatchCommitRecord
DispatchAuthority.current_snapshot(...) -> DispatchWorkforceSnapshot
SqliteDispatchAuthority.seed_snapshot(snapshot) -> DispatchWorkforceSnapshot
SqliteDispatchAuthority.commit_if_current(record, *, expected_snapshot_sha256) -> DispatchCommitRecord
```

SQLite authority 的持久化结构是
`dispatch_workforce_snapshots(project_id, task_id, payload_json, snapshot_sha256)` 与
`dispatch_commits(id, project_id, task_id, payload_json, dispatch_sha256)`。commit row 是单一原子提交点；
三组 Assignment/Lease 从经过完整性校验的 typed record 投影，不另写可能半成功的子记录。

`CommitDispatchRequest` 必须携带完整 prepared-to-plan stage chain、exact READY revision、durable
PlannerRunRecord/ExecutionPlan/PlannerCommitCheckpoint、`DELIVERY_DISPATCH` authorization、PlanningPreview，以及 Delivery Task 的
repository/base ref/attempt/time 输入。current WorkItem/AgentProfile/Lease/Assignment/ModelPolicy 不由调用方
自报；服务从 `DispatchAuthority.current_snapshot` 读取并校验 canonical digest。RunDemand 由 exact
Task + ExecutionPlan 机械派生，不接受调用方注入。

验证通过后，服务对 Coder、QA、Reviewer 按顺序重新调用同一 Scheduler/ModelRouter；前一 phase 的
新 Assignment/Lease 只在本次内存候选中占用 capacity。commit-time Agent 必须与 preview 相同，
model 的 policy/version/provider/model/tier 语义也必须相同，且不能低于 ExecutionPlan 的 minimum
BrainTier。任何 phase 拒绝、决策漂移、自我评审、容量不足或 model refusal 都发生在 store 调用前，
因此不能产生部分持久化。

全部三阶段成功后，服务再次读取 current READY revision 以及完整 Planner run/plan/checkpoint，然后构造一个
`DispatchCommitRecord`。record 除 exact NEW Task 和 `(RoleAssignment, TaskLease, ModelSelection) × 3`
外，还记录 request、READY revision、Planner run、Design checkpoint、planning authorization 与
Planner checkpoint 的 exact identity/digest。最后只调用一次
`DispatchAuthority.commit_if_current`。生产 `SqliteDispatchAuthority` 先获取 Product revision fence，
再进入 SQLite `BEGIN IMMEDIATE`：在同一围栏中重新验证 current READY head、durable Planner 完整
handoff 和 workforce snapshot CAS，并以单个 commit record 作为三组 Assignment/Lease 的原子提交点。
跨实例竞争只有一个事务可以占用资源，另一个必须 exact replay 或 stale/conflict，不能超分配。
`FileDispatchCommitStore` 使用 digest envelope、dirfd + `O_NOFOLLOW`、exclusive hard-link publish 和
inode/root 校验；相同 record 重放幂等，changed identity、篡改、symlink/path race 全部拒绝。

T031 的 commit record 本身是原子 dispatch bundle；T032 由 `DispatchTaskMaterializer` 将其中的 NEW
Task exact-create-or-compare 到现有 TaskRepository，并由统一入口启动 Delivery。Planner preview
不能代替 commit，Project Manager commit 也不授权自动 merge 或部署。

### T031 失败矩阵

| 失败点 | 处理 | 持久化结果 |
|---|---|---|
| ProductSpec 未 APPROVED、ProjectRequest 状态或 stage authorization 错 | Designer context/service typed rejection | 无新 design/revision/checkpoint |
| Designer identity、design lineage/coverage 或 immutable read-back 错 | `DesignerOutputRejected`/typed persistence error | 不发布 commit checkpoint |
| Designer 在 receipt 后中断 | exact replay materialize design + PLANNING revision | 最终只发布一个 checkpoint |
| Designer/Planner Agent 运行期间 current revision 被推进 | adapter 后 current recheck / CAS | 无 design/plan/checkpoint effect |
| Planner 输出具体分配字段、错误 phase 顺序、旧 plan version | strict Pydantic/domain/adapter rejection | 无 plan/READY revision |
| Planner 在 receipt 后崩溃并以 fresh adapter 重启 | durable receipt recovery | 不再次调用 adapter，只补齐唯一 effects/checkpoint |
| preview capacity 或 model route 不可行 | `PlanningPreviewRejected` + decision evidence | zero store writes |
| preview 过期、WorkItem/workforce/policy/demand 变化 | `DispatchPreviewStale` | zero dispatch writes |
| Planner run/plan/checkpoint 缺失、伪造或 lineage 不一致 | complete durable handoff read-back | zero dispatch writes |
| READY revision 或 workforce 在最终提交围栏变化 | Product revision fence + SQLite CAS | `DispatchPreviewStale`/`DispatchAuthorityConflict`，zero writes |
| commit 重算改变 Agent 或 model semantics | `DispatchDecisionDrift` | zero dispatch writes |
| commit-time capacity/model refusal或三角色不独立 | `DispatchRejected`/record validator | zero partial writes |
| dispatch ID changed replay、envelope/digest/path 篡改 | typed store conflict/corruption/path error | 保留首次可信 record |

T031 的 canonical wire contracts 是 `schemas/technical-design.schema.json`、
`schemas/execution-plan.schema.json`、`schemas/designer-context.schema.json`、
`schemas/designer-agent-run.schema.json`、`schemas/planner-context.schema.json`、
`schemas/planner-agent-run.schema.json`、`schemas/planner-preview.schema.json` 和
`schemas/dispatch-commit.schema.json`。所有跨进程输入必须先通过对应 Schema 与 strict Pydantic
`to_wire()` round-trip，不能用裸 `dict` 绕过 typed contract。

## 13. 统一项目接单与恢复（T032）

`UnifiedProjectEntryService` 固定组合 prepare→Product gate→Designer→Planner→dispatch→delivery，公开
`start/reply/approve/resume/status`。CLI 只接收绝对项目目录、需求、Product 消息和 exact checkpoint；
内部 Runtime paths 由 application host 从 organization workspace 与 project sidecar 组合。

首次 start 在 stage checkpoint 之外 exact-create `ProjectDeliveryIntake`，保存原始目录、标题、需求与
提交时间。因此进程在 Product 原生事实产生前中断，`resume` 仍能重放完全相同的 Product command。
`ProjectDeliveryCheckpoint` 是连续的 append-only hash chain，只保存 native preparation/Product/
Design/Plan/Dispatch/Task references 与 digests；人工 reply/approve 使用旧 checkpoint 时必须 zero
effects。可预期的 native stage 失败由 backend 分类为 `DeliveryBackendFailure`，只把 typed code 与安全
摘要写入 BLOCKED checkpoint；未分类异常保留当前 checkpoint 供 resume。应用宿主未调用
`configure_project_entry(...)` 时 CLI 明确失败，不会默选 fake Agent。

Dispatch 到 Delivery 的 bridge 有三个约束：`DispatchTaskMaterializer` 只允许 NEW Task exact create 或
合法已推进 Task 的 immutable replay；`ExecutionPlanAgentAdapter` 只把 approved organization plan 机械
转换为 PlanArtifact，不二次规划；`DispatchRoleWorktreeCoordinator` 必须让 Agent/model/provider 与
dispatch allocation 完全一致。Coder 在 frozen base SHA 的 branch worktree 执行，QA 和 Reviewer 在
同一 full candidate SHA 的独立 detached worktree 执行；recovery 核对 path、common-dir、role、attempt、
branch/detached 与 HEAD，dirty 现场不得清理。

完整 executable contract、错误矩阵与必测项见 `.trellis/spec/core/contracts.md` 第 15 节。
