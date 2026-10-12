# 增量验收与存量处置

## Contract and test evidence

- 新模型初始缺模块失败；新transport routes/capability初始5失败1通过后实现。
- 原生ProductSpec真实store测试先5失败（空正文与缺损未拒绝），实现后5通过。
- 最终定点batch：`PYTHONPATH=src python -m pytest tests/team_view/test_read_models.py
  tests/team_view/test_summary_detail_reader.py tests/web_console/test_team_summary_detail.py
  tests/web_console/test_team_snapshot_coalescing.py tests/team_view/test_task_read_snapshot.py
  tests/team_view/test_snapshot_schema.py -q -k 'not current_task_compact'`：82通过，3排除，5.01秒。
- 实际当前Task读取：`pytest tests/team_view/test_summary_detail_reader.py -q
  -k current_task_compact`：3通过，24.45秒。完整accepted artifact/continuation校验计数一致，
  exact current receipt、live QA清旧receipt、terminal engineering STOPPED和corrupt拒绝均覆盖。
- 新verification真实stores/route ledger测试：同阶段新结果、QA→Review、completion保存与release/
  abandonment均使只读版本变化；旧state查询在pretty调用前拒绝，corrupt原completion拒绝。
  SQL reservation assembly使用小fake cursor，来源Task读单独stub；实际版本输入来自真实持久化store。
- 独立复核 `/root/summary_result_scope_compat`：此前61通过，最终4定点（3当前事实+verification）
  通过/24.78秒；required-state Python/JSON Schema24边界独立一致；代码scoped PASS。
- Ruff通过；`mypy --strict --follow-imports=silent`检查7个自有Python文件通过。
  不带silent遍历旧导入test module会遇到已存在的tests/recovery/test_execution.py:369 Optional错误，
  不纳入本任务改动；生产源码另行strict检查。Schema isolated重复生成与parity由测试验证。
- 仅增量测试，未运行全量或调用真实模型。Starlette/httpx两项现有弃用提示不影响通过。

13轮history fixture仅验证装配选择性与完整历史，不伪称真实SQL数据库e2e。
性能收益要由root在安全加载后测量；本任务不宣称已解决所有durable current-fact读取开销。

## 存量数据处置

无需修改SQL/journal/Task/Operation/审批/预算/worktree；read-state从现有已验证事实计算。
不改变任何旧审批、结果、调用或中断记录。Root拥有生产维护与交付，加载已验证版本后刷新原需求，
可以读取新的摘要与精确完整详情；历史仍完整保留。此子任务没有操作服务/配置/生产平台。

## Rollback

停用新capability和新GET/UI消费，恢复旧v0.2 full路径；无数据迁移和反向改库。
具体跨层契约记录在 `.trellis/spec/core/team-summary-detail.md`，对应UI规范由root维护。
