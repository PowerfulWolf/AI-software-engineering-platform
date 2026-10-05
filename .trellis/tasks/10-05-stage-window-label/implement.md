# 实现

`designBudgetSummary()` 未触及容量上限时，统一把 `next_timeout_seconds` 标为“当前可用执行窗口”。
仍直接使用已有只读 StageBudget，默认窗口、容量耗尽判断及全部审批/重试控件逻辑保持原有契约。

真实浏览器新增 Product、Designer、Planner × RUNNING、FAILED 六种组合，确认文案一致且不含
“下次时限”。现有 Designer 失败窗口及耗尽回归、knowledge-gap 轻量窗口断言同步使用准确措辞。
执行重试规范记录预算与 invocation 时间事实的区别、存量处置及回滚。

增量验证发现 knowledge-gap 原有“已批准知识不再显示旧阻塞”断言检查整个详情，而完整操作历史
按现有规范必须保留旧 Operation 的下一步。该漂移已在修改生产文案前复现。将否定断言收窄为
当前需求概览、阻塞区和知识区，并明确断言原历史问题仍存在；原精确 checkpoint 提交、无旧确认
表单与单一“继续交付”控件断言继续保留。没有改变任何生产历史展示行为。
