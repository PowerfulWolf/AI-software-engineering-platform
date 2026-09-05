# Runtime 配置与任务执行

> 日常使用请从 [`production-setup.md`](production-setup.md) 的 `ase project ...` 开始。Production Team
> Host 自动使用 MySQL、组织 Workforce、项目 sidecar、GPT-5.5 路由和隔离 worktree，不需要手工构造
> 本文的 RuntimeConfig。本文描述的是可独立调试的低层 Task Runtime。

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
    "handoffs": "artifacts/handoffs",
    "evidence": "artifacts/evidence",
    "runs": "artifacts/run-manifests"
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

路径可以是相对当前工作目录的路径，也可以是绝对路径。低层 `ase task run` 仍要求显式 Runtime
配置；不得在外部目标项目 cwd 中误用 `.ase/state.sqlite3` 或 `artifacts/*` 默认值。T022 的
`RuntimeWorkspaceBinding.compose_runtime_config(...)` 能把全部 paths 绑定到 T017 sidecar；T032 的
`ase project ...` application facade 要求宿主自动调用这类 composition，不把内部路径暴露为每次
接单参数。`RuntimeSession` 会打开 SQLite
Task/StateEvent、不可变 Artifact、Context manifest、Evaluation event store 和独立的
`FileEvidenceStore`。`evidence` 保存 command/diff/test/usage records，`runs` 保存封存 manifest；
两者不能与 ArtifactStore root 重叠。`handoffs` 路径由 `ase handoff build` 使用。目录由各自的
store 按需创建。当前 role adapter 尚未自动包装每个 tool call，接入应用服务时必须显式创建
`RunEvidenceSession`，不能把 EvidenceStore 暴露给 Agent。

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

T018 后，上述 `role_overrides` 和 `RuntimeConfig.agent_definitions()` 只是当前单 Task Runtime 的
兼容入口。它们产生的 `AgentDefinition` 是某次单角色执行的 resolved config，不是组织成员身份。
T022 的 `RuntimeWorkforceResolver` 已从 AgentProfile、RoleAssignment、active TaskLease、
ModelSelection、CompiledSpec、Context 与 project policy 解析同一结构；具体 model 按 AgentRun
分配，不永久写入 AgentProfile。`RuntimeSession` 接受该 resolved definitions 和绑定 project root，
并拒绝 Task.repository 漂移。T032 的 Project Manager 入口消费 T031 已提交的 Assignment/Lease；T034
的 Production Team Host 已将该入口绑定到 MySQL 与真实 Codex/Responses adapters。低层
`ase task run` 兼容命令仍不会创建 Assignment/Lease、准备项目或跨 Task 调度。

## 明确边界

T014 仍然是单仓库、单 Task、串行 Coder → QA → Reviewer。`RuntimeSession` 不创建复杂
DAG、消息队列、向量库、容器 sandbox，也不自动 merge/deploy；Git worktree 的创建、候选
commit 和最终合并继续属于后续 Git composition/human boundary。Provider SDK 和 HTTP 只
存在于 `agents/openai_compatible.py`，Runtime 层只依赖 typed `AgentAdapter`。

T015 提供后续 QA/Coder 集成使用的 `SubprocessCommandExecutor`。它绑定一个已经创建的
worktree 根目录，调用前复用 `WorkspacePolicy.authorize_command`，只接受 tokenized argv，
通过 `shell=False`、进程组 timeout、最小环境和 stdout/stderr 截断返回 `CommandResult`。
当前 `ase task run` 尚未自动让 Agent 执行任意命令；接入必须继续由角色 application service
显式调用该端口，并把非零退出和日志转换为 evidence，不能把它直接当作 PASS。

T016 的 `RoleWorktreeSession` 进一步把 `WorktreeSpec`、同角色 `AgentDefinition`、
`GitWorkspace` 和 `SubprocessCommandExecutor` 组合成可复用 binding：Coder 获得 attempt
branch，QA/Reviewer 获得 candidate SHA 的 detached worktree；`close` 复用 dirty-worktree
保护。T032 新增 `DispatchRoleWorktreeCoordinator`，在创建或恢复 worktree 前核对 exact dispatch
Agent/model/provider/Assignment/Lease，并要求 QA/Reviewer 使用同一个 full candidate SHA。T034 的
production delivery adapter 现在消费该 seam，动态为 Coder 创建 branch worktree，并让 QA/Reviewer
在 exact candidate SHA 的独立 detached worktree 中运行；完成后只清理干净 worktree，dirty 现场保留。
该路径仍不会执行 merge/deploy。
