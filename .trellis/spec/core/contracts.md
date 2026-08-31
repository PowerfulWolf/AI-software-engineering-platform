# Core Role & Artifact Contract

## 1. Scope / Trigger

本规范适用于所有 Agent request/response、JSON artifact、权限 policy 和跨角色路由。新增或修改任何字段、角色、权限、finding 或 verdict 时，必须同步更新 `schemas/`、`docs/contracts.md` 和 contract fixtures。

## 2. Signatures

```python
AgentAdapter.run(request: AgentRequest) -> AgentResult
ArtifactStore.put(artifact: ArtifactEnvelope) -> ArtifactRef
Policy.check(role: AgentRole, operation: Operation) -> PolicyDecision
validate_artifact(payload: object, kind: ArtifactKind) -> Artifact
```

`AgentRequest` 必须携带 `task_id`、`run_id`、`attempt`、`source_revision`、`context_manifest_id`、permissions 和 output schema；`AgentResult` 不能直接改变 Task 状态。

## 3. Contracts

### Role boundaries

- `orchestrator`：读全量元数据，写状态/索引，不写业务代码；
- `coder`：写允许的生产代码/单元测试，输出 implementation-report，不写 verdict；
- `qa`：读候选代码，可写测试目录，输出 qa-report，不写生产代码；
- `reviewer`：只读候选代码和上游 artifact，输出 review-report，不改仓库。

### Artifact boundary

Artifact 通过 `schemas/artifact.schema.json` 的共同 envelope 传递；业务内容分别由 `plan.schema.json`、`implementation-report.schema.json`、`qa-report.schema.json`、`review-report.schema.json` 约束。Schema 变化必须同步更新 `docs/contracts.md`、`AGENTS.md` 和 contract fixtures。

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
| QA 有 `NOT_TESTED` required criterion | `qa-report=FAIL`，路由 Coder 或阻塞 | 是（FAIL） |
| Reviewer `APPROVE` 但有 MAJOR/BLOCKER finding | validator 拒绝 verdict，重跑 Reviewer | 否 |
| evidence URI/sha 缺失 | artifact 无效，不允许状态迁移 | 否 |

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
