# 恢复当前状态徽标不沿用旧终态阶段

## 实证问题

原 K1 新精确恢复方案已经准备，requestNodeExecution/Presentation 显示待工程确认，但顶部
requestNodeBadge 仍把 deliveryPhase 的旧 BLOCKED 回退值拼成“已阻塞 · 待工程确认”。平台
恢复处理中存在同一误导前缀。保持原终态是正确持久化事实，前缀不能冒充当前状态。

## 范围与验收

- currentApproval 的 badge 只显示“待工程确认”，platformProcessing 只显示“平台正在处理恢复”。
- 这两个 badge 保留原 node.state 样式；恢复审批仍为 blocked，平台处理仍为 paused，不暗示
  Coder 正在运行。阶段事实仍由具体模块展示。
- currentRoleDispatch 继续显示真实阶段与 queued/running；实际新的 blocked 状态不隐藏。
- 不变更其他布局、流程、审批门、任何持久化事实；不操作生产 ASE，不提交。

## 验证与回滚

给真实 STOPPED + terminal BLOCKED fixture 添加当前审批、平台处理两个完整 badge 断言，
先 RED 再 GREEN。仅运行新增两个窄case和受影响三个 Node 文件，不跑全量。回滚只恢复
requestNodeBadge 本次拼接逻辑；无需数据库或artifact操作。
