# 活动子任务优先于旧验证阻塞展示

## 目标

当 Requirement 的旧 QA/Review 验证任务仍保留终态阻塞事实，但新的 Coder 恢复 Task 已经进入
`IMPLEMENTING`，Team View 必须展示当前交付正在进行，而不是把旧验证失败继续投影为需求顶部状态。

## 范围与约束

- 只修改 `ProductionTeamReader` 的只读投影和对应增量测试。
- 不修改 Task、StateEvent、Operation、审批、verdict 或任何历史事实。
- 保留终态验证 Task 在任务历史中的可见性。

## 验收标准

- 活动的非终态子 Task 与旧终态阻塞同时存在时，需求阶段为 `DELIVERING` 或 `INTEGRATING`，阻塞字段为空，下一步来自活动子 Task。
- 没有活动子 Task 时，最新终态子 Task 的具体阻塞仍覆盖泛化父级建议。
- 既有知识等待、租约中断和纯终态阻塞投影不变。

## 验证计划

只运行 `tests/team_view/test_live.py` 中相关测试及 Ruff/mypy 增量检查；不运行全量测试。

## 存量数据处置与回滚

无需改库；历史事实保持原样，重新加载服务即可生效。回滚只恢复本次 reader/test/Trellis 文件变更，
不删除 sidecar 或重放任何审批。
