# Core Role & Artifact Contract

## 1. Scope / Trigger

本规范适用于所有 Agent request/response、JSON artifact、权限 policy 和跨角色路由。新增或修改任何字段、角色、权限、finding 或 verdict 时，必须同步更新 `schemas/`、`docs/contracts.md` 和 contract fixtures。

## 2. Signatures

```python
AgentAdapter.run(request: AgentRequest) -> AgentResult
ArtifactStore.put(artifact: Artifact) -> ArtifactRef
ArtifactStore.get(artifact_id: ArtifactId) -> Artifact
artifact_digest(artifact: Artifact) -> Sha256
seal_artifact(artifact: Artifact, *, validated_at: datetime) -> Artifact
WorkspacePolicy(workspace_root: str | Path, permissions: AgentPermissions,
                *, denied_paths: tuple[str, ...] = ())
WorkspacePolicy.authorize_read(path: str | PurePosixPath) -> PurePosixPath
WorkspacePolicy.authorize_write(path: str | PurePosixPath) -> PurePosixPath
WorkspacePolicy.authorize_command(arguments: tuple[str, ...]) -> tuple[str, ...]
ContextRouter.route(sources: tuple[ContextSource, ...], role: AgentRole) -> tuple[ContextSource, ...]
ContextBuilder.build(task: Task, role: AgentRole, *, attempt: int,
                     candidate_revision: str | None = None) -> ContextBundle
ContextStore.put(context: ContextBundle) -> ContextBundle
ContextStore.get(context_id: ContextId) -> ContextBundle
validate_artifact(payload: object, kind: ArtifactKind) -> Artifact
ProjectWorkspaceRegistry.register(project_root: str | Path, *,
                                   project_id: ProjectId | str | None = None) -> ProjectWorkspace
ProjectWorkspace.directory(name: WorkspaceDirectory) -> Path
```

`AgentRequest` 必须携带 `task_id`、`run_id`、`attempt`、`source_revision`、`context_manifest_id`、permissions 和 output schema；`AgentResult` 不能直接改变 Task 状态。

`source_revision` 在 request/result identity 中表示 Agent Run 的输入 revision。Orchestrator、QA、
Reviewer 输出仍必须与它完全相同；Coder 是唯一创建新 commit 的角色，其
implementation-report Artifact 可以使用新 revision，但必须满足
`artifact.source_revision == artifact.content.commit_sha`。后续 QA/Reviewer 的 request/result
必须严格绑定该 candidate。

`ContextSource` 只能是 inline content 或 root-relative path 之一；`ContextBundle` 的 sections 先脱敏再 hash/count，并由 `context_id` canonical manifest identity。priority 0 仅属于机器 policy；外部 source、Task prose 和命令输出都不能覆盖 policy 或产生隐式消息。
`FileContextStore` 将 manifest 写成 immutable canonical JSON；built_at 不参与 identity，等价重放保留首次观察值。读取必须重新验证 Pydantic 与 context ID，路径只能来自有效 ContextId。

### Project binding and sidecar workspace

`ProjectWorkspaceManifest` 的 wire contract 是 `schemas/project-workspace.schema.json`。它固定
`project_id`、canonical absolute `project_root`、external `ai_workspace_root`、layout version、
创建时间和排除自身字段计算的 `manifest_sha256`。当前初始 `layout_version=v0.1`；
`ProjectWorkspaceRegistry` 在 sidecar 中创建 `workspace.json` 以及 profile/assignments/
knowledge/policy/state/artifacts/contexts/evidence/evaluations/handoffs/runs/locks/logs/
spec-conflicts 目录；所有目录先 staging + fsync，再以 rename 发布。重复注册返回首次 manifest，
不会覆盖或修复现有 workspace。

目标项目是实际代码 cwd，平台不在其中写 `.ase`、Agent 日志、Artifact 或数据库，也不默认复制
源码。项目原生规范只能被读取和引用；`SpecCompiler` 若发现 project rule、platform rule 或
Task constraint 冲突，必须产生 `SPEC_CONFLICT` 并使 WorkItem 进入 `WAITING_HUMAN`、释放 Lease；
只有人工决定终止交付时 Task 才进入 `BLOCKED`，resolution 必须持久化。
项目规范不得放宽 hard safety policy。可视化 read API/dashboard 只读这些 durable records，不
接受状态或 verdict 写入。

## 3. Contracts

### Role boundaries

- `orchestrator`：读全量元数据，写状态/索引，不写业务代码；
- `coder`：写允许的生产代码/单元测试，输出 implementation-report，不写 verdict；
- `qa`：读候选代码，可写测试目录，输出 qa-report，不写生产代码；
- `reviewer`：只读候选代码和上游 artifact，输出 review-report，不改仓库。

### Machine workspace policy

`WorkspacePolicy` 绑定一个 manager-owned role worktree root 和该 role 的 `AgentPermissions`。read/write allowlist 分别判断，Task deny glob 永远优先；absolute、`..`、`.git`、非 canonical path 和解析后越过 root 的 symlink 一律拒绝。command entry 解析为 token prefix，不能用 `git` 或字符串包含关系误授权 `git push`。policy violation 抛稳定错误，调用方后续必须将拒绝路径/argv 写成 evidence；自然语言 prompt 不参与授权。

### Artifact boundary

Artifact 通过 `schemas/artifact.schema.json` 的共同 envelope 传递；业务内容分别由 `plan.schema.json`、`implementation-report.schema.json`、`qa-report.schema.json`、`review-report.schema.json` 约束。Schema 变化必须同步更新 `docs/contracts.md`、`AGENTS.md` 和 contract fixtures。

`FileArtifactStore` 只接受 `schema_version=v0.1`、typed union 校验通过、`integrity.validated=true` 且 canonical digest 匹配的 Artifact。Digest 排除顶层 `integrity` 避免循环；`seal_artifact` 返回带 digest 和 `validated_at` 的新 immutable Artifact。

Artifact ID 映射到受控 root 下的单一 JSON 文件。相同 ID/相同正文重放幂等，相同 ID/不同正文拒绝覆盖；parent/supersedes 必须先存在且属于同一 Task，`supersedes` 还必须同 kind。写入采用同目录临时文件、`fsync` 和原子 rename。

### No self-approval

`implementation-report` 只能描述实现事实；QA verdict 必须来自独立 QA Agent/run；Review verdict
必须来自独立 Reviewer Agent/run。同一 Task 历史中的 Coder、QA、Reviewer agent_id 两两不同；
同一 run 或同一 Agent 跨这些角色产生实现与批准信号都视为 policy violation。

### Evidence requirements

测试命令、Git diff、文件定位、日志和指标都必须以 evidence 引用。没有可复核 evidence 的 PASS/APPROVE 不能驱动状态迁移。

