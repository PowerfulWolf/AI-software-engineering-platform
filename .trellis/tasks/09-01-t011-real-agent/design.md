# T011 设计

## Boundary

```text
AgentRequest
    ↓
PromptBuilder (typed messages; explicit Context/Artifact resolver)
    ↓
HttpTransport (POST /chat/completions, timeout, auth header)
    ↓
Provider JSON decoder
    ↓
validate_artifact(kind) + AgentResult identity guard
```

`OpenAICompatibleAgentAdapter` 只拥有 provider HTTP 细节、响应解码和 replay cache。
它不修改 Task、不写 ArtifactStore、不执行 Git，也不负责 sealing；Orchestrator 仍会
重新 seal 并持久化模型返回的 Artifact。

## Public seams

- `PromptBuilder.build(request) -> PromptPayload`：默认 `ContextPromptBuilder` 读取显式
  `ContextResolver` 的 manifest 和 input Artifact；测试可注入固定 builder。
- `ContextStore.put/get`：`FileRunContextBuilder` 登记 manifest，真实运行使用原子
  `FileContextStore`，`StoredContextResolver` 再组合 ArtifactStore 给 PromptBuilder。
- `HttpTransport.post(url, headers, body, timeout_seconds) -> HttpResponse`：默认
  `UrllibHttpTransport` 使用 `urllib.request`, `shell` 概念不存在；测试使用 fake transport。
- `OpenAICompatibleAgentAdapter.run(request) -> AgentResult`：唯一交付 seam。

## Provider protocol

请求发送到完整 `chat/completions` endpoint（base URL 会规范化），body 使用：

```json
{
  "model": "configured-model",
  "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
  "temperature": 0,
  "stream": false,
  "response_format": {"type": "json_object"}
}
```

响应读取 `choices[0].message.content`，也接受 Responses 风格的 `output_text` 字段，
再移除单层 Markdown `json` fence 并 `json.loads`。Artifact 必须是完整 v0.1 envelope；未 sealing
的 integrity 可以是 `validated=false`，后续由 Orchestrator `seal_artifact` 接管。

## Error policy

provider 返回体只用于内部诊断，不能进入 `AgentFailure.message`；消息只包含 HTTP 状态
或稳定的 transport 分类。Authorization key 永不写入日志/异常。2xx 非法 JSON/Artifact
是不可重试的 `INVALID_OUTPUT`；429/5xx/连接失败可由 T010 retry router 重试。
