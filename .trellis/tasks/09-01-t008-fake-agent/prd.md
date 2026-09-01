# T008 — Deterministic FakeAgentAdapter

## Goal

为串行 Orchestrator 提供一个不依赖网络或模型 SDK 的 typed `AgentAdapter`，可重复注入成功、QA FAIL、Reviewer REJECT、timeout 以及 adapter failure，验证角色边界、Artifact 契约和恢复路由。

## Requirements

- 定义 `AgentRequest`、`AgentResult`、`AgentFailure` 和 `AgentAdapter` Protocol；request 必须绑定 run/task/role/attempt/source revision/context manifest/permissions/output schema/timeout。
- `AgentResult` 只允许 typed Artifact 或 typed failure；成功必须有 Artifact，失败/超时不能携带 verdict Artifact。
- `FakeAgentAdapter` 支持按 `(AgentRole, attempt)` 脚本化 `SUCCESS`、`QA_FAIL`、`REVIEW_REJECT`、`TIMEOUT`、`INVALID_OUTPUT` 和 `PROVIDER_ERROR`，并提供 default scenario。
- 对 Artifact 重新验证 task、role、kind、source revision、context manifest 和 QA/Review verdict 一致性；错误输出转换为稳定 `INVALID_OUTPUT`，不把裸 dict 穿透领域层。
- 同一 `run_id` 的完全相同 request 重放返回同一结果；相同 run ID 搭配不同 request 抛出 typed conflict，防止重复/篡改运行。
- timeout 结果无 Artifact、无 verdict，包含 `TIMEOUT` failure 和 transient 标志；provider error 可标记 transient，供后续 retry router 使用。
- 不调用网络、Git、文件系统或模型 SDK；Fake adapter 只能在 Agent Execution Plane 使用。

## Acceptance Criteria

- [x] Request/Result/Failure 是 immutable、extra-forbid 的 typed models，非法状态组合被拒绝。
- [x] Success 返回与 request 对齐的 plan/implementation/QA/Review Artifact；QA FAIL 和 Review REJECT 只能由对应角色产生。
- [x] Timeout、invalid output 和 provider error 产生稳定 failure code，结果不携带 Artifact/verdict。
- [x] 同一 run 重放幂等，不同 request 冲突；未配置 scenario 的调用 fail closed。
- [x] Fake/real adapter 共用 `AgentAdapter.run(request) -> AgentResult` seam，公开包导出稳定入口。
- [x] 测试覆盖每种行为、角色/kind/verdict/revision/context mismatch、idempotency 和 immutability。
- [x] Ruff、strict mypy、pytest、lock、build 和 diff checks 全部通过。

## Out of Scope

- 真实模型 SDK、网络调用、prompt 模板渲染、Orchestrator 状态迁移、ArtifactStore 持久化和并行执行。

## Rollback

回退单个 T008 commit；不修改已有 Task、StateEvent、Context、Git 或 ArtifactStore 数据。
