# 项目 Trellis 知识层

`.trellis/` 是组织知识和任务历史的持久化边界。Agent 可以被替换、升级或删除，但这里记录的规则、契约和决策不能依赖某个 Agent 的私有上下文。

## 目录约定

- `spec/index.md`、`spec/core/index.md`：规范索引和开发前检查清单；
- `spec/core/`：v0.1 架构、角色、权限、artifact 和状态机的规范；
- `tasks/`：每个实现任务的 PRD、设计、执行计划和上下文清单；
- `workspace/`：开发会话日志（默认不提交个人身份文件）；
- `workflow.md`：本项目的最小开发流程和质量门。

任何跨层契约变更都要同步更新 `docs/`、`schemas/` 与 `spec/core/`，并添加 contract test 计划。
