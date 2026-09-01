# Runtime 配置与任务执行

T014 把已经通过测试的 Domain、Context、Artifact、Evaluation 和 `RetryingOrchestrator`
组装成一个可运行的 composition root。Runtime 配置属于操作者和部署环境，不是 Agent
artifact；真实模型凭据只从进程环境读取。

## 最小配置

配置文件必须符合 [`schemas/runtime-config.schema.json`](../schemas/runtime-config.schema.json)。
`endpoint` 是 OpenAI-compatible Chat Completions endpoint，`model` 是默认模型名：

```json
{
  "endpoint": "https://api.example.test/v1",
  "model": "gpt-5",
  "api_key_env": "OPENAI_API_KEY",
  "paths": {
    "database": ".ase/state.sqlite3",
    "artifacts": "artifacts/runs",
    "contexts": "artifacts/contexts",
    "evaluation_events": "artifacts/evaluation-events",
    "handoffs": "artifacts/handoffs"
  },
  "test_entrypoints": ["pytest"],
  "timeout_seconds": 600,
  "token_budget": 20000,
  "max_retries": 0
}
```

不要添加 `api_key`、Authorization header 或 provider 原始响应到配置文件。运行前设置：

```bash
export OPENAI_API_KEY='...'
```

`api_key_required` 默认为 `true`。只有离线 fake adapter 测试才可以显式设为 `false`；
CLI 仍然使用真实 OpenAI-compatible adapter，不会因为该开关自动创建 fake 模型。

路径可以是相对当前工作目录的路径，也可以是绝对路径。`RuntimeSession` 会打开 SQLite
Task/StateEvent、不可变 Artifact、Context manifest 和 Evaluation event store；`handoffs`
路径由 `ase handoff build` 使用。目录由各自的 store 按需创建。

## 运行一个 Task

先把 Schema-valid、`status=NEW` 的 Task 写入同一 SQLite：

```bash
ase task create --file task.json --database .ase/state.sqlite3
ase task run task_example_001 --config runtime.json
```

`task run` 的执行顺序固定为：

```text
RuntimeConfig
  → RuntimeSession
  → RoleAwareAgentAdapter
  → EvaluatingAgentAdapter
  → RetryingOrchestrator
  → planning → coder → qa → reviewer
```

成功输出包含 `case_id` 和 typed `RetryDeliveryResult`；QA FAIL、Review REJECT、timeout、
非法输出或预算耗尽由既有 retry policy 处理，无法安全继续时返回 `BLOCKED`。所有 Agent
run 都自动产生 `EvaluationEvent`，不会在任务结束后补造历史。

可选 `--case-id` 用于外部评估系统提供稳定 case identity：

```bash
ase task run task_example_001 \
  --config runtime.json \
  --case-id case_release_candidate_001
```

同一个 case 重启时会复用完全相同的 `CaseStartedEvent`；如果 Task、base revision、model、
prompt/spec version 或 test entrypoints 不同，运行会 fail closed。没有显式 case ID 时，
平台根据 Task ID 的 SHA-256 生成稳定 ID。
如果 case 已有其他 Evaluation facts 但缺少 CaseStartedEvent，Runtime 也会拒绝补造起始事实。

## Role override

`role_overrides` 可以覆盖某个角色的模型、版本、超时、token budget、命令和路径权限，
但不能改变角色的 artifact 输入/输出契约，也不能授予 merge 权限：

```json
{
  "role_overrides": [
    {
      "role": "reviewer",
      "model": "review-model",
      "read_paths": ["src/**", "tests/**", ".trellis/spec/**"],
      "write_paths": [],
      "commands": ["pytest", "git diff", "git status"],
      "network": "model_endpoint_only",
      "timeout_seconds": 900
    }
  ]
}
```

每个 role 最多一个 override；缺省权限为 Coder 写 `src/**` 与 `tests/**`、QA 只写
`tests/**`、Reviewer 不写仓库、Orchestrator 不写业务代码。配置只收窄或明确声明运行
策略，不能绕过 Task deny paths、Artifact lineage 或状态机。

## 明确边界

T014 仍然是单仓库、单 Task、串行 Coder → QA → Reviewer。`RuntimeSession` 不创建复杂
DAG、消息队列、向量库、容器 sandbox，也不自动 merge/deploy；Git worktree 的创建、候选
commit 和最终合并继续属于后续 Git composition/human boundary。Provider SDK 和 HTTP 只
存在于 `agents/openai_compatible.py`，Runtime 层只依赖 typed `AgentAdapter`。
