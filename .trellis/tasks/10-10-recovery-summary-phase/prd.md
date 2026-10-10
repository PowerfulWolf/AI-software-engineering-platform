# 恢复摘要阶段一致性

## 目标与根因

真实 Chrome 的 390/1440 页面中，`productExecutionSummary` 左侧仍用旧 durable 阶段
显示“交付阶段 · 已阻塞”，右侧已用 `requestNodeExecution` 显示“平台正在处理恢复”。
让同一摘要的阶段与当前只读节点事实一致，用户可理解正在准备恢复还是需要确认方案。
已封存旧失败与交付历史继续保留；不从恢复 Operation 推断 Coder 已启动。
同源 `currentOperationProgress` 当前执行记录标题也纳入修复，统一从同一次已核验 node
派生阶段；sealed `recordedOperationOutcome` 保持原始当次结果。

## 验收

- 用真实 `productExecutionSummary` 入口先 RED：精确未消费的 ready 审批、同作用域已批准
  恢复处理均不把旧 blocked/failed 阶段当当前阶段。
- 仅使用 `requestNodeExecution` 的当前精确审批/恢复处理中标志显示恢复阶段，不新增授权判断。
  `deliveryPhase(item, node = null)` 默认行为保持，调用者显式传入已有 node，不能在其内部
  重新求 node 或引入循环。
- 当前新阻塞、新有效角色 claim、知识/业务等待保持原优先级；不能用旧恢复审批/Operation
  盖住这些新 facts。没有可靠恢复事实时不生成恢复准备状态。
- Team 读取失败的控制门禁、原 callback 精确守卫和全部 durable bytes/hash 保持原样。
- Team 读取竞争回归使用真实的 `busy/unavailable/timeout` 字符串，分别验证两个表面。
- 只运行 product-execution 与关联只读状态的增量 Node 测试和 syntax/diff 检查；真实 Chrome
  验收由 root 的独立 browser 测试完成，本任务不编辑该测试。
  `browser/recovery-read-contention.test.cjs` 属于本任务允许路径，由 root 独占编写与验证。

## 存量数据处置、操作与回滚

纯只读前端展示，无需 SQL、journal、Task、Operation 或批准历史迁移；原需求和开发进度保留。
兼容资产加载并刷新后按当前 facts 重算摘要。root 负责部署及继续交付；本任务不执行生产
操作、审批、重启或提交。回滚本次前端、测试与规范改动并刷新即可，不改写历史或停止角色。