## 4. Validation & Error Matrix

| 问题 | 处理 | 是否产生 verdict |
|---|---|---|
| 缺少 required 字段 | Schema validator 拒绝，要求同角色重试一次 | 否 |
| producer role 与 output kind 不匹配 | policy violation，`BLOCKED` | 否 |
| Coder 写入 QA/Review artifact | 立即终止 run，保留命令/路径 evidence | 否 |
| 路径越过 allowlist、deny、`.git` 或 worktree root | `PathPolicyViolation`，命令不启动 | 否 |
| command token prefix 不匹配或含 shell syntax | `CommandPolicyViolation`，命令不启动 | 否 |
| QA 有 `NOT_TESTED` required criterion | `qa-report=FAIL`，路由 Coder 或阻塞 | 是（FAIL） |
| Reviewer `APPROVE` 但有 MAJOR/BLOCKER finding | validator 拒绝 verdict，重跑 Reviewer | 否 |
| evidence URI/sha 缺失 | artifact 无效，不允许状态迁移 | 否 |
| AgentResult 成功但 Artifact 身份/role/kind/context 不匹配 | adapter output guard | 否 |
| Coder candidate 与 `implementation-report.commit_sha` 不匹配 | adapter output guard | 否 |
| 非 Coder Artifact revision 与 request 不匹配 | adapter output guard | 否 |
| Agent timeout/provider/invalid output | typed AgentFailure mapping | 否 |
| same `run_id` 重放相同 request | adapter replay cache | 原结果幂等返回 |
| same `run_id` 搭配不同 request | replay identity guard | 否，抛 `AgentRequestConflict` |
| digest 不匹配或 `validated=false` | `ArtifactIntegrityError`，不落盘 | 否 |
| parent/supersedes 缺失或越界 | `ArtifactParentError`，不落盘 | 否 |
| 相同 artifact ID 的正文变化 | `ArtifactAlreadyExists`，保留旧正文 | 否 |
| Project root 缺失 / sidecar 与项目重叠 | registry 拒绝初始化，目标项目保持不变 | 否 |
| Project ID 已绑定另一目录 | `ProjectWorkspaceConflict`，保留首次 manifest | 否 |
| manifest/layout 损坏或缺失 | `ProjectWorkspaceCorruption`，不自动修复 | 否 |

## 5. Good / Base / Bad Cases

- **Good**：QA 逐条返回 criterion status、命令和 evidence ID，Reviewer 在独立 run 复核同一 SHA。
- **Base**：模型输出额外字段时 adapter 先过滤/拒绝，绝不把未定义字段当作授权信息。
- **Bad**：Coder 在报告中写 `qa_status=PASS`，Orchestrator 直接采信；这属于自我裁判和契约越界。
- **Project workspace Good**：注册只在外置 sidecar 发布固定 layout，重复调用返回首次 manifest。
- **Project workspace Base**：空本地目录可以注册，语言、构建和规范发现留给 ProjectProfile。
- **Project workspace Bad**：把平台 SQLite/Artifact/Agent 日志写到目标项目，或自动修补损坏 layout。

## 6. Tests Required

- 每个 JSON Schema 的 valid/invalid fixture；
- producer-role/output-kind 矩阵测试；
- policy 对路径、命令、状态和 artifact 写入的拒绝测试；
- 独立 run ID 测试：同一 run 不能同时产生 implementation 与 approval；
- evidence 完整性、source revision 一致性和 supersedes 不可变测试。
- 原子写入、exact replay、digest 篡改、缺失/跨 Task lineage 和损坏文件测试。
- Project workspace stable ID、外置边界、固定 layout、幂等、collision、symlink、损坏 manifest、
  staging cleanup 和 Python model ↔ JSON Schema 正反契约测试。

## 7. Wrong vs Correct

### Wrong

```python
# 把模型自由文本当成 QA 结论，并让 Coder 产生批准信号
if "all tests pass" in coder_result.text:
    task.status = "DONE"
```

### Correct

```python
qa = validate_artifact(qa_payload, ArtifactKind.QA_REPORT)
review = validate_artifact(review_payload, ArtifactKind.REVIEW_REPORT)
assert qa.producer.role == "qa" and review.producer.role == "reviewer"
assert qa.source_revision == review.source_revision == candidate_sha
assert qa.content["status"] == "PASS"
assert review.content["verdict"] == "APPROVE"
```

## 8. T011 OpenAI-compatible provider adapter

真实模型 adapter 必须实现与 Fake 相同的 `AgentAdapter.run` Protocol。Provider HTTP 细节
只能存在 `agents/openai_compatible.py`；PromptBuilder 与 HttpTransport 是可替换端口，
不得让 SDK response、裸 dict 或 provider exception 进入 Orchestrator。请求使用显式
policy-first messages、`temperature=0`、`stream=false` 和 JSON response format；API key
只放在 Authorization header。

`FileRunContextBuilder` 通过注入的 ContextStore 原子登记 manifest；真实运行使用
`FileContextStore`，测试可用 `InMemoryContextStore`。`StoredContextResolver` 组合
ContextStore/ArtifactStore，且 input Artifact 正文只使用已计入预算的 `artifact://<id>`
Context section，不在 prompt 中重复。

2xx body 必须解码为完整 v0.1 Artifact，再执行 `validate_artifact` 和 AgentResult identity
guard。允许单层 Markdown JSON fence，但不允许从自由文本猜 verdict。Coder candidate 的
`source_revision` 必须等于 `content.commit_sha`；provider 返回的 producer agent identity
由 adapter 绑定当前 Agent Definition 后再交付给 Orchestrator。adapter 不 sealing、不写
ArtifactStore，runner 负责重新 seal 和持久化。

错误映射固定为：transport timeout → `TIMED_OUT/TIMEOUT(transient=true)`；HTTP 408/429/5xx
或连接失败 → `FAILED/PROVIDER_ERROR(transient=true)`；其他 HTTP 4xx →
`FAILED/PROVIDER_ERROR(transient=false)`；2xx 非法 JSON、Schema、role/kind、run/context
或 revision → `FAILED/INVALID_OUTPUT(transient=false)`。失败结果没有 Artifact 或 verdict，
错误消息不得包含 API key 或 provider 原始 body。完全相同的 request 重放返回同一结果，
相同 `run_id` 搭配不同 request 必须抛 `AgentRequestConflict` 且不发起第二次调用。

## 9. T012 EvaluationEvent 与 HandoffBundle

Evaluation wire contract 固定为 `schemas/evaluation-event.schema.json` 的 discriminated union：

- `case_started`：`case_id/task_id/base_revision/model_id/prompt_version/spec_version/
  test_entrypoints/included`；
