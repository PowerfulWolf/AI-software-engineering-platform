# 设计

`designBudgetSummary(request)` 继续只读取 `request.stage_budget`。未触及容量上限时，将
`next_timeout_seconds`（兼容默认 600 秒）标注为“当前可用执行窗口”；达到上限仍展示
“已达上限”。函数不读取 Operation 或模型诊断，不推断某次 invocation 的真实时限。

使用现有隔离 Playwright fixture，在真实浏览器 DOM 中分别组合 Product、Designer、Planner
阶段与 RUNNING、FAILED Operation，断言预算文案不带“下次时限”。现有容量耗尽回归继续验证
无效重试按钮隐藏；同步调整轻量 knowledge-gap 回归的一条文案断言。
