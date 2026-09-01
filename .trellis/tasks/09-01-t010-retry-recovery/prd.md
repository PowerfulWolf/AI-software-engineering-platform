# T010 Retry and Recovery

## 目标

在 T009 单次串行闭环之上，交付可审计、可恢复的失败路由：瞬时 Agent failure 在 Task
attempt budget 内重试；QA/Review finding 回流 Coder；无法安全继续时进入 BLOCKED，并保留
所有已验证 Artifact 与事件。

## 范围

- `RetryingOrchestrator` 接受 `NEW`、中间 checkpoint，并继续
  `Orchestrator → Coder → QA → Reviewer` 串行路径；
- attempt 在 Agent 调用前持久化，重启从 SQLite StateEvent/Task 与 ArtifactStore 恢复；
- 新 implementation-report 不覆盖旧文件，通过 `supersedes` 和 finding parent 建立 lineage；
- 提供瞬时超时、QA FAIL、attempt exhausted、T009 中断后恢复测试。

## 非目标

不引入复杂 DAG、消息队列、向量数据库、并发 Agent、自动 merge/push、真实模型 adapter 或
生产部署。所有路由仍由一个进程内 Orchestrator 串行执行。
