# T011 — OpenAI-compatible real AgentAdapter

## Goal

为 v0.1 接入一个可替换供应商的真实 AgentAdapter。Adapter 通过 OpenAI-compatible
Chat Completions HTTP 接口调用模型，严格复用现有 `AgentRequest → AgentResult` typed
contract，并把模型输出转换为可验证的四类 Artifact；Fake adapter 和真实 adapter 可以
在 Orchestrator 中互换。

## Scope

- 使用 Python 标准库 HTTP client，不把供应商 SDK 引入 domain 或 orchestration 层；
- 提供可注入的 prompt builder 与 HTTP transport seam，默认实现可读取 ContextBundle 和上游 Artifact；
- 提供 typed ContextStore，并让 FileRunContextBuilder 可在真实调用前登记/持久化 manifest；
- 支持 JSON object 响应、Markdown JSON fence 清理、身份/role/kind/revision 校验；
- 将 timeout、HTTP provider error、非法 JSON/Artifact 映射为稳定的 typed `AgentResult`；
- 对相同 `run_id` 的完全相同 request 做内存内幂等重放，冲突 request 立即拒绝；
- API key 只进入请求 header，错误消息和 evidence 不泄露 key 或 provider 原始响应。

## Non-goals

- 不在 T011 修改 Orchestrator 状态机、Task/Artifact Schema 或引入并行/DAG；
- 不实现模型供应商 SDK 专用能力、tool calling、streaming、自动 Git 操作或自动 merge；
- 不把 ContextBundle/Artifact 隐式塞入 AgentRequest wire contract；默认 prompt builder 通过显式 resolver 读取它们。

## Acceptance Criteria

- [x] `OpenAICompatibleAgentAdapter` 实现现有 `AgentAdapter` Protocol；
- [x] 成功响应能得到对应 role 的 typed Artifact 和 `SUCCEEDED` AgentResult；
- [x] HTTP timeout/provider error/invalid output 均无 Artifact/verdict，并返回正确 error code/transient；
- [x] request/result identity、producer role/run、output schema、Coder candidate revision 全部 fail closed；
- [x] 同一 run ID exact replay 幂等，变更任一 request 字段抛 `AgentRequestConflict`；
- [x] HTTP body、Authorization、timeout、JSON response format 通过 transport seam 可验证；
- [x] ContextBundle 可由 FileContextStore 原子持久化、按 ID 读回并检测冲突/篡改；
- [x] contract tests、Ruff、strict mypy、pytest、uv lock/build 与 diff check 全部通过。

## Contract and validation matrix

| 输入 | 行为 |
|---|---|
| HTTP 2xx + valid JSON Artifact | `SUCCEEDED` + one typed Artifact |
| HTTP 2xx + fenced/invalid JSON | `FAILED/INVALID_OUTPUT`，无 Artifact |
| HTTP 4xx | `FAILED/PROVIDER_ERROR`，`transient=false` |
| HTTP 429/5xx、连接错误 | `FAILED/PROVIDER_ERROR`，`transient=true` |
| transport timeout 或 request timeout | `TIMED_OUT/TIMEOUT`，`transient=true` |
| Artifact identity/kind/revision/context 不匹配 | `FAILED/INVALID_OUTPUT`，无 Artifact |
| same run ID + exact request | 返回同一 immutable result |
| same run ID + changed request | `AgentRequestConflict`，不发 HTTP |

## Rollback

删除 provider adapter 和其 docs/tests 即可回退；Orchestrator 默认继续使用
`FakeAgentAdapter`，不改变已有 Task、Artifact、StateEvent 数据。
