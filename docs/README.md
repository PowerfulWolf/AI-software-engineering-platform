# 文档分类索引

日常入口是 Web Console。按当前问题选择文档，历史归档用于追溯当时的事实。
本目录说明使用方法和设计；实现约束见 [工程规范索引](../.trellis/spec/index.md)，
机器协议见 [schemas](../schemas/)，术语见 [CONTEXT.md](../CONTEXT.md)。

## 使用与运维

| 文档 | 适用场景 |
|---|---|
| [生产部署与配置](production-setup.md) | 安装、启动、设置、MySQL、模型路由、备份 |
| [团队工作台](visualization.md) | 网页操作、运行状态和交付信息 |
| [问题反馈与恢复](operator-feedback-loop.md) | 定位失败、继续交付、恢复审批和交接 |
| [规划与知识运行](planning-knowledge-operations.md) | 规划分流、知识导入、检索和缺口恢复 |
| [CLI 参考](cli.md) | 运维、诊断及低层兼容命令 |
| [低层 Runtime 配置](runtime.md) | 直接组合 Task runtime，非日常 Console 设置 |

## 架构与协议

| 文档 | 内容 |
|---|---|
| [总体架构](architecture.md) | 控制面、工作空间、持久化和信任边界 |
| [只读投影与静态 Renderer](architecture.md#read-projection) | 保留的底层投影、GET-only API 和离线展示库 |
| [技术选型](tech-stack.md) | 当前技术栈及取舍 |
| [Task 状态机](state-machine.md) | 合法迁移、事件和守卫 |
| [角色与 Artifact 契约](contracts.md) | 跨角色协议的人类可读参考 |
| [Prompt 与执行信封](prompt-protocol.md) | 平台角色的输入输出边界 |
| [Typed tools](prompt-protocol.md#typed-tools) | 受控文件、命令工具及权限矩阵 |
| [Context 路由](context-routing.md) | 来源、预算、脱敏和确定性 |
| [Git 隔离](git-worktree.md) | 平台管理目标 Repository/worktree 的契约 |
| [Orchestrator](orchestration.md) | 串行交付和调度边界 |
| [失败路由](failure-routing.md) | 重试、终态与人工处理 |
| [Evaluation 与 Handoff](evaluation.md) | 可重算指标和交付材料 |

## 开发、决策与历史

- [开发与验证入口](../README.md#开发与验证)、[跨语言 E2E](target-project-e2e.md)。
- [工程任务索引](../.trellis/tasks/README.md)：当前工作、待核实记录和已完成历史。
- [当前路线与待验收事项](milestones.md)。
- [ADR-0001：Python 控制面](decisions/0001-python-control-plane.md)。
- [ADR-0002：组织拥有 Agent](decisions/0002-organization-owned-agent-workforce.md)。
- [历史归档索引](archive/README.md)：交付报告、旧计划、事故处置。
- [文档迁移表](archive/document-migrations.json)：旧路径、新位置和原文摘要。

## 文档维护约定

- 使用手册写当前可执行的操作；一次性交付结果和具体事故放在 archive。
- docs 解释原理和用法；.trellis/spec 维护输入输出、不变量和测试要求；schemas 维护机器协议。
  同一细节优先引用其负责模块，避免在多个入口复制完整规则。
- 迁移历史文档保留来源提交、旧路径和摘要；旧任务允许路径属于当时事实，不随目录整理改写。
- 归档报告保留当时的结论及后续更正。新链接和迁移映射可以补充，不能把历史未完成写成已完成。
- 工程任务缺少记录时标为待核实；独立报告原样保存，索引负责映射旧临时路径。