- `agent_run`：`run_id/role/attempt/output_status/artifact_id/policy_violations/
  caught_policy_violations/duration_ms`；只有 `VALID` 可带 artifact ID；
- `human_action`：枚举 action、evidence URI、可选 note；
- `regression_check`：PASS/FAIL、window start/end、evidence URI、hidden-tests 标志。

`EvaluatingAgentAdapter` 从 typed AgentResult 发出确定 ID 的 AgentRunEvent；exact Agent replay
保留第一次 `occurred_at`，INVALID_OUTPUT 计作 invalid artifact output，timeout/provider failure
计作 not-produced，捕获的 POLICY_VIOLATION 同时记录 total/caught。

Handoff wire contract 固定为 `schemas/handoff-bundle.schema.json`。DONE 必须有 candidate、QA PASS、
Review APPROVE 和四 HandoffArtifact refs；BLOCKED 必须有 `blocked_reason`。criteria evidence IDs 必须
能在 bundle evidence 中解析；review command 保存 argv tokens，不保存可执行 shell 字符串。
Handoff ID 排除 `generated_at`，等价 replay 保留第一次观察；JSON 与 deterministic Markdown
任何一侧不一致都拒绝读取。

## 10. T018 Organization Workforce Contract

### 10.1 Signatures

```python
AgentProfile.model_validate(payload: object) -> AgentProfile
ModelPolicy.model_validate(payload: object) -> ModelPolicy
RunDemand.model_validate(payload: object) -> RunDemand
WorkItem.model_validate(payload: object) -> WorkItem
RoleAssignment.model_validate(payload: object) -> RoleAssignment
TaskLease.model_validate(payload: object) -> TaskLease
AgentRunAllocation.model_validate(payload: object) -> AgentRunAllocation
is_waiting(status: WorkItemStatus) -> bool
lease_is_active(lease: TaskLease, *, at: datetime) -> bool
validate_assignment_independence(candidate: RoleAssignment,
                                 existing: tuple[RoleAssignment, ...]) -> None
PortfolioScheduler.match(...) -> AssignmentDecision
PortfolioScheduler.schedule(...) -> tuple[AssignmentDecision, ...]
ModelRouter.route(...) -> ModelRoutingDecision
ProjectProfile.discover(...) -> ProjectProfile
SpecCompiler.compile(...) -> SpecCompilation
RuntimeWorkforceResolver.resolve(...) -> RuntimeAgentRun
```

Wire contract 是 `schemas/workforce.schema.json` 的 discriminated union。`AgentProfile` 是组织成员
身份，不包含 project path 或 concrete model；`AgentDefinition` 仍是 TaskOrchestrator 消费的
resolved single-role run config。Project sidecar 只持久化 `assignments/`，AgentProfile、
ModelPolicy、全局 WorkQueue 和绩效属于组织 workspace。

`RunDemand` 是 ModelRouter 的输入事实：它记录 role/risk、required capabilities、context token
估计、计划文件数、受影响架构层、历史失败/QA 驳回/Review 驳回次数和是否触及 critical path。计数
来自可观察的 Task、Context、Artifact 和事件，不接受 Agent 自报置信度作为唯一依据。

### 10.2 Validation matrix

| 输入/状态 | 结果 |
|---|---|
| AgentProfile capability/eligible role 重复或 capacity 不在 1..16 | Pydantic/Schema 拒绝 |
| AgentProfile 包含 concrete `model` | extra field 拒绝 |
| ModelPolicy 缺任一 RiskTier floor 或 floor 无 eligible route | 拒绝，不允许 ModelRouter 猜测 |
| WAITING WorkItem 无 `wait_reason` | 拒绝；RETRY_SCHEDULED 还必须有未来 available_at |
| Lease expiry 不晚于 acquired_at，或用 naive datetime 评估 | 拒绝 |
| 同一 Task 历史的 Coder/QA/Reviewer 使用同一 agent_id | `AssignmentConflict` |
| AgentRunAllocation 缺 Agent/Model/Context/Prompt/Spec/tool policy 任一归因 | Schema 拒绝 |
| project sidecar 声明 `agents/` | ProjectWorkspace 拒绝结构漂移；AgentProfile 只能存在于 organization workspace |
| waiting/future retry/closed WorkItem | Scheduler 返回 typed rejection，不创建 Assignment/Lease |
| batch 内新 Lease 将导致 capacity 超限 | 后续 WorkItem 返回 `CAPACITY_EXHAUSTED` |
| route 无显式 context capacity 或没有满足 tier 的 route | ModelRouter typed refusal，不能猜测 |
| ProjectProfile 遇到 symlink escape、非 UTF-8 rule、revision mismatch | typed error，不返回 partial profile |
| 结构化规范冲突 | `SpecCompilation.status=CONFLICT` + `WAITING_HUMAN`；不按层级静默覆盖 |
| resolution 尝试放宽 hard safety 或缺 evidence | `SpecResolutionRejected` |
| runtime workspace 重叠、manifest/profile/binding 漂移 | RuntimeWorkspace typed conflict/corruption |
| allocation 的 Lease 过期或任一 task/agent/model/context/spec 身份不一致 | `RuntimeAllocationError` |

### 10.3 Good / Base / Bad

- Good：同一 AgentProfile 持有两个不同 Task 的 Lease；每个 Run 有独立 Assignment、Context、
  worktree 和 ModelSelection，且未超过 capacity。
- Base：没有满足 RiskTier floor 的 route 时不创建 Assignment/Run，等待 operator 更新 ModelPolicy。
- Bad：为每个 Project 复制 AgentProfile，或一个模型会话共享多个 Task 的可变上下文。

### 10.4 Tests required

- `tests/workforce/test_contracts.py` 覆盖 organization identity、risk floor、waiting reason、lease
  window、自审冲突、run attribution 和 Python ↔ JSON Schema；
- `tests/project_workspace/` 与 `tests/contracts/` 覆盖当前 v0.1 assignments layout 和
  project-owned agents 结构拒绝；
- `tests/scheduling/` 覆盖 capacity aggregate、Lease release/expiry、priority/age/risk、batch 新 Lease、
  no-self-review、deterministic ModelRouter 和 typed refusal；
- `tests/project_profile/`、`tests/spec_compiler/`、`tests/runtime_workspace/` 覆盖跨语言发现、规则
  完整性、人工冲突治理、workspace 隔离和 allocation cross-object guards。

### 10.5 Wrong vs Correct

#### Wrong

```python
# Project owns a copied Agent and one mutable session multiplexes unrelated Tasks.
project_agents[project_id] = AgentDefinition(model="largest-model", role="coder", ...)
shared_session.run(task_a)
shared_session.run(task_b)
```

