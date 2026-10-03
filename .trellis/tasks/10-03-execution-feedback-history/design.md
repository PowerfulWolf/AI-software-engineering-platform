# 设计

## 数据流

`Task/StateEvent/Artifact/Evidence/Run → RunProjectionBuilder → ProductionTeamReader → TaskView.execution_history → Team View task detail`。

Artifact 本身已经保存 immutable `parent_artifact_ids`、`supersedes`、`source_revision`、`integrity.sha256` 和 typed QA/Review/Coder 内容；投影只选择可审计摘要，不新建事实。QA/Review finding 继续以原文、位置和 evidence ID 展示，平台标签与阶段说明保持中文。

## 历史合并

`_native_task_sources` 已按 native delivery 的 checkpoint hash chain 收集历史 Task。当前 Task 仍作为唯一调度/状态事实；读侧为每个历史 Task 重算投影，并将 timeline、runs、documents 以 Task ID/source URI 去重后合并到 `execution_history`。当前活动 successor 也会作为当前轮保留，不能覆盖历史记录。

## 安全与兼容

Reader 对摘要中的字符串递归执行既有 redaction，Timeline schema 的 `details` 保持 JSON value。旧 Task 没有新字段时由 Pydantic 默认空数组；没有报告 findings 时显示“未提供 finding”，不猜测 PASS/修复结论。前端仅使用 textContent。
