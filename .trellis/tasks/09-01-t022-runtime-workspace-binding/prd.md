# T022 — Runtime organization/project workspace binding

## Goal

把组织 Workspace、Project sidecar 和目标项目代码目录接入现有 Runtime composition：目标项目继续
是命令和 Git 的真实 cwd，平台 metadata/SQLite/Artifact/Context/Evaluation/Handoff 写入外置
sidecar，AgentProfile/ModelPolicy/WorkQueue 写入组织 workspace。每个 AgentRun 通过 T019 的
Assignment/Lease/ModelSelection 解析成现有 `AgentDefinition`，保持单 Task `Coder → QA → Reviewer`
串行。

## Requirements

- 提供 typed workspace binding，验证组织 root、ProjectWorkspace manifest 和 target project root；
- 从 sidecar paths 构造 RuntimePaths，禁止默认回落到目标项目 `.ase` 或 `artifacts/`；
- Runtime 使用 target project root 作为 Git/command cwd，平台 stores 使用 sidecar；
- 读取组织 AgentProfile/ModelPolicy，接收 T019 `RoleAssignment`/`TaskLease`/`ModelSelection`；
- 生成 `AgentRunAllocation` 并解析现有 RoleAwareAgentAdapter/RetryingOrchestrator 输入；
- 释放/过期 Lease 和等待 WorkItem 不修改 Task delivery state；
- 保留现有显式 config/fake adapter 兼容路径，并在冲突/缺失绑定时 fail closed；
- 不自动 merge、部署、共享 session 或引入分布式调度。

## Acceptance Criteria

- [ ] 绑定后的 Runtime paths 全部位于正确 sidecar/organization roots；
- [ ] target project 内容无写入，command cwd 和 Git root 正确；
- [ ] 缺失/篡改 manifest、跨项目 workspace、组织 Agent/Policy 不匹配时拒绝启动；
- [ ] Assignment/Lease/Model/Context/Prompt/Spec/Tool policy 能生成 AgentRunAllocation；
- [ ] T010/T014 serial runtime tests 继续通过，fake adapter 可离线运行；
- [ ] Python ↔ JSON Schema、全量测试、Ruff、strict Mypy 和 build 通过。

## Out of Scope

持久化 PortfolioScheduler、复杂 DAG、消息队列、向量库、真实 dashboard 和保护分支 merge。

## Rollback

回滚 T022 提交即可恢复 T014 的显式 paths/runtime config，不影响 ProjectWorkspace/Workforce facts。