#### Correct

```python
profile = AgentProfile.model_validate(organization_agent_payload)
assignment = RoleAssignment.model_validate(project_assignment_payload)
validate_assignment_independence(assignment, existing_assignments)
allocation = AgentRunAllocation.model_validate(run_allocation_payload)
assert allocation.agent_id == profile.id
assert allocation.assignment_id == assignment.id
```

前者复制组织身份、把 model 固化到成员并产生跨 Task 上下文串扰；后者让 Project 只保存
Assignment，每个 Run 显式记录成员、模型、Context 与 policy。

## 11. T028 Project Manager Agent, Skills, and stage artifacts

Project Manager 是组织级团队领导 Agent，不是与 Agent 并列的用户可见 Service。它只能通过 typed、
policy-bound Skills 执行 `prepare_project`、`advance_stage`、`commit_dispatch`、`route_failure` 和
`deliver_result`；每个 Skill 由 deterministic application service 实现，并只持有完成该能力所需的
最小 ports。Prompt 不授予状态、store、shell 或启动其他 Agent 的 ambient authority。

Planner Agent 可调用 read-only Scheduler/ModelRouter preview Skills，把当前 capacity、risk floor 和
context capacity 形成 feasibility evidence；preview 不创建 Assignment/Lease/ModelSelection。Project
Manager 的 `commit_dispatch` 必须基于当前 facts 重新运行同一 engines，typed decision 成功后才
持久化具体分配。这样 Planner 可以做真实可行的计划，但不能既计划又批准自己的资源方案。

上游 stage artifacts 固定为 `ProjectPreparation → ProjectRequest → ProductSpec +
ProductSpecApproval → TechnicalDesign → ExecutionPlan`。Product Agent 不能创建 Approval；只有用户对
exact ProductSpec ID/digest 的 APPROVED record 才能解锁 Designer。TechnicalDesign 必须精确覆盖
requirement/acceptance IDs；ExecutionPlan v0.1 固定 Coder→QA→Reviewer，并禁止 concrete Agent/model/
provider/Lease 字段。完整 chain 通过 `derive_delivery_task` 后，现有 Task/Artifact/Orchestrator contract
才开始生效。

## 12. T029 Project Manager preparation Skill

### 12.1 Scope / Trigger

当实现或修改“只给项目目录即准备项目”、project-level baseline、ProjectPreparation
重放或上游 stage authorization 时必须遵守本契约。该 seam 发生在 Product Agent 启动前，
不得构造 Task 或猜测需求级 constraints。

### 12.2 Signatures

```python
class ProjectManagerSkill(Protocol):
    def prepare_project(self, request: PrepareProjectRequest) -> PrepareProjectResult: ...
    def require_product_context(self, result: PrepareProjectResult) -> ProjectPreparation: ...
    def advance_stage(self, request: StageAdvanceRequest) -> StageAdvanceAuthorization: ...

ProjectBaselineCompiler.compile(
    profile: ProjectProfile,
    rules: Sequence[SpecRule],
    *,
    compiled_at: datetime,
) -> ProjectBaselineCompilation

FileProjectPreparationStore.put(preparation: ProjectPreparation) -> ProjectPreparation
FileProjectPreparationStore.get(project_id: ProjectId | str) -> ProjectPreparation
FileProjectPreparationStore.find(project_id: ProjectId | str) -> ProjectPreparation | None
```

Agent-visible wire schema：`schemas/agent-skill-project-manager.schema.json`。Project baseline wire
schema：`schemas/project-baseline.schema.json`。

### 12.3 Contracts

- public request 只允许无控制字符的绝对 `project_root`；organization、registry、rules、clock、
  binder 和 stores 为 policy-bound dependencies，不从 Agent payload 取得；
- 基线只接受 `PLATFORM_HARD/PLATFORM_ENGINEERING/PROJECT`，必须包含 hard safety，
  `TASK` rule 一律拒绝；PROJECT rule 必须绑定 current ProjectProfile URI + digest；
- native project document 在没有显式 adapter 时只作为 opaque source；不从 Markdown 自动推断结构化
  rule；
- 成功结果只有 `PREPARED + ProjectPreparation`；冲突结果只有 `WAITING_HUMAN +
  conflicts + route`，两者互斥；未 PREPARED 时 Product context 必须拒绝；
- `require_product_context` 不信任调用方持有的旧 result；它必须通过同一 Skill service
  重新 prepare/reopen sidecar，重验 current profile/binding/baseline，然后才返回 Preparation；
- baseline compilation 和 ProjectPreparation 都是 canonical-SHA、append-once sidecar 记录，通过
  temporary file + fsync + exclusive hard-link publish 保护并发首写；exact
  replay（包括 conflict）返回首次记录，不更新首次时间；
- `advance_stage` 只验证 exact immutable prefix 并产生 digest-bound authorization，不修改
  stage artifact、delivery Artifact、verdict 或 Task status。

### 12.4 Validation & Error Matrix

| Input / state | Detection | Required result |
|---|---|---|
| relative/control-character root 或 unknown request field | request model | validation failure，不注册 |
| 缺 `PLATFORM_HARD` | baseline compiler | `HardPolicyMissing` |
| `TASK` rule 进入 prepare | baseline compiler | `TaskScopedRuleRejected` |
| PROJECT source URI/hash 不在 exact profile | source guard | `SpecSourceMismatch` |
| overlapping scope 下 field value 冲突 | project conflict detector | `WAITING_HUMAN`，Product Agent 禁止启动 |
| profile/binding/workspace identity 漂移 | binder/preparation comparison | typed conflict/drift，不复用旧 checkpoint |
| record envelope/stage digest 被篡改 | store read + integrity guard | typed corruption，不返回 partial model |
| symlink/path escape/sidecar overlap | registry/store path guard | typed path/workspace error，目标项目不写入 |
| stage prefix 缺失、多余或 lineage 不一致 | request shape + stage guard | validation failure / `ProjectStageNotReady` |
| naive runtime clock | service/compiler/stage guard | typed/value error，不持久化 |

### 12.5 Good / Base / Bad Cases

- **Good**：给一个 Python/Java/C++ 项目的绝对目录，得到带 profile/binding/baseline digests
  的 ProjectPreparation；相同输入重放返回首次 checkpoint。
- **Base**：原生规范只索引 URI/hash，没有 adapter 就不把文本猜成 SpecRule。
- **Bad**：创建临时 Task 来复用 task compiler、项目规范静默覆盖 hard safety、冲突时继续
  Product Agent，或把运行事实写进目标仓库。

### 12.6 Tests Required

