# T014 设计

## Configuration boundary

`RuntimeConfig` 是 operator-owned 配置，不是 Agent artifact。它只允许 endpoint、模型、版本、
环境变量名、路径、ContextSource 和可选 role override；API key 永远不进入 JSON、日志或异常。

## Composition

```text
RuntimeConfig
  → RuntimeSession
  → SqliteTaskRepository + FileArtifactStore + FileContextStore + FileEvaluationEventStore
  → RoleAwareAgentAdapter(OpenAICompatibleAgentAdapter x 4)
  → EvaluatingAgentAdapter
  → RetryingOrchestrator
```

`RoleAwareAgentAdapter` 只做 typed role routing；Provider SDK/HTTP 仍隔离在既有
`OpenAICompatibleAgentAdapter`。`RuntimeSession` 是 composition root，不改变 Orchestrator 的
状态机和 retry 规则。

## Case identity

没有显式 `--case-id` 时，以 Task ID 的 SHA-256 前 32 位生成稳定 case ID/event ID；已有
`CaseStartedEvent` 只做 exact replay，base/task identity 不一致则拒绝。run 事件由既有
`EvaluatingAgentAdapter` 自动发出。

## Good / Base / Bad

- Good：相同 config/task/case replay 使用相同 CaseStartedEvent，Agent run facts 不重复计数；
- Base：fake adapter 可注入 `RuntimeSession` 测试状态机，无网络也能跑离线 fixture；
- Bad：配置直接携带 `api_key`、CLI 接收 `--adr=true`、或通过 `RuntimeSession` 直接把 Task 改成 DONE。
