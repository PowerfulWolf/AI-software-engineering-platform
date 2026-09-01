# T014 实施记录

## 交付

- `RuntimeConfig`、`RuntimePaths` 和 `RoleAgentOverride` 提供 operator-owned、Pydantic
  校验的运行配置；`schemas/runtime-config.schema.json` 是跨语言 wire contract，API key
  只通过 `api_key_env` 从环境读取。
- `RuntimeSession` 组合 SQLite Task repository、Artifact/Context/Evaluation stores、
  `RoleAwareAgentAdapter`、`EvaluatingAgentAdapter` 和 `RetryingOrchestrator`；每个 case
  先写入可幂等重放的 `CaseStartedEvent`。
- `ase task run TASK_ID --config runtime.json [--case-id CASE_ID]` 提供真实 provider 入口；
  fake adapter 通过同一 `AgentAdapter` seam 在测试中完成离线四角色闭环。
- Reviewer/Orchestrator 写权限和 override agent ID 在 composition boundary 再次收紧，防止
  配置意外扩大 v0.1 角色边界。

## 已知限制

- CLI 当前只装配 OpenAI-compatible adapter；离线 fake 仅用于 Python 测试注入，不由 JSON
  配置选择。
- RuntimeSession 不负责创建 Git worktree、merge 或 deploy；这些动作继续属于 Repository
  Plane 和 human boundary。
- 未引入复杂 DAG、消息队列、向量库、容器 sandbox 或多租户。