- `tests/project_manager/test_baseline.py`：Task-free/稳定排序、Schema、hard safety、scope overlap、
  source provenance、WAITING_HUMAN、append-once/tamper；
- `tests/project_manager/test_store.py`：exact replay、changed identity、atomic failure、digest/envelope
  corruption、symlink/path boundary；
- `tests/project_manager/test_preparation.py`：Python/Java/C++ 仅目录接入、零污染、首次时间重放、
  profile drift、recorder mismatch、重新验证 Product gate；
- `tests/project_manager/test_stages.py`：exact prefix、approval/lineage、authorization digest 和无修改边界；
- targeted pytest 与全量 pytest、Ruff check/format、strict Mypy、offline build、
  `git diff --check` 都是合并门禁。

### 12.7 Wrong vs Correct

#### Wrong

```python
fake_task = Task(description="unknown request", acceptance_criteria=())
baseline = SpecCompiler().compile(fake_task, platform_rules, project_rules, ())
if baseline.conflicts:
    baseline = prefer_project_rules(baseline)
start_product_agent(project_root)
```

#### Correct

```python
request = PrepareProjectRequest(project_root=str(project_root.resolve()))
result = project_manager.prepare_project(request)
preparation = project_manager.require_product_context(result)
authorization = project_manager.advance_stage(
    StageAdvanceRequest(
        target=ProjectStage.PRODUCT_DISCOVERY,
        preparation=preparation,
    )
)
```

正确流程在任何需求出现前只编译项目基线，冲突必须给人类，且只有重新校验通过的
ProjectPreparation 才能解锁 Product Agent。

## 13. T030 Product Agent discovery contract

### 13.1 Scope / Trigger

当实现或修改 Product Agent、需求澄清、ProductSpec 版本、用户确认、Product discovery
重放或 Designer gate 时必须遵守本契约。Product discovery 是 Task-free 上游阶段：不得创建假
Delivery Task，也不得复用 Coder/QA/Reviewer 的 `AgentRole`、ContextBundle 或审批能力。

`OrganizationRole` 表示长期团队岗位；`AgentRole` 只表示现有 Delivery runtime 的
`ORCHESTRATOR/CODER/QA/REVIEWER`。Product Agent 是组织成员，但不是 Delivery verdict participant。

### 13.2 Public signatures

```python
class ProductAgentAdapter(Protocol):
    def run(self, request: ProductAgentRequest) -> ProductAgentResult: ...

class HumanProductDecisionVerifier(Protocol):
    def verify(self, command: HumanProductDecisionCommand) -> VerifiedHumanProductDecision: ...

class ProjectStageAdvancePort(Protocol):
    def advance_stage(self, request: StageAdvanceRequest) -> StageAdvanceAuthorization: ...

class ProductRecordStore(Protocol):
    # append-only typed dialogue/request/spec/approval/checkpoint/operation methods
    ...

ProductDiscoveryService.start(command: StartProductDiscoveryCommand) -> ProductDiscoveryResult
ProductDiscoveryService.record_human_message(
    command: RecordHumanMessageCommand,
) -> ProductDiscoveryResult
ProductDiscoveryService.run_product(command: RunProductAgentCommand) -> ProductDiscoveryResult
ProductDiscoveryService.decide_as_human(
    command: HumanProductDecisionCommand,
) -> ProductDiscoveryResult
```

Wire schemas：`schemas/product-context.schema.json`、`schemas/product-agent-run.schema.json`、
`schemas/product-dialogue.schema.json`、`schemas/product-discovery-checkpoint.schema.json`。

### 13.3 Executable contracts

- 四类 command 都必须带调用方生成的 aware `submitted_at`；command identity 包含完整 typed
  input。相同 operation/run ID + 相同 input 是 exact replay，不同 input 是 conflict；
- Product context 必须携带并绑定 exact `ProjectProfile`、`ProjectSpecBaseline`、preparation、request
  revision、checkpoint 所引用的 dialogue prefix、current ProductSpec 和 fail-closed permissions；Agent
  不能只收到无内容的 hash 引用。独立 source 只有在存在独立 digest 时才能单独声明，项目 baseline
  作为一个 verified aggregate source；
- Product Agent 只能返回 clarification 或 `READY_FOR_REVIEW` ProductSpec；不能写代码、执行 shell、
  改项目状态或批准 ProductSpec；ProductSpec 必须覆盖 acceptance criteria，并严格使用
  `version=current+1`、`supersedes=current.id`；
- 人类 decision command 只携带可信 channel reference。只有 `HumanProductDecisionVerifier` 返回的
  `VerifiedHumanProductDecision` 才能创建 Approval；Product Agent 不能构造 decision/operator/rationale；
- APPROVED 必须在写入审批事实前调用 Project Manager 的 `advance_stage(request)`，由该 Skill
  重新检查 current project facts；旧 preparation、旧 spec ID/digest 或 project drift 全部 fail closed；
- Dialogue、ProjectRequestRevision、ProductSpec、Approval、Operation、Checkpoint 都 append-only。
  adapter/verifier/advancer 输出在内存中校验后，第一个 durable write 必须是携带完整 effect bundle、
  目标 checkpoint 和不可重算外部授权 evidence 的 operation receipt；随后才发布 effects → checkpoint。
  checkpoint 是原子提交点；重启通过 receipt 补齐缺失 effects/checkpoint，不得再次调用已完成的外部端口；
- store 必须使用 root-relative directory descriptors、`O_NOFOLLOW` 与 exclusive hard-link publish，
  并在 publish 前后校验目录 inode；symlink swap、路径逃逸、并发 changed winner 和篡改全部拒绝。

### 13.4 Validation & Error Matrix

| Input / state | Detection | Required result |
|---|---|---|
| 未 PREPARED 或 preparation/request lineage 不一致 | context/service gate | typed error，不调用 Product Agent |
| dialogue sequence/head 或 source digest 不一致 | context integrity | fail closed，不构建 context |
| adapter timeout/provider error/invalid output | typed result boundary | 记录失败 operation，不推进 checkpoint |
| clarification | adapter result | 追加 Product dialogue，提交新 checkpoint |
| ProductSpec 版本、supersedes、scope 或 status 错误 | service/domain guard | `ProductAgentOutputRejected`，无 approval |
| Product Agent 自带 approval 字段 | schema/tool boundary | rejected；只有 human verifier port 可决策 |
| approval reference 未验证或 verified identity 不一致 | trusted verifier guard | `ProductDiscoveryStateError`，无 approval fact |
| stale checkpoint/spec 或 current project facts drift | checkpoint + PM Skill | typed stale/drift error，不解锁 Designer |
| crash before operation receipt | no durable operation exists | 由外部端口自身 idempotency/retry policy 处理，不猜测完成 |
| crash after receipt/before effects/checkpoint | receipt effect bundle | 补齐 effects 并提交 exact checkpoint，不重复外部调用 |
| operation ID 改 input | operation store/service | `ProductOperationConflict` |
| symlink swap/path escape/tamper | store path/integrity guards | typed store error，不写目标项目 |

