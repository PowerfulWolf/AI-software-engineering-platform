# T021 — SpecCompiler 与人工冲突治理

## Goal

把平台 hard safety policy、项目原生规范和 Task 约束编译成可审计的有效规范上下文；当工程规范
发生冲突时，不让 Agent 猜测优先级，而是生成 `SPEC_CONFLICT` 事实，使 WorkItem 进入
`WAITING_HUMAN`、释放 Lease，等待人工 resolution。只有人工明确终止本次交付时 Task 才进入
`BLOCKED`。

## Requirements

- 消费 T020 `ProjectProfile`/native rule sources、平台 `.trellis/spec/` 和 Task constraints；
- 为每条规则保留来源 URI、内容 hash、层级、优先级和适用范围；
- hard safety policy 不可被项目规范或 Task 约束放宽；
- engineering rule conflict 生成 typed conflict artifact/resolution request，不静默选择一方；
- 无冲突时生成 deterministic compiled spec/context source；
- 冲突时返回 `WAITING_HUMAN` 路由事实、恢复条件和受影响 Task/criteria；
- 支持人工 resolution 的 immutable record，拒绝越权放宽 hard policy；
- 不修改项目源文件、TaskStatus、verdict 或 Lease 状态（由上层调度器/Orchestrator 应用）。

## Acceptance Criteria

- [ ] 相同输入规则集合得到稳定 hash 和稳定编译结果；
- [ ] hard safety 与任何较低层规则冲突时 fail closed；
- [ ] 工程规范冲突生成 `SPEC_CONFLICT`，包含双方 URI/hash、字段、理由和人工问题；
- [ ] 无冲突结果可供 Context Builder 使用，且来源顺序/优先级可解释；
- [ ] resolution 不能无证据删除冲突或降低 hard safety；
- [ ] Python ↔ JSON Schema、全量测试、Ruff、strict Mypy 和 build 通过。

## Out of Scope

自动修改项目规范、自动接受人工决定、复杂策略语言、分布式审批和 UI inbox。

## Rollback

回滚 T021 提交即可恢复只读 ProjectProfile；不修改 Task/Artifact/Context 历史。
