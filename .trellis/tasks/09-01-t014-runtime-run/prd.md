# T014 — Runtime configuration and Task run composition

## Goal

为已经完成的串行 Orchestrator 提供一个明确、可校验的 runtime composition seam，使操作者
可以用配置文件和 `ase task run` 启动一条真实的 Coder → QA → Reviewer 流程，并自动登记
Evaluation case/run 事实。

## Requirements

- 增加 typed `RuntimeConfig`、role overrides、runtime paths 和 `RoleAwareAgentAdapter`；
- 配置文件不允许保存 API key，只保存 `api_key_env`，密钥从进程环境读取；
- `RuntimeSession.run_task` 打开现有 SQLite/Artifact/Context/Evaluation stores，创建
  `RetryingOrchestrator`，自动写入唯一/幂等 `CaseStartedEvent`；
- 增加 `ase task run TASK_ID --config runtime.json`，成功输出 case ID 和 typed result，
  失败输出稳定错误，不打印 provider secret；
- 保持单仓库、单 Task、串行路径，不自动 merge/deploy，不添加并行 DAG 或消息队列。

## Acceptance criteria

- [ ] Runtime config 的正例通过 Pydantic 与 JSON Schema，未知字段、重复 role、明文 key 被拒绝；
- [ ] role definitions 能确定性生成四个 AgentDefinition，且权限/输入输出契约正确；
- [ ] task run 使用可注入 fake adapter 完成并复用同一 runtime composition seam；
- [ ] 缺少 API key、配置损坏、终态 Task、Agent failure 都 fail closed；
- [ ] CLI `task run` 只依赖配置和 durable stores，不直接修改状态或 artifact；
- [ ] 全量测试、Ruff、strict Mypy、lock、build、diff check 通过。

## Contract impact

- 新增 `schemas/runtime-config.schema.json`；不修改既有 Task/Agent/Artifact/StateEvent wire format；
- 更新 `docs/runtime.md`、`docs/cli.md`、`docs/milestones.md`、`AGENTS.md` 和 core specs。

## Rollback

删除 runtime module、CLI 命令和 runtime config schema/docs；已有 T001–T013 stores、orchestrator
和 artifact 不受影响。
