# 上游 Host 中断后的状态与接续入口

## 目标与根因

ProductSpec 精确批准已保存后，首次 PRODUCT_APPROVAL 在 Designer 执行中因用户重启服务
标记 INTERRUPTED/HOST_INTERRUPTED。Requirement 保持 DESIGNING，execution UNKNOWN，
无活动 Operation；前端却遗漏中断终态，Designer 成员把阶段归属当成执行中，且无继续设计入口。

## 范围与验收

- 同需求同 Project 的交付中断在无更新执行时显示红色“操作已中断”，保留原已批准阶段。
- 后端已有 typed CONTINUE 合法时，DESIGNING/PLANNING 提供绑定当前 checkpoint 的
  “继续设计”/“继续计划”；不重复提交 PRODUCT_APPROVAL、不重置预算或改 source。
- 已有精确审批、知识等待、预算与合法活动 Operation 优先，不能以中断入口绕过 gates。
- Product 仍使用“继续需求讨论”；关闭、删除等 lifecycle 中断不产生交付续跑入口。
- Designer/Planner 等上游成员、队列、工作卡片消费共享节点事实，当前阶段归属不是执行证明；
  保留 durable current_stage_delivery_ids/Assignment，仅改变当前显示。
- Host 停止固定英文通过精确映射显示中文，原 Operation bytes/hash 不改。
- 产品侧不再展示模糊“状态待核对”。native UNKNOWN 缺运行/排队/停止证明时红色等待工程
  处理，普通 Continue 拒绝，原 UNKNOWN 留在工程详情。合法上游 idle checkpoint 灰色待继续；
  NEW/PLANNING 仅在匹配交付 Operation RUNNING 且无 blocker/wait/expired 时灰色准备执行。
- Task/Request 摘要同时更新执行状态、原因、责任和下一步；成员 paused 显示真实调度/重试/
  准备/接续状态。非当前 assignment 不继承其他角色 RUNNING，轮询签名包含 assignment。
- Operation 中断 badge 改局部红色停止样式；Team 待处理计数与队列消费同一状态派生。

## 验证与回滚

轻量契约先复现 PRODUCT_APPROVAL/CONTINUE 中断、当前新 checkpoint 续跑、预算/审批/活动
门禁与成员队列；真实 Chrome 检查颜色、轮询、可见入口和提交 intent。只运行相关增量文件。
无需迁移或改库，更新前端资产后刷新现有需求即可。回滚资产并刷新，保留所有原始事实。
