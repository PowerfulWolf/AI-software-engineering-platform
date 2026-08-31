# v0.1 项目工作流

## Phase 1 — Plan

读取 `AGENTS.md` 和相关 spec，创建一个任务目录，写清需求、技术设计、验收标准、影响的 Schema、测试计划和回滚点。复杂变更必须同时有 `prd.md`、`design.md`、`implement.md`。

## Phase 2 — Execute

按里程碑顺序实现。默认使用 fake AgentAdapter 验证 Orchestrator，再接入真实模型。每次 Agent 运行都必须记录 context manifest、policy、输入 artifact IDs、输出 artifact、耗时和 token budget。

## Phase 3 — Verify & Learn

运行 lint/typecheck/unit/contract/e2e；检查状态机和跨层 Schema 一致性；将新的 failure mode、边界条件和设计决策写入 `.trellis/spec/`，再提交代码。

## 不可跳过的门

- 没有有效 plan 不能进入 `IMPLEMENTING`；
- 没有同一 candidate SHA 的 QA `PASS` 不能进入 `REVIEW`；
- 没有独立 Review `APPROVE` 不能进入 `DONE`；
- 任何 policy violation、artifact 伪造或 revision 不匹配都不能静默恢复；
- v0.1 不以引入并行调度、向量库或分布式基础设施为“完成标准”。
