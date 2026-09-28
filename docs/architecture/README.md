# 架构与协议

面向 ASE 开发者和技术评审者。文档解释设计；实现必须同时遵守
[工程规范](../../.trellis/spec/index.md)与 [JSON Schema](../../schemas/)。

| 文档 | 内容 |
|---|---|
| [总体架构](overview.md) | 控制面、工作空间、组件与信任边界 |
| [技术选型](tech-stack.md) | 技术栈及其取舍 |
| [角色与 Artifact 契约](contracts.md) | 跨角色输入输出、权限与事实链 |
| [Task 状态机](state-machine.md) | 合法迁移、事件与守卫 |
| [Prompt 与执行信封](prompt-protocol.md) | 角色输入输出、[typed tools](prompt-protocol.md#typed-tools) |
| [Context 路由](context-routing.md) | 来源、预算、脱敏与确定性 |
| [Git 隔离](git-worktree.md) | Repository、worktree 与候选契约 |
| [Orchestrator](orchestration.md) | 串行交付与调度边界 |
| [失败路由](failure-routing.md) | 重试、终态与人工处理 |
| [Evaluation 与 Handoff](evaluation.md) | 可重算指标与交付材料 |
| [工作台数据与接口](team-console.md) | Console 读写边界、数据链和 HTTP 契约 |

底层只读投影与静态 Renderer 见[架构对应章节](overview.md#read-projection)。
技术决策见[ADR 索引](../decisions/README.md)，历史对比研究见
[2026-09-20 架构对比](../archive/2026-09-20-trellis-multica-ase-comparison.md)。
返回[文档导航](../README.md)。
