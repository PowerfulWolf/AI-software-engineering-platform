# T030 Product Agent 与确认循环

## 阶段目标

在 T029 的 `PREPARED` 项目 checkpoint 之后，建立一个可审计、可重放、可人工验证的
Product Agent 需求澄清循环。Product Agent 可以追问、整理和修订 ProductSpec，但不能
自己批准产品定义；只有经可信人工通道验证且绑定 exact spec ID/digest 的
决策，才能请求 Project Manager 解锁 Solution Designer。

## 已完成

- 将组织成员胜任资格与 delivery runtime 岗位分开：`OrganizationRole` 包含
  Project Manager、Product、Designer、Planner 与四个 delivery 岗位；`AgentRole` 继续只包含
  Orchestrator/Coder/QA/Reviewer，不放宽现有 Task state machine、Assignment 或 RunDemand。
- 新增 `ai_software_engineer.product` package，提供 Product models、filesystem store、
  context builder、adapter/fake 与 `ProductDiscoveryService`。
- 新增 task-free `ProductContextManifest`，精确绑定 ProjectPreparation、当前
  ProjectRequest、对话前缀、当前 ProductSpec、next version/supersedes、只读来源 URI/hash 与
  fail-closed Product 权限；不复用或伪造 Delivery Task context。
- 新增 `ProductAgentAdapter.run(ProductAgentRequest) -> ProductAgentResult`；成功结果只能是
  clarification 或 `READY_FOR_REVIEW` ProductSpec，timeout/provider/invalid output 都是 typed failure，
  不生成批准 verdict。Fake adapter 支持确定重放和故障注入。
- `ProductDiscoveryService` 实现 start、记录人类消息、运行 Product Agent、
  `REQUEST_CHANGES` 与 `APPROVED` 循环；过期 checkpoint、错误阶段、输入或 lineage
  不一致均 fail closed。
- 人工决策命令只传入 `approval_reference`、exact spec ID/digest 和 expected checkpoint。
  隔离的 `HumanProductDecisionVerifier` 解析并返回已验证的 decision/operator/rationale/time；
  Product Agent 不持有 verifier，也无法构造可信批准。
- `APPROVED` 还必须经 Project Manager `advance_stage` 使用当前 ProjectPreparation、
  ProjectRequest、ProductSpec 和 ProductSpecApproval 重新校验。已完成 operation 重放时使用
  durable verified decision/authorization，不重复调用人工 verifier 或 stage advancer。
- 新增 `product-agent-run`、`product-context`、`product-dialogue` 和
  `product-discovery-checkpoint` JSON Schema，并验证 Python model 与 wire 形状。

## 持久化与崩溃恢复

Product sidecar store 以 append-only 方式保存：

```text
ProductDialogueRecord       digest-linked dialogue
ProjectRequestRevision      supersedes-linked request state
ProductSpec                 version + supersedes lineage
ProductSpecApproval         exact spec ID + digest + verified human fact
ProductDiscoveryCheckpoint  current committed Product view
ProductOperationRecord      command digest + result + intended checkpoint
```

一次状态变更在外部结果校验后按“operation receipt（完整 effect bundle）→ 效果事实 →
checkpoint”发布。checkpoint 是提交点：较新但未被 checkpoint 引用的事实不会被当作当前状态。
如果进程在 operation 后、effect 或 checkpoint 发布前崩溃，exact replay 会从 operation payload
补齐不可变事实并恢复 checkpoint，且不会重新调用已经完成的 adapter/verifier/advancer。

所有记录都在读写时复核 typed schema、canonical SHA-256、序号、supersedes 与跨记录
lineage。filesystem publish 使用独占、不可覆盖的同目录发布，并对 root/directory 替换、
symlink 和 path escape fail closed，不写入目标项目。

## 关键不变量

1. Product Agent 可以生成 ProductSpec，但不能生成或修改 ProductSpecApproval。
2. 人工批准不是 prompt 字段；它来自可信 verifier，并绑定 exact current checkpoint 和 spec digest。
3. `REQUEST_CHANGES` 生成新 request revision 和后续 ProductSpec 版本，不覆盖旧对话、spec 或批准。
4. Product context 只读 checkpoint 已提交的事实前缀，不依赖某个 Agent 会话记忆。
5. 相同 operation 重放是幂等的；相同 ID 下改变 typed input 是冲突，不允许宽松接受。

## 验证

- T030 Product targeted suite：**51 passed**；
- 覆盖 Product model/store/context/adapter/service 的正向、反向、版本、完整性和 schema 契约；
- 覆盖 clarification、ready-for-approval、request-changes、approved、timeout/provider/invalid-output；
- 覆盖 stale checkpoint、operation 输入冲突、Product self-approval 阻断、人工验证失败、
  Project Manager current-fact stage guard、重启后批准重放与 checkpoint 恢复；
- 覆盖 record tamper、lineage 断裂、并发首写、symlink/path boundary 与目录替换竞态。
- 全量 pytest：**504 passed**；Ruff check/format、strict Mypy、offline sdist/wheel build 和
  `git diff --check` 全部通过。

## 当前边界与下一阶段

T030 交付的是 Python application seam 和 fake adapter，尚未将 Product discovery 暴露成
“项目目录 + 需求”的统一 CLI。T031 将在已批准 ProductSpec 上接入 Designer/Planner
与调度 Skills；T032 再把 prepare、Product、Design、Plan、dispatch 和现有串行 delivery
组成可 resume 的统一入口。T033 暂不执行。

本记录随 T030 集成提交归档；精确提交可通过
`git log -- docs/archive/2026-09-02-t030-product-agent.md` 查询。
