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
创建时间和排除自身字段计算的 `manifest_sha256`。`ProjectWorkspaceRegistry` 在 sidecar 中创建 `workspace.json` 以及 profile/agents/
knowledge/policy/state/artifacts/contexts/evidence/evaluations/handoffs/runs/locks/logs/
spec-conflicts 目录；所有目录先 staging + fsync，再以 rename 发布。重复注册返回首次 manifest，
不会覆盖或修复现有 workspace。

目标项目是实际代码 cwd，平台不在其中写 `.ase`、Agent 日志、Artifact 或数据库，也不默认复制
源码。项目原生规范只能被读取和引用；`SpecCompiler` 后续若发现 project rule、platform rule 或
Task constraint 冲突，必须产生 `SPEC_CONFLICT`/`BLOCKED`，由人工通过持久化 resolution 决定。
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

`implementation-report` 只能描述实现事实；QA verdict 必须来自独立 QA run；Review verdict 必须来自独立 Reviewer run。任何同一 run 同时产出实现与批准信号都视为 policy violation。

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