### 13.5 Good / Base / Bad Cases

- **Good**：PREPARED 项目收到需求，Product Agent 多轮澄清并生成 v1 ProductSpec；可信人类通道
  批准 exact ID/digest，Project Manager 重验 current facts 后解锁 Designer。
- **Base**：adapter timeout 只形成 typed failure receipt；current discovery checkpoint 不变，后续可重试。
- **Bad**：Product Agent 自批、从会话记忆猜用户决定、用最新文件替代 checkpoint prefix、把旧 preview
  当授权、在目标项目写对话/状态，或在 restart 时再次执行外部审批副作用。

### 13.6 Required tests

- `tests/product/test_context.py`：Task-free exact sources、dialogue chain、baseline aggregate provenance、
  permission deny 与 Schema；
- `tests/product/test_agents.py`：clarification/ready/timeout/provider/invalid output、request echo 与 conflict；
- `tests/product/test_models.py`、`test_store.py`：digest/lineage、exact replay、tamper、concurrency、
  symlink/path race；
- `tests/product/test_service.py`：start/message/clarify/version/approval/change request、stale/drift、
  human-only verification、restart replay 与 interrupted checkpoint recovery；
- targeted/full pytest、Ruff check/format、strict Mypy、offline build 和 `git diff --check` 是合并门禁。

### 13.7 Wrong vs Correct

#### Wrong

```python
decision = product_agent.approve(spec)
store.overwrite_current_spec(spec)
designer.start(latest_spec_from_directory())
```

#### Correct

```python
ready = product_service.run_product(run_command)
approved = product_service.decide_as_human(
    HumanProductDecisionCommand(
        approval_reference=trusted_human_reference,
        product_spec_id=ready.product_spec.id,
        product_spec_sha256=ready.product_spec.product_spec_sha256,
        expected_checkpoint_sha256=ready.checkpoint.checkpoint_sha256,
        submitted_at=received_at,
        **identity,
    )
)
assert approved.authorization is not None
```

正确流程让产品决策成为可验证、可恢复的组织事实，而不是某个 Agent 对当前聊天的解释。

## 14. T031 Designer、Planner preview 与 commit-dispatch

### 14.1 Scope / Trigger

修改 approved ProductSpec 到 Delivery Task 之间的 Designer、Planner、Scheduler/ModelRouter preview
或 Project Manager dispatch 边界时，必须遵守本节。Designer/Planner 是
`OrganizationRole`；它们不能加入只承载交付 verdict 的 `AgentRole`，也不能复用 Delivery
`ContextBundle`。

### 14.2 Signatures

```python
DesignerAgentAdapter.run(DesignerAgentRequest) -> DesignerAgentResult
DesignerService.run(RunDesignerCommand) -> DesignerServiceResult
PlannerAgentAdapter.run(PlannerAgentRequest) -> PlannerAgentResult
PlannerStageService.produce(ProduceExecutionPlanCommand) -> PlanningStageResult
PlanningPreviewService.preview(...) -> PlanningPreview
FileExecutionPlanStore.put_execution_plan(plan) -> ExecutionPlan
FileExecutionPlanStore.find_for_request(request_id) -> ExecutionPlan | None
FileExecutionPlanStore.put_run(record) -> PlannerRunRecord
FileExecutionPlanStore.put_checkpoint(checkpoint) -> PlannerCommitCheckpoint
ProjectManagerDispatchService.commit_dispatch(request) -> DispatchCommitRecord
DispatchAuthority.current_snapshot(project_id, task_id) -> DispatchWorkforceSnapshot
DispatchAuthority.commit_if_current(record, expected_snapshot_sha256) -> DispatchCommitRecord
SqliteDispatchAuthority.seed_snapshot(snapshot) -> DispatchWorkforceSnapshot
```

`src/ai_software_engineer/project_manager/dispatch_authority.py` owns two SQLite tables:
`dispatch_workforce_snapshots(project_id, task_id, payload_json, snapshot_sha256)` and
`dispatch_commits(id, project_id, task_id, payload_json, dispatch_sha256)`. The latter row is the
single allocation commit point; Assignment/Lease projections are rebuilt from its exact typed payload.

Wire contracts：`designer-context.schema.json`、`designer-agent-run.schema.json`、
`planner-context.schema.json`、`planner-agent-run.schema.json`、`planner-preview.schema.json`、
`dispatch-commit.schema.json`，以及既有 `technical-design.schema.json`、
`execution-plan.schema.json`。

### 14.3 Contracts

- Designer context 必须携带完整 ProjectPreparation、ProjectProfile、ProjectSpecBaseline、当前
  DESIGNING request revision 和 exact approved ProductSpec/Approval；URI/hash 不能代替 Agent 需要的正文；
- Designer 只能生成 TechnicalDesign。成功结果必须精确覆盖所有 requirement/acceptance IDs；
  receipt 必须先于任何 effect；PLANNING revision 使用 expected-predecessor CAS 发布，随后发布 design
  与最终 DesignCommitCheckpoint。adapter 返回后、receipt 前必须再次检查 current Product facts；
- Planner context 只接受当前 PLANNING `ProjectRequestRevision`、exact DesignCommitCheckpoint、planning
  authorization、ProductSpec/Approval/TechnicalDesign；adapter 前后都必须重新检查 current fact；
- Planner 的 accepted result 必须先写 durable `PlannerRunRecord`，再以 expected-predecessor CAS 发布
  READY revision、ExecutionPlan 和 PlannerCommitCheckpoint；checkpoint 写入和读取都必须重建并比较
  exact run，orphan/forged checkpoint 一律拒绝；重启只从 receipt 补齐，不再次调用 adapter；
- ExecutionPlan 固定 `Coder → QA → Reviewer`，只包含 capability、risk、minimum BrainTier 和
  checkpoints 等抽象 demand；具体 Agent/model/provider/Assignment/Lease 一律禁止；
- PlanningPreviewService 不得持有 write store。preview 临时计算三阶段 Assignment/Lease/ModelSelection，
  并把前一阶段候选纳入后续阶段 capacity/self-review 检查，但不落盘；
- preview identity 必须绑定 Task、WorkItem、ExecutionPlan、三个 RunDemand 和 canonical workforce/
  policy snapshot；collection 排序不影响 identity，phase 顺序必须影响 identity；
- commit-dispatch 必须从权威端口验证 exact current READY revision 和 durable Planner run/plan/checkpoint，验证
  未过期 preview，并由 `DispatchAuthority` 读取 current workforce snapshot；调用方不能自报 current facts；
