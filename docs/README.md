# ASE 文档导航

这里保存 ASE 平台自身的使用、运维、设计和维护文档。按你的角色进入对应目录；
普通用户从使用指南开始，无需先阅读内部任务编号或工程协议。
平台运行时各业务项目的知识保存在外置 Team/Project workspace，位置见部署手册。

| 你要做什么 | 阅读入口 | 主要读者 |
|---|---|---|
| 接入项目、提交需求、审批、领取交付 | [用户使用](user/README.md) | 平台使用者 |
| 安装配置、升级、备份、诊断与恢复 | [部署与运维](operations/README.md) | 平台管理员、值守维护者 |
| 理解组件、状态机、角色协议和信任边界 | [架构与协议](architecture/README.md) | ASE 开发者、技术评审者 |
| 修改平台、运行验证、维护文档 | [开发与验证](development/README.md) | 人类开发者与开发 AI 协作者 |
| 查看下一步建设和待验收事项 | [路线与待办](roadmap/README.md) | 项目维护者、规划者 |
| 了解重要技术决策的理由 | [设计决策](decisions/README.md) | 架构维护者、后续接手者 |
| 追溯某次交付、事故、升级或调研 | [历史归档](archive/README.md) | 排障、审计和交接人员 |

## 从哪里开始

- 第一次使用：[用户入门](user/README.md#一次需求的基本流程) → [团队工作台](user/team-console.md)。
- 第一次部署：[生产部署与配置](operations/production-setup.md)。
- 需求中断：[用户恢复指引](user/recovery.md)；需要排障时由维护者阅读[交付恢复手册](operations/delivery-recovery.md)。
- 第一次参与开发：[开发入口](development/README.md) → [总体架构](architecture/overview.md) → 相关工程规范。
- 查旧文件：[迁移记录与旧路径](archive/README.md#document-migrations)。

## 文档与工程记录的边界

`docs/` 解释原理和用法；[.trellis/spec](../.trellis/spec/index.md) 维护输入输出、不变量和测试要求；
[schemas](../schemas/) 定义机器协议；[.trellis/tasks](../.trellis/tasks/README.md) 保存每次工程任务的
需求、实施和验证记录。术语见 [CONTEXT.md](../CONTEXT.md)。

持续维护的手册以主题命名，任务编号只用于来源追溯。带日期的交付结论、具体需求 ID 和当时的
部署现场放在 archive；历史快照不能直接作为当前操作指令。新增文档和移动文件时遵循
[文档维护约定](development/documentation.md)，同时维护目录索引和链接。
