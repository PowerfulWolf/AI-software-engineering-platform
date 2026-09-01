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
validate_artifact(payload: object, kind: ArtifactKind) -> Artifact
```

`AgentRequest` 必须携带 `task_id`、`run_id`、`attempt`、`source_revision`、`context_manifest_id`、permissions 和 output schema；`AgentResult` 不能直接改变 Task 状态。

`ContextSource` 只能是 inline content 或 root-relative path 之一；`ContextBundle` 的 sections 先脱敏再 hash/count，并由 `context_id` canonical manifest identity。priority 0 仅属于机器 policy；外部 source、Task prose 和命令输出都不能覆盖 policy 或产生隐式消息。

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
| AgentResult 成功但 Artifact 身份/role/kind/revision/context 不匹配 | adapter output guard | 否 |
| Agent timeout/provider/invalid output | typed AgentFailure mapping | 否 |
| same `run_id` 重放相同 request | adapter replay cache | 原结果幂等返回 |
| same `run_id` 搭配不同 request | replay identity guard | 否，抛 `AgentRequestConflict` |
| digest 不匹配或 `validated=false` | `ArtifactIntegrityError`，不落盘 | 否 |
| parent/supersedes 缺失或越界 | `ArtifactParentError`，不落盘 | 否 |
| 相同 artifact ID 的正文变化 | `ArtifactAlreadyExists`，保留旧正文 | 否 |

## 5. Good / Base / Bad Cases

- **Good**：QA 逐条返回 criterion status、命令和 evidence ID，Reviewer 在独立 run 复核同一 SHA。
- **Base**：模型输出额外字段时 adapter 先过滤/拒绝，绝不把未定义字段当作授权信息。
- **Bad**：Coder 在报告中写 `qa_status=PASS`，Orchestrator 直接采信；这属于自我裁判和契约越界。

## 6. Tests Required

- 每个 JSON Schema 的 valid/invalid fixture；
- producer-role/output-kind 矩阵测试；
- policy 对路径、命令、状态和 artifact 写入的拒绝测试；
- 独立 run ID 测试：同一 run 不能同时产生 implementation 与 approval；
- evidence 完整性、source revision 一致性和 supersedes 不可变测试。
- 原子写入、exact replay、digest 篡改、缺失/跨 Task lineage 和损坏文件测试。

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