- commit 在内存中重新运行相同 engines，并比较 Agent 与 policy/version/provider/model/tier 语义；
  RunDemand 必须由 exact Task + ExecutionPlan 机械派生，不能由调用方注入；
- 三阶段全部成功后，必须再次读取 current READY 与完整 Planner handoff，再只调用一次
  `DispatchAuthority.commit_if_current`。生产实现必须先获取所有 request revision writer 共享的 Product
  fence，再进入所有 reservation writer 共享的 SQLite transaction；同一围栏内重验 READY/Planner，
  CAS snapshot，并原子保存 NEW Task 与 `(RoleAssignment, TaskLease, ModelSelection) × 3`；
- append-only stores 对 exact replay 幂等，changed identity、digest/envelope tamper、ambiguous
  request plan 和 symlink/path escape 必须 fail closed。Designer/Planner stores 使用 dirfd、
  `O_NOFOLLOW`、write-all、目录 inode 前后校验和 publish 后 exact read-back。

### 14.4 Validation & Error Matrix

| Input / state | Detection | Required result |
|---|---|---|
| Product 未批准、DESIGNING revision 非 current、context lineage 漂移 | Designer context/service | 不调用或不接受 Designer output |
| TechnicalDesign 缺 requirement/acceptance coverage | domain output guard | `DesignerOutputRejected`，无 checkpoint |
| receipt 后中断 | Designer replay | 补齐 exact effects，不再次调用外部端口 |
| Agent 运行期间 request revision 被并发推进 | adapter 后 current-fact recheck / revision CAS | 只保留可审计 receipt 或 zero effects；无 design/plan/checkpoint |
| Planner request 非 current PLANNING revision | Planner stage current-fact gate | typed stale error，zero plan writes |
| Planner receipt 后进程中断或 fresh adapter 输出不同 plan | durable run receipt replay | 补齐 receipt 中唯一 plan/READY/checkpoint，不再次调用 adapter |
| ExecutionPlan phase 顺序错或含具体分配字段 | strict model/schema | invalid output，无 READY revision |
| capacity/model route 不可行 | preview pure engines | `PlanningPreviewRejected`，zero writes |
| preview 到期或 Task/WorkItem/demand/workforce/policy 改变 | commit preview guard | `DispatchPreviewStale`，zero writes |
| Planner run/plan/checkpoint orphan、伪造或 lineage 不一致 | durable full-handoff read-back | `DispatchPreviewStale`，zero writes |
| READY revision 或 workforce snapshot 在 commit fence 中改变 | Product revision fence + SQLite CAS | stale/conflict，zero writes |
| commit 选择与 preview 语义不同 | commit engine comparison | `DispatchDecisionDrift`，zero writes |
| 后续 phase 复用同 Agent 或超 capacity | pending assignment/lease inputs | typed rejection，zero partial writes |
| store replay 内容不同或文件被篡改 | append-only store read-back | conflict/corruption，不覆盖首次记录 |

### 14.5 Good / Base / Bad Cases

- **Good**：approved spec → complete design checkpoint → abstract plan + feasible preview → current-fact
  commit → 一个包含三个独立 Agent 分配的 dispatch record；两个 authority 实例竞争时只有一个 commit。
- **Base**：当前没有满足 context/risk/minimum tier 的 route，preview 明确拒绝；更新组织 policy/facts
  后重新 preview，不把不可行计划伪装成可执行。
- **Bad**：Planner 把 agent/model 写进 ExecutionPlan，或 Project Manager 逐阶段写 store 后才发现
  Reviewer 无容量；这会让建议越权并留下半提交事实。

### 14.6 Tests Required

- Designer：完整 context/permissions、adapter success/failure/conflict、coverage、current Product facts、
  adapter-window concurrent revision、receipt-first interrupted recovery、store replay/tamper/path/short-write；
- Planner：context/adapter、current revision stale guard、plan store find/replay/ambiguity/tamper、
  durable fresh-process replay、concurrent revision、abstract plan、READY_FOR_DELIVERY revision；
- Preview：无 write port、determinism、demand digest、capacity/model/minimum tier refusal；
- Dispatch：stage/task/work-item/current workforce drift、expiry、self-review、commit-time capacity/model
  refusal、fabricated/current READY+checkpoint、commit-window CAS、single store call、exact replay/conflict/tamper；
- 所有 Python wire fixture 必须同时通过 Pydantic round-trip 与 Draft 2020-12 Schema 正反测试。

### 14.7 Wrong vs Correct

#### Wrong

```python
for phase in plan.phases:
    store.put(scheduler.match(phase))  # 第三个角色失败时前两个已经被提交
```

#### Correct

```python
preview = planner_preview.preview(snapshot)  # pure/read-only evidence
record = project_manager.commit_dispatch(exact_handoff.with_preview(preview))
# service 自行读取权威 facts；全部成功后仅调用一次 authority.commit_if_current(...)
```

## 15. T032 统一项目接单、恢复与 Delivery bridge

### 15.1 Scope / Trigger

修改“项目目录 + 需求”入口、Project Manager delivery checkpoint、Dispatch 到 Task runtime 的桥接，
或 role worktree 恢复规则时，必须遵守本节。T032 只组合既有阶段；不得在 bridge 中重新做产品、
设计、资源规划，也不得把 Runtime 内部路径暴露成每次接单的业务参数。

### 15.2 Signatures

```python
UnifiedProjectEntryService.start(StartProjectDelivery) -> ProjectDeliveryResult
UnifiedProjectEntryService.reply(ReplyToProduct) -> ProjectDeliveryResult
UnifiedProjectEntryService.approve(ApproveProductSpec) -> ProjectDeliveryResult
UnifiedProjectEntryService.resume(ResumeProjectDelivery) -> ProjectDeliveryResult
UnifiedProjectEntryService.status(DeliveryId) -> ProjectDeliveryResult
FileProjectDeliveryCheckpointStore.put_intake(ProjectDeliveryIntake) -> ProjectDeliveryIntake
FileProjectDeliveryCheckpointStore.put(ProjectDeliveryCheckpoint) -> ProjectDeliveryCheckpoint
DispatchTaskMaterializer.materialize(DispatchCommitRecord) -> Task
ExecutionPlanAgentAdapter.run(AgentRequest) -> AgentResult
DispatchRoleWorktreeCoordinator.open_coder(...) -> RoleWorktreeBinding
DispatchRoleWorktreeCoordinator.open_verifiers(...) -> VerificationWorktreeBindings
configure_project_entry(ProjectEntryProvider) -> None
project_entry() -> UnifiedProjectEntryService
```

