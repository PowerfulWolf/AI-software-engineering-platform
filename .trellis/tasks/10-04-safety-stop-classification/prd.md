# 首次安全暂停的准确分类和恢复提示

目标：POLICY_VIOLATION 和 PLATFORM_BUG 的立即暂停不能兜底为 RETRY_BUDGET_EXHAUSTED；Codex 本地超时且保留改动的展示必须说明无可接纳报告及精确恢复审批。

允许路径：task.json scope 中四个源/测试文件、本任务文档及相关 failure-routing / live-team-view 规范。

验收：原 typed classification、原始 reason、Run/SHA 与状态历史保留；安全拒绝分别映射到现有 PERMISSION_DENIED / INVARIANT_VIOLATION；真正预算耗尽不改变；不触发 dirty 自动重试、不合成 coder-progress、不改变角色权限或 verdict。

验证：增量 UnifiedProjectEntry 离线完整阶段链及 blocker_text 回归；Ruff、源文件 mypy、git diff --check。不得跑全量测试。

存量数据处置：旧 sealed checkpoint 不改库；重载后中文读侧按原始 reason 重算；使用最新 Resume 恢复计划审阅完整捕获、当前基线和范围，再批准 exact SHA 并由原生 Worker 交付。旧失败 Task/approval 保留，不重复消费。