CLI 合同固定为 `ase project start/reply/approve/resume/status`。测试宿主可以显式绑定
organization-owned team composition；T034 后，未注入测试 provider 时 `project_entry()` 必须惰性创建
`OrganizationTeamHost.from_environment()`。配置、MySQL 或 provider 前置条件失败时以稳定错误退出，不得
回退伪造 Agent。

### 15.3 Contracts

- delivery ID 由 canonical absolute project root + initial requirement 确定派生；同一 ID 的 title、
  requirement 或 root 变化必须拒绝；首次接单先 exact-create `ProjectDeliveryIntake`，使 Product 原生
  fact 生成前的崩溃也能从原始业务输入恢复；
- `ProjectDeliveryCheckpoint` 是 append-only、连续 sequence/hash chain，只引用各阶段权威 fact 的
  ID/digest，不复制其 payload；每次命令都先读 current checkpoint，再由 backend `reconcile` 重验
  原生事实；人工 reply/approve 必须提交 exact current checkpoint digest；
- `resume` 不接收新业务事实。PREPARING/PRODUCT_DISCOVERY 从 durable intake 重放；DESIGNING、
  PLANNING、DISPATCHING、DELIVERING 从最后 checkpoint 继续；WAITING、BLOCKED、FAILED、DONE 不被
  静默推进；
- ProductSpec approval 是正常流程唯一人工业务门禁。规范冲突、资源不可行、权限/完整性错误属于
  安全阻塞，不得被解释为业务确认；
- `DispatchCommitRecord.task` 是 TaskRepository 的 durable intent。production host 使用 MySQL，低层
  测试可使用 SQLite；materializer 只允许不存在时
  创建，或把已推进 Task 归一到 NEW/attempt=0 后 exact compare；同 ID 不同 immutable facts 立即拒绝；
- T031 `ExecutionPlan` 到 Delivery `PlanArtifact` 的转换是确定性 materialization：必须保留 exact
  Product/Design/acceptance lineage，不能重新调用 Planner，也不能引入新的 concrete allocation；
- role runtime 必须消费 dispatch 内的 exact Agent/model/provider/Assignment/Lease。Coder 从 Task 的
  full base SHA 创建 branch worktree；QA 与 Reviewer 从同一 full candidate SHA 创建互相独立的 detached
  worktree；恢复必须核对 common-dir、path、role、attempt、branch/detached 和 HEAD，dirty 现场保留；
- CLI 每次接单只需要 project root、requirement 和可选 title。数据库、artifact、context、evidence、
  evaluation、handoff、worktree roots 由 application host 从 project sidecar/organization workspace
  组合，不能由用户逐次拼装；
- checkpoint/intake 文件使用 canonical digest envelope、exclusive publish、write-all、root/directory
  inode 与 symlink/path 检查；changed replay 和篡改不能覆盖首次事实。
- backend 必须把可预期的 provider/policy/output 失败分类为
  `DeliveryBackendFailure(code, safe_summary)`；facade 将其提交为安全 BLOCKED checkpoint。未分类异常视为
  进程中断，保留当前可恢复 checkpoint，不能把异常字符串或 provider payload 原样持久化。

### 15.4 Validation & Error Matrix

| Input / state | Detection | Required result |
|---|---|---|
| relative project root、unsafe sidecar/intake/checkpoint path | command model / store guards | typed validation/path error，zero stage effects |
| same delivery ID 的 title/root/requirement 改变 | durable intake comparison | conflict，不调用 Product |
| Product start 前进程中断 | intake + PREPARING/PRODUCT_DISCOVERY checkpoint | `resume` 使用原 submitted_at 与原始输入继续 |
| reply/approve 使用旧 checkpoint | current digest fence | `DeliveryCheckpointStale`，zero Product effects |
| native Product/Design/Plan/Dispatch/Task digest 漂移 | backend reconcile / bridge guards | fail closed，不从 checkpoint 猜测 payload |
| Dispatch Task 已存在且 immutable facts 不同 | `DispatchTaskMaterializer` exact compare | `DispatchTaskConflict`，不覆盖 Task |
| concrete Agent/model 与 dispatch allocation 不同 | worktree coordinator binding check | checkout 前 `DispatchRoleBindingMismatch` |
| QA/Reviewer revision 非 full SHA 或不同 | worktree coordinator | 拒绝验证，不使用 movable ref |
| worktree path/common-dir/HEAD/branch 漂移或 dirty | strict recovery inspection | typed recovery error；dirty evidence 不清理 |
| application host 未绑定 team runtime | `project_entry()` | CLI exit 2、安全单行错误、无 traceback |
| Delivery retry budget exhausted | native retry result | terminal BLOCKED checkpoint + evidence references |

### 15.5 Good / Base / Bad Cases

- **Good**：Python/Java/C++ Git fixture 只提交目录和需求，在 Product exact approval 后串行得到 DONE、
  full candidate SHA 和完整 checkpoint chain；目标 main checkout 保持不变。
- **Base**：Product 要求澄清或等待批准，命令返回 WAITING checkpoint；进程重启后 status/reply/approve/
  resume 从 durable facts 继续，不依赖 adapter 内存。
- **Bad**：用旧 approval checkpoint、伪造 dispatch Task、给 QA movable branch，或把不同 model 的
  AgentDefinition 绑定到已提交 allocation；系统必须在 effect 前拒绝，而不是“尽量继续”。

### 15.6 Tests Required

- checkpoint/intake：strict model、canonical identity、exact replay、sequence/hash chain、tamper、gap、
  symlink/root swap、changed replay、Product-start interruption resume；
- unified entry：Python/Java/C++ directory+requirement、Product approval fence、DONE/BLOCKED、reopen/status、
  target tree zero pollution；
- delivery bridge：Task create-or-compare、progressed replay、Task collision、PlanArtifact acceptance lineage；
- worktree：真实 Git branch/detached recovery、wrong path/common-dir/HEAD/ref、dirty preservation、dispatch
  Agent/model drift、QA/Reviewer exact same candidate；
- CLI：只暴露业务参数；unconfigured host 稳定退出且无 traceback；全量 Ruff、strict Mypy、offline build。

### 15.7 Wrong vs Correct

#### Wrong

```python
runtime = RuntimeConfig(database=user_flag, artifacts=user_flag)  # 每个需求手拼内部路径
qa = git.checkout("candidate")  # movable ref，未消费 dispatch
```

#### Correct

```python
result = project_manager.start(StartProjectDelivery(project_root=root, requirement=text))
# host 从 sidecar/organization 自动组合内部路径；人工只确认 exact Product checkpoint
bindings = worktrees.open_verifiers(dispatch, full_candidate_sha, assigned_definitions)
```
